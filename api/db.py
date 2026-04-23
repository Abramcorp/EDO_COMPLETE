"""
Async SQLAlchemy: engine, session, ORM-таблица jobs.

Единственная таблица в проекте. Бизнес-данные (Project, BankOperation и т.д.)
в БД не хранятся — pipeline stateless.
"""
from __future__ import annotations

import os
from datetime import datetime, UTC
from typing import AsyncGenerator

from sqlalchemy import CHAR, Column, DateTime, Integer, LargeBinary, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON as GenericJSON
import uuid as _uuid


# ============================================================
# Config
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://usn:usn@localhost:5432/usn",
)

# Railway иногда выдаёт URL в формате postgres:// — нормализуем в postgresql+asyncpg://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


engine_kwargs: dict = {
    "pool_pre_ping": True,
    "echo": False,
}
# SQLite (dev / tests) не поддерживает pool_size / max_overflow
if not DATABASE_URL.startswith("sqlite"):
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10

engine = create_async_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


# ============================================================
# Base ORM
# ============================================================

class Base(DeclarativeBase):
    pass


# ============================================================
# Cross-dialect types (Postgres в prod, SQLite в dev/tests)
# ============================================================

class GUID(TypeDecorator):
    """UUID: postgresql.UUID в postgres, CHAR(36) в sqlite."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return value
        return _uuid.UUID(value)


class JSONType(TypeDecorator):
    """JSONB в postgres, JSON в sqlite."""
    impl = GenericJSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(GenericJSON())


class JobRow(Base):
    """
    Одна таблица для хранения состояния pipeline jobs.
    Результат (PDF до 1-2 МБ) хранится прямо в BYTEA колонке.
    Для больших объёмов в будущем — вынести в S3/R2.
    """
    __tablename__ = "jobs"

    id = Column(GUID(), primary_key=True)
    status = Column(String(20), nullable=False, index=True)  # queued|running|complete|failed
    stage = Column(String(40), nullable=False, default="initializing")
    progress_pct = Column(Integer, nullable=False, default=0)

    # Метаданные входа (без самих файлов) — для диагностики
    input_meta = Column(JSONType, nullable=True)

    # Результат — полный PDF байтами. NULL пока не готов.
    result_blob = Column(LargeBinary, nullable=True)
    result_filename = Column(String(255), nullable=True)

    # Ошибка — JSON {code, message, stage}. NULL если нет
    error = Column(JSONType, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


# ============================================================
# Session dependency
# ============================================================

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


# ============================================================
# Init / teardown (вызывается из lifespan)
# ============================================================

async def init_db() -> None:
    """
    Создаёт таблицы если их нет.
    В prod Alembic должен быть основным путём — эта функция как fallback для dev.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    await engine.dispose()
