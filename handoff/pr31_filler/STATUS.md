# STATUS — PR31 Filler

**Последнее обновление:** конец сессии 30.04.2026 — Stage 2 (новые бланки + page1+page4 mapping) ✅

## ✅ DONE

### Шаблоны blank (новая ревизия от Валентина 30.04.2026)
- [x] `templates/knd_1152017/blank_2024.pdf` (197 KB, md5 `ba373910...`)
- [x] `templates/knd_1152017/blank_2025.pdf` (198 KB, md5 `a7f16505...`) —
      отличается от 2024 только floating-point точностью на стр.4 (1.4197532 vs 1.4197531)
- [x] **Стр.1 теперь 8 content streams**. Streams [0..6] = pixel-graphics (`re f`).
      **Stream [7] (36 KB)** содержит все BT-блоки с TJ и 505 `<0010>`-прочерков
- [x] **Стр.4 расширена**: использует /C2_0..C2_4 (ArialMT) вместо /F-шрифтов;
      добавлены поля **150** (взносы по ст.430 НК совокупный фикс. размер),
      **160** (взносы 1% с дох.>300тыс), **161** (1% за тек.период), **162** (1% за пред.период)
- [x] Стр.2-3 — без изменений (F11/F5/F7 шрифты)

### /C2_0 теперь полный встроенный ArialMT
- [x] `/C2_0` на стр.1 (FontFile2 = 58 672 bytes) — **1680 глифов, 1425 unicode codepoints**
- [x] **Полная русская кириллица 0x0410-0x044F (64 буквы из 64)** — все ранее проблемные
      символы (Б, Ё, Ж, З, Х, Ц, Ш, Щ, Ъ, Ы, Э, Ю) покрыты
- [x] `/C2_4` на стр.4 = `/C2_0` на стр.1 побайтово (тот же FontFile2)
- [x] Hybrid font/FX больше **не нужен** — filler рисует всё через `/C2_0`

### Координатная карта полей
- [x] **Стр.1: 32 поля resolved без ошибок** (`page1_field_mapping.json`)
- [x] **Стр.4: 9 полей resolved без ошибок**, включая новые 150/160/161/162
      (`page4_field_mapping.json`)
- [x] Парсер: `handoff/pr31_filler/scripts/build_page_mapping.py` — self-contained,
      извлекает widths/cmap/TTF из PDF, парсит все content streams последовательно
      с CTM tracking (q/Q stack + cm), резолвит anchor/prev_field/expected_rl_y

### POC pixel-perfect через /C2_0 (новый blank)
- [x] `handoff/pr31_filler/artifacts/poc_inn_pixel_perfect.pdf` — ИНН '330573397709'
- [x] **PIXEL-PERFECT 0/235222 диф-пикселей** в зоне ИНН в 600 DPI vs эталон Романова
- [x] Скрипт: `handoff/pr31_filler/scripts/poc_fill_inn_pixel_perfect.py`

### Координатная семантика
- `tm_x = (rl_x - 14) / 0.7043478;  tm_y = (827.91998 - rl_y) / 0.7043478`
- text matrix для рисования: `1 0 0 -1 tm_x tm_y Tm` в `/C2_0 12 Tf` BT,
  обёрнуто в `q + 0.24 0 0 -0.24 0 841.91998 cm + 2.9347825 0 0 2.9347825 58.333332 58.333332 cm`

## 🔧 IN PROGRESS / 🔲 TODO

### 1. Поля стр.1/4, исключённые из mapping (ограничения reference)
- **kpp** — отсутствует в reference (Валентин стёр для ИП). Для ЮЛ-клиентов потребуется
  альтернативный reference.
- **page_number** ('001'/'004') уже встроен в blank в отдельном q-блоке;
  filler его не трогает. Если нужен dynamic page_number — потребуется заменять q-блок.

### 2. Mapping для стр.2-3
TJ-структура отличается: одиночные `<0010> Tj` блоки на каждое знакоместо (не TJ-array).
Шрифты /F11/F5/F7. Алгоритм: координатный поиск по fields_*.json[page=2/3] cells →
найти BT с Tm близко к ожидаемой, сохранить span этого `<0010>` для substitution.

### 3. Filler v2 — единый production модуль
```python
# scripts/filler.py
def fill_declaration(blank_path: Path,
                     mapping_paths: dict[int, Path],
                     data: dict[int, dict],
                     output_path: Path):
    # 1. Открыть blank
    # 2. Для каждой страницы и каждого поля:
    #    a. Substitution <0010>→<0003> в spans_in_stream правильного stream_idx
    #       (ОБРАТНЫЙ порядок span'ов чтобы не сбить байт-смещения)
    #    b. Параллельный stream:
    #       q + CTM_2 + BT /C2_0 12 Tf 1 0 0 -1 tm_x tm_y Tm <cid_hex> Tj ET ... Q
    # 3. Записать
```

В `/C2_0` встроенный ArialMT покрывает все 1425 unicode codepoints (включая полную
кириллицу) → ожидаемый pixel-diff на любых данных = 0%.

Для расширенного покрытия (Б, Ё, Ж, З, Х, Ц, Ш, Щ, Ъ, Ы, Э, Ю и т.д. отсутствующих
в ToUnicode CMap но присутствующих в TTF cmap) — использовать TTF cmap для
unicode→GID lookup; CID = GID в Identity-H Encoding.

### 4. Pixel-perfect сверка Романова (полные 4 страницы)
- diff в 600 DPI через рендер pdfium
- Допустимое расхождение: только ЭДО-штамп (вне scope PR31)

### 5. Интеграция в репо
- `modules/usn_declaration/services/pdf_filler.py` — основной модуль
- Переключить `usn_declaration_adapter.py` под флагом `USE_PDF_FILLER=true`
- Старый xlsx-путь оставить как fallback

### 6. Известные баги pr31+
- Кривое заполнение legacy формы — починить отдельным PR
- Пропали PDF417 баркоды — проверить
- Дата штампа квитанций неправильная — проверить

## 🎯 Тестовые данные Романова

```python
ROMANOV_DATA = {
    1: {  # Титульный
        'inn': '330573397709',
        'correction_number': '1--',
        'tax_period_code': '34',
        'tax_period_year': '2025',
        'ifns_code': '3300',
        'at_location_code': '120',
        'taxpayer_fio_line1': 'РОМАНОВ ДМИТРИЙ ВЛАДИМИРОВИЧ',
        'phone': '79157503070',
        'tax_object_code': '1',
        'pages_count': '4--',
        'appendix_pages_count': '---',
        'signer_type': '2',
        'signer_name_line1': 'КУПРИЯНОВА',
        'signer_name_line2': 'ЕЛЕНА',
        'signer_name_line3': 'ЕВГЕНЬЕВНА',
        'signing_date_day': '24', 'signing_date_month': '01', 'signing_date_year': '2026',
        'representative_document_line1': 'ДОВЕРЕННОСТЬ№2ОТ',
        'representative_document_line2': '01.07.2025',
    },
    2: { 'oktmo_q1': '17725000' },  # + остальные показатели разд.1.1
    3: {
        'taxpayer_sign': '1',
        'tax_rate_reason_code': '2',
        'income_y': '409517',
        'tax_rate_y': '6.0',
        'tax_calc_y': '24571',
    },
    4: {
        'insurance_y': '24571',
        'insurance_fixed': '24571',  # строка 150
        # 'insurance_1pct': '0',     # 160 — для проверки тестового набора
    },
}
```

## 📋 Чеклист завершения PR31

- [ ] Все поля заполняются корректно через filler v2
- [ ] Pixel-perfect Романова на стр.1-4 (без штампа)
- [ ] Mapping для стр.2-3 (одиночные `<0010> Tj` подход)
- [ ] Тест на ФИО с буквами Б, Ж, Ш, Щ — поддержка через TTF cmap
- [ ] Интеграция filler в `usn_declaration_adapter.py`
- [ ] Smoke-тест на Railway
- [ ] Code review + merge в main
