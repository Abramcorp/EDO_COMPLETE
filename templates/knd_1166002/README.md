# templates/knd_1166002 — Квитанция о приёме налоговой декларации

**Форма КНД 1166002** — квитанция о приёме декларации налоговым органом в электронном виде.

Добавляется в итоговый PDF как страница 5 (см. ADR-003).

## Статус

| Артефакт | Статус | Комментарий |
|---|---|---|
| `source_page.pdf` | ✅ есть | Извлечено из эталона Тензора (заполненное) |
| `fields_auto.json` | ✅ есть | 165 координат автоматически через pdfplumber |
| `fields.json` | ✅ есть | Боевая разметка, 22 logical-поля |
| `blank.pdf` | 🟡 TODO | Нужно очистить source_page.pdf от значений |
| Реальный рендер (замена placeholder) | 🟡 TODO | Связано с blank.pdf |
| Pixel-diff тест | 🟡 TODO | Запускать на reference_tensor_6pages.pdf page 5 |

## Поля в fields.json

Динамические (рендерятся из данных):
- `representative_fio_line1` + `representative_inn` — реквизиты декларанта справа вверху
- `ifns_full_name` + `ifns_code_after_name` — данные налогового органа
- `declarant_fio_and_inn_line` + `declarant_inn_explicit` — ФИО + ИНН в основной фразе
- `submission_date` + `submission_time` — когда представлена декларация
- `declaration_name_and_knd` — название декларации
- `correction_number` — "корректирующий (N)"
- `tax_period_code_and_year` + `tax_period_year_only` — период и год
- `file_name_line1` + `file_name_line2` — имя файла (переносится)
- `ifns_code_reception` — код ИФНС при приёме
- `reception_date` + `acceptance_date` — даты поступления/принятия
- `registration_number` — регистрационный номер
- `stamp_document_uuid` + `stamp_ifts_datetime` + `stamp_ifts_cert` — для штампа footer

Статические (часть формы, уже на blank.pdf, рендерить не нужно):
- `form_knd_code`, `receipt_title_line{1..3}`, `label_*` — см. `_static_fields` в JSON

## Получение blank.pdf

**Вариант А: очистить source_page.pdf программно.**
Скрипт `scripts/make_blank_from_reference.py` (TODO) накладывает белые прямоугольники на координаты динамических полей, превращая заполненный PDF в чистый бланк.

**Вариант Б: скачать с nalog.ru.**
Найти приказ ФНС, скачать форму КНД 1166002 как PDF. Минус — может не совпасть пиксельно с эталоном ТЕНЗОРа.

Рекомендую А — тогда pixel-diff будет работать на 100%.

## Тестовые значения

Взять из эталона `reference_tensor_6pages.pdf`:

```json
{
  "representative_fio_line1": "Куприянова Елена Евгеньевна,",
  "representative_inn": "330517711336",
  "ifns_full_name": "УФНС России по Владимирской области",
  "ifns_code_after_name": "3300)",
  "declarant_fio_and_inn_line": "Романов Дмитрий Владимирович, 330573397709",
  "submission_date": "24.01.2026",
  "submission_time": "07.49.53",
  "declaration_name_and_knd": "Налоговая декларация по налогу, уплачиваемому в связи с применением упрощенной системы налогообложения (КНД 1152017)",
  "correction_number": "корректирующий (1)",
  "tax_period_year_only": "2025",
  "file_name_line1": "NO_USN_3300_3300_330517711336_20260124_12d6c8ca-4bf8-4d",
  "file_name_line2": "f5-a370-ce44469d1650",
  "reception_date": "24.01.2026",
  "acceptance_date": "24.01.2026",
  "registration_number": "00000000002774176425"
}
```
