"""
Главный оркестратор pipeline.

Дизайн:
  - Вход: bytes выписки + opt bytes ОФД + DeclarationRequest
  - Выход: bytes готового PDF (со штампами)
  - Всё in-memory, никаких файлов на диске
  - Прогресс через ProgressTracker (callback)
  - Ошибки — подклассы PipelineError (api/core/errors.py)

Слой делает ТОЛЬКО оркестрацию. Бизнес-логика парсинга/расчётов/рендера —
в modules/declaration_filler/ и modules/edo_stamps/.

ВАЖНО: на момент написания modules/declaration_filler/ ещё пустой — будет
заполнен скриптом scripts/sync_sources.sh из repo usn-declaration. Импорты
ниже сделаны под ожидаемые имена функций. См. modules/declaration_filler/README.md
для точного списка что должно быть экспортировано.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from api.models import DeclarationRequest, PipelineStage
from core.errors import (
    ClassificationError,
    DaDataError,
    DeclarationRenderError,
    OfdParseError,
    PipelineError,
    ReceiptsRenderError,
    StampRenderError,
    StatementParseError,
    TaxCalculationError,
)
from core.progress import ProgressTracker

log = logging.getLogger(__name__)


def _resolve_signing_datetime(override: str | None):
    """Возвращает datetime подписания: либо из override, либо now() MSK.

    Принимает override в форматах:
      - ISO8601: 2026-04-25, 2026-04-25T12:30, 2026-04-25T12:30:00+03:00
      - Русский с точками: 25.04.2026, 25.04.2026 12:30
      - С дефисами: 25-04-2026
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    msk = ZoneInfo("Europe/Moscow")
    if not override:
        return datetime.now(msk)

    s = override.strip()
    dt: datetime | None = None

    # 1. ISO (UI по умолчанию генерит YYYY-MM-DD)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        pass

    # 2. Русские форматы
    if dt is None:
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
                    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue

    if dt is None:
        raise ValueError(
            f"Не удалось распарсить дату подписания {override!r}. "
            f"Поддерживаемые форматы: 2026-04-25, 25.04.2026, 25-04-2026 "
            f"(с опциональным временем через пробел)."
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=msk)
    return dt.astimezone(msk)


# ============================================================
# DTO между стадиями (не путать с API-моделями!)
# ============================================================

@dataclass
class PipelineInputs:
    """То, что пришло с HTTP multipart: байты + распарсенная DeclarationRequest."""
    statement_bytes: bytes
    ofd_bytes: bytes | None
    request: DeclarationRequest


# ============================================================
# Pipeline
# ============================================================

async def run_pipeline(
    inputs: PipelineInputs,
    tracker: ProgressTracker,
) -> tuple[bytes, str]:
    """
    Выполняет весь pipeline.

    Returns:
        (pdf_bytes, filename)

    Raises:
        PipelineError (или подкласс) при ошибке на любой стадии.
    """
    req = inputs.request

    # -------- 1. Парсинг 1С-выписки --------
    await tracker.emit(PipelineStage.PARSING_STATEMENT)
    try:
        from modules.declaration_filler import parse_1c_statement_bytes
        parsed_statement = parse_1c_statement_bytes(inputs.statement_bytes)
    except Exception as e:
        raise StatementParseError(f"Не удалось разобрать 1С-выписку: {e}", cause=e) from e

    # -------- 2. Парсинг ОФД (опционально) --------
    ofd_receipts = []
    if inputs.ofd_bytes is not None:
        await tracker.emit(PipelineStage.PARSING_OFD)
        try:
            from modules.declaration_filler import parse_ofd_bytes
            ofd_receipts = parse_ofd_bytes(inputs.ofd_bytes)
        except Exception as e:
            raise OfdParseError(f"Не удалось разобрать чеки ОФД: {e}", cause=e) from e

    # -------- 3. Классификация операций --------
    await tracker.emit(PipelineStage.CLASSIFYING)
    try:
        from modules.declaration_filler import classify_operations
        classified = classify_operations(parsed_statement)
    except Exception as e:
        raise ClassificationError(f"Ошибка классификации операций: {e}", cause=e) from e

    # -------- 3b. Override помесячных доходов (если пришёл из UI-wizard) --------
    # Пользователь мог отредактировать доходы на шаге 2 wizard'а — его значения
    # должны перебить результат автоклассификации.
    # Переводим помесячные суммы (безнал+нал) в квартальные для ClassifiedOps.
    if req.monthly_income_override:
        from decimal import Decimal
        # classified хранит квартальные суммы — перезаписываем
        classified.q1 = Decimal("0")
        classified.q2 = Decimal("0")
        classified.q3 = Decimal("0")
        classified.q4 = Decimal("0")
        for item in req.monthly_income_override:
            total_for_month = item.cashless + item.cash
            q = (item.month - 1) // 3 + 1
            setattr(classified, f"q{q}", getattr(classified, f"q{q}") + total_for_month)
        # ОФД-чеки уже учтены в override'е — обнуляем чтобы tax_engine не удвоил
        ofd_receipts = []

    # -------- 4. Расчёт налога --------
    await tracker.emit(PipelineStage.CALCULATING_TAX)
    try:
        from modules.declaration_filler import tax_engine_calculate
        tax_result = tax_engine_calculate(
            classified=classified,
            ofd_receipts=ofd_receipts,
            contributions=req.contributions,
            personnel=req.personnel,
            tax_period_year=req.tax_period_year,
        )
    except Exception as e:
        raise TaxCalculationError(f"Ошибка расчёта налога: {e}", cause=e) from e

    # -------- 5. Рендер PDF декларации (reportlab Canvas + таблицы клеточек) --------
    # С PR #21 перешли с overlay-over-raster на table_renderer — теперь декларация
    # рисуется с нуля через ReportLab, без подложки ФНС. Это устранило проблемы
    # -------- 5. Рендер PDF декларации (xlsx-шаблон ФНС + LibreOffice) --------
    # Переход с ReportLab Table (pr24) на xlsx → PDF через LibreOffice.
    # Заполняем шаблон templates/knd_1152017/declaration_template_2024.xlsx
    # через openpyxl + структурно модифицируем Титул (сжимаем пустые
    # строки для освобождения зоны под штамп ЭДО), затем `soffice --convert-to pdf`.
    await tracker.emit(PipelineStage.RENDERING_DECLARATION)
    try:
        from modules.xlsx_renderer import render_declaration_pdf
        signing_dt_for_decl = _resolve_signing_datetime(req.stamps.signing_datetime_override)
        declaration_pdf: bytes = render_declaration_pdf(
            taxpayer=req.taxpayer,
            tax_period_year=req.tax_period_year,
            tax_result=tax_result,
            correction_number=req.correction_number,
            signing_date=signing_dt_for_decl,
        )
    except Exception as e:
        raise DeclarationRenderError(f"Ошибка рендера декларации: {e}", cause=e) from e

    # -------- Без штампов — отдаём 4-страничный PDF --------
    if not req.stamps.enabled:
        return declaration_pdf, f"declaration_{req.taxpayer.inn}_{req.tax_period_year}.pdf"

    # -------- 6. Данные ИФНС (нужны для штампов И для квитанций) --------
    # Если пользователь передал override из UI (заполнил вручную или после DaData preview)
    # — используем его и не зовём DaData. Это позволяет работать без DADATA_API_KEY.
    if req.stamps.ifts_info_override is not None:
        from modules.edo_stamps import IftsInfo
        ov = req.stamps.ifts_info_override
        ifts_info = IftsInfo(
            inn=ov.inn,
            name=ov.name,
            address=ov.address,
            manager_name=ov.manager_name,
            manager_post=ov.manager_post,
        )
    else:
        await tracker.emit(PipelineStage.FETCHING_IFTS)
        try:
            from modules.edo_stamps import fetch_ifts_data
            ifts_info = await fetch_ifts_data(
                ifns_code=req.taxpayer.ifns_code,
                override_inn=req.stamps.tax_authority_inn,
            )
        except Exception as e:
            raise DaDataError(f"Ошибка получения данных ИФНС: {e}", cause=e) from e

    # -------- 7. Квитанции ФНС (КНД 1166002 + КНД 1166007) — опционально --------
    full_pdf = declaration_pdf
    signing_dt = _resolve_signing_datetime(req.stamps.signing_datetime_override)

    if req.stamps.include_receipts:
        await tracker.emit(PipelineStage.APPENDING_RECEIPTS)
        try:
            from modules.table_renderer.receipts import (
                ReceiptRenderData, render_receipt_pages,
            )
            from modules.edo_stamps import assemble_full_package
            from modules.edo_stamps.receipt_data import (
                compute_receipt_timestamps,
                generate_document_uuid,
                generate_file_name,
                generate_registration_number,
            )

            op = req.stamps.operator.value if hasattr(req.stamps.operator, "value") else str(req.stamps.operator)

            # Параметры: override → авто-генерация
            document_uuid = req.stamps.document_uuid_override or generate_document_uuid(op)  # type: ignore
            registration_number = req.stamps.registration_number_override or generate_registration_number()
            file_name = generate_file_name(
                operator=op,  # type: ignore
                ifns_code=req.taxpayer.ifns_code,
                declarant_inn=req.taxpayer.inn,
                date=signing_dt,
                document_uuid=document_uuid,
            )
            # Таймстампы: override → auto
            if req.stamps.submission_datetime_override:
                submission_dt = _resolve_signing_datetime(req.stamps.submission_datetime_override)
            else:
                submission_dt = compute_receipt_timestamps(signing_datetime=signing_dt, operator=op).submission  # type: ignore
            if req.stamps.acceptance_datetime_override:
                acceptance_dt = _resolve_signing_datetime(req.stamps.acceptance_datetime_override)
            else:
                acceptance_dt = compute_receipt_timestamps(signing_datetime=signing_dt, operator=op).acceptance  # type: ignore

            # ФИО налогоплательщика + ИНН в виде как отображается в квитанции
            taxpayer_fio_with_inn = f"{req.taxpayer.fio}, {req.taxpayer.inn}"

            rec_data = ReceiptRenderData(
                taxpayer_inn=req.taxpayer.inn,
                taxpayer_fio=taxpayer_fio_with_inn,
                ifns_code=req.taxpayer.ifns_code,
                ifts_full_name=ifts_info.name or "",
                declaration_knd="1152017",
                correction_number=req.correction_number,
                tax_period_year=req.tax_period_year,
                file_name=file_name,
                submission_datetime=submission_dt,
                acceptance_datetime=acceptance_dt,
                registration_number=registration_number,
            )
            receipts_pdf = render_receipt_pages(rec_data)
            full_pdf = assemble_full_package(
                declaration_pdf=declaration_pdf,
                receipts_pdf=receipts_pdf,
            )
        except Exception as e:
            raise ReceiptsRenderError(f"Ошибка генерации квитанций: {e}", cause=e) from e

    # -------- 8. Штампы ЭДО на весь пакет (4 или 6 страниц) --------
    await tracker.emit(PipelineStage.RENDERING_STAMPS)
    try:
        from modules.edo_stamps import apply_stamps
        stamped_pdf: bytes = apply_stamps(
            pdf_bytes=full_pdf,
            operator=req.stamps.operator,
            taxpayer_inn=req.taxpayer.inn,
            ifts_info=ifts_info,
            tax_office_code=req.taxpayer.ifns_code,
            signing_datetime=signing_dt,
        )
    except Exception as e:
        raise StampRenderError(f"Ошибка наложения штампов: {e}", cause=e) from e

    await tracker.emit(PipelineStage.COMPLETE)

    filename = f"declaration_{req.taxpayer.inn}_{req.tax_period_year}_signed.pdf"
    return stamped_pdf, filename
