# templates/knd_1166002 — Квитанция о приёме налоговой декларации

**Форма КНД 1166002** — квитанция о приёме декларации налоговым органом в электронном виде.

Добавляется в итоговый PDF как страница 5 (см. ADR-003).

## Что должно быть в этой директории

```
knd_1166002/
├── blank.pdf              ← чистый бланк ФНС формы 1166002 (A4, 1 страница)
├── fields.json            ← координатная карта полей для reportlab overlay
└── reference/             ← эталоны для pixel-diff
    ├── sample_01_input.json
    ├── sample_01_expected.pdf
    └── sample_01_expected.png
```

## Где взять blank.pdf

Вариант А — скачать с nalog.ru:
  - Поиск: «КНД 1166002 квитанция о приёме налоговой декларации в электронном виде»
  - Формат: чистый бланк, 1 страница A4

Вариант Б — извлечь из эталона `Романов_УСН_2025.pdf` через `pdfplumber`:
  ```python
  import pdfplumber
  from pypdf import PdfReader, PdfWriter
  r = PdfReader("Романов_УСН_2025.pdf")
  w = PdfWriter()
  w.add_page(r.pages[4])  # страница 5 (индекс 4) — это КНД 1166002
  with open("page5.pdf", "wb") as f:
      w.write(f)
  # затем очистить поля вручную (или через OCR-замену белым прямоугольником)
  ```

Вариант Б даёт pixel-perfect совпадение с эталоном, но требует ручной очистки заполненных полей.

## Формат fields.json

Аналогично `templates/knd_1152017/fields_YYYY.json` (см. ADR-002):

```json
{
  "form_version": "1166002",
  "pages": 1,
  "fonts": {
    "primary": {"name": "DeclFont", "size": 10}
  },
  "pages_def": {
    "1": {
      "fields": {
        "taxpayer_short": {
          "type": "text_line",
          "cells": [[x, y]],
          "align": "left"
        },
        "taxpayer_inn": { ... },
        "ifns_full_name": { ... },
        "ifns_code": { ... },
        "declarant_fio": { ... },
        "declarant_inn": { ... },
        "submission_date": {"type": "text_line", "cells": [[x, y]]},
        "submission_time": { ... },
        "declaration_name": { ... },
        "correction_number": { ... },
        "tax_period_code": { ... },
        "tax_period_year": { ... },
        "file_name_line1": {"type": "text_line", "cells": [[x, y]]},
        "file_name_line2": { ... },
        "reception_date": { ... },
        "acceptance_date": { ... },
        "registration_number": { ... }
      }
    }
  }
}
```

## Список полей, которые должен заполнить рендерер

Из эталона ТЕНЗОР (страница 5):

| Поле | Источник данных |
|---|---|
| Реквизиты справа-вверху (декларант) | `taxpayer.fio + taxpayer.inn` |
| Налоговый орган | `ifts_info.name + "(код " + ifns_code + ")"` |
| Полное имя налогоплательщика | `taxpayer.fio + ", " + taxpayer.inn` |
| Дата/время представления | `receipt_data.timestamps.submission` |
| Наименование декларации | константа "Налоговая декларация по налогу..." |
| КНД | константа "1152017" |
| Номер корректировки | из DeclarationRequest |
| Отчётный период | "34" (год) |
| Отчётный год | `tax_period_year` |
| Имя файла | `receipt_data.file_name` |
| Дата поступления | `receipt_data.timestamps.submission.date()` |
| Дата принятия | `receipt_data.timestamps.acceptance.date()` |
| Регистрационный номер | `receipt_data.registration_number` |

## Статус

🟡 **Phase 0c.1 pending:** bold.pdf + fields.json требуют ручной разметки координат.

Сейчас рендер использует placeholder в `edo_stamps/__init__.py::build_receipt_pages`.
