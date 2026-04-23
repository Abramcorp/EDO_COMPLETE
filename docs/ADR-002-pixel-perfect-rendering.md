# ADR-002: Pixel-perfect рендер + стек pypdf (без pymupdf)

**Статус:** Accepted
**Дата:** 23.04.2026
**Заменяет:** решения #2 и #3 из ADR-001
**Триггеры:**
1. Новое требование заказчика: «рендер только в максимальном качестве, для тестов использовать попиксельную проверку по координатам»
2. Анализ edo-stamps показал, что там **pypdf + reportlab**, не pymupdf

---

## Решение 1: Стек PDF — reportlab + pypdf, без pymupdf

**Выбрано.** Весь проект на одном стеке:
- `reportlab` — генерация overlay-слоя (текст в координатах)
- `pypdf` — открытие подложки ФНС, merge overlay, сохранение

**Отвергнуто: pymupdf.** Причины:
1. edo-stamps уже на pypdf → если добавлять pymupdf, будет два параллельных PDF-стека
2. pypdf.merge_page() даёт zero-loss overlay, как и pymupdf
3. Лицензирование: pypdf (Apache 2.0) vs pymupdf (AGPL-3.0)
4. Размер образа: pymupdf тянет MuPDF C-библиотеку (~40 МБ)

**Обновление requirements.txt:**
```diff
-pymupdf>=1.24.0
+pypdf>=4.0.0
+pdfplumber>=0.10.0        # для pixel-diff тестов (чтение координат)
+pypdfium2>=4.0.0          # для pixel-diff тестов (растеризация PDF→PNG)
+Pillow>=10.0.0            # для pixel-diff сравнения PNG
```

---

## Решение 2: Рендер декларации — PDF-подложка ФНС + координатный overlay

**Выбрано.** Финальная архитектура:

```
templates/knd_1152017/
├── blank_2024.pdf              ← официальный бланк ФНС (4 страницы)
├── blank_2025.pdf              ← форма 2025
├── fields_2024.json            ← координатная карта знакомест
├── fields_2025.json
└── reference/                  ← эталоны для pixel-diff
    ├── sample_01/
    │   ├── input.json          ← DeclarationRequest для рендера
    │   ├── expected.pdf        ← эталонный PDF
    │   └── expected_p{1..4}.png  ← растеризованные страницы 150 DPI
    └── sample_02/
```

### Алгоритм render_declaration_pdf(...)

```python
from io import BytesIO
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

def render_declaration_pdf(taxpayer, tax_period_year, tax_result) -> bytes:
    # 1. Загружаем подложку ФНС для нужного года
    blank_path = f"templates/knd_1152017/blank_{tax_period_year}.pdf"
    fields_map = load_fields_json(tax_period_year)

    # 2. Подготавливаем данные для каждой страницы
    page_data = prepare_page_data(taxpayer, tax_result)  # dict{page_idx: dict{field_name: value}}

    # 3. Генерируем overlay (reportlab canvas) — 4 страницы, каждая с наложенным текстом
    overlay_buf = BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=A4)
    c.setFont(fields_map["fonts"]["primary"]["name"], 11)  # зарегистрирован заранее

    for page_idx in range(1, fields_map["pages"] + 1):
        page_fields = fields_map["pages_def"][str(page_idx)]["fields"]
        for field_name, spec in page_fields.items():
            value = page_data.get(page_idx, {}).get(field_name)
            if value is None:
                continue
            render_field(c, spec, value)  # рисует в cells согласно spec
        c.showPage()
    c.save()

    # 4. Merge overlay на подложку (zero-loss pypdf)
    reader_base = PdfReader(blank_path)
    reader_overlay = PdfReader(overlay_buf)
    writer = PdfWriter()

    for i, base_page in enumerate(reader_base.pages):
        base_page.merge_page(reader_overlay.pages[i])
        writer.add_page(base_page)

    out_buf = BytesIO()
    writer.write(out_buf)
    return out_buf.getvalue()
```

### Формат fields_YYYY.json

```json
{
  "form_version": "2024",
  "pages": 4,
  "fonts": {
    "primary": {
      "name": "PTSans",
      "file": "templates/knd_1152017/fonts/PT_Sans.ttf",
      "size": 11
    }
  },
  "pages_def": {
    "1": {
      "fields": {
        "inn": {
          "type": "char_cells",
          "cells": [
            [72.0, 790.5], [84.0, 790.5], [96.0, 790.5],
            [108.0, 790.5], [120.0, 790.5], [132.0, 790.5],
            [144.0, 790.5], [156.0, 790.5], [168.0, 790.5],
            [180.0, 790.5], [192.0, 790.5], [204.0, 790.5]
          ],
          "align": "center"
        },
        "fio_line_1": {
          "type": "char_cells",
          "cells": [ /* координаты 40 клеток для строки 1 ФИО */ ],
          "align": "left"
        },
        "tax_period": {
          "type": "char_cells",
          "cells": [ [...], [...] ],
          "align": "center"
        }
      }
    },
    "2": {
      "fields": {
        "inn": { ... },
        "line_020_amount": {
          "type": "char_cells",
          "cells": [ /* клетки для суммы аванса Q1, разряд за разрядом */ ],
          "align": "right"
        }
      }
    }
  }
}
```

Типы полей:
- `char_cells` — каждая буква/цифра в отдельной клетке (ИНН, ОКТМО, ФИО, суммы)
- `checkbox` — галочка (крестик) в одной клетке

### Координатная система reportlab

- Origin (0, 0) — **левый нижний угол** страницы
- A4: 595.0 × 841.89 pt (1 pt = 1/72 inch)
- Для знакомест в КНД 1152017 типичный размер клетки: ~4.5 × 5.5 мм ≈ 12.8 × 15.6 pt
- Размер шрифта: Arial/PTSans 11pt для цифр

---

## Решение 3: Pixel-diff тесты

**Выбрано:** двухуровневая стратегия.

### Уровень 1: быстрые координатные тесты (pdfplumber)

```python
import pdfplumber

def test_inn_position():
    pdf_bytes = render_declaration_pdf(sample_taxpayer, 2024, sample_tax_result)
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        page1 = pdf.pages[0]
        # Извлекаем все символы с координатами
        chars = page1.chars
        # Находим все цифры ИНН
        inn_chars = [c for c in chars if abs(c["y0"] - 790.5) < 2.0]
        inn_text = "".join(c["text"] for c in sorted(inn_chars, key=lambda c: c["x0"]))
        assert inn_text.endswith(sample_taxpayer.inn)  # оставшиеся пробелы допустимы
```

**Плюсы:** быстро (секунды), не требует растеризации.
**Минусы:** не ловит визуальные регрессии (цвет, шрифт, выравнивание).

### Уровень 2: pixel-perfect diff (pypdfium2 + Pillow)

```python
import pypdfium2 as pdfium
from PIL import Image, ImageChops

def rasterize_pdf(pdf_bytes: bytes, dpi: int = 150) -> list[Image.Image]:
    pdf = pdfium.PdfDocument(pdf_bytes)
    return [
        page.render(scale=dpi / 72).to_pil()
        for page in pdf
    ]

def test_pixel_perfect_sample_01():
    with open("templates/knd_1152017/reference/sample_01/input.json") as f:
        req = DeclarationRequest.model_validate_json(f.read())
    rendered = render_declaration_pdf(req.taxpayer, req.tax_period_year, compute_tax(req))
    actual_pages = rasterize_pdf(rendered)

    for i, actual in enumerate(actual_pages, start=1):
        expected = Image.open(f"templates/knd_1152017/reference/sample_01/expected_p{i}.png")
        assert actual.size == expected.size
        diff = ImageChops.difference(actual, expected)
        diff_pixels = sum(1 for px in diff.getdata() if px != (0, 0, 0))
        assert diff_pixels < 10, f"Page {i}: {diff_pixels} pixels differ (>10 tolerance)"
```

**Tolerance: ≤ 10 пикселей на страницу.** Учитывает антиалиасинг на краях шрифтов.

**DPI: 150.** Баланс точности и скорости — 3300×2550 px для A4.

**Эталоны генерируются вручную** при инициализации:
1. Запускаем `render_declaration_pdf()` с fixture-данными
2. Проверяем глазами что PDF корректный
3. Коммитим результат как `expected.pdf` + растеризованные `expected_p{1..4}.png`

---

## Влияние на Фазу 0

Roadmap пересматривается:

### Фаза 0a: Макеты (2–3 дня → теперь 3–4 дня)

**Было (по ADR-001):** использовать готовый `declaration_generator.py`.
**Стало:**
- [ ] Скачать официальный PDF бланк КНД 1152017 2024 года с nalog.ru
- [ ] Скачать форму 2025 года
- [ ] Разметить `fields_2024.json` (≈100 полей × 4 страницы = работа дня)
- [ ] Разметить `fields_2025.json` (3 страницы)
- [ ] Написать `PdfTemplateFiller` (pypdf + reportlab)
- [ ] Написать pixel-diff harness (pypdfium2 + Pillow)
- [ ] Создать 3 эталона (sample_01..03)

### Фаза 1: Адаптеры (1 → 2 дня)

**Было:** `declaration_filler/__init__.py` с вызовом `generate_pdf`.
**Стало:**
- [ ] Убрать из adapter'а вызов `generate_pdf` (он исключён по ADR-002)
- [ ] Адаптер рендера = `PdfTemplateFiller.render(decl_data, project_data)`
- [ ] Адаптер штампов = обёртка над `apply_stamps(bytes, cfg) -> bytes`

---

## Tool для разметки `fields.json`

Для ручной разметки координат знакомест разработаем визуальный инструмент:

```
scripts/mark_fields.py   # pygame/pillow - кликаешь по клеткам бланка, сохраняет координаты
```

Альтернатива: используем существующий XLSX-шаблон usn-declaration как «координатную сетку»
(в XLSX уже размечено где какой символ идёт) + автоматически извлекаем координаты
из XLSX через openpyxl → конвертируем в PDF-координаты.

**Рекомендуется: гибрид.** Автоматически извлечь из XLSX-шаблона 80% координат + ручная доводка 20%.
