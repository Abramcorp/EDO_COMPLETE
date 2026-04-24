"""
Adapter для modules/edo_stamps/*.

Оригинал: https://github.com/Abramcorp/edo-stamps

Оригинальный apply_stamps() принимает ПУТИ к файлам. Наш pipeline работает
на BytesIO (stateless). Этот adapter оборачивает apply_stamps в bytes-API.

ВАЖНО: файлы edo_core.py, edo_kontur.py, edo_tensor.py, edo_stamp.py
должны быть скопированы сюда через scripts/sync_stamps.sh ДО импорта.
Шрифты копируются в fonts/.
"""
from __future__ import annotations

import secrets
import tempfile
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


# ============================================================
# DTO для ответа fetch_ifts_data
# ============================================================

@dataclass
class IftsInfo:
    """Данные налогового органа для штампа получателя."""
    inn: str
    name: str
    address: str
    manager_name: str = ""
    manager_post: str = ""


# ============================================================
# Lazy imports (чтобы ImportError не ломал старт приложения)
# ============================================================

def _src_core():
    from . import edo_core
    return edo_core


def _src_stamp_shim():
    # shim-модуль edo_stamp экспортирует Party, StampConfig, apply_stamps, cert generators
    # edo_stamp.py использует абсолютные импорты (from edo_core, from edo_tensor, ...)
    # Эти файлы лежат в папке modules/edo_stamps/, которой может не быть в sys.path.
    # Добавляем её перед импортом, чтобы shim работал.
    import sys
    from pathlib import Path
    _stamps_dir = str(Path(__file__).parent)
    if _stamps_dir not in sys.path:
        sys.path.insert(0, _stamps_dir)
    from . import edo_stamp
    return edo_stamp


# ============================================================
# fetch_ifts_data — async обёртка над DaData
# ============================================================

import os
import httpx

DADATA_PARTY_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
DADATA_FNS_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/fns_unit"


async def fetch_ifts_data(ifns_code: str, override_inn: str | None = None) -> IftsInfo:
    """
    Резолвит данные ИФНС для штампа получателя через DaData.

    Args:
        ifns_code: 4-значный код ИФНС
        override_inn: если указан — используется как ИНН налогового органа
                      без запроса к DaData

    Returns:
        IftsInfo с полями для штампа
    """
    token = os.environ.get("DADATA_API_KEY", "")
    if not token:
        raise RuntimeError(
            "DADATA_API_KEY не задан в окружении. "
            "Заполните данные ИФНС вручную в UI — они попадут в "
            "ifts_info_override и DaData не потребуется."
        )

    if override_inn:
        return await _lookup_party(override_inn, token)
    return await _lookup_fns_unit(ifns_code, token)


async def _dadata_post_with_retry(
    url: str, token: str, query: str, max_retries: int = 2,
) -> dict:
    """POST в DaData с retry при network-ошибках и понятными сообщениями на HTTP-коды."""
    import asyncio as _asyncio
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Authorization": f"Token {token}",
                    },
                    json={"query": query.strip()},
                )
            if resp.status_code in (401, 403):
                raise RuntimeError(
                    f"DaData вернул {resp.status_code}: неверный или истёкший "
                    f"DADATA_API_KEY. Проверь токен в переменных окружения."
                )
            if resp.status_code == 429:
                raise RuntimeError(
                    "DaData вернул 429 (rate limit превышен). "
                    "Подожди минуту или увеличь лимит в тарифе."
                )
            if resp.status_code >= 500:
                raise RuntimeError(
                    f"DaData временно недоступна (HTTP {resp.status_code}). "
                    f"Попробуй ещё раз или заполни данные ИФНС вручную."
                )
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            last_exc = e
            if attempt < max_retries:
                await _asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise RuntimeError(
                f"DaData недоступна (network error после {max_retries + 1} попыток): {e}. "
                f"Заполни данные ИФНС вручную или выбери 'Без штампа'."
            ) from e
    raise last_exc or RuntimeError("DaData: unknown error")


async def _lookup_party(inn: str, token: str) -> IftsInfo:
    """Запрос findById/party (по ИНН) с retry и defensive parsing."""
    data = await _dadata_post_with_retry(DADATA_PARTY_URL, token, inn)
    suggestions = data.get("suggestions", [])

    if not suggestions:
        raise ValueError(f"DaData: ничего не найдено по ИНН {inn}")

    d = suggestions[0].get("data") or {}
    manager = _as_dict(d.get("management"))
    full_name = _as_dict(d.get("name")).get("full_with_opf", "") or suggestions[0].get("value", "")
    address = _as_dict(d.get("address")).get("unrestricted_value", "")

    return IftsInfo(
        inn=inn,
        name=full_name,
        address=address,
        manager_name=manager.get("name", ""),
        manager_post=manager.get("post", ""),
    )


async def _lookup_fns_unit(ifns_code: str, token: str) -> IftsInfo:
    """Запрос findById/fns_unit (по коду ИФНС) с retry и defensive parsing.

    Поле address может прийти как строка или как dict — _as_dict защищает."""
    data = await _dadata_post_with_retry(DADATA_FNS_URL, token, ifns_code)
    suggestions = data.get("suggestions", [])

    if not suggestions:
        raise ValueError(f"DaData: не найден ИФНС с кодом {ifns_code}")

    d = suggestions[0].get("data") or {}
    address_obj = _as_dict(d.get("address"))
    address = (
        address_obj.get("unrestricted_value")
        or address_obj.get("value")
        or (d.get("address") if isinstance(d.get("address"), str) else "")
        or ""
    )

    return IftsInfo(
        inn=d.get("inn", "") or "",
        name=suggestions[0].get("value", "") or "",
        address=address,
    )


def _as_dict(v: Any) -> dict:
    """Защитный cast: если v не dict — вернуть пустой dict.

    Лечит баг 'str' object has no attribute 'get': DaData иногда возвращает
    поля строками вместо dict (или None)."""
    return v if isinstance(v, dict) else {}


# ============================================================
# apply_stamps — bytes API над file-based оригиналом
# ============================================================

def apply_stamps(
    *,
    pdf_bytes: bytes,
    operator: Any,          # api.models.EdoOperator (enum)
    taxpayer_inn: str,
    ifts_info: IftsInfo,
    tax_office_code: str,
    signing_datetime: datetime | None = None,
    doc_uuid: str | None = None,
) -> bytes:
    """
    Накладывает штамп ЭДО (Контур или Тензор) на PDF.

    Args:
        pdf_bytes: готовая декларация без штампов
        operator: EdoOperator.KONTUR или EdoOperator.TENSOR
        taxpayer_inn: ИНН отправителя (ИП)
        ifts_info: данные получателя (ИФНС)
        tax_office_code: 4-значный код ИФНС
        send_date: дата отправки (по умолчанию — сейчас)
        doc_uuid: uuid документа (если None — генерируется)

    Returns:
        bytes PDF со штампом
    """
    core = _src_core()
    shim = _src_stamp_shim()

    op_value = operator.value if hasattr(operator, "value") else str(operator)
    send_dt = signing_datetime or datetime.now()

    if op_value == "kontur":
        cfg = core.StampConfig(
            operator="kontur",
            tax_office_code=tax_office_code,
            inn=taxpayer_inn,
            send_date=send_dt.strftime("%Y%m%d"),
            doc_uuid=doc_uuid or str(secrets.token_hex(16)),
            sender=core.Party(
                name="",                                  # ФИО отправителя; подключим в UI
                datetime_msk=send_dt.strftime("%d.%m.%Y в %H:%M"),
                certificate=shim.gen_cert_kontur(),
                cert_valid_from=(send_dt.replace(year=send_dt.year - 1)).strftime("%d.%m.%Y"),
                cert_valid_to=(send_dt.replace(year=send_dt.year + 1)).strftime("%d.%m.%Y"),
            ),
            receiver=core.Party(
                name=ifts_info.name,
                role=f"{ifts_info.manager_post} {ifts_info.manager_name}".strip(),
                datetime_msk=send_dt.strftime("%d.%m.%Y в %H:%M"),
                certificate="",
            ),
        )
    elif op_value == "tensor":
        cfg = core.StampConfig(
            operator="tensor",
            identifier=doc_uuid or str(secrets.token_hex(16)),
            sender=core.Party(
                name="",
                role="",
                datetime_msk=send_dt.strftime("%d.%m.%Y %H:%M"),
                certificate=shim.gen_cert_send_tensor(),
            ),
            receiver=core.Party(
                name=ifts_info.name,
                role=f"{ifts_info.manager_name}, {ifts_info.manager_post}".strip(", ").strip(),
                datetime_msk=send_dt.strftime("%d.%m.%Y %H:%M"),
                certificate=shim.gen_cert_ifns_tensor(),
            ),
        )
    else:
        raise ValueError(f"Неизвестный оператор: {op_value}")

    # Оригинальный apply_stamps принимает пути — пишем во временные файлы
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_in:
        tmp_in.write(pdf_bytes)
        in_path = tmp_in.name
    out_path = in_path.replace(".pdf", "_stamped.pdf")

    try:
        core.apply_stamps(in_path, out_path, cfg)
        return Path(out_path).read_bytes()
    finally:
        Path(in_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


# ============================================================
# Квитанции ФНС: КНД 1166002 + КНД 1166007 (см. ADR-003)
# ============================================================

def build_receipt_pages(
    *,
    operator: Any,
    taxpayer,                    # api.models.TaxpayerInfo
    tax_period_year: int,
    correction_number: int,
    ifts_info: IftsInfo,
    signing_datetime: datetime,
    document_uuid_override: str | None = None,
    registration_number_override: str | None = None,
    submission_datetime_override: datetime | None = None,
    acceptance_datetime_override: datetime | None = None,
) -> bytes:
    """
    Рендерит 2 страницы квитанций как единый PDF:
      - стр. 1: КНД 1166002 «Квитанция о приёме»
      - стр. 2: КНД 1166007 «Извещение о вводе сведений»

    Загружает подложки templates/knd_NNNNNNN/blank.pdf и координатные карты
    templates/knd_NNNNNNN/fields.json, накладывает overlay через reportlab,
    merge'ит через pypdf (zero-loss).

    Данные (UUID, имя файла, регистрационный номер, таймстампы) генерируются
    здесь через receipt_data.* функции — если не переданы override-параметры.

    Args:
        document_uuid_override: UUID документа (если None — генерируется)
        registration_number_override: 20-значный регистрационный номер
        submission_datetime_override: дата отправки в ФНС
        acceptance_datetime_override: дата приёма ФНС
    """
    from .receipt_data import (
        compute_receipt_timestamps,
        generate_document_uuid,
        generate_file_name,
        generate_registration_number,
    )
    from .receipt_renderer import ReceiptRenderData, render_receipt_pages

    op_value = operator.value if hasattr(operator, "value") else str(operator)

    # Реквизиты: используем override если переданы, иначе автогенерация.
    doc_uuid = document_uuid_override or generate_document_uuid(op_value)  # type: ignore[arg-type]
    file_name = generate_file_name(
        operator=op_value,  # type: ignore[arg-type]
        ifns_code=taxpayer.ifns_code,
        declarant_inn=taxpayer.inn,
        date=signing_datetime,
        document_uuid=doc_uuid,
    )
    reg_number = registration_number_override or generate_registration_number()
    timestamps = compute_receipt_timestamps(
        signing_datetime=signing_datetime,
        operator=op_value,  # type: ignore[arg-type]
    )
    submission_dt = submission_datetime_override or timestamps.submission
    acceptance_dt = acceptance_datetime_override or timestamps.acceptance

    # Разбиение полного имени ИФНС на 2 строки (как в шаблоне КНД 1166002).
    # Эвристика: делим примерно пополам по ближайшему пробелу.
    full = (ifts_info.name or "").strip()
    if len(full) > 30:
        mid = len(full) // 2
        # Ищем ближайший пробел к середине
        left_space = full.rfind(" ", 0, mid + 10)
        split_pt = left_space if left_space > 0 else mid
        line1 = full[:split_pt].rstrip()
        line2 = full[split_pt:].lstrip()
    else:
        line1, line2 = full, ""

    data = ReceiptRenderData(
        taxpayer_inn=taxpayer.inn,
        taxpayer_fio=taxpayer.fio,
        representative_inn="",           # если будем различать представителя — расширить
        representative_fio="",
        ifns_code=taxpayer.ifns_code,
        ifns_full_name_line1=line1,
        ifns_full_name_line2=line2,
        ifns_full_name_upper=full.upper(),
        declaration_knd="1152017",
        correction_number=correction_number,
        tax_period_year=tax_period_year,
        file_name=file_name,
        submission_datetime=submission_dt,
        acceptance_datetime=acceptance_dt,
        registration_number=reg_number,
    )

    return render_receipt_pages(data)


def assemble_full_package(
    *,
    declaration_pdf: bytes,
    receipts_pdf: bytes,
) -> bytes:
    """
    Склеивает 4-страничную декларацию + 2-страничные квитанции в единый PDF (6 страниц).
    """
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for page in PdfReader(BytesIO(declaration_pdf)).pages:
        writer.add_page(page)
    for page in PdfReader(BytesIO(receipts_pdf)).pages:
        writer.add_page(page)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


# ============================================================
# Public API
# ============================================================
__all__ = [
    "IftsInfo",
    "fetch_ifts_data",
    "apply_stamps",
    "build_receipt_pages",
    "assemble_full_package",
]
