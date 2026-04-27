"""
Генераторы параметров ЭДО-штампов и квитанций — портировано из
https://github.com/Abramcorp/edo-stamps (edo_app/app.py).

Содержит:
- generate_fns_manager_name(code) — ФИО начальника ИФНС (детерминировано по SHA256)
- FNS_MANAGER_FALLBACK — известные реальные руководители
- generate_datetime_pair(...) — реалистичные даты отправки/приёма (будни 9-18 MSK)
- generate_cert_dates(send_dt) — период действия сертификата (25%-75% от 365 дней)
- generate_uuid() — UUID документа / идентификатор отправки
- generate_certificate(op, is_receiver) — форматы kontur/tensor
- generate_registration_number() — 20 цифр с ведущими нулями
- generate_file_name() — NO_USN_{ifns}_{ifns}_{inn}_{date}_{uuid}
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta


# ============================================================
# Пулы имён для детерминированной генерации ФИО начальника
# ============================================================

FNS_SURNAMES = [
    "Иванова", "Петрова", "Сидорова", "Кузнецова", "Попова", "Соколова",
    "Лебедева", "Козлова", "Новикова", "Морозова", "Волкова", "Соловьёва",
    "Васильева", "Зайцева", "Павлова", "Семёнова", "Голубева", "Виноградова",
    "Смирнов", "Иванов", "Кузнецов", "Попов", "Соколов", "Лебедев",
    "Козлов", "Новиков", "Морозов", "Петров", "Волков", "Соловьёв",
]

FNS_NAMES_FEMALE = [
    "Елена", "Ольга", "Наталья", "Татьяна", "Ирина", "Светлана",
    "Марина", "Людмила", "Екатерина", "Анна", "Юлия", "Мария",
]

FNS_NAMES_MALE = [
    "Александр", "Сергей", "Андрей", "Дмитрий", "Алексей", "Владимир",
    "Евгений", "Михаил", "Николай", "Олег", "Игорь", "Виктор",
]

FNS_PATRONYMICS_FEMALE = [
    "Александровна", "Сергеевна", "Андреевна", "Дмитриевна", "Алексеевна",
    "Владимировна", "Евгеньевна", "Михайловна", "Николаевна", "Олеговна",
]

FNS_PATRONYMICS_MALE = [
    "Александрович", "Сергеевич", "Андреевич", "Дмитриевич", "Алексеевич",
    "Владимирович", "Евгеньевич", "Михайлович", "Николаевич", "Олегович",
]


FNS_MANAGER_FALLBACK: dict[str, dict[str, str]] = {
    "5800": {  # УФНС по Пензенской области
        "name": "Шилова Елена Алексеевна",
        "post_kontur": "начальник инспекции",
        "post_tensor": "Начальник",
    },
    "5027": {  # МИФНС №17 по Московской области
        "name": "Лабзова Наталья Владимировна",
        "post_kontur": "начальник инспекции",
        "post_tensor": "Начальник",
    },
    "7734": {  # ИФНС №34 по г. Москве
        "name": "Шевлякова Анастасия Сергеевна",
        "post_kontur": "начальник инспекции",
        "post_tensor": "Начальник",
    },
}


def generate_fns_manager_name(fns_code: str) -> str:
    """ФИО начальника ИФНС: детерминированно по SHA256(fns_code).
    Сначала FNS_MANAGER_FALLBACK, иначе генерация из пулов."""
    if not fns_code:
        return ""
    if fns_code in FNS_MANAGER_FALLBACK:
        return FNS_MANAGER_FALLBACK[fns_code]["name"]
    seed = int(hashlib.sha256(fns_code.encode()).hexdigest(), 16)
    is_female = (seed % 2) == 0
    if is_female:
        surnames_pool = [s for s in FNS_SURNAMES if s.endswith('ва') or s.endswith('ая')]
        surname = surnames_pool[(seed // 2) % len(surnames_pool)]
        name = FNS_NAMES_FEMALE[(seed // 3) % len(FNS_NAMES_FEMALE)]
        patronymic = FNS_PATRONYMICS_FEMALE[(seed // 5) % len(FNS_PATRONYMICS_FEMALE)]
    else:
        surnames_pool = [s for s in FNS_SURNAMES if not (s.endswith('ва') or s.endswith('ая'))]
        surname = surnames_pool[(seed // 2) % len(surnames_pool)]
        name = FNS_NAMES_MALE[(seed // 3) % len(FNS_NAMES_MALE)]
        patronymic = FNS_PATRONYMICS_MALE[(seed // 5) % len(FNS_PATRONYMICS_MALE)]
    return f"{surname} {name} {patronymic}"


def get_manager_post(fns_code: str, operator: str) -> str:
    """Должность начальника в формате оператора (kontur/tensor)."""
    if fns_code in FNS_MANAGER_FALLBACK:
        key = "post_tensor" if operator == "tensor" else "post_kontur"
        return FNS_MANAGER_FALLBACK[fns_code].get(key, "Начальник")
    return "Начальник" if operator == "tensor" else "начальник инспекции"


# ============================================================
# UUID
# ============================================================

def generate_uuid() -> str:
    return str(uuid.uuid4())


# ============================================================
# Сертификаты
# ============================================================

def generate_cert_dates(send_dt: datetime, offset_extra: int = 0) -> tuple[str, str]:
    """Период действия сертификата. Дата отправки попадает в 25-75%
    срока (91-274 дня после выдачи). Срок — 365 дней."""
    days_since_issue = 91 + int(secrets.randbelow(183))
    cert_from = send_dt - timedelta(days=days_since_issue) + timedelta(days=offset_extra)
    actual_pct = (send_dt - cert_from).days / 365 * 100
    if not (25 <= actual_pct <= 75):
        cert_from = send_dt - timedelta(days=91 + int(secrets.randbelow(183)))
    cert_to = cert_from + timedelta(days=365)
    return cert_from.strftime("%d.%m.%Y"), cert_to.strftime("%d.%m.%Y")


def gen_cert_kontur() -> str:
    hex_len = 39 + secrets.randbelow(2)
    return secrets.token_hex(hex_len // 2 + 1)[:hex_len].lower()


def gen_cert_send_tensor() -> str:
    """'02' + 32 hex (34 total UPPER)."""
    return "02" + secrets.token_hex(16).upper()


def gen_cert_ifns_tensor() -> str:
    """32 или 34 hex UPPER."""
    n = 32 + secrets.randbelow(2) * 2
    return secrets.token_hex(n // 2).upper()


def generate_certificate(operator: str = "kontur", is_receiver: bool = False) -> str:
    if operator == "tensor":
        return gen_cert_ifns_tensor() if is_receiver else gen_cert_send_tensor()
    return gen_cert_kontur()


# ============================================================
# Даты отправки/приёма
# ============================================================

def generate_datetime_pair(
    send_date: str | None = None,
    report_year: int | None = None,
    correction: int = 0,
) -> dict:
    """Реалистичная пара дат отправки/приёма декларации УСН.

    Первичная (correction=0): случайный рабочий день 21 янв — 19 апр.
    Корректирующая: 25 апр — 30 ноя. Время 9-18 MSK.
    Задержка приёма 15-180 мин.
    """
    if send_date:
        try:
            dt_send = datetime.strptime(send_date, "%Y%m%d")
            hour = 9 + int(secrets.randbelow(10))
            minute = int(secrets.randbelow(60))
            dt_send = dt_send.replace(hour=hour, minute=minute)
        except ValueError:
            dt_send = datetime.now()
    elif report_year:
        year_next = report_year + 1
        if correction == 0:
            start = datetime(year_next, 1, 21)
            end = datetime(year_next, 4, 19)
        else:
            start = datetime(year_next, 4, 25)
            end = datetime(year_next, 11, 30)
        total_days = max((end - start).days, 1)
        rand_day = int(secrets.randbelow(total_days))
        dt_send = start + timedelta(days=rand_day)
        while dt_send.weekday() >= 5:
            dt_send += timedelta(days=1)
        hour = 9 + int(secrets.randbelow(10))
        minute = int(secrets.randbelow(60))
        dt_send = dt_send.replace(hour=hour, minute=minute)
    else:
        dt_send = datetime.now()

    delay_min = 15 + int(secrets.randbelow(165))
    dt_recv = dt_send + timedelta(minutes=delay_min)

    return {
        "tensor_send": dt_send.strftime("%d.%m.%y %H:%M (MSK)"),
        "tensor_recv": dt_recv.strftime("%d.%m.%y %H:%M (MSK)"),
        "kontur_send": dt_send.strftime("%d.%m.%Y в %H:%M"),
        "kontur_recv": dt_recv.strftime("%d.%m.%Y в %H:%M"),
        "date_send_short": dt_send.strftime("%d.%m.%Y"),
        "date_recv_short": dt_recv.strftime("%d.%m.%Y"),
        "send_date_yyyymmdd": dt_send.strftime("%Y%m%d"),
        "cert_from": dt_send.strftime("%d.%m.%Y"),
        "cert_to": (dt_send + timedelta(days=365)).strftime("%d.%m.%Y"),
        "dt_send_iso": dt_send.isoformat(),
        "dt_recv_iso": dt_recv.isoformat(),
    }


# ============================================================
# Регистрационный номер и имя файла
# ============================================================

def generate_registration_number() -> str:
    """Регистрационный номер ФНС: 20 цифр (ведущие нули для реализма)."""
    return "00000000" + "".join(str(secrets.randbelow(10)) for _ in range(12))


def generate_file_name(
    *,
    ifns_code: str,
    declarant_inn: str,
    date_yyyymmdd: str,
    document_uuid: str,
) -> str:
    """Имя файла декларации в стандарте ФНС:
    NO_USN_{ifns}_{ifns}_{inn}_{yyyymmdd}_{uuid}"""
    return f"NO_USN_{ifns_code}_{ifns_code}_{declarant_inn}_{date_yyyymmdd}_{document_uuid}"
