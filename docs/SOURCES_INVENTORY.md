# SOURCES_INVENTORY — obsah dvoch repo

**Дата:** 23.04.2026
**Scope:** оба репо (usn-declaration + edo-stamps)

## Репозитории

| Имя | URL | Commit | Статус |
|---|---|---|---|
| usn-declaration | https://github.com/Abramcorp/usn-declaration | HEAD `main` | ✅ проанализирован |
| edo-stamps | https://github.com/Abramcorp/edo-stamps | HEAD `main` | ✅ проанализирован |

---

## 1. usn-declaration

Подробный инвентарь — см. предыдущую версию (9500 строк, FastAPI + SQLite + LibreOffice).
Ключевое для merge:

**Переиспользуем (services/):**
- `parser.py` (875) — `BankStatementParser` для 1С-выписки
- `ofd_parser.py` (579) — `parse_ofd_file(path)` для ОФД-чеков
- `classifier.py` (299) — `OperationClassifier` (требует БД → даём stateless subclass)
- `tax_engine.py` (403) — `TaxEngine.calculate()` + `get_declaration_data()`
- `contributions_calculator.py` (296) — `compute_total_contributions()`
- `dictionaries/income_markers.json`, `exclude_markers.json`

**Не переиспользуем:**
- `declaration_generator.py` (1048) — рисует «близко к форме», не pixel-perfect → ❌ исключён по ADR-002
- `excel_declaration.py` (659) — XLSX-заполнитель → не нужен, т.к. выбран pdf-overlay путь
- `xlsx_to_pdf.py` (259) — LibreOffice → удалён из стека

**Шаблоны (переносим):**
- `data/declaration_template.xlsx`
- `data/declaration_template_2024.xlsx`
- `data/declaration_template_2025.xlsx`

ВАЖНО: XLSX-шаблоны — для справки/разметки координат. Финальный рендер через PDF-подложку ФНС (см. ADR-002).

---

## 2. edo-stamps

**Стек:** Flask 3.0 + reportlab 4.0 + **pypdf 4.0** + pdfplumber (чтение) + gunicorn.

**КЛЮЧЕВОЙ ФАКТ: НЕ pymupdf.** Overlay штампов через `pypdf.PdfWriter.merge_page()` — это чистый overlay без пересжатия базового PDF.

### Файлы

| Файл | Строк | Роль |
|---|---|---|
| `edo_core.py` | 216 | Модели (`Party`, `StampConfig`), `apply_stamps(inp, out, cfg)`, шрифты, метаданные PDF |
| `edo_kontur.py` | 346 | Рендер штампа Контур.Эльба (1 стр + N страниц) |
| `edo_tensor.py` | 256 | Рендер штампа СБИС/Тензор |
| `edo_stamp.py` | 117 | Обратносовместимый shim + CLI |
| `edo_app/app.py` | 1821 | Flask веб-интерфейс + DaData integration |
| `edo_app/fonts/` | 9.1 МБ | 14 шрифтов Tahoma / Segoe UI |

### Публичный API

```python
from edo_core import Party, StampConfig, apply_stamps

cfg = StampConfig(
    operator="kontur",           # или "tensor"
    tax_office_code="7734",
    inn="312772472951",
    send_date="20250127",
    doc_uuid="...",
    sender=Party(name="...", datetime_msk="...", certificate="...", cert_valid_from=..., cert_valid_to=...),
    receiver=Party(name="...", role="...", datetime_msk="...", certificate="..."),
)

apply_stamps("input.pdf", "output.pdf", cfg)   # ⚠ принимает ПУТИ, не bytes!
```

### DaData integration

В `edo_app/app.py`:
- `lookup_party(inn, token)` — возвращает `{name, manager_name, manager_post, fns_code, address}`
- URL: `https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party`
- Для ИФНС (по коду): `DADATA_FNS_URL = ".../findById/fns_unit"`

### Шрифты для штампов

Приоритет:
1. `tahoma.ttf` / `tahomabd.ttf` — эталон Тензора (7pt)
2. `segoeui.ttf` / `segoeuib.ttf` — Контур
3. Liberation Sans, FreeSans, DejaVu — системные fallback'и

**ВАЖНО:** в Docker образе USN_COMPLETE ОБЯЗАТЕЛЬНО должны быть скопированы Tahoma/Segoe UI из `edo_app/fonts/`. Без них штампы потеряют pixel-perfect.

### Нужно адаптировать

1. **Bytes API:** `apply_stamps(bytes, cfg) -> bytes` вместо `(path, path)`
2. **Async DaData:** переписать requests на httpx (для нашего async-стека)
3. **FNS lookup:** выделить из app.py в отдельный модуль
4. **Fallback руководителей ИФНС:** переносим (в app.py есть словарь)

### Что НЕ переносим

- `edo_app/app.py` целиком — это Flask UI, наш UI уже есть
- Flask как dependency — убираем из requirements
- gunicorn — не нужен (uvicorn используется)

---

## Объединённый стек USN_COMPLETE (пересмотр после анализа edo-stamps)

| Слой | Технология | Откуда |
|---|---|---|
| Runtime | Python 3.12 | usn-declaration |
| Web | FastAPI | usn-declaration |
| PDF рендер текста | **reportlab 4.2.5** | обоюдно (usn-declaration + edo-stamps) |
| PDF overlay | **pypdf 4.0+** | edo-stamps |
| PDF чтение | pdfplumber | edo-stamps (опционально) |
| ~~pymupdf~~ | **исключён** | был в моём плане, но избыточен |
| Async HTTP | httpx | вместо requests из edo-stamps |
| DB | PostgreSQL + asyncpg | наш |
| Deploy | Railway | обоюдно |

## Критическое решение стека

**Переход с pymupdf на pypdf.** pymupdf убираем из requirements.txt. Причины:

1. edo-stamps уже использует pypdf → совместимость
2. `pypdf.PdfWriter.merge_page()` делает zero-loss overlay (pixel-perfect требование — удовлетворено)
3. pypdf Apache 2.0, pymupdf AGPL-3.0 — pypdf дружелюбнее к коммерческому использованию
4. Меньше размер образа (pymupdf тащит C-библиотеки ~40 МБ)

---

## Pipeline после всех пересмотров

```
┌──────────────────────────────────────────────────────┐
│ 1. Parse statement (BankStatementParser)             │ → ops list
├──────────────────────────────────────────────────────┤
│ 2. Parse OFD (optional, OfdParser)                   │ → receipts
├──────────────────────────────────────────────────────┤
│ 3. Classify (stateless OperationClassifier)          │ → quarterly income
├──────────────────────────────────────────────────────┤
│ 4. Tax calc (TaxEngine + contributions_calculator)   │ → decl_data
├──────────────────────────────────────────────────────┤
│ 5. Render declaration PDF                            │ reportlab canvas → overlay
│    - Load blank_YYYY.pdf (ФНС подложка)              │    on pypdf.merge_page
│    - Generate overlay layer (только текст в клетки)  │    pixel-perfect!
│    - Merge overlay на подложку (zero-loss)           │
├──────────────────────────────────────────────────────┤
│ 6. Fetch IFTS (DaData, httpx async)                  │ → fns_code, name, address
├──────────────────────────────────────────────────────┤
│ 7. Apply EDO stamps (edo_core.apply_stamps)          │ reportlab + pypdf
│    - Bytes-adapter над apply_stamps(path, path, cfg) │
│    - Kontur или Tensor рендерер                      │
└──────────────────────────────────────────────────────┘
```

## Pixel-perfect test strategy

Тесты через `pypdf` + сравнение PDF-text-позиций или растеризацию через поддерживаемый инструмент:

**Вариант A:** `pdf2image` (Wand/Poppler) → PNG → Pillow `ImageChops.difference`
- Плюс: точное pixel-сравнение
- Минус: +Poppler в Docker (~50 МБ) или pypdfium2

**Вариант B:** `pypdfium2` (Pdfium wrapper) — рендер PDF→PNG нативно
- pip пакет, без системных зависимостей
- ~15 МБ

**Вариант C:** `pdfplumber` (уже в edo-stamps deps) — extract text + координаты, сравнивать позиции
- Без растеризации, просто сверяем что в координате (x, y) именно этот символ
- Быстрее, но не ловит визуальные регрессии

**Выбор: B (pypdfium2) для визуальных тестов + C (pdfplumber) для быстрых smoke-проверок координат.**
