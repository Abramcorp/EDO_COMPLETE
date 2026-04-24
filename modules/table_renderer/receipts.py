"""
Рендер квитанций ФНС через reportlab Canvas:
- стр.1: Квитанция о приёме налоговой декларации (КНД 1166002)
- стр.2: Извещение о вводе сведений (КНД 1166007)

Замена старого modules/edo_stamps/receipt_renderer.py — теперь вся
вёрстка идёт через текст + линии + таблицы, без векторной подложки.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from reportlab.pdfgen import canvas as _canvas

from ._cells import PAGE_W, PAGE_H, FONT_REGULAR, FONT_BOLD, hline, register_fonts, text


# ============================================================
# DTO — input для рендера
# ============================================================

@dataclass
class ReceiptRenderData:
    # Кто подаёт
    taxpayer_inn: str
    taxpayer_fio: str             # "ИНДИВИДУАЛЬНЫЙ ПРЕДПРИНИМАТЕЛЬ ИВАНОВ И.И., 330573397709" etc.
    ifns_code: str                # "5003"
    ifts_full_name: str           # Полное наименование ИФНС
    declaration_knd: str = "1152017"
    correction_number: int = 0
    tax_period_year: int = 2025
    # Параметры квитанции
    file_name: str = ""
    submission_datetime: datetime | None = None
    acceptance_datetime: datetime | None = None
    registration_number: str = ""


# ============================================================
# Публичный API
# ============================================================

def render_receipt_pages(data: ReceiptRenderData) -> bytes:
    """Рендерит 2-страничный PDF с квитанциями.

    Returns:
        bytes — двухстраничный PDF.
    """
    register_fonts()
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setTitle(f"Квитанции ФНС — ИНН {data.taxpayer_inn}")
    c.setAuthor("EDO_COMPLETE")

    _draw_1166002(c, data)
    c.showPage()
    _draw_1166007(c, data)
    c.showPage()

    c.save()
    return buf.getvalue()


# ============================================================
# Стр.1 — КНД 1166002 "Квитанция о приёме"
# ============================================================

def _draw_1166002(c, data: ReceiptRenderData) -> None:
    # Форма КНД в правом верхнем углу
    text(c, PAGE_W - 30, 820, "КНД 1166002", font_size=9.0, align="right")

    # "место штампа налогового органа" (левый верх)
    text(c, 40, 800, "место штампа", font_size=8.5)
    text(c, 40, 790, "налогового органа", font_size=8.5)

    # Блок справа — реквизиты налогоплательщика
    rx = 350.0
    hline(c, rx, 790, PAGE_W - 30)
    # Имя + ИНН над линией
    text(c, rx, 795, data.taxpayer_fio, font_size=9.0)
    hline(c, rx, 770, PAGE_W - 30)
    text(c, rx, 775, data.taxpayer_inn, font_size=9.0)
    # Подпись к блоку — мелким шрифтом
    y_hint = 760
    lines = [
        "(реквизиты налогоплательщика",
        "(представителя):",
        "- полное наименование",
        "организации, ИНН/КПП;",
        "- Ф.И.О. индивидуального",
        "предпринимателя (физического",
        "лица), ИНН (при наличии))",
    ]
    for i, line in enumerate(lines):
        text(c, rx, y_hint - i * 9, line, font_size=7.0)

    # Заголовок квитанции (по центру)
    text(c, PAGE_W / 2, 660, "Квитанция", bold=True, font_size=12.0, align="center")
    text(c, PAGE_W / 2, 645,
         "о приеме налоговой декларации (расчета)",
         bold=True, font_size=11.0, align="center")
    text(c, PAGE_W / 2, 632, "в электронном виде",
         bold=True, font_size=11.0, align="center")

    # "Налоговый орган ..."
    y = 600
    text(c, 40, y, "Налоговый орган", font_size=9.5)
    # Место под название ИФНС — две строки
    hline(c, 130, y - 2, 430)
    # Разделим имя ИФНС на 2 строки если длинное
    name = data.ifts_full_name
    if len(name) > 40:
        # ищем пробел ближе к середине
        mid = len(name) // 2
        left = name.rfind(" ", 0, mid + 10)
        if left > 0:
            line1 = name[:left]
            line2 = name[left + 1:]
        else:
            line1, line2 = name, ""
    else:
        line1, line2 = name, ""
    text(c, 135, y + 2, line1, font_size=9.0)
    if line2:
        text(c, 135, y - 13, line2, font_size=9.0)
        hline(c, 130, y - 17, 430)
    text(c, 435, y, "настоящим документом подтверждает, что", font_size=9.5)
    text(c, 280, y - 15, "(наименование и код налогового органа)",
         font_size=7.0, align="center")

    # Строка для имени налогоплательщика
    y = 560
    hline(c, 40, y, PAGE_W - 30)
    text(c, PAGE_W / 2, y + 3, data.taxpayer_fio, font_size=9.0, align="center")
    text(c, PAGE_W / 2, y - 10,
         "(полное наименование организации, ИНН/КПП; ФИО индивидуального",
         font_size=7.0, align="center")
    text(c, PAGE_W / 2, y - 18,
         "предпринимателя (физического лица), ИНН (при наличии))",
         font_size=7.0, align="center")

    # Дата/время приёма декларации
    y = 515
    if data.submission_datetime:
        dt_str = data.submission_datetime.strftime("%d.%m.%Y  %H:%M.%S")
        text(c, 40, y, dt_str, font_size=9.5)
    hline(c, 40, y - 4, 300)

    # Имя декларации
    y = 490
    decl_text = (
        f"Налоговая декларация по налогу, уплачиваемому в связи с применением "
        f"упрощенной системы налогообложения"
    )
    text(c, 40, y, decl_text, font_size=9.0)
    hline(c, 40, y - 4, PAGE_W - 30)
    text(c, 40, y - 15,
         f"корректирующий ({data.correction_number})", font_size=9.0)
    hline(c, 40, y - 19, 200)
    text(c, 210, y - 15, f"за год, 34, {data.tax_period_year} год", font_size=9.0)
    hline(c, 205, y - 19, PAGE_W - 30)
    text(c, PAGE_W / 2, y - 28,
         "(наименование налоговой декларации, вид документа, отчетный период, отчетный год)",
         font_size=7.0, align="center")

    # "в файле"
    y = 445
    text(c, 40, y, "в файле", font_size=9.5)
    text(c, 100, y, data.file_name, font_size=8.5)
    hline(c, 95, y - 4, PAGE_W - 30)
    text(c, PAGE_W / 2, y - 15, "(наименование файла)", font_size=7.0, align="center")

    # "в налоговый орган"
    y = 420
    text(c, 40, y, "в налоговый орган", font_size=9.5)
    text(c, 140, y, f"{data.ifns_code})", font_size=9.0)
    hline(c, 135, y - 4, PAGE_W - 30)
    text(c, 40, y - 15,
         "                             (наименование и код налогового органа)",
         font_size=7.0)
    text(c, PAGE_W - 30, y, ",", font_size=9.5, align="right")

    # Дата приёма
    y = 395
    if data.acceptance_datetime:
        a_str = data.acceptance_datetime.strftime("%d.%m.%Y")
    else:
        a_str = ""
    text(c, 40, y, f"которая поступила {a_str} и принята налоговым органом {a_str}",
         font_size=9.5)
    text(c, 40, y - 15, "регистрационный номер", font_size=9.5)
    text(c, 145, y - 15, data.registration_number, font_size=9.0)
    hline(c, 140, y - 19, 300)
    text(c, PAGE_W / 2, y - 15, ".", font_size=9.0)

    # "Должностное лицо"
    y = 340
    text(c, 40, y, "Должностное лицо", bold=True, font_size=9.5)
    hline(c, 40, y - 15, 280)
    text(c, 160, y - 25, "(наименование налогового органа)",
         font_size=7.0, align="center")

    # Линии под "классный чин / подпись / Ф.И.О."
    y = 290
    hline(c, 40, y, 170)
    hline(c, 190, y, 320)
    hline(c, 340, y, PAGE_W - 30)
    text(c, 105, y - 10, "(классный чин)", font_size=7.0, align="center")
    text(c, 255, y - 10, "(подпись)", font_size=7.0, align="center")
    text(c, (340 + PAGE_W - 30) / 2, y - 10, "(Ф.И.О.)", font_size=7.0, align="center")

    # М.П.
    text(c, 200, y - 30, "М.П.", font_size=9.0)


# ============================================================
# Стр.2 — КНД 1166007 "Извещение о вводе сведений"
# ============================================================

def _draw_1166007(c, data: ReceiptRenderData) -> None:
    # Форма КНД в правом верхнем углу
    text(c, PAGE_W - 30, 820, "КНД 1166007", font_size=9.0, align="right")

    # "место штампа" (левый верх)
    text(c, 40, 800, "место штампа", font_size=8.5)
    text(c, 40, 790, "налогового органа", font_size=8.5)

    # Блок справа — реквизиты
    rx = 350.0
    hline(c, rx, 790, PAGE_W - 30)
    text(c, rx, 795, data.taxpayer_fio, font_size=9.0)
    hline(c, rx, 770, PAGE_W - 30)
    text(c, rx, 775, data.taxpayer_inn, font_size=9.0)
    hint_lines = [
        "(реквизиты налогоплательщика (представителя):",
        "- полное наименование организации, ИНН/КПП;",
        "- Ф.И.О. индивидуального предпринимателя",
        "(физического лица), ИНН (при наличии))",
    ]
    for i, line in enumerate(hint_lines):
        text(c, rx, 760 - i * 9, line, font_size=7.0)

    # Заголовок
    text(c, PAGE_W / 2, 670,
         "Извещение о вводе сведений, указанных в налоговой декларации (расчете)",
         bold=True, font_size=11.0, align="center")
    text(c, PAGE_W / 2, 657, "в электронной форме",
         bold=True, font_size=11.0, align="center")

    # "Налоговый орган XXXX настоящим документом подтверждает, что"
    y = 625
    text(c, 40, y, "Налоговый орган", font_size=9.5)
    text(c, 140, y, data.ifns_code, font_size=9.0)
    hline(c, 130, y - 4, 230)
    text(c, 235, y, "настоящим документом подтверждает, что", font_size=9.5)
    text(c, 175, y - 15, "(код налогового органа)", font_size=7.0, align="center")

    # Имя налогоплательщика
    y = 590
    hline(c, 40, y, PAGE_W - 30)
    text(c, PAGE_W / 2, y + 3, data.taxpayer_fio, font_size=9.0, align="center")
    text(c, PAGE_W / 2, y - 10,
         "(полное наименование организации, ИНН/КПП; Ф.И.О. индивидуального предпринимателя (физического лица), ИНН (при наличии))",
         font_size=6.5, align="center")
    text(c, PAGE_W - 30, y - 2, ",", font_size=10.0, align="right")

    # "в налоговой декларации (расчете)"
    y = 560
    text(c, 40, y, "в налоговой декларации (расчете)", font_size=9.5)

    # Описание декларации
    y = 540
    decl = (
        f"Налоговая декларация по налогу, уплачиваемому в связи с применением "
        f"упрощенной системы налогообложения {data.declaration_knd}, "
        f"корректирующий ({data.correction_number}), за год, {data.tax_period_year} год"
    )
    text(c, 40, y, decl, font_size=8.5)
    hline(c, 40, y - 4, PAGE_W - 30)
    text(c, PAGE_W / 2, y - 15,
         "(наименование и КНД налоговой декларации, вид документа (номер корректировки), отчетный (налоговый) период, отчетный год)",
         font_size=6.5, align="center")

    # "представленной в файле"
    y = 510
    text(c, 40, y, "представленной в файле", font_size=9.5)
    text(c, 150, y, data.file_name, font_size=8.5)
    hline(c, 145, y - 4, PAGE_W - 30)
    text(c, PAGE_W / 2, y - 15, "(наименование файла)", font_size=7.0, align="center")

    # "не содержится ошибок (противоречий)."
    y = 480
    text(c, 40, y, "не содержится ошибок (противоречий).", font_size=9.5)

    # Налоговый орган имя снизу
    y = 360
    hline(c, 40, y, PAGE_W - 30)
    text(c, PAGE_W / 2, y + 3,
         f"{data.ifts_full_name}, {data.ifns_code}",
         font_size=9.0, align="center")
    text(c, PAGE_W / 2, y - 10,
         "(наименование, код налогового органа)",
         font_size=7.0, align="center")
