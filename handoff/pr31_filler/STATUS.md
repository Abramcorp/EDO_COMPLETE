# STATUS — PR31 Filler

**Последнее обновление:** конец сессии 30.04.2026

## ✅ DONE

### Шаблоны blank
- [x] `templates/knd_1152017/blank_2024.pdf` — 4-страничный шаблон, одобрен Валентином
- [x] `templates/knd_1152017/blank_2025.pdf` — копия (форма 5.08 действует на оба года)
- [x] Стр.1 = твой ручной reference + удалены прочерки Стр.№ + добавлены '001'
- [x] Стр.2-4 = v2-стирание из эталона + защита /F11 + восстановлены '002'/'003'/'004'
- [x] Стр.5 (финальный лист штампа) удалена

### Координатная карта полей
- [x] `templates/knd_1152017/fields_2024.json` — 62 поля, координаты в reportlab pt
- [x] `templates/knd_1152017/fields_2025.json` — оригинал (62 поля, sample_value заполнены данными Романова)

### Шрифт /FX (полная кириллица)
- [x] `handoff/pr31_filler/artifacts/liberation_subset.ttf` — 22.8 КБ subset Liberation Sans
- [x] `handoff/pr31_filler/artifacts/font_subset_data.json` — unicode→GID mapping
- [x] `handoff/pr31_filler/artifacts/blank_with_FX.pdf` — blank_2024.pdf + встроенный /FX на всех 4 страницах
- [x] CIDFontType2 + FontFile2 + ToUnicode CMap корректно собраны
- [x] 87 символов (вся заглавная и строчная кириллица + цифры + пунктуация)
- [x] Метрики Liberation Sans = ArialMT 1-в-1 (это open-source клон Arial)

### POC одного поля
- [x] `handoff/pr31_filler/artifacts/poc_inn_replaced.pdf` — ИНН Романова `330573397709` записан и стёр прочерки в TJ
- [x] Pixel-perfect совпало с эталоном Тензора (визуально подтверждено в 600 DPI)
- [x] Координаты ΔX < 0.05 pt, ΔY = 0 после калибровки -2.555

### Карта последовательностей стр.1
- [x] `handoff/pr31_filler/artifacts/page1_text_sequences.json` — все 4 BT-блока с TJ
- [x] Для каждого `<hex>` — abs_span в content stream (готово для substitution)
- [x] Якоря-лейблы между группами прочерков идентифицированы

## 🔧 IN PROGRESS

### Mapping FIELD_TO_DASH_GROUP для стр.1
**Сделано** (для 9 полей точно):
- inn (block=BLOCK_TOP, idx=1, count=12) ✓
- page_number (idx=15, count=3) ✓
- correction_number (idx=63, count=3) ✓
- tax_period_code (idx=73, count=2) ✓
- tax_period_year (idx=79, count=4) ✓
- ifns_code (idx=95, count=4) ✓
- reorg_form (idx=284, count=1) ✓
- signer_type (idx=58 в BLOCK_MIDDLE, count=1) ✓
- signing_date_day/month/year (idx=309/312/315) ✓

**Требует разбора** (большие склеенные группы):
- at_location_code: reference содержит count=4 на idx=108, но fields ожидает 3 — проверить
- BLOCK_TOP idx=108 count=161 — это at_location (3-4) + 4 строки ФИО налогоплательщика (по ~40)?
- BLOCK_MIDDLE idx=120 count=160 — содержит несколько полей подряд (наименование организации представителя или что-то ещё)
- phone (11 знакомест) — где он в BLOCK_MIDDLE?
- signer_name_line1/2/3 — точные start_idx и count
- representative_document_line1/2 — count в reference 16 vs 40 в fields, возможно reference не содержит часть знакомест

## 🔲 TODO (по порядку)

### 1. Достроить mapping для всех 17 полей стр.1
- Запустить `python3 scripts/dump_block_top_full.py` (создать) — выведет полную последовательность всех 311+358 элементов с indices
- Сопоставить визуально с эталоном Романова в 600 DPI и составить точный mapping
- Сохранить в `scripts/page1_field_mapping.json`

### 2. Mapping для стр.2-4 (другая структура)
- На стр.2-4 каждое знакоместо = отдельный BT-блок `<0010> Tj` на конкретных tm-coords
- Алгоритм: для каждой клетки [x_rl, y_rl] из fields_2024.json:
  - Перевести в tm: `tm_x, tm_y = rl_to_tm(x_rl, y_rl)`
  - Найти в content stream BT-блок с Tm близко к (tm_x, tm_y) ± 1pt, содержащий `<0010> Tj`
  - Сохранить span этого `<0010>` для последующей замены

### 3. Filler v2 — единый модуль
```python
# scripts/filler.py
def fill_declaration(blank_path, fields_path, data: dict, output_path):
    # 1. Открыть blank
    # 2. Для стр.1: использовать page1_field_mapping для удаления прочерков в TJ
    # 3. Для стр.2-4: для каждой клетки найти и удалить одиночный <0010> Tj
    # 4. Параллельно во второй content stream написать данные через /FX
    # 5. Сохранить
```

### 4. Pixel-perfect сверка Романова
- `python3 scripts/render_diff.py filled.pdf etalon.pdf` — diff в 600 DPI
- Визуально проверить все 4 страницы рядом с эталоном
- Допустимое расхождение: только ЭДО-штамп (его нет в blank, добавляется отдельно)

### 5. Интеграция в репо
- `modules/usn_declaration/services/pdf_filler.py` — основной модуль
- Переключить `usn_declaration_adapter.py` под флагом `USE_PDF_FILLER=true`
- Старый xlsx-путь оставить как fallback

### 6. Известные баги pr31+ (для чек-листа после filler)
- Кривое заполнение legacy формы — починить отдельным PR
- Пропали PDF417 баркоды — проверить
- Дата штампа квитанций неправильная — проверить

## 🎯 Тестовые данные Романова (для проверки)

```python
ROMANOV_DATA = {
    1: {  # Титульный
        'inn': '330573397709',
        'page_number': '001',
        'correction_number': '1--',
        'tax_period_code': '34',
        'tax_period_year': '2025',
        'ifns_code': '3300',
        'at_location_code': '120',
        'phone': '79157503070',  # 11 цифр без + и () (раздели по знакоместам в filler)
        'signer_type': '2',  # представитель
        'taxpayer_fio_full': 'РОМАНОВ ДМИТРИЙ ВЛАДИМИРОВИЧ',
        'signer_name_line1': 'КУПРИЯНОВА',
        'signer_name_line2': 'ЕЛЕНА',
        'signer_name_line3': 'ЕВГЕНЬЕВНА',
        'representative_document_line1': 'ДОВЕРЕННОСТЬ № 2 ОТ',
        'representative_document_line2': '01.07.2025',
        'signing_date_day': '24',
        'signing_date_month': '01',
        'signing_date_year': '2026',
    },
    2: {  # Раздел 1.1
        'inn_header': '330573397709',
        'page_number_header': '002',
        'oktmo_q1': '17725000',  # 8 цифр + 3 прочерка автоматом
        'signing_date_p2': '24.01.2026',
    },
    3: {  # Раздел 2.1.1
        'inn_header': '330573397709',
        'page_number_header': '003',
        'taxpayer_sign': '1',
        'tax_rate_reason_code': '2',
        'income_9m': '409517',
        'income_y': '409517',
        'tax_rate_9m': '6.0',
        'tax_rate_y': '6.0',
        'tax_calc_9m': '24571',
        'tax_calc_y': '24571',
    },
    4: {  # Раздел 2.1.1 продолж.
        'inn_header': '330573397709',
        'page_number_header': '004',
        'insurance_9m': '24571',
        'insurance_y': '24571',
    },
}
```

## 📋 Чеклист завершения PR31

- [ ] Все 62 поля заполняются корректно через filler
- [ ] Pixel-perfect Романова на стр.1-4 (без штампа)
- [ ] Тест на Дошукаевой (буквы выходящие за subset, например в ФИО)
- [ ] Тест на ФИО с буквами Б, Ж, Ш, Щ — проверить что /FX рисует их правильно
- [ ] Интеграция filler в `usn_declaration_adapter.py`
- [ ] Smoke-тест на Railway
- [ ] Code review + merge в main
