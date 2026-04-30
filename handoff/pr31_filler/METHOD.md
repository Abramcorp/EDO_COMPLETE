# METHOD — Поиск полей и замена прочерков на стр.1 reference

> Детальный разбор метода которым в прошлой сессии был решён кейс «Стр.№ 001».
> Это **рабочий шаблон** для всех остальных полей стр.1.

## Контекст: почему стр.1 особенная

Стр.1 в `blank_2024.pdf` — это твой ручной reference, прошедший через PDF-редактор. PDF-редактор **переупаковал** оригинальную структуру эталона Тензора:

- В эталоне Тензора каждое знакоместо было **отдельным BT-блоком** с одиночным `<0010> Tj` и собственной Tm-матрицей
- В reference все символы стр.1 **сжаты в 4 больших BT-блока с TJ-массивами** (с kern-adjustments между символами)
- Шрифты переупакованы: вместо `/F5` (эталон) → `/C2_0..C2_3` (reference, subset Тензора)

Поэтому **обычный поиск по координатам Tm не работает на стр.1**. Координаты есть только в начале блока (Tm), а позиция конкретного `<hex>` внутри TJ-массива — результат накопления kern-сдвигов, которые сложно посчитать точно.

**Решение:** использовать **порядок следования** символов в TJ как ключ, а не координаты.

## Метод (тот что сработал на «001»)

### Шаг 1: Извлечение последовательности символов

Из `page1_text_sequences.json` (готовый артефакт) для каждого из 4 BT-блоков с TJ есть массив:

```json
{
  "BLOCK_TOP": {
    "tm_pdf": [165.5888, 791.2939],
    "bt_span": [275843, 281943],
    "sequence": [
      {"idx": 0, "hex": "024202470247", "text": "ИНН", "abs_span": [...]},
      {"idx": 1, "hex": "0010", "text": "-", "abs_span": [275928, 275934]},
      {"idx": 2, "hex": "0010", "text": "-", "abs_span": [275944, 275950]},
      ...
      {"idx": 13, "hex": "024402490249", "text": "КПП", "abs_span": [...]},
      {"idx": 14, "hex": "024B026C026A0011", "text": "Стр.", "abs_span": [...]},
      {"idx": 15, "hex": "0010", "text": "-", "abs_span": [275928 + offset, ...]},
      ...
    ]
  }
}
```

**Это даёт полную карту**: для каждого символа я знаю:
- его **позицию в последовательности** (idx)
- его **расшифровку** (text — это что отображается)
- его **точные байтовые границы в content stream** (abs_span)

### Шаг 2: Идентификация поля через якорь-лейбл

Каждое поле имеет **предшествующий лейбл** в последовательности:

| Поле | Якорь-лейбл (text) | Сразу после него N прочерков |
|---|---|---|
| inn | `'ИНН'` (idx=0) | 12 (idx=1..12) |
| page_number | `'Стр.'` (idx=14) | 3 (idx=15..17) |
| correction_number | `'тировки'` (idx=62, конец «Номер корректировки») | 3 (idx=63..65) |
| tax_period_code | `'д)'` (idx=72, конец «Налоговый период (код)») | 2 (idx=73..74) |
| tax_period_year | `'д'` (idx=78, конец «Отчетный год») | 4 (idx=79..82) |
| ifns_code | `'д)'` (idx=94, конец «налоговый орган (код)») | 4 (idx=95..98) |

Алгоритм поиска поля:
```python
def find_field_dashes(sequence, anchor_text, dash_count):
    """Найти dash_count прочерков идущих сразу после якоря-лейбла."""
    for i, item in enumerate(sequence):
        if item['text'] == anchor_text:
            # Проверяем что следующие dash_count элементов это '-'
            dashes = sequence[i+1 : i+1+dash_count]
            if all(d['text'] == '-' for d in dashes):
                return dashes  # их abs_span'ы — то что нам нужно
    return None
```

### Шаг 3: Удаление прочерков (literal substring replacement)

Для каждого найденного прочерка:
- Извлекаем `abs_span = [start, end]` (это байтовые позиции в content stream)
- В этих байтах находится литерал `<0010>` (hex прочерка)
- Заменяем на `<0003>` (hex пробела)

```python
# КРИТИЧЕСКИ ВАЖНО: делать в обратном порядке (с конца), 
# чтобы предыдущие span'ы не сдвигались
for span in sorted(target_spans, key=lambda s: -s[0]):
    start, end = span
    fragment = raw[start:end]
    assert fragment == '<0010>', f"Ожидался <0010>, нашёл {fragment!r}"
    raw = raw[:start] + '<0003>' + raw[end:]
```

**Почему `<0003>` (пробел), а не пустая строка:**
- Структура TJ-массива должна сохранять количество элементов
- Kern-adjustments между ними остаются прежними
- Если удалить `<0010>` совсем — соседние символы съедут (kern не сработает корректно)
- `<0003>` (пробел) занимает в визуальном смысле 0 (этот шрифт не имеет глифа пробела), но сохраняет позицию

**Пробел НЕ менять на другой CID** — мы оставляем шрифт `C2_0` нетронутым, рисуем данные параллельно через `/FX`.

### Шаг 4: Параллельная отрисовка данных через `/FX`

В отдельном content stream (новый stream добавляется в `/Contents` массив страницы):

```python
# Координатная калибровка (зафиксирована в памяти)
def rl_to_tm(x_rl, y_rl):
    tm_x = (x_rl - 14) / 0.7043
    tm_y = (827.92 - y_rl) / 0.7043 - 2.555
    return tm_x, tm_y

# Получение CID для символа в шрифте /FX
# В /FX: CID == GID (Identity), GID берётся из subset Liberation Sans
unicode_to_gid = json.load('font_subset_data.json')
def char_to_fx_hex(ch):
    return f'{unicode_to_gid[ord(ch)]:04X}'

# Сборка content stream
content = "q\n0.24 0 0 -0.24 0 841.91998 cm\n2.9347825 0 0 2.9347825 58.333332 58.333332 cm\n"
for i, ch in enumerate(value):
    x_rl, y_rl = field_def['cells'][i]
    tm_x, tm_y = rl_to_tm(x_rl, y_rl)
    cid = char_to_fx_hex(ch)
    content += f"BT\n/FX 12 Tf\n1 0 0 -1 {tm_x:.3f} {tm_y:.3f} Tm\n<{cid}> Tj\nET\n"
content += "Q\n"
```

## Полный воркфлоу для одного поля (на примере «Стр. 001»)

```python
import json
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, ArrayObject

# Артефакты handoff
with open('handoff/pr31_filler/artifacts/page1_text_sequences.json') as f:
    sequences = json.load(f)
with open('handoff/pr31_filler/artifacts/font_subset_data.json') as f:
    subset = json.load(f)
unicode_to_gid = {int(k, 16): v for k, v in subset['unicode_to_gid'].items()}

# Шаг 1+2: находим прочерки Стр.№ через якорь 'Стр.'
seq = sequences['BLOCK_TOP']['sequence']
anchor_idx = next(i for i, s in enumerate(seq) if s['text'] == 'Стр.')
target_dashes = seq[anchor_idx + 1 : anchor_idx + 4]  # 3 прочерка после
target_spans = [d['abs_span'] for d in target_dashes]

# Шаг 3: удаляем прочерки в основном content stream
reader = PdfReader('blank_2024.pdf')  # или blank_with_FX.pdf
writer = PdfWriter(clone_from=reader)
page = writer.pages[0]
contents = page.get('/Contents')
main_stream_ref = contents[0] if isinstance(contents, ArrayObject) else page.raw_get('/Contents')
main_stream = main_stream_ref.get_object()
raw = main_stream.get_data().decode('latin-1')

for span in sorted(target_spans, key=lambda s: -s[0]):
    start, end = span
    assert raw[start:end] == '<0010>'
    raw = raw[:start] + '<0003>' + raw[end:]

new_main = DecodedStreamObject()
new_main.set_data(raw.encode('latin-1'))
new_main_ref = writer._add_object(new_main)

# Шаг 4: рисуем '001' через /FX
def rl_to_tm(x_rl, y_rl):
    return (x_rl - 14) / 0.7043, (827.92 - y_rl) / 0.7043 - 2.555

# Из fields_2024.json берём cells для page_number
cells = [[463.71, 766.0], [477.09, 766.0], [490.47, 766.0]]  # пример координат
value = '001'
content = "q\n0.24 0 0 -0.24 0 841.91998 cm\n2.9347825 0 0 2.9347825 58.333332 58.333332 cm\n"
for i, ch in enumerate(value):
    tm_x, tm_y = rl_to_tm(*cells[i])
    cid = f'{unicode_to_gid[ord(ch)]:04X}'
    content += f"BT\n/FX 12 Tf\n1 0 0 -1 {tm_x:.3f} {tm_y:.3f} Tm\n<{cid}> Tj\nET\n"
content += "Q\n"

add_stream = DecodedStreamObject()
add_stream.set_data(content.encode('latin-1'))
add_ref = writer._add_object(add_stream)

# Собираем /Contents = [main_modified, add_with_data]
page[NameObject('/Contents')] = ArrayObject([new_main_ref, add_ref])

writer.write('output.pdf')
```

## Готовый mapping (DONE для 9 полей стр.1)

```python
# Поле → (block_name, anchor_text, dash_count)
# anchor_text — точное text который встречается в sequence ПЕРЕД группой прочерков
KNOWN_FIELD_ANCHORS_PAGE1 = {
    'inn':                {'block': 'BLOCK_TOP', 'anchor': 'ИНН', 'count': 12},
    'page_number':        {'block': 'BLOCK_TOP', 'anchor': 'Стр.', 'count': 3},
    'correction_number':  {'block': 'BLOCK_TOP', 'anchor': 'тировки', 'count': 3},
    'tax_period_code':    {'block': 'BLOCK_TOP', 'anchor': 'д)', 'count': 2, 'occurrence': 1},
    'tax_period_year':    {'block': 'BLOCK_TOP', 'anchor': 'д', 'count': 4, 'occurrence': 1},
    'ifns_code':          {'block': 'BLOCK_TOP', 'anchor': 'д)', 'count': 4, 'occurrence': 2},
    'reorg_form':         {'block': 'BLOCK_TOP', 'anchor': '(код)', 'count': 1, 'occurrence': N},  # уточнить
    'signer_type':        {'block': 'BLOCK_MIDDLE', 'anchor': 'ерждаю:', 'count': 1},
    'signing_date_day':   {'block': 'BLOCK_MIDDLE', 'anchor': 'та', 'count': 2, 'occurrence': N},
    'signing_date_month': {'block': 'BLOCK_MIDDLE', 'anchor': '-.', 'count': 2, 'occurrence': 1},  # после первой точки
    'signing_date_year':  {'block': 'BLOCK_MIDDLE', 'anchor': '-.', 'count': 4, 'occurrence': 2},  # после второй точки
}
```

**Важно**: некоторые лейблы повторяются в последовательности (`(код)` встречается несколько раз — для налогового периода, налогового органа, формы реорганизации). Поле `occurrence` указывает какое именно вхождение брать.

## TODO для следующей сессии: разобрать большие склеенные группы

Самые сложные места:

### BLOCK_TOP idx=108, count=161 (~)

161 прочерков подряд между «(код)» (для at_location) и «(налогоплательщик)». Это:
- `at_location_code` — 3 знакоместа (но в reference 4 — лишний или опечатка?)
- `taxpayer_fio_full` — это **4 строки по 40 знакомест** для ФИО налогоплательщика
- + что-то между ними

Чтобы разобрать: визуально на эталоне Романова в 600 DPI посмотреть **какие именно** 161 прочерков видны в этой зоне и в каком порядке (сверху вниз, слева направо). Сопоставить с порядком в TJ-последовательности.

### BLOCK_MIDDLE idx=120, count=160

Аналогично — «наименование организации представителя» это 8 строк × 20 = 160 знакомест. Подряд их 160 в reference TJ — точное совпадение по count, нужно только подтвердить что это именно они.

## Pixel-perfect верификация

После заполнения каждого поля:

```python
import pypdfium2 as pdfium
from PIL import Image
import numpy as np

DPI = 600
my = pdfium.PdfDocument('filled.pdf')[0].render(scale=DPI/72).to_pil().convert('L')
etalon = pdfium.PdfDocument('etalon.pdf')[0].render(scale=DPI/72).to_pil().convert('L')

# Pixel diff
diff = np.abs(np.array(my, dtype=np.int16) - np.array(etalon, dtype=np.int16))
diff_pixels = (diff > 30).sum()
print(f"Различий: {diff_pixels} из {diff.size}")
```

Допустимое число расхождений: **только в зонах ЭДО-штампа** (его в эталоне нет, в нашем тоже не будет). Все знакоместа должны совпадать pixel-perfect.

## Чеклист процесса для каждого поля

```
☐ 1. Найти якорь-лейбл в page1_text_sequences.json (BLOCK_X.sequence)
☐ 2. Подтвердить что после якоря идут N прочерков (где N = len(field.cells))
☐ 3. Извлечь abs_spans этих прочерков
☐ 4. Заменить <0010> → <0003> в основном content stream (в обратном порядке span'ов!)
☐ 5. Рассчитать tm-coords через rl_to_tm() для каждой клетки field.cells
☐ 6. Сгенерировать BT-блоки с /FX 12 Tf и нужными CID символов
☐ 7. Добавить новый content stream к странице
☐ 8. Рендер 600 DPI + сравнение с эталоном
☐ 9. Если pixel-perfect — переходить к следующему полю
```

## Подводные камни

1. **Якорь должен быть уникальным или с указанием occurrence**. Лейбл «(код)» встречается 4 раза подряд — нужен счётчик.

2. **count в reference иногда ≠ len(cells) в fields_2024.json**. Это означает либо:
   - У reference в этом поле есть пустые клетки без прочерков (reference дополняется руками)
   - В fields_2024.json неправильный count
   - Нужно сверять визуально

3. **Spans берутся из page1_text_sequences.json**. Этот файл сгенерирован один раз для текущего blank. Если blank изменится — нужно перегенерировать через скрипт парсинга BT/TJ.

4. **Шрифт /FX уже встроен** в `blank_with_FX.pdf` (handoff/pr31_filler/artifacts/). Используем его как стартовый файл, не перевстраиваем шрифт каждый раз.

5. **Не путать `blank_2024.pdf` (без /FX) и `blank_with_FX.pdf`**:
   - `templates/knd_1152017/blank_2024.pdf` — production-шаблон, 4 страницы, без встроенного шрифта filler
   - `handoff/pr31_filler/artifacts/blank_with_FX.pdf` — со встроенным /FX, для filler v2
   - Для production filler v2 встройку шрифта делать **runtime** (не сохранять blank с /FX в репо как продакт)

## Связанные артефакты

- `handoff/pr31_filler/artifacts/page1_text_sequences.json` — карта sequences
- `handoff/pr31_filler/artifacts/font_subset_data.json` — unicode→GID для /FX
- `handoff/pr31_filler/artifacts/blank_with_FX.pdf` — blank со встроенным шрифтом
- `handoff/pr31_filler/artifacts/poc_inn_replaced.pdf` — рабочий пример POC
- `handoff/pr31_filler/etalons/etalon_romanov_5pages.pdf` — для pixel-perfect сверки
