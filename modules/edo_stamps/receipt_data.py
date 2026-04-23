"""
Генератор реквизитов для квитанций КНД 1166002 и КНД 1166007.

Реализует генерацию:
  - document UUID (разные форматы для Kontur / Tensor)
  - имя файла PDF (NO_USN_<ifns>_<ifns>_<inn>_<YYYYMMDD>_<uuid>)
  - регистрационный номер (20 цифр)
  - таймстампы: submission / acceptance / processing

Все даты/время — в московской TZ (налоговые квитанции работают в MSK).

См. ADR-003 для деталей.
"""
from __future__ import annotations

import random
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


# ============================================================
# Типы
# ============================================================

OperatorLiteral = Literal["kontur", "tensor"]


@dataclass
class ReceiptTimestamps:
    """Три контрольных момента жизни декларации у оператора ЭДО."""
    signing: datetime         # клиент подписал (исходная точка)
    submission: datetime      # оператор зафиксировал отправку (+секунды от signing)
    acceptance: datetime      # ФНС приняла (квитанция 1166002) — +30–120 минут
    processing: datetime      # ФНС ввела без ошибок (1166007) — +0–5 минут от acceptance


# ============================================================
# UUID для идентификатора документа
# ============================================================

# Kontur: нестандартный формат "8-4-4-12" (всего 32 hex, дефисы в позициях 8, 12, 16)
# Пример: 11d1af3ccff1-d445-dc47-a23025d6aa8a
#  Реально это 8-4-4-12 = 28 hex + 4 hex prefix = 32. Даже не совсем стандарт.
#  Разметка: [XXXXXXXX][XXXX]-[XXXX]-[XXXX]-[XXXXXXXXXXXX]
#  = префикс 8 hex + 4 hex слитно, потом три дефиса и 4-4-12
#  Итого 32 hex символа с дефисами в позициях 12, 17, 22.

def _kontur_uuid_from_hex32(hex32: str) -> str:
    """Превратить 32 hex символа в Kontur-формат 12-4-4-12."""
    assert len(hex32) == 32 and re.fullmatch(r"[0-9a-f]{32}", hex32), \
        f"expected 32 lowercase hex, got {hex32!r}"
    return f"{hex32[0:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"


def _tensor_uuid_from_hex32(hex32: str) -> str:
    """Стандартный UUID v4 формат 8-4-4-4-12."""
    assert len(hex32) == 32 and re.fullmatch(r"[0-9a-f]{32}", hex32), \
        f"expected 32 lowercase hex, got {hex32!r}"
    return f"{hex32[0:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"


def generate_document_uuid(operator: OperatorLiteral) -> str:
    """
    Генерирует UUID для идентификатора документа в формате оператора.

    >>> u = generate_document_uuid("tensor")
    >>> re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", u) is not None
    True
    >>> u = generate_document_uuid("kontur")
    >>> re.fullmatch(r"[0-9a-f]{12}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", u) is not None
    True
    """
    hex32 = secrets.token_hex(16)  # 16 bytes = 32 hex chars
    if operator == "kontur":
        return _kontur_uuid_from_hex32(hex32)
    elif operator == "tensor":
        return _tensor_uuid_from_hex32(hex32)
    raise ValueError(f"unknown operator: {operator}")


# ============================================================
# Имя файла PDF
# ============================================================

_FILENAME_INN_RE = re.compile(r"^\d{10}|\d{12}$")
_FILENAME_IFNS_RE = re.compile(r"^\d{4}$")


def generate_file_name(
    *,
    operator: OperatorLiteral,
    ifns_code: str,
    declarant_inn: str,
    date: datetime,
    document_uuid: str | None = None,
) -> str:
    """
    Формат имени файла квитанции/декларации:
        NO_USN_<ifns>_<ifns>_<inn>_<YYYYMMDD>_<uuid>

    Примеры из эталонов:
        NO_USN_5800_5800_583806352199_20250210_11d1af3ccff1-d445-dc47-a23025d6aa8a  (Kontur)
        NO_USN_3300_3300_330517711336_20260124_12d6c8ca-4bf8-4df5-a370-ce44469d1650  (Tensor)

    Args:
        operator: 'kontur' или 'tensor' — определяет формат UUID
        ifns_code: 4-значный код ИФНС
        declarant_inn: 10 или 12 цифр
        date: дата операции (год-месяц-день попадёт в имя)
        document_uuid: если не указан — генерируется

    Returns:
        Имя файла без расширения.
    """
    if not _FILENAME_IFNS_RE.fullmatch(ifns_code):
        raise ValueError(f"ifns_code должен быть 4 цифры, получено: {ifns_code!r}")
    if not declarant_inn.isdigit() or len(declarant_inn) not in (10, 12):
        raise ValueError(f"declarant_inn должен быть 10 или 12 цифр, получено: {declarant_inn!r}")

    uuid_str = document_uuid or generate_document_uuid(operator)
    date_str = date.strftime("%Y%m%d")
    return f"NO_USN_{ifns_code}_{ifns_code}_{declarant_inn}_{date_str}_{uuid_str}"


# ============================================================
# Регистрационный номер
# ============================================================

def generate_registration_number(
    *,
    seed: int | None = None,
    leading_zeros: int = 8,
) -> str:
    """
    Регистрационный номер квитанции: 20 цифр.

    Эталон Тензора: "00000000002774176425" — 8 ведущих нулей + 12-значный ID.

    Для демо/тестов возвращаем именно такую структуру.

    Args:
        seed: если указан — используется для RNG (детерминизм тестов)
        leading_zeros: число ведущих нулей (дефолт 8, как в эталоне)

    Returns:
        20-значная строка с ведущими нулями.
    """
    if leading_zeros < 0 or leading_zeros > 19:
        raise ValueError("leading_zeros должно быть в [0, 19]")

    rnd = random.Random(seed) if seed is not None else random.SystemRandom()
    tail_digits = 20 - leading_zeros
    tail_max = 10 ** tail_digits - 1
    tail = rnd.randint(1, tail_max)
    return "0" * leading_zeros + str(tail).zfill(tail_digits)


# ============================================================
# Таймстампы
# ============================================================

# Эталонные дельты (наблюдения из образцов):
#   Tensor: signing 07:49 → submission 07:49:53 → acceptance 08:23 → processing 08:26
#           submission = +0..59 сек
#           acceptance = +30..60 мин
#           processing = +2..5 мин после acceptance
#   Kontur: signing 14:12 → принято 16:42
#           acceptance = +150 мин (иногда дольше)

_DELTAS = {
    "kontur": {
        "submission_sec": (5, 90),        # +секунды
        "acceptance_min": (60, 180),      # +минуты
        "processing_min": (0, 5),         # +минуты после acceptance
    },
    "tensor": {
        "submission_sec": (5, 90),
        "acceptance_min": (25, 75),
        "processing_min": (2, 10),
    },
}


def compute_receipt_timestamps(
    *,
    signing_datetime: datetime,
    operator: OperatorLiteral,
    seed: int | None = None,
) -> ReceiptTimestamps:
    """
    Для заданного момента подписания декларации генерирует три последующих таймстампа
    (submission / acceptance / processing), правдоподобные для оператора.

    Все даты принудительно приводятся к MSK (Europe/Moscow). Если вход naïve — считаем что он MSK.

    Args:
        signing_datetime: момент подписания декларации клиентом
        operator: 'kontur' или 'tensor' — у них разные временные дельты
        seed: детерминизм для тестов

    Returns:
        ReceiptTimestamps с 4 полями (signing + submission + acceptance + processing).
    """
    if signing_datetime.tzinfo is None:
        signing = signing_datetime.replace(tzinfo=MSK)
    else:
        signing = signing_datetime.astimezone(MSK)

    if operator not in _DELTAS:
        raise ValueError(f"unknown operator: {operator!r}")

    rnd = random.Random(seed) if seed is not None else random.SystemRandom()
    d = _DELTAS[operator]

    submission = signing + timedelta(seconds=rnd.randint(*d["submission_sec"]))
    acceptance = signing + timedelta(minutes=rnd.randint(*d["acceptance_min"]))
    processing = acceptance + timedelta(minutes=rnd.randint(*d["processing_min"]))

    return ReceiptTimestamps(
        signing=signing,
        submission=submission,
        acceptance=acceptance,
        processing=processing,
    )


# ============================================================
# Публичный API
# ============================================================

__all__ = [
    "OperatorLiteral",
    "ReceiptTimestamps",
    "MSK",
    "generate_document_uuid",
    "generate_file_name",
    "generate_registration_number",
    "compute_receipt_timestamps",
]
