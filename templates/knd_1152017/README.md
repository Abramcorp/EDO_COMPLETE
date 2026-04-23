# templates/knd_1152017 — Декларация по налогу УСН

**Форма КНД 1152017** — налоговая декларация по налогу, уплачиваемому в связи
с применением упрощённой системы налогообложения. Основной документ в pipeline
(см. ADR-001).

Pipeline (по ADR-004):
```
  XLS / 1C / OФД → DeclarationData → PdfOverlayFiller.render() → blank+overlay → apply_stamps → final PDF
```

## Структура директории

```
knd_1152017/
├── README.md                             — этот файл
├── blank_2025.pdf                        — ПУСТОЙ БЛАНК для формы 2025 (4 страницы)
├── fields_2025.json                      — TODO: координаты полей 2025 (PR #11-14)
├── blank_2024.pdf                        — TODO: бланк 2024 (PR #18)
├── fields_2024.json                      — TODO: координаты 2024
├── declaration_template.xlsx             — xlsx-шаблон (от usn-declaration, для аудита)
├── declaration_template_2024.xlsx        — то же, версия 2024
└── declaration_template_2025.xlsx        — то же, версия 2025
```

## blank_2025.pdf

**Растровый бланк с сохранёнными статическими лейблами** — 4 страницы A4 соответствующие Титульный лист /
Р.1.1 / Р.2.1.1 / Р.2.1.1(продолж). Получен из эталона ТЕНЗОРа
(`reference_tensor_6pages.pdf`) автоматической очисткой через
`scripts/make_blank_raster_auto.py`.

Содержит:
- Штрих-код (0301 5018) — сохранён как вектор
- Клетки (знакоместа) для ИНН, КПП, сумм, ОКТМО и т.д.
- Рамки разделов формы

НЕ содержит:
- Заголовков разделов ("Раздел 1.1. Сумма налога...")
- Лейблов колонок ("Код строки", "Значения показателей")
- Подписей полей ("(Ф.И.О.)")

Это особенность автоочистки — pdfplumber извлекает ВСЕ слова, статические
вместе с динамическими. Статические лейблы вернутся обратно:
- либо через `form_static_<page>.json` + overlay слой
- либо перерендером blank через `make_blank_raster.py` с размеченным
  `fields_2025.json` (который стирает только динамические поля)

## Регенерация blank_2025.pdf

Для воспроизведения нужен локальный эталон `reference_tensor_6pages.pdf`
(он в `.gitignore` — содержит ПД).

```bash
# 1. Извлечь 4 страницы декларации
python -c "
from pypdf import PdfReader, PdfWriter
r = PdfReader('templates/_user_reference/reference_tensor_6pages.pdf')
for i in range(4):
    w = PdfWriter(); w.add_page(r.pages[i])
    with open(f'templates/knd_1152017/source_page_p{i+1}.pdf', 'wb') as f: w.write(f)
"

# 2. Сгенерировать blank для каждой страницы
for i in 1 2 3 4; do
    python scripts/make_blank_raster_auto.py \
        --source templates/knd_1152017/source_page_p${i}.pdf \
        --out templates/knd_1152017/blank_p${i}.pdf
done

# 3. Объединить в один PDF
python -c "
from pypdf import PdfReader, PdfWriter
w = PdfWriter()
for i in range(1, 5):
    r = PdfReader(f'templates/knd_1152017/blank_p{i}.pdf')
    w.add_page(r.pages[0])
with open('templates/knd_1152017/blank_2025.pdf', 'wb') as f: w.write(f)
"

# 4. Очистить промежуточные
rm templates/knd_1152017/source_page_p*.pdf templates/knd_1152017/blank_p*.pdf
```

## Статус

| Артефакт | Статус |
|---|---|
| `blank_2025.pdf` | ✅ 4 страницы A4, перегенерирован в PR #14 через make_blank_raster.py (со статическими лейблами) |
| `fields_2025.json` | 🟡 TODO — разметка по страницам (PR #11-14) |
| Статические лейблы формы | 🟡 TODO |
| `blank_2024.pdf` + `fields_2024.json` | 🔴 не начато |
| `PdfOverlayFiller.render()` | 🟡 заглушка, реализация после разметки fields.json |

## Версионность форм

Форма КНД 1152017 менялась:
- **Редакция от 05.08.2024** (приказ ЕД-7-3/813@) — действует для деклараций за 2024
- **Редакция от 29.12.2024** — для 2025 (+ раздел 4 «Предприниматели без ИНН»)

Эталон ТЕНЗОРа содержит `COMPARE_TAG_BEGIN_1152017_5_08_*` → это редакция **5.08**
(05.08.2024). То есть эталон использует форму **для 2024 отчётности**. Проверить
на эталоне за 2025 когда будет доступен.

## Ссылки

- [Приказ ФНС ЕД-7-3/813@ от 05.08.2024](https://www.nalog.gov.ru/)
- `docs/ADR-002-pixel-perfect-rendering.md` — общий подход к рендеру
- `docs/ADR-004-declaration-data-flow.md` — data flow
