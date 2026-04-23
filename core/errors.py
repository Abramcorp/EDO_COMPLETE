"""
Типированные ошибки pipeline. Каждая мапится в ErrorInfo (api/models.py)
и сохраняется в jobs.error колонке.
"""
from __future__ import annotations

from api.models import PipelineStage


class PipelineError(Exception):
    """Базовый класс всех бизнес-ошибок pipeline."""
    code: str = "PIPELINE_ERROR"
    stage: PipelineStage = PipelineStage.INITIALIZING

    def __init__(self, message: str, *, cause: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.cause = cause


class StatementParseError(PipelineError):
    code = "STATEMENT_PARSE_ERROR"
    stage = PipelineStage.PARSING_STATEMENT


class OfdParseError(PipelineError):
    code = "OFD_PARSE_ERROR"
    stage = PipelineStage.PARSING_OFD


class ClassificationError(PipelineError):
    code = "CLASSIFICATION_ERROR"
    stage = PipelineStage.CLASSIFYING


class TaxCalculationError(PipelineError):
    code = "TAX_CALCULATION_ERROR"
    stage = PipelineStage.CALCULATING_TAX


class DeclarationRenderError(PipelineError):
    code = "DECLARATION_RENDER_ERROR"
    stage = PipelineStage.RENDERING_DECLARATION


class DaDataError(PipelineError):
    code = "DADATA_ERROR"
    stage = PipelineStage.FETCHING_IFTS


class StampRenderError(PipelineError):
    code = "STAMP_RENDER_ERROR"
    stage = PipelineStage.RENDERING_STAMPS


class ReceiptsRenderError(PipelineError):
    code = "RECEIPTS_RENDER_ERROR"
    stage = PipelineStage.APPENDING_RECEIPTS


class InputValidationError(PipelineError):
    code = "INPUT_VALIDATION_ERROR"
    stage = PipelineStage.INITIALIZING
