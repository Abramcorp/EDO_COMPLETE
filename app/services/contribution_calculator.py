"""
Shim для `from app.services.contribution_calculator import get_rates`.

Возвращает ставки/лимиты за нужный год, забирая их из справочных таблиц
в modules.declaration_filler.contributions_calculator.
"""
from modules.declaration_filler.contributions_calculator import FIXED_IP, MAX_1PCT


def get_rates(year: int) -> dict:
    """
    Возвращает словарь со ставками/лимитами для указанного года.

    Ключи:
      - max_1pct:  максимум 1%-взноса ИП сверх 300 000 ₽
      - fixed_ip:  фиксированный совокупный взнос ИП за себя
    """
    return {
        "max_1pct": MAX_1PCT.get(year, MAX_1PCT[max(MAX_1PCT.keys())]),
        "fixed_ip": FIXED_IP.get(year, FIXED_IP[max(FIXED_IP.keys())]),
    }


__all__ = ["get_rates"]
