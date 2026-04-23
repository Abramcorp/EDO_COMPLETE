"""
Прогресс-трекер. Маппит стадии на проценты и вызывает async callback.

Стратегия процентов:
  0  → initializing
  5  → parsing_statement начат
  15 → parsing_ofd
  25 → classifying
  40 → calculating_tax
  65 → rendering_declaration (тяжёлая стадия)
  80 → fetching_ifts (DaData)
  95 → rendering_stamps
  100 → complete
"""
from __future__ import annotations

from typing import Awaitable, Callable

from api.models import PipelineStage


# Разумные дефолты прогресса в начале каждой стадии
STAGE_PROGRESS: dict[PipelineStage, int] = {
    PipelineStage.INITIALIZING: 0,
    PipelineStage.PARSING_STATEMENT: 5,
    PipelineStage.PARSING_OFD: 15,
    PipelineStage.CLASSIFYING: 25,
    PipelineStage.CALCULATING_TAX: 40,
    PipelineStage.RENDERING_DECLARATION: 60,
    PipelineStage.FETCHING_IFTS: 75,
    PipelineStage.APPENDING_RECEIPTS: 85,
    PipelineStage.RENDERING_STAMPS: 95,
    PipelineStage.COMPLETE: 100,
}


ProgressCallback = Callable[[PipelineStage, int], Awaitable[None]]


class ProgressTracker:
    """
    Хелпер: `async with tracker.stage(PipelineStage.PARSING_STATEMENT): ...`
    не нужен. Достаточно `await tracker.emit(stage)`.
    """

    def __init__(self, callback: ProgressCallback):
        self._cb = callback

    async def emit(self, stage: PipelineStage, override_pct: int | None = None) -> None:
        pct = override_pct if override_pct is not None else STAGE_PROGRESS[stage]
        await self._cb(stage, pct)
