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
        raise RuntimeError("DADATA_API_KEY не задан в окружении")

    # Если явно передали ИНН — получаем данные по нему через findById/party
    # Иначе — через findById/fns_unit по коду ИФНС
    if override_inn:
        return await _lookup_party(override_inn, token)
    return await _lookup_fns_unit(ifns_code, token)


async def _lookup_party(inn: str, token: str) -> IftsInfo:
    """Запрос findById/party (по ИНН)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            DADATA_PARTY_URL,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Token {token}",
            },
            json={"query": inn.strip()},
        )
        resp.raise_for_status()
        suggestions = resp.json().get("suggestions", [])

    if not suggestions:
        raise ValueError(f"DaData: ничего не найдено по ИНН {inn}")

    d = suggestions[0]["data"]
    manager = d.get("management") or {}
    full_name = (d.get("name") or {}).get("full_with_opf", "") or suggestions[0].get("value", "")
    address = (d.get("address") or {}).get("unrestricted_value", "")

    return IftsInfo(
        inn=inn,
        name=full_name,
        address=address,
        manager_name=manager.get("name", ""),
        manager_post=manager.get("post", ""),
    )


async def _lookup_fns_unit(ifns_code: str, token: str) -> IftsInfo:
    """Запрос findById/fns_unit (по коду ИФНС)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            DADATA_FNS_URL,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Token {token}",
            },
            json={"query": ifns_code.strip()},
        )
        resp.raise_for_status()
        suggestions = resp.json().get("suggestions", [])

    if not suggestions:
        raise ValueError(f"DaData: не найден ИФНС с кодом {ifns_code}")

    d = suggestions[0]["data"]
    return IftsInfo(
        inn=d.get("inn", ""),
        name=suggestions[0].get("value", ""),
        address=d.get("address", {}).get("unrestricted_value", ""),
    )


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
) -> bytes:
    """
    Рендерит 2 страницы квитанций как единый PDF:
      - стр. 1: КНД 1166002 «Квитанция о приёме»
      - стр. 2: КНД 1166007 «Извещение о вводе сведений»

    Данные для полей генерируются через receipt_data:
      - UUID, имя файла, регистрационный номер, таймстампы.

    TODO: Реализация требует:
      1. templates/knd_1166002/blank.pdf + fields.json (разметка координат)
      2. templates/knd_1166007/blank.pdf + fields.json
      3. Рендер через reportlab canvas + pypdf merge_page на подложки.

    Сейчас возвращает placeholder — 2 пустые A4-страницы с отметкой "TODO".
    Полная реализация — в Фазе 0c.
    """
    from io import BytesIO
    from pypdf import PdfWriter
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas

    from .receipt_data import (
        compute_receipt_timestamps,
        generate_document_uuid,
        generate_file_name,
        generate_registration_number,
    )

    op_value = operator.value if hasattr(operator, "value") else str(operator)

    # Генерируем все реквизиты один раз — они будут ОДИНАКОВЫМИ на обеих страницах
    doc_uuid = generate_document_uuid(op_value)  # type: ignore[arg-type]
    file_name = generate_file_name(
        operator=op_value,  # type: ignore[arg-type]
        ifns_code=taxpayer.ifns_code,
        declarant_inn=taxpayer.inn,
        date=signing_datetime,
        document_uuid=doc_uuid,
    )
    reg_number = generate_registration_number()
    timestamps = compute_receipt_timestamps(
        signing_datetime=signing_datetime,
        operator=op_value,  # type: ignore[arg-type]
    )

    # TODO (Фаза 0c): заменить на рендер на PDF-подложках ФНС.
    # Сейчас placeholder: 2 пустых страницы с текстом-маркером.
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    for page_name, knd in [
        ("Квитанция о приёме", "1166002"),
        ("Извещение о вводе сведений", "1166007"),
    ]:
        c.setFont("Helvetica", 14)
        c.drawString(50, 780, f"[PLACEHOLDER] КНД {knd} — {page_name}")
        c.setFont("Helvetica", 9)
        c.drawString(50, 750, f"Налогоплательщик: {taxpayer.fio} (ИНН {taxpayer.inn})")
        c.drawString(50, 735, f"Налоговый орган: {ifts_info.name}")
        c.drawString(50, 720, f"Имя файла: {file_name}")
        c.drawString(50, 705, f"Регистрационный №: {reg_number}")
        c.drawString(50, 690, f"Представлено: {timestamps.submission.strftime('%d.%m.%Y %H:%M:%S')} MSK")
        c.drawString(50, 675, f"Принято: {timestamps.acceptance.strftime('%d.%m.%Y %H:%M:%S')} MSK")
        c.drawString(50, 660, f"Идентификатор: {doc_uuid}")
        c.drawString(50, 620, "⚠ Placeholder. Реальный рендер — после разметки fields.json (см. ADR-003).")
        c.showPage()
    c.save()
    return buf.getvalue()


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
