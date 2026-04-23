"""
E2E smoke test: полный pipeline на sqlite БД с замоканными модулями.

Проверяет:
  - Создание job через POST /api/complete/create-declaration
  - Обработку через BackgroundTasks
  - Прогресс и финальный статус через GET /api/jobs/{id}
  - Скачивание результата через GET /api/jobs/{id}/result

Модули declaration_filler и edo_stamps заменены заглушками, которые
возвращают фиктивные PDF bytes. Этот тест проверяет именно orchestration
слой, а не бизнес-логику.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest


# Устанавливаем sqlite для тестов ДО любых импортов из api/
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def initialized_client(monkeypatch):
    """
    Инициализирует БД (create_all) и подменяет плоские функции adapter'а
    на тестовые заглушки через monkeypatching modules.declaration_filler.
    """
    from httpx import AsyncClient, ASGITransport
    import types

    # Создаём минимальный пакет modules.declaration_filler с плоскими функциями
    mod = types.ModuleType("modules.declaration_filler")
    mod.parse_1c_statement_bytes = lambda data: {"operations": [], "owner_inn": "770123456789"}
    mod.parse_ofd_bytes = lambda data: []
    mod.classify_operations = lambda st: {"income": [], "expense": []}
    mod.tax_engine_calculate = lambda **kwargs: {"tax_due": 0, "revenue_by_quarter": [0, 0, 0, 0]}
    mod.render_declaration_pdf = lambda **kwargs: b"%PDF-1.4\nfake declaration\n%%EOF"

    sys.modules["modules.declaration_filler"] = mod

    # 2. Импортируем app и инициализируем БД
    from api.db import init_db
    await init_db()

    from api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_full_pipeline_without_stamps(initialized_client):
    """Pipeline без штампов должен завершиться успешно с фейковым PDF."""
    meta = {
        "taxpayer": {
            "inn": "770123456789",
            "fio": "Иванов Иван Иванович",
            "oktmo": "45382000",
            "ifns_code": "7701",
        },
        "tax_period_year": 2024,
        "contributions": {"q1": "0", "half_year": "30000", "nine_months": "30000", "year": "49500"},
        "personnel": {"has_employees": False},
        "stamps": {"enabled": False, "operator": "kontur"},
    }

    # 1. POST → 202 + job_id
    r = await initialized_client.post(
        "/api/complete/create-declaration",
        data={"meta": json.dumps(meta)},
        files={"statement": ("statement.txt", b"fake 1C content", "text/plain")},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    job_id = body["job_id"]
    assert body["status_url"].endswith(job_id)
    assert body["result_url"].endswith(f"{job_id}/result")

    # 2. Ждём завершения (с таймаутом)
    final = None
    for _ in range(30):
        await asyncio.sleep(0.2)
        r = await initialized_client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        final = r.json()
        if final["status"] in ("complete", "failed"):
            break

    assert final is not None
    assert final["status"] == "complete", f"Expected complete, got {final}"
    assert final["progress_pct"] == 100
    assert final["stage"] == "complete"
    assert final["error"] is None
    assert final["result_url"] is not None

    # 3. Скачиваем результат
    r = await initialized_client.get(f"/api/jobs/{job_id}/result")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_pipeline_fails_on_bad_statement(initialized_client, monkeypatch):
    """Если parser бросает — job должен завершиться со status=failed."""
    import sys
    mod = sys.modules["modules.declaration_filler"]
    original = mod.parse_1c_statement_bytes

    def _bad_parse(data):
        raise ValueError("looks like garbage")

    mod.parse_1c_statement_bytes = _bad_parse

    try:
        meta = {
            "taxpayer": {"inn": "770123456789", "fio": "Иванов Иван", "oktmo": "45382000", "ifns_code": "7701"},
            "tax_period_year": 2024,
            "contributions": {"q1": "0", "half_year": "0", "nine_months": "0", "year": "0"},
            "personnel": {"has_employees": False},
            "stamps": {"enabled": False, "operator": "kontur"},
        }

        r = await initialized_client.post(
            "/api/complete/create-declaration",
            data={"meta": json.dumps(meta)},
            files={"statement": ("s.txt", b"garbage", "text/plain")},
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]

        final = None
        for _ in range(30):
            await asyncio.sleep(0.2)
            r = await initialized_client.get(f"/api/jobs/{job_id}")
            final = r.json()
            if final["status"] in ("complete", "failed"):
                break

        assert final["status"] == "failed"
        assert final["error"]["code"] == "STATEMENT_PARSE_ERROR"
        assert final["error"]["stage"] == "parsing_statement"
        assert "garbage" in final["error"]["message"]
    finally:
        mod.parse_1c_statement_bytes = original


@pytest.mark.asyncio
async def test_result_409_for_failed_job(initialized_client):
    """GET /result для failed job должен возвращать 409."""
    import sys
    mod = sys.modules["modules.declaration_filler"]
    original = mod.parse_1c_statement_bytes
    mod.parse_1c_statement_bytes = lambda data: (_ for _ in ()).throw(ValueError("boom"))

    try:
        meta = {
            "taxpayer": {"inn": "770123456789", "fio": "Тест", "oktmo": "45382000", "ifns_code": "7701"},
            "tax_period_year": 2024,
            "contributions": {"q1": "0", "half_year": "0", "nine_months": "0", "year": "0"},
            "personnel": {"has_employees": False},
            "stamps": {"enabled": False, "operator": "kontur"},
        }
        r = await initialized_client.post(
            "/api/complete/create-declaration",
            data={"meta": json.dumps(meta)},
            files={"statement": ("s.txt", b"content", "text/plain")},
        )
        job_id = r.json()["job_id"]

        # Ждём пока не станет failed
        for _ in range(30):
            await asyncio.sleep(0.1)
            r = await initialized_client.get(f"/api/jobs/{job_id}")
            if r.json()["status"] == "failed":
                break

        # Теперь /result — должен 409
        r = await initialized_client.get(f"/api/jobs/{job_id}/result")
        assert r.status_code == 409
    finally:
        mod.parse_1c_statement_bytes = original
