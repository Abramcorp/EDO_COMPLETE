"""
POST /api/autofill/by-inn — единая кнопка "Сгенерировать параметры".

По ИНН налогоплательщика одним вызовом собирает ВСЁ (по логике
портированной из https://github.com/Abramcorp/edo-stamps):

1. DaData party → ОКТМО + ФИО + код ИФНС + адрес
2. DaData fns_unit (по коду ИФНС) → имя ИФНС + ИНН + адрес
3. stamps_generator:
   - Реалистичные даты отправки/приёма (рабочий день 21 янв - 19 апр
     для первичной декларации; корр ≥1 — 25 апр - 30 ноя; 9-18 MSK)
   - Два сертификата (отправитель + получатель) с периодами действия
     в 25-75% годового окна
   - UUID документа + идентификатор отправки (отдельный UUID)
   - ФИО начальника ИФНС — детерминированно по SHA256(ifns_code) с
     FALLBACK для известных ИФНС
   - Регистрационный номер ФНС (20 цифр)
   - Имя файла по стандарту ФНС NO_USN_{ifns}_{ifns}_{inn}_{date}_{uuid}

UI отображает всё в блоке "ПРОВЕРЬТЕ ИФНС И ОКТМО" с редактируемыми полями.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.models import EdoOperator

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autofill", tags=["autofill"])


class AutofillByInnRequest(BaseModel):
    inn: str = Field(..., min_length=10, max_length=12,
                     description="ИНН налогоплательщика (10=ЮЛ, 12=ИП)")
    operator: EdoOperator = EdoOperator.TENSOR
    signing_datetime: Optional[str] = None
    tax_period_year: int = Field(2025, ge=2020, le=2099)
    correction_number: int = Field(0, ge=0, le=99)


class AutofillByInnResponse(BaseModel):
    # DaData party
    fio: str = ""
    oktmo: str = ""
    ifns_code: str = ""
    taxpayer_address: str = ""

    # DaData fns_unit
    ifts_inn: str = ""
    ifts_name: str = ""
    ifts_address: str = ""

    # Сгенерировано stamps_generator (реалистично)
    ifts_manager_name: str = ""
    ifts_manager_post: str = ""
    document_uuid: str = ""
    identifier: str = ""
    registration_number: str = ""
    file_name: str = ""
    sender_dt: str = ""
    recv_dt: str = ""
    submission_datetime: str = ""
    acceptance_datetime: str = ""
    sender_cert: str = ""
    recv_cert: str = ""
    sender_cert_from: str = ""
    sender_cert_to: str = ""
    recv_cert_from: str = ""
    recv_cert_to: str = ""

    warnings: list[str] = []


@router.post(
    "/by-inn",
    response_model=AutofillByInnResponse,
    summary="Собрать ВСЁ по ИНН (DaData + генерация параметров штампов)",
)
async def autofill_by_inn(req: AutofillByInnRequest) -> AutofillByInnResponse:
    """Одним вызовом заполняет максимум полей по ИНН.
    Не падает целиком — возвращает частичный ответ + warnings."""
    warnings: list[str] = []
    token = os.environ.get("DADATA_API_KEY", "")
    if not token:
        raise HTTPException(
            status_code=503,
            detail="DADATA_API_KEY не задан. Заполните поля вручную.",
        )

    from modules.edo_stamps import _dadata_post_with_retry, _as_dict
    from modules.stamps_generator import (
        generate_uuid,
        generate_datetime_pair,
        generate_cert_dates,
        generate_certificate,
        generate_fns_manager_name,
        get_manager_post,
        generate_registration_number,
        generate_file_name,
    )

    op = req.operator.value if hasattr(req.operator, "value") else str(req.operator)

    # === Шаг 1: DaData party по ИНН ===
    PARTY_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
    try:
        party_data = await _dadata_post_with_retry(PARTY_URL, token, req.inn)
    except Exception as e:
        raise HTTPException(502, f"DaData party: {e}")

    suggestions = party_data.get("suggestions", [])
    if not suggestions:
        raise HTTPException(404, f"DaData не нашёл организацию/ИП по ИНН {req.inn}")

    d = suggestions[0].get("data") or {}
    name_dict = _as_dict(d.get("name"))
    addr_dict = _as_dict(d.get("address"))
    addr_data = _as_dict(addr_dict.get("data"))

    fio = name_dict.get("full_with_opf", "") or suggestions[0].get("value", "") or ""
    oktmo = addr_data.get("oktmo", "") or ""
    ifns_code = addr_data.get("tax_office", "") or ""
    taxpayer_address = addr_dict.get("unrestricted_value", "") or ""

    if not oktmo:
        warnings.append(f"DaData не вернул ОКТМО для ИНН {req.inn}")
    if not ifns_code:
        warnings.append(f"DaData не вернул код ИФНС для ИНН {req.inn}")

    # === Шаг 2: DaData fns_unit по коду ИФНС ===
    ifts_inn = ""
    ifts_name = ""
    ifts_address = ""

    if ifns_code:
        FNS_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/fns_unit"
        try:
            fns_data = await _dadata_post_with_retry(FNS_URL, token, ifns_code)
            fns_suggestions = fns_data.get("suggestions", [])
            if fns_suggestions:
                fd = fns_suggestions[0].get("data") or {}
                ifts_inn = fd.get("inn", "") or ""
                ifts_name = fns_suggestions[0].get("value", "") or ""
                fns_addr = _as_dict(fd.get("address"))
                ifts_address = (
                    fns_addr.get("unrestricted_value")
                    or fns_addr.get("value")
                    or (fd.get("address") if isinstance(fd.get("address"), str) else "")
                    or ""
                )
            else:
                warnings.append(f"DaData fns_unit: не найден ИФНС {ifns_code}")
        except Exception as e:
            warnings.append(f"DaData fns_unit: {e}")

    # === Шаг 3: stamps_generator ===
    ifts_manager_name = generate_fns_manager_name(ifns_code) if ifns_code else ""
    ifts_manager_post = get_manager_post(ifns_code, op) if ifns_code else ""

    # Даты
    send_date_yyyymmdd: Optional[str] = None
    if req.signing_datetime:
        try:
            from core.pipeline import _resolve_signing_datetime
            _dt = _resolve_signing_datetime(req.signing_datetime)
            send_date_yyyymmdd = _dt.strftime("%Y%m%d")
        except Exception:
            send_date_yyyymmdd = None

    try:
        dates = generate_datetime_pair(
            send_date=send_date_yyyymmdd,
            report_year=req.tax_period_year,
            correction=req.correction_number,
        )
    except Exception as e:
        log.exception("generate_datetime_pair failed")
        warnings.append(f"Генерация дат: {e}")
        dates = {
            "tensor_send": "", "tensor_recv": "",
            "kontur_send": "", "kontur_recv": "",
            "dt_send_iso": "", "dt_recv_iso": "",
            "send_date_yyyymmdd": "",
        }

    document_uuid = generate_uuid()
    identifier = generate_uuid()

    try:
        _dt_send = datetime.strptime(dates.get("send_date_yyyymmdd", ""), "%Y%m%d")
    except Exception:
        _dt_send = datetime.now()
    sender_cert_from, sender_cert_to = generate_cert_dates(_dt_send)
    recv_cert_from, recv_cert_to = generate_cert_dates(_dt_send)
    while recv_cert_from == sender_cert_from:
        recv_cert_from, recv_cert_to = generate_cert_dates(_dt_send)
    sender_cert = generate_certificate(op, is_receiver=False)
    recv_cert = generate_certificate(op, is_receiver=True)

    registration_number = generate_registration_number()
    file_name = generate_file_name(
        ifns_code=ifns_code or "0000",
        declarant_inn=req.inn,
        date_yyyymmdd=dates.get("send_date_yyyymmdd", ""),
        document_uuid=document_uuid,
    ) if ifns_code else ""

    if op == "tensor":
        sender_dt = dates.get("tensor_send", "")
        recv_dt = dates.get("tensor_recv", "")
    else:
        sender_dt = dates.get("kontur_send", "")
        recv_dt = dates.get("kontur_recv", "")

    return AutofillByInnResponse(
        fio=fio,
        oktmo=oktmo,
        ifns_code=ifns_code,
        taxpayer_address=taxpayer_address,
        ifts_inn=ifts_inn,
        ifts_name=ifts_name,
        ifts_address=ifts_address,
        ifts_manager_name=ifts_manager_name,
        ifts_manager_post=ifts_manager_post,
        document_uuid=document_uuid,
        identifier=identifier,
        registration_number=registration_number,
        file_name=file_name,
        sender_dt=sender_dt,
        recv_dt=recv_dt,
        submission_datetime=dates.get("dt_send_iso", ""),
        acceptance_datetime=dates.get("dt_recv_iso", ""),
        sender_cert=sender_cert,
        recv_cert=recv_cert,
        sender_cert_from=sender_cert_from,
        sender_cert_to=sender_cert_to,
        recv_cert_from=recv_cert_from,
        recv_cert_to=recv_cert_to,
        warnings=warnings,
    )
