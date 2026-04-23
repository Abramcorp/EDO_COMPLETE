# USN_COMPLETE

**Единый пайплайн для создания подписанных деклараций УСН 6%.**

Объединяет функциональность двух проектов в один stateless сервис:
- **usn-declaration** — парсинг 1С-выписки, расчёт налога, генерация PDF декларации КНД 1152017
- **edo-stamps** — наложение штампов ЭДО (Контур.Эльба / СБИС-Тензор)

## Как работает

```
┌────────────────────┐      ┌──────────────────────┐      ┌─────────────────┐
│ POST /complete     │      │ Background pipeline  │      │ GET /jobs/{id}  │
│ (multipart + JSON) ├─────▶│  1. parse statement  │      │ → status        │
└────────────────────┘      │  2. parse OFD        │      │ GET .../result  │
         │                  │  3. calc tax         │◀─────┤ → PDF stream    │
         ▼                  │  4. render pdf       │      └─────────────────┘
  { job_id: uuid }          │  5. fetch IFTS       │
                            │  6. apply stamps     │
                            └──────────┬───────────┘
                                       │
                                       ▼
                                ┌─────────────┐
                                │  Postgres   │
                                │   (jobs)    │
                                └─────────────┘
```

## Стек

- Python 3.12 + FastAPI + Pydantic v2
- async SQLAlchemy 2.0 + asyncpg (только для таблицы `jobs`)
- reportlab (рендер декларации) + pymupdf (overlay штампов)
- Docker slim (~250 MB, **без LibreOffice**)
- Деплой: Railway

## Быстрый старт (local)

```bash
cp .env.example .env
# отредактируй DATABASE_URL, DADATA_API_KEY
docker compose up --build
```

Открой http://localhost:8000/api/docs

## Структура

```
usn_complete/
├── api/                    # FastAPI слой
│   ├── main.py             # приложение, CORS, lifespan
│   ├── models.py           # Pydantic-модели API-контрактов
│   ├── db.py               # async SQLAlchemy engine
│   ├── jobs.py             # JobStore (CRUD для jobs)
│   └── routers/
│       ├── complete.py     # POST /api/complete/create-declaration
│       └── jobs.py         # GET /api/jobs/{id}[/result]
├── core/                   # Pipeline / бизнес-оркестрация
│   ├── pipeline.py         # главный оркестратор стадий
│   ├── progress.py         # прогресс-колбэки
│   └── errors.py           # типированные ошибки pipeline
├── modules/
│   ├── declaration_filler/ # ⬅ services/ из usn-declaration (см. scripts/sync_sources.sh)
│   └── edo_stamps/         # ⬅ adapter для edo-stamps
├── templates/
│   ├── knd_1152017/        # PDF-подложки и fields.json
│   └── stamps/             # координаты штампов kontur/tensor
├── migrations/             # Alembic (async)
├── scripts/
│   └── sync_sources.sh     # копирование services/ из исходных репо
├── docs/
│   └── ADR-001-architecture.md
├── Dockerfile
├── railway.toml
├── pyproject.toml
├── requirements.txt
└── .env.example
```

## Документы

- [ADR-001: архитектура](docs/ADR-001-architecture.md)
- [SOURCES_INVENTORY.md](docs/SOURCES_INVENTORY.md)

## Статус

🟡 Фаза 0: скелет проекта и архитектурные решения зафиксированы. Следующий шаг — копирование sources и реализация pipeline.
