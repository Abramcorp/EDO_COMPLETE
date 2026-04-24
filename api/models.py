"""
Pydantic-модели API-контрактов USN_COMPLETE.

Три группы:
  1. Входные модели заявки (DeclarationRequest и подструктуры)
  2. Job lifecycle (JobStatus, JobResponse, ErrorInfo)
  3. Общие типы (Quarter, EdoOperator)

Все модели — pydantic v2.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# Enums / const
# ============================================================

class EdoOperator(str, Enum):
    KONTUR = "kontur"
    TENSOR = "tensor"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class PipelineStage(str, Enum):
    """Стадии pipeline. Прогресс привязан к стадии через core/progress.py."""
    INITIALIZING = "initializing"
    PARSING_STATEMENT = "parsing_statement"
    PARSING_OFD = "parsing_ofd"
    CLASSIFYING = "classifying"
    CALCULATING_TAX = "calculating_tax"
    RENDERING_DECLARATION = "rendering_declaration"
    FETCHING_IFTS = "fetching_ifts"
    APPENDING_RECEIPTS = "appending_receipts"
    RENDERING_STAMPS = "rendering_stamps"
    COMPLETE = "complete"


# ============================================================
# Входные модели (DeclarationRequest)
# ============================================================

class TaxpayerInfo(BaseModel):
    """Данные налогоплательщика для титульного листа."""
    model_config = ConfigDict(str_strip_whitespace=True)

    inn: str = Field(..., min_length=10, max_length=12, description="ИНН ИП (10 или 12 цифр)")
    fio: str = Field(..., min_length=3, max_length=255, description="ФИО полностью")
    oktmo: str = Field(..., min_length=8, max_length=11, description="ОКТМО (8 или 11 цифр)")
    ifns_code: str = Field(..., min_length=4, max_length=4, description="Код ИФНС (4 цифры)")

    @field_validator("inn")
    @classmethod
    def _validate_inn(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("ИНН должен содержать только цифры")
        if len(v) not in (10, 12):
            raise ValueError("ИНН должен быть 10 или 12 цифр")
        return v

    @field_validator("oktmo")
    @classmethod
    def _validate_oktmo(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("ОКТМО должен содержать только цифры")
        if len(v) not in (8, 11):
            raise ValueError("ОКТМО должен быть 8 или 11 цифр")
        return v


class ContributionsInfo(BaseModel):
    """Страховые взносы ИП — кумулятивные суммы на конец каждого отчётного периода."""
    q1: Decimal = Field(Decimal("0"), ge=0, description="На 31 марта")
    half_year: Decimal = Field(Decimal("0"), ge=0, description="На 30 июня")
    nine_months: Decimal = Field(Decimal("0"), ge=0, description="На 30 сентября")
    year: Decimal = Field(Decimal("0"), ge=0, description="На 31 декабря")


class PersonnelInfo(BaseModel):
    """Работники и взносы за работников (влияет на лимит уменьшения налога)."""
    has_employees: bool = False
    employee_start_quarter: Optional[int] = Field(None, ge=1, le=4)
    avg_salary: Decimal = Field(Decimal("0"), ge=0)
    num_employees: int = Field(0, ge=0)


class StampsConfig(BaseModel):
    """Конфиг для наложения штампов ЭДО."""
    enabled: bool = True
    operator: EdoOperator = EdoOperator.KONTUR
    # ИНН налогового органа (получателя) — если не указан, резолвим через DaData по ifns_code
    tax_authority_inn: Optional[str] = None
    # Добавлять ли страницы квитанций КНД 1166002 + КНД 1166007 (см. ADR-003).
    # False: PDF из 4 страниц (как современный КОНТУР-образец)
    # True:  PDF из 6 страниц (как ТЕНЗОР-образец)
    include_receipts: bool = True
    # Опциональное явно заданное время подписания (для тестов / офлайн-режима).
    # Если None — берётся now() в MSK при старте pipeline.
    signing_datetime_override: Optional[str] = None  # ISO8601


class MonthlyIncomeItem(BaseModel):
    """Помесячный доход (используется как override — значения с UI-wizard'а)."""
    month: int = Field(..., ge=1, le=12)
    cashless: Decimal = Field(Decimal("0"), ge=0, description="Безнал за месяц")
    cash: Decimal = Field(Decimal("0"), ge=0, description="Наличка за месяц")


class DeclarationRequest(BaseModel):
    """Единая модель заявки — передаётся в поле `meta` multipart-формы как JSON."""
    model_config = ConfigDict(str_strip_whitespace=True)

    taxpayer: TaxpayerInfo
    tax_period_year: int = Field(..., ge=2020, le=2030)
    contributions: ContributionsInfo = ContributionsInfo()
    personnel: PersonnelInfo = PersonnelInfo()
    stamps: StampsConfig = StampsConfig()
    # Номер корректировки — 0 для первичной, 1, 2, ... для уточнённой
    correction_number: int = Field(0, ge=0, le=99)
    # Если передан — используется вместо пересчёта из выписки.
    # Формируется UI-wizard'ом после шага 2 (пользователь отредактировал).
    monthly_income_override: Optional[list[MonthlyIncomeItem]] = None


# ============================================================
# Contributions preview (для UI-кнопки "Рассчитать автоматически")
# ============================================================

class ContributionsPreviewRequest(BaseModel):
    """Вход для /api/contributions/preview."""
    year: int = Field(..., ge=2020, le=2030)
    annual_income: Decimal = Field(..., ge=0, description="Общий годовой доход (безнал+нал)")
    has_employees: bool = False
    avg_salary: Decimal = Field(Decimal("0"), ge=0)
    num_employees: int = Field(0, ge=0)


class ContributionsPreviewResponse(BaseModel):
    """Результат авторасчёта страховых взносов."""
    # Детализация
    ip_fixed: int = Field(..., description="Фиксированный взнос ИП за себя")
    ip_1pct: int = Field(..., description="1% с доходов свыше 300 000")
    employee_total: int = Field(0, description="Взносы за работников (за год)")
    # Кумулятивные суммы по периодам (для заполнения полей ContributionsInfo)
    q1: int
    half_year: int
    nine_months: int
    year: int


# ============================================================
# Job lifecycle
# ============================================================

class ErrorInfo(BaseModel):
    code: str
    message: str
    stage: Optional[PipelineStage] = None


class JobAccepted(BaseModel):
    """Response для POST /api/complete/create-declaration (202)."""
    job_id: UUID
    status_url: str
    result_url: str


class JobResponse(BaseModel):
    """Response для GET /api/jobs/{id}."""
    id: UUID
    status: JobStatus
    stage: PipelineStage
    progress_pct: int = Field(..., ge=0, le=100)
    error: Optional[ErrorInfo] = None
    result_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ============================================================
# Health
# ============================================================

class HealthResponse(BaseModel):
    status: str
    db: str  # "ok" | "degraded" | "down"
    version: str
