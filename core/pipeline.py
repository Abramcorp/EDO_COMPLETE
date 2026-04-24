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
    """Возвращает datetime подписания: либо из override (ISO8601), либо now() MSK."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    msk = ZoneInfo("Europe/Moscow")
    if override:
        dt = datetime.fromisoformat(override)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=msk)
        return dt.astimezone(msk)
    return datetime.now(msk)


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

    # -------- 5. Рендер PDF декларации (reportlab + pypdf overlay на ФНС-подложку) --------
    await tracker.emit(PipelineStage.RENDERING_DECLARATION)
    try:
        from modules.declaration_filler import render_declaration_pdf
        declaration_pdf: bytes = render_declaration_pdf(
            taxpayer=req.taxpayer,
            tax_period_year=req.tax_period_year,
            tax_result=tax_result,
        )
    except Exception as e:
        raise DeclarationRenderError(f"Ошибка рендера декларации: {e}", cause=e) from e

    # -------- Без штампов — отдаём 4-страничный PDF --------
    if not req.stamps.enabled:
        return declaration_pdf, f"declaration_{req.taxpayer.inn}_{req.tax_period_year}.pdf"

    # -------- 6. Данные ИФНС (нужны для штампов И для квитанций) --------
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
            from modules.edo_stamps import build_receipt_pages, assemble_full_package
            receipts_pdf = build_receipt_pages(
                operator=req.stamps.operator,
                taxpayer=req.taxpayer,
                tax_period_year=req.tax_period_year,
                correction_number=0,
                ifts_info=ifts_info,
                signing_datetime=signing_dt,
            )
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
