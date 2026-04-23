# modules/edo_stamps

**Источник:** https://github.com/AMCPROG/edo-stamps (приватный, ждём доступа)

## Статус

🟡 Блокер — edo-stamps всё ещё приватный на момент написания. После того как сделаешь public:

```bash
git clone https://github.com/AMCPROG/edo-stamps.git /tmp/edo-stamps
./scripts/sync_stamps.sh /tmp/edo-stamps  # скрипт появится после анализа
```

## Контракт, который должен экспортировать модуль

```python
# modules/edo_stamps/__init__.py

from .ifts import fetch_ifts_data
from .stamps import apply_stamps

__all__ = ["fetch_ifts_data", "apply_stamps"]
```

### fetch_ifts_data(ifns_code: str, override_inn: str | None = None) -> IftsInfo

**Вход:**
- `ifns_code` — 4-значный код ИФНС
- `override_inn` — ИНН налогового органа, если явно задан пользователем

**Выход:**
```python
@dataclass
class IftsInfo:
    inn: str       # ИНН налогового органа
    name: str      # краткое наименование
    address: str   # адрес (для штампа)
    ogrn: str | None = None
```

**Источник данных:** DaData API по `ifns_code`. В оригинале edo-stamps уже есть.

### apply_stamps(pdf_bytes: bytes, operator: EdoOperator, taxpayer_inn: str, ifts_info: IftsInfo) -> bytes

**Вход:**
- `pdf_bytes` — готовая декларация без штампов
- `operator` — `kontur` или `tensor` (разные макеты штампов)
- `taxpayer_inn` — ИНН отправителя
- `ifts_info` — данные получателя

**Выход:** bytes PDF со штампами отправителя и получателя.

**Важно:** оверлей без пересжатия — использовать pymupdf (`page.insert_text`, `page.insert_image`) или оставшуюся реализацию из edo-stamps. НЕ использовать reportlab canvas merge — он может испортить качество.

## После получения доступа к edo-stamps

Задачи:

1. Прочитать `stamp_rendering.py` — определить стек (pymupdf / reportlab / pdfrw)
2. Если pymupdf — копируем почти как есть + адаптируем сигнатуру
3. Если другое — мигрировать на pymupdf (ADR-001, решение 3)
4. Извлечь координаты штампов в `templates/stamps/kontur.json` и `tensor.json`
5. Написать `__init__.py` под контракт выше
6. Обновить `docs/SOURCES_INVENTORY.md` с commit hash

## Координаты штампов (templates/stamps/*.json)

После анализа там должны появиться файлы вида:
```json
{
  "sender": {
    "position": { "x": 20, "y": 750, "width": 180, "height": 80 },
    "font": "PTSans",
    "font_size": 8,
    "color": "#1E5AA8",
    "fields": {
      "title": { "x": 10, "y": 10, "text": "Документ подписан..." },
      "inn": { "x": 10, "y": 25 },
      "timestamp": { "x": 10, "y": 40 }
    }
  },
  "receiver": { "..." }
}
```
