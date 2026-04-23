# modules/declaration_filler

**Источник:** https://github.com/Abramcorp/usn-declaration, директория `app/services/`

## Как попадает сюда

```bash
./scripts/sync_sources.sh /path/to/cloned/usn-declaration
```

После копирования здесь должны лежать:

```
declaration_filler/
├── __init__.py              ⬅ пишется вручную, экспортирует контракт (см. ниже)
├── parser.py
├── ofd_parser.py
├── classifier.py
├── revenue_calculator.py
├── contributions_calculator.py
├── tax_engine.py
├── declaration_generator.py
├── utils.py
└── dictionaries/
    ├── income_markers.json
    └── exclude_markers.json
```

## Почему нужен `__init__.py` и адаптация

Оригинальный код в usn-declaration был завязан на ORM-сущности (Project, BankOperation из SQLAlchemy). В USN_COMPLETE мы БД-сущностей не используем (stateless pipeline).

Поэтому нужен тонкий адаптер (`__init__.py`), который:
1. Подменяет ORM-сущности на dataclasses/dict
2. Адаптирует сигнатуры функций под контракт `core/pipeline.py`

## Контракт, который должен экспортировать модуль

```python
# modules/declaration_filler/__init__.py

from . import parser, ofd_parser, classifier, tax_engine, declaration_generator
```

И каждый подмодуль должен предоставить следующие функции **после адаптации**:

### parser.parse_1c_statement_bytes(data: bytes) -> Statement
**Вход:** байты .txt файла 1С-выписки
**Выход:** dataclass Statement с полями:
```python
@dataclass
class Statement:
    owner_inn: str
    owner_fio: str
    period_start: date
    period_end: date
    operations: list[BankOperation]  # dataclass, не ORM
```
**В оригинале:** `BankStatementParser` работает с файлом. Нужна обёртка, читающая из `BytesIO`.

### ofd_parser.parse_ofd_bytes(data: bytes) -> list[OfdReceipt]
**Вход:** байты .xlsx с чеками ОФД
**Выход:** список dataclass OfdReceipt

### classifier.classify_operations(statement: Statement) -> ClassifiedOps
**Вход:** Statement от парсера
**Выход:** dataclass с разделением операций на доходы/расходы/прочее + квартальные суммы

### tax_engine.calculate(**kwargs) -> TaxResult
**Вход:** classified + ofd_receipts + contributions + personnel + tax_period_year
**Выход:** dataclass TaxResult с полями для заполнения декларации (строки 110-143 раздела 2.1.1 и т.д.)

### declaration_generator.render_declaration_pdf(taxpayer, tax_period_year, tax_result) -> bytes
**Вход:** все данные для декларации
**Выход:** bytes готового PDF (reportlab)

## Что НЕ переносить

- `xlsx_to_pdf.py` — путь через LibreOffice, не используется
- `excel_declaration.py` — если выбран путь `declaration_generator.py` (reportlab)
  - Если оставить XLSX-путь как опцию — тогда перенести, но переключатель feature-flag не добавляем в MVP
- `summary_pdf.py` — справочный PDF, не нужен
- `contribution_calculator.py` (без `s`) — старая версия, удалить в пользу `contributions_calculator.py`

## Commit hash оригинала

Заполнить после первого запуска `sync_sources.sh`:

```
Source: https://github.com/Abramcorp/usn-declaration
Commit: TBD
Date:   TBD
```
