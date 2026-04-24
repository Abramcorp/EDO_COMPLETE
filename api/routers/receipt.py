"""
POST /api/receipt/preview-params — генерация параметров квитанций ФНС
для UI-превью ("Сгенерировать параметры").

Возвращает UUID документа, регистрационный номер, имя файла и все
4 таймстампа. UI может показать их в редактируемых полях — если
пользователь оставит без изменений, pipeline сам сгенерит те же
значения; если исправит — override через stamps.*_override.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.models import ReceiptParamsRequest, ReceiptParamsResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/receipt", tags=["receipt"])


@router.post(
    "/preview-params",
    response_model=ReceiptParamsResponse,
    summary="Сгенерировать параметры квитанций (UUID, регномер, таймстампы)",
)
def preview_params(req: ReceiptParamsRequest) -> ReceiptParamsResponse:
    """Возвращает все параметры квитанций для отображения в UI."""
    try:
        from core.pipeline import _resolve_signing_datetime
        from modules.edo_stamps.receipt_data import (
            compute_receipt_timestamps,
            generate_document_uuid,
            generate_file_name,
            generate_registration_number,
        )
    except ImportError as e:
        raise HTTPException(500, f"Не удалось загрузить receipt_data: {e}")

    try:
        signing_dt = _resolve_signing_datetime(req.signing_datetime)
    except ValueError as e:
        raise HTTPException(422, f"Неверный формат signing_datetime: {e}")

    op = req.operator.value

    try:
        doc_uuid = generate_document_uuid(op)  # type: ignore[arg-type]
        file_name = generate_file_name(
            operator=op,  # type: ignore[arg-type]
            ifns_code=req.ifns_code,
            declarant_inn=req.declarant_inn,
            date=signing_dt,
            document_uuid=doc_uuid,
        )
        reg_number = generate_registration_number()
        ts = compute_receipt_timestamps(signing_datetime=signing_dt, operator=op)  # type: ignore[arg-type]
    except Exception as e:
        log.exception("Receipt preview generation failed")
        raise HTTPException(500, f"Ошибка генерации параметров: {e}")

    return ReceiptParamsResponse(
        document_uuid=doc_uuid,
        registration_number=reg_number,
        file_name=file_name,
        submission_datetime=ts.submission.isoformat(),
        acceptance_datetime=ts.acceptance.isoformat(),
        processing_datetime=ts.processing.isoformat(),
    )
