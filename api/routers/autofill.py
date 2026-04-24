"""
POST /api/autofill/by-inn — единая кнопка "Сгенерировать параметры".

По ИНН налогоплательщика одним вызовом собирает ВСЁ:
1. DaData party: ОКТМО + ФИО + код ИФНС по регистрации + адрес
2. DaData fns_unit: название ИФНС + адрес + начальник
3. receipt_data.*: UUID + регномер + имя файла + таймстампы квитанций

UI отображает всё это readonly в блоке "ПРОВЕРЬТЕ ИФНС И ОКТМО" с
возможностью исправить вручную.
"""
from __future__ import annotations

import logging
import os
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
    signing_datetime: Optional[str] = None  # ISO8601 / русский
    tax_period_year: int = Field(2025, ge=2020, le=2099)


class AutofillByInnResponse(BaseModel):
    # Из DaData party (по ИНН)
    fio: str = Field("", description="ФИО ИП или название юрлица")
    oktmo: str = Field("", description="ОКТМО по адресу регистрации")
    ifns_code: str = Field("", description="Код ИФНС регистрации")
    taxpayer_address: str = ""

    # Из DaData fns_unit (по коду ИФНС)
    ifts_inn: str = ""
    ifts_name: str = ""
    ifts_address: str = ""
    ifts_manager_name: str = ""
    ifts_manager_post: str = ""

    # Сгенерированные параметры квитанций
    document_uuid: str = ""
    registration_number: str = ""
    file_name: str = ""
    submission_datetime: str = ""
    acceptance_datetime: str = ""

    # Диагностика
    warnings: list[str] = []


@router.post(
    "/by-inn",
    response_model=AutofillByInnResponse,
    summary="Собрать ВСЁ по ИНН (DaData + генерация квитанций)",
)
async def autofill_by_inn(req: AutofillByInnRequest) -> AutofillByInnResponse:
    """Одним вызовом заполняет максимум полей по ИНН.

    Не падает целиком если часть данных не нашлась — возвращает что
    получилось + список warnings. UI может применить частичный ответ.
    """
    warnings: list[str] = []
    token = os.environ.get("DADATA_API_KEY", "")
    if not token:
        raise HTTPException(
            status_code=503,
            detail=(
                "DADATA_API_KEY не задан. Включите fallback на ручной ввод "
                "в UI или настройте токен на сервере."
            ),
        )

    from modules.edo_stamps import _dadata_post_with_retry, _as_dict

    # ============================================================
    # Шаг 1: DaData party по ИНН → ОКТМО + ФИО + код ИФНС + адрес
    # ============================================================
    PARTY_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
    try:
        party_data = await _dadata_post_with_retry(PARTY_URL, token, req.inn)
    except Exception as e:
        raise HTTPException(502, f"DaData party: {e}")

    suggestions = party_data.get("suggestions", [])
    if not suggestions:
        raise HTTPException(404, f"DaData не нашёл организацию по ИНН {req.inn}")

    d = suggestions[0].get("data") or {}
    name_dict = _as_dict(d.get("name"))
    addr_dict = _as_dict(d.get("address"))
    addr_data = _as_dict(addr_dict.get("data"))

    fio = (
        name_dict.get("full_with_opf", "")
        or suggestions[0].get("value", "")
        or ""
    )
    oktmo = addr_data.get("oktmo", "") or ""
    ifns_code = addr_data.get("tax_office", "") or ""
    taxpayer_address = addr_dict.get("unrestricted_value", "") or ""

    if not oktmo:
        warnings.append(f"DaData не вернул ОКТМО для ИНН {req.inn}")
    if not ifns_code:
        warnings.append(f"DaData не вернул код ИФНС для ИНН {req.inn}")

    # ============================================================
    # Шаг 2: DaData fns_unit по коду ИФНС → название + начальник
    # ============================================================
    ifts_inn = ""
    ifts_name = ""
    ifts_address = ""
    ifts_manager_name = ""
    ifts_manager_post = ""

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

    # ============================================================
    # Шаг 3: Параметры квитанций (UUID, регномер, таймстампы)
    # ============================================================
    document_uuid = ""
    registration_number = ""
    file_name = ""
    submission_dt = ""
    acceptance_dt = ""

    try:
        from core.pipeline import _resolve_signing_datetime
        from modules.edo_stamps.receipt_data import (
            compute_receipt_timestamps,
            generate_document_uuid,
            generate_file_name,
            generate_registration_number,
        )
        sign_dt = _resolve_signing_datetime(req.signing_datetime)
        op = req.operator.value
        document_uuid = generate_document_uuid(op)  # type: ignore[arg-type]
        registration_number = generate_registration_number()
        if ifns_code:
            file_name = generate_file_name(
                operator=op,  # type: ignore[arg-type]
                ifns_code=ifns_code,
                declarant_inn=req.inn,
                date=sign_dt,
                document_uuid=document_uuid,
            )
        ts = compute_receipt_timestamps(signing_datetime=sign_dt, operator=op)  # type: ignore[arg-type]
        submission_dt = ts.submission.isoformat()
        acceptance_dt = ts.acceptance.isoformat()
    except Exception as e:
        log.exception("Receipt params generation failed")
        warnings.append(f"Генерация параметров квитанций: {e}")

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
        registration_number=registration_number,
        file_name=file_name,
        submission_datetime=submission_dt,
        acceptance_datetime=acceptance_dt,
        warnings=warnings,
    )
