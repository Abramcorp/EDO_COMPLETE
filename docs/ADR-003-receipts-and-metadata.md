# ADR-003: Квитанции ФНС (КНД 1166002 + КНД 1166007) и генератор реквизитов

**Статус:** Accepted
**Дата:** 23.04.2026
**Триггер:** анализ реальных эталонов КОНТУР (4 стр.) и ТЕНЗОР (6 стр.) показал, что ТЕНЗОР-PDF содержит 2 дополнительные страницы квитанций. Заказчик требует добавить такие же страницы к КОНТУР и генератор правильных значений для них.

## Контекст

### Что нашли в эталонах

**КОНТУР эталон** (`ОРИГИНАЛ_NO_USN_5800_..._d445.pdf`):
- 4 страницы декларации КНД 1152017
- Штампы ЭДО Контур.Эльба: справа на стр.1 (широкий блок), внизу на стр.2-4 (узкий footer)
- **НЕТ страниц КНД 1166002 и КНД 1166007**
- Имя файла в штампе: `NO_USN_5800_5800_583806352199_20250210_11d1af3ccff1-d445-dc47-a23025d6aa8a`
- UUID формат Контура: `8-4-4-12` (нестандартный, с дефисами в иных позициях)

**ТЕНЗОР эталон** (`Романов_УСН_2025.pdf`):
- 4 страницы декларации + **стр.5 КНД 1166002** + **стр.6 КНД 1166007**
- Штампы ЭДО Тензор в footer **на всех 6 страницах**
- UUID формат Тензора: стандартный v4 `8-4-4-4-12`
- Регистрационный номер: `00000000002774176425` (20 цифр)

### Что делают штампы в edo-stamps

Анализ `edo_core.apply_stamps()`: функция только накладывает overlay на **существующие** страницы. Она **НЕ создаёт** страниц 5-6 (квитанций). В эталоне ТЕНЗОРа эти страницы были добавлены во внешней системе (СБИС).

Значит для USN_COMPLETE мы реализуем генерацию квитанций **с нуля**.

## Решения

### Решение 1: Новая стадия pipeline `APPENDING_RECEIPTS`

Добавляется между `RENDERING_DECLARATION` и `FETCHING_IFTS`:

```
... → RENDERING_DECLARATION (4 стр. декларации)
    → APPENDING_RECEIPTS    (+ 2 стр. квитанций, всего 6 стр.)
    → FETCHING_IFTS
    → RENDERING_STAMPS      (штампы на все 6 страниц)
```

**Важно:** квитанции добавляются **до** наложения штампов. Причина — из эталона ТЕНЗОР видно, что штампы ЭДО присутствуют и на стр. 5 (квитанция) и на стр. 6 (извещение). Если бы мы делали `stamps → append`, штампы на 5-6 отсутствовали бы.

### Решение 2: Шаблоны квитанций = отдельные PDF-подложки ФНС

Структура:
```
templates/
├── knd_1152017/          ← декларация (ADR-002)
├── knd_1166002/          ← квитанция о приёме
│   ├── blank.pdf
│   ├── fields.json
│   └── reference/
│       ├── sample_01_input.json
│       ├── sample_01_expected.pdf
│       └── sample_01_expected.png
└── knd_1166007/          ← извещение о вводе сведений
    ├── blank.pdf
    ├── fields.json
    └── reference/
```

**Откуда бланки:** скачать с nalog.ru или извлечь из реальных квитанций через `pdfplumber` (очистив поля).

### Решение 3: Генератор реквизитов квитанций

Новый модуль: `modules/edo_stamps/receipt_data.py`

```python
@dataclass
class ReceiptData:
    # Общее
    operator: EdoOperator
    document_uuid: str                      # формат зависит от оператора
    file_name: str                          # NO_USN_<ifns>_<ifns>_<inn>_<date>_<uuid>
    # Декларант
    taxpayer_inn: str
    taxpayer_fio: str
    # Представитель (может совпадать с декларантом)
    representative_inn: str
    representative_fio: str
    # Налоговый орган
    ifns_code: str                          # 4 цифры
    ifns_full_name: str                     # "УФНС России по ... области"
    ifns_manager_name: str
    ifns_manager_post: str
    # Сама декларация
    declaration_knd: str = "1152017"
    declaration_name: str = "Налоговая декларация по налогу..."
    correction_number: int = 0
    tax_period_code: str = "34"             # год
    tax_period_year: int = 2024
    # Даты/время
    submission_datetime: datetime           # когда отправил
    acceptance_datetime: datetime           # когда приняли (1166002)
    processing_datetime: datetime           # когда ввели без ошибок (1166007)
    # Реквизиты квитанции
    registration_number: str                # 20 цифр
```

Генераторы:

```python
def generate_document_uuid(operator: EdoOperator) -> str:
    """
    Kontur: формат 8-4-4-12 через дефисы (нестандарт):
      "11d1af3ccff1-d445-dc47-a23025d6aa8a"
    Tensor: стандартный UUID v4 8-4-4-4-12:
      "12d6c8ca-4bf8-4df5-a370-ce44469d1650"
    """

def generate_file_name(
    operator: EdoOperator,
    ifns_code: str,
    declarant_inn: str,
    date: datetime,
    uuid_str: str,
) -> str:
    """NO_USN_<ifns>_<ifns>_<inn>_<YYYYMMDD>_<uuid>"""

def generate_registration_number(
    received_at: datetime,
    sequence: int | None = None,
) -> str:
    """
    20 цифр. Эталон Тензора: 00000000002774176425.
    Структура: видимо 8 ведущих нулей + 12-значный ID (timestamp+counter).
    Для демо-режима генерируем случайный 20-значный с ведущими нулями.
    """

def compute_receipt_timestamps(
    signing_datetime: datetime,
    operator: EdoOperator,
) -> tuple[datetime, datetime, datetime]:
    """
    Returns (submission_dt, acceptance_dt, processing_dt).

    Правила из эталонов:
    - submission ≈ signing_datetime + несколько секунд (для Тензора: 07:49:53 vs signing 07:49)
    - acceptance ≈ signing_datetime + 30-120 минут (Тензор: 07:49 → 08:23)
    - processing ≈ acceptance + 0-5 минут (Тензор: 08:23 → 08:26)

    Для Контура — аналогичная дельта но другой текст: 14:12 (отправлено) → 16:42 (принято)
    """
```

### Решение 4: Штампы ЭДО на квитанциях

После `RENDERING_STAMPS`, `apply_stamps(pdf_bytes, ...)` накладывает штампы на весь 6-страничный PDF. Тензоровский рендерер уже поддерживает произвольное число страниц (footer одинаковый на каждой). Для Контура — проверить, что `render_kontur_page(cfg, page_idx)` корректно работает для page_idx >= 1 (там `_render_kontur_page1` только для стр.1 — большой блок справа; для остальных `_render_kontur_page_n` — footer).

### Решение 5: Опциональность квитанций

Добавить в `StampsConfig`:
```python
class StampsConfig(BaseModel):
    enabled: bool = True
    operator: EdoOperator = EdoOperator.KONTUR
    tax_authority_inn: str | None = None
    include_receipts: bool = True    # ← новое: добавлять ли КНД 1166002 и 1166007
```

Если `include_receipts=False` — pipeline вернёт 4-страничный PDF (как текущий КОНТУР эталон).
Если `True` — 6-страничный.

## Обновление `modules/edo_stamps/__init__.py`

```python
# было:
def apply_stamps(*, pdf_bytes, operator, taxpayer_inn, ifts_info, tax_office_code) -> bytes: ...

# станет:
def apply_stamps(
    *,
    pdf_bytes,                # 4- или 6-страничный PDF
    operator,
    taxpayer_inn,
    ifts_info,
    tax_office_code,
) -> bytes: ...

# новая функция:
def build_receipt_pages(
    *,
    receipt_data: ReceiptData,
) -> bytes:
    """Рендерит 2 страницы квитанций (КНД 1166002 + КНД 1166007) как единый PDF."""

# новая функция:
def assemble_full_package(
    *,
    declaration_pdf: bytes,   # 4 стр.
    receipts_pdf: bytes,      # 2 стр.
) -> bytes:
    """Объединяет декларацию и квитанции в один 6-страничный PDF через pypdf."""
```

## Обновление pipeline

```python
async def run_pipeline(...):
    ...
    # 5. Рендер декларации → 4 стр.
    declaration_pdf = render_declaration_pdf(...)

    # NEW 5b. Если нужны квитанции — собираем полный пакет
    if req.stamps.enabled and req.stamps.include_receipts:
        await tracker.emit(PipelineStage.APPENDING_RECEIPTS)
        try:
            # Данные для квитанций требуют ifts_info — значит fetch_ifts_data
            # переносим ДО рендера квитанций
            ifts_info = await fetch_ifts_data(...)
            receipt_data = build_receipt_data(
                operator=req.stamps.operator,
                taxpayer=req.taxpayer,
                tax_period_year=req.tax_period_year,
                ifts_info=ifts_info,
                signing_datetime=now_msk(),
            )
            receipts_pdf = build_receipt_pages(receipt_data=receipt_data)
            full_pdf = assemble_full_package(
                declaration_pdf=declaration_pdf,
                receipts_pdf=receipts_pdf,
            )
        except Exception as e:
            raise ReceiptsRenderError(...) from e
    else:
        full_pdf = declaration_pdf

    # 7. Штампы на всех страницах (4 или 6)
    if req.stamps.enabled:
        stamped_pdf = apply_stamps(pdf_bytes=full_pdf, ...)
    else:
        stamped_pdf = full_pdf
```

## Порядок реализации

### Фаза 0c.1 — разметка КНД 1166002 (1 день)
- Скачать/извлечь чистый бланк с nalog.ru
- Разметить `fields.json` (~20 полей)
- Написать `render_receipt_1166002(data) -> bytes`
- Pixel-diff тест с 1 эталоном

### Фаза 0c.2 — разметка КНД 1166007 (0.5 дня)
- То же самое, форма проще (~12 полей)
- Pixel-diff тест

### Фаза 0c.3 — генератор реквизитов (0.5 дня)
- `generate_document_uuid` (Kontur и Tensor форматы)
- `generate_file_name`
- `generate_registration_number`
- `compute_receipt_timestamps`
- Unit-тесты на каждый

### Фаза 0c.4 — assemble + apply_stamps integration (0.5 дня)
- `build_receipt_pages` склейка 2 страниц
- `assemble_full_package` склейка деклараций + квитанций
- Убедиться что штампы Контур-footer правильно рендерятся на стр.5-6

### Фаза 0c.5 — pixel-diff на эталоне ТЕНЗОР (0.5 дня)
- Взять `Романов_УСН_2025.pdf` как эталон
- Вбить его данные в input.json
- Прогнать полный pipeline
- Compare с эталоном (допуск ≤10 px на страницу)

**Итого к Фазе 0: +3 дня** сверх ADR-002.

## Новые зависимости

Нет. Всё на reportlab + pypdf, которые уже в стеке.

## Открытые вопросы

1. **Регистрационный номер квитанции** — как именно его генерировать? В эталоне: `00000000002774176425`. Первые 8 цифр — нули, похоже на бухгалтерский счётчик ФНС. Для демо режима генерируем псевдо-случайно, в проде может потребоваться синхронизация с реальным СБИС/Контуром или просто ставить `00000000000000000000` (неучитываемое значение).

2. **Содержимое полей "руководитель ИФНС"** — через DaData `lookup_fns_unit` по коду ИФНС. В эталоне КОНТУР: "Шилова Елена Алексеевна, начальник инспекции". В ТЕНЗОР: "Фахретдинов Марат Мансурович, Руководитель".

3. **Дата и время представления** — брать из `signing_datetime` клиента (в UI) или генерировать на сервере? **Решение: генерировать на сервере** с текущим временем MSK (как реальные оператора ЭДО).

4. **Часовой пояс** — все тексты в эталонах указывают `(MSK)`. Используем `ZoneInfo("Europe/Moscow")`, не UTC.

5. **Представитель vs налогоплательщик** — в эталоне КОНТУР подпись представителя (Коровина), в ТЕНЗОР тоже представитель (Куприянова). В UI нужны поля для представителя; если не заполнены — используется сам ИП.
