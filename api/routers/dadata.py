"""
POST /api/dadata/lookup-ifts — запрос данных налогового органа через DaData.

Нужен для UI-wizard: пользователь на шаге 4 нажимает "Запросить данные ИФНС",
UI получает название, адрес, ИНН, начальника — показывает редактируемо.
Данные потом передаются в stamps.ifts_info_override при генерации.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dadata", tags=["dadata"])


class IftsLookupRequest(BaseModel):
    ifns_code: str = Field(..., min_length=4, max_length=4, description="4-значный код ИФНС")
    # Если передан — lookup по ИНН органа; иначе — по коду ИФНС
    tax_authority_inn: Optional[str] = Field(None, min_length=10, max_length=10)


class IftsLookupResponse(BaseModel):
    inn: str
    name: str
    address: str
    manager_name: str = ""
    manager_post: str = ""
    lookup_by: str = Field(..., description="'inn' | 'ifns_code'")


@router.post(
    "/lookup-ifts",
    response_model=IftsLookupResponse,
    summary="Получить данные налогового органа через DaData",
)
async def lookup_ifts(req: IftsLookupRequest) -> IftsLookupResponse:
    if not os.environ.get("DADATA_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail=(
                "DADATA_API_KEY не задан на сервере. "
                "Заполните поля ИФНС вручную — они попадут в stamps.ifts_info_override."
            ),
        )

    try:
        from modules.edo_stamps import fetch_ifts_data
    except ImportError as e:
        raise HTTPException(500, f"Модуль edo_stamps недоступен: {e}")

    try:
        info = await fetch_ifts_data(
            ifns_code=req.ifns_code,
            override_inn=req.tax_authority_inn,
        )
    except ValueError as e:
        raise HTTPException(404, f"DaData: {e}")
    except RuntimeError as e:
        # fetch_ifts_data сам строит понятные сообщения (401/403/429/5xx/timeout)
        raise HTTPException(502, str(e))
    except Exception as e:
        log.exception("DaData lookup failed")
        raise HTTPException(502, f"Ошибка обращения к DaData: {e}")

    return IftsLookupResponse(
        inn=info.inn,
        name=info.name,
        address=info.address,
        manager_name=info.manager_name,
        manager_post=info.manager_post,
        lookup_by="inn" if req.tax_authority_inn else "ifns_code",
    )
