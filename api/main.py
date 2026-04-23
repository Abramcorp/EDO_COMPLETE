"""
FastAPI entry point.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import text

from api.db import SessionLocal, dispose_db, init_db
from api.jobs import JobStore
from api.models import HealthResponse
from api.routers import complete, jobs

__version__ = "0.1.0"

# ============================================================
# Logging
# ============================================================
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = os.environ.get("LOG_FORMAT", "console")

logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
    if _LOG_FORMAT == "console"
    else "%(message)s",
)
log = logging.getLogger("usn_complete")


# ============================================================
# Lifespan
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting up…")

    # Инициализация БД (в dev создаёт таблицы; в prod — миграции через Alembic,
    # но init_db безопасен: create_all не пересоздаёт существующие таблицы)
    await init_db()

    # Восстановление после рестарта: running jobs помечаем как failed
    async with SessionLocal() as session:
        store = JobStore(session)
        orphaned = await store.recover_orphaned_running()
        if orphaned:
            log.warning("Recovered %d orphaned running jobs as failed", orphaned)

        ttl_hours = int(os.environ.get("JOB_TTL_HOURS", "24"))
        deleted = await store.cleanup_stale(ttl_hours=ttl_hours)
        if deleted:
            log.info("Cleaned up %d stale jobs (TTL=%dh)", deleted, ttl_hours)

    log.info("Ready.")
    yield

    log.info("Shutting down…")
    await dispose_db()


# ============================================================
# App
# ============================================================
app = FastAPI(
    title="USN_COMPLETE",
    description="Единый пайплайн: декларация УСН 6% + штампы ЭДО в одном PDF",
    version=__version__,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS — явный список из env
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Routers
app.include_router(complete.router)
app.include_router(jobs.router)


# Health check
@app.get("/api/health", response_model=HealthResponse, tags=["meta"])
async def health_check() -> HealthResponse:
    db_status = "ok"
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "down"
    return HealthResponse(status="ok", db=db_status, version=__version__)


@app.get("/", include_in_schema=False)
async def root():
    """Отдаёт UI (если есть) или JSON fallback."""
    ui_index = Path(__file__).resolve().parent.parent / "ui" / "index.html"
    if ui_index.exists():
        return HTMLResponse(content=ui_index.read_text(encoding="utf-8"))
    return {
        "service": "usn_complete",
        "version": __version__,
        "docs": "/api/docs",
    }


# Статика UI (CSS/JS, если добавится)
_ui_dir = Path(__file__).resolve().parent.parent / "ui"
if _ui_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_ui_dir), html=True), name="ui")
