# ADR-001: Архитектура USN_COMPLETE

**Статус:** Accepted
**Дата:** 22.04.2026
**Автор решения:** Валентин + Claude (engineering merge mode)

## Контекст

Нужно объединить два существующих проекта:
- `usn-declaration` — CRUD-приложение на FastAPI+SQLite с wizard-мастером и XLSX-заполнителем декларации УСН 6%, конвертация в PDF через LibreOffice
- `edo-stamps` — сервис на Railway, накладывает штампы ЭДО (Контур/Тензор) на PDF

Требование: один API-вызов → готовый подписанный PDF декларации.

## Ключевые решения

### 1. Переиспользование кода: копирование `services/`

**Выбрано:** Скопировать `app/services/*.py` из `usn-declaration` в `modules/declaration_filler/` с фиксированным commit hash оригинала в `docs/SOURCES_INVENTORY.md`.

**Отвергнуто:**
- Git submodules — сложный деплой, хрупкость при изменениях исходников
- pip-пакеты — оверинжиниринг для двух проектов одного владельца
- Импорт FastAPI приложения целиком — исходный проект слишком сильно завязан на БД и wizard

**Цена:** ручной sync при обновлениях исходников. Решается скриптом `scripts/sync_sources.sh`.

### 2. Рендер PDF декларации: reportlab, без LibreOffice

**Выбрано:** использовать существующий `declaration_generator.py` (1048 строк, reportlab) как основу для PDF-рендера. LibreOffice исключается полностью.

**Отвергнуто:**
- LibreOffice в Docker — +700 MB образ, 20 сек cold start на Railway
- pymupdf с PDF-подложкой ФНС — дублирует уже существующую в `declaration_generator.py` координатную разметку
- Сохранение XLSX-пути — не решает проблему конвертации в PDF

**Цена:** `declaration_generator.py` даёт «визуально близкую» форму (по комментарию автора), не pixel-perfect. На Фазе 0c сравнить с эталонами ФНС, при расхождениях — достроить подложкой.

### 3. Рендер штампов

**Решение отложено** до анализа стека edo-stamps. Варианты:
- Если edo-stamps на pymupdf — используем pymupdf
- Если на reportlab — сводим всё на reportlab (образ ещё легче)
- Если на pdfrw/PyPDF2 — мигрируем на pymupdf ради качества overlay

### 4. Pipeline: stateless, in-memory

**Выбрано:** весь pipeline работает на BytesIO. Никаких `uploads/`/`outputs/` директорий на диске.

**Отвергнуто:**
- Файловая система (уходит при рестарте Railway)
- Railway Volume (стоит денег, single-instance binding)
- S3 (лишняя зависимость для MVP)

**Цена:** всё должно влезать в RAM одного job'а. Оценка: выписка до 10 МБ + 2 PDF по 200 КБ = 10–15 МБ/job. На Railway 512 МБ RAM это 30+ параллельных job'ов — запас есть.

### 5. Постоянство состояния: Postgres только для `jobs`

**Выбрано:** Railway Postgres с одной таблицей `jobs` (status, progress, result_blob, error, timestamps). Никакие бизнес-таблицы из usn-declaration (Project, BankOperation и т.д.) не переносим.

**Отвергнуто:**
- In-memory jobs dict — теряются при рестарте, ломают polling
- Миграция всей схемы usn-declaration — нет wizard'а, нет CRUD, таблицы не нужны
- Redis — дополнительная инфра для одной таблицы

**Цена:** result PDF хранится в BYTEA колонке (до 1 МБ). Roadmap: вынести в S3/R2 при росте трафика.

### 6. Выполнение pipeline: FastAPI BackgroundTasks

**Выбрано:** для MVP — `BackgroundTasks`, pipeline выполняется в том же процессе что и API.

**Отвергнуто:**
- arq + Redis worker — правильно для prod, но оверкилл для MVP одного инстанса
- Celery — тяжёлый
- Синхронный endpoint — таймауты на Cloudflare/прокси при pipeline >30 сек

**Цена:**
- При рестарте контейнера running-jobs остаются в status='running' навсегда → нужен cleanup-startup-hook, который помечает осиротевшие jobs как failed
- Не масштабируется горизонтально

**Roadmap:** при росте нагрузки — миграция на arq + отдельный worker-сервис Railway.

### 7. Wizard из usn-declaration: не используем

**Выбрано:** пишем свой `/api/complete/*` оркестратор, stateless, без БД бизнес-логики.

**Отвергнуто:** адаптация 4-шагового wizard'а — он stateful и требует всех таблиц БД usn-declaration.

**Цена:** не переиспользуем 686 строк `wizard.py`. Но сама оркестрация проще (линейный pipeline) и stateless — в итоге кода меньше.

## API-контракты

### POST /api/complete/create-declaration

Вход (multipart/form-data):
- `statement` (file, required) — 1С-выписка .txt
- `ofd` (file, optional) — чеки ОФД .xlsx
- `meta` (JSON string, required) — `DeclarationRequest` модель (см. `api/models.py`)

Выход: `{ job_id: "uuid", status_url: "/api/jobs/{id}" }`, код 202 Accepted

### GET /api/jobs/{id}

Выход:
```json
{
  "id": "uuid",
  "status": "queued|running|complete|failed",
  "stage": "parsing_statement|...|complete",
  "progress_pct": 0..100,
  "error": null | { "code": "...", "message": "..." },
  "result_url": null | "/api/jobs/{id}/result"
}
```

### GET /api/jobs/{id}/result

StreamingResponse с PDF. Доступен только при `status=complete`, иначе 409.

## Error handling

Типированные ошибки в `core/errors.py`:
- `StatementParseError` — невалидная 1С-выписка
- `OfdParseError` — невалидный ОФД-файл
- `TaxCalculationError` — ошибка в расчёте
- `RenderError` — reportlab упал
- `DaDataError` — не удалось получить данные ИФНС
- `StampRenderError` — штамп не поместился / ошибка overlay

Каждая ошибка сохраняется в `jobs.error` как `{code, message, stage}`. Stack trace — в лог.

## Observability

- Logging: structlog, JSON format в prod, console в dev
- Каждый job имеет request_id = job_id, прокидывается через pipeline
- Health check: `GET /api/health` — включает проверку БД

## Безопасность

- CORS: явный список доменов через `CORS_ORIGINS` env var, не `*`
- Size limits на multipart: 10 МБ statement, 5 МБ OFD (через `fastapi.UploadFile`)
- DaData credentials — только из env, никогда не в коде
- Result TTL: jobs и их результаты удаляются через `JOB_TTL_HOURS` (дефолт 24ч), cleanup задача при старте

## Что НЕ сделано на MVP (roadmap)

1. Multi-worker (arq + Redis)
2. Rate limiting
3. Аутентификация
4. S3 для больших result-blob
5. Sentry для ошибок
6. Миграция БД через Alembic (сейчас скрипт init_jobs_table.sql создаёт вручную)
7. E2E тесты с реальными выписками
