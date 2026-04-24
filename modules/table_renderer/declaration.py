"""
Рендер декларации КНД 1152017 через reportlab Canvas + таблицы клеточек.

На каждой из 4 страниц:
1. Штрих-код (PNG из templates/barcodes/) + "Форма по КНД 1152017"
2. Клетки ИНН + КПП + "Стр.XXX" в верхней правой зоне
3. Заголовок страницы (Приложение, № приказа...)
4. Body — формальные поля со значениями

Стр.1 — нижняя часть (подпись + дата) СДВИНУТА ВЫШЕ для освобождения
места под штамп ЭДО оператора.
"""
from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from typing import Any

from reportlab.pdfgen import canvas as _canvas

from ._cells import (
    PAGE_W, PAGE_H,
    CELL_W, CELL_H,
    FONT_REGULAR, FONT_BOLD,
    barcode_image, draw_cell_row, hline, register_fonts, text, wrap_text,
)


# ============================================================
# Утилиты форматирования
# ============================================================

def _fmt_int_12(amount: Any) -> str:
    """Сумма в копейках → строка цифр для 12-клеточного поля (в рублях,
    без копеек, как в УСН-декларации).

    5 000 руб → "5000"
    """
    if amount is None or amount == "":
        return ""
    try:
        # В данных уже рубли (Decimal), просто в int
        v = int(Decimal(str(amount)))
        return str(v)
    except Exception:
        return ""


def _fmt_rate(r: Any) -> str:
    """Ставка '6.0' → ('6', '0') для 2-клеточных групп.
    Возвращает 2 символа: integer + desimal (без точки)."""
    try:
        d = Decimal(str(r))
        int_part = int(d)
        dec_part = int((d - int_part) * 10)
        return f"{int_part}{dec_part}"
    except Exception:
        return "60"


# ============================================================
# Публичный API
# ============================================================

def render_declaration_pdf(
    *,
    taxpayer,              # api.models.TaxpayerInfo
    tax_period_year: int,
    tax_result,            # modules.declaration_filler.tax_engine.TaxResult
    correction_number: int = 0,
    signing_date: datetime | None = None,
) -> bytes:
    """Главная точка входа. Аналог старого render_declaration_pdf из
    declaration_filler, но рисует всё с нуля через Canvas+Table.

    Returns:
        bytes готового 4-страничного PDF (без штампов и квитанций).
    """
    register_fonts()
    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setTitle(f"Декларация УСН {tax_period_year} — ИНН {taxpayer.inn}")
    c.setAuthor("EDO_COMPLETE")

    # Плоский dict для удобного доступа
    data = dict(
        inn=taxpayer.inn,
        kpp="",
        fio=taxpayer.fio,
        oktmo=taxpayer.oktmo,
        ifns_code=taxpayer.ifns_code,
        year=tax_period_year,
        correction_number=correction_number,
        signing_date=signing_date or datetime.now(),
    )
    # Тянем декл-данные из tax_result (уже вычисленный pipeline'ом)
    decl = getattr(tax_result, "decl_data", {}) or {}
    data.update(decl)

    _draw_page_1(c, data)
    c.showPage()
    _draw_page_2(c, data)
    c.showPage()
    _draw_page_3(c, data)
    c.showPage()
    _draw_page_4(c, data)
    c.showPage()

    c.save()
    return buf.getvalue()


# ============================================================
# Стр.1 — Титульный лист
# ============================================================

def _draw_header_ink_kpp(c, data, page_num: int) -> None:
    """Общий header на всех страницах: штрих-код + "Форма по КНД..." +
    ИНН + КПП + "Стр.XXX" в правой зоне."""
    # Штрих-код (x=30, y=790, width=110)
    barcode_image(c, page_num, 30.0, 790.0, width=110.0)
    # "Форма по КНД 1152017" под штрих-кодом (только стр.1)
    if page_num == 1:
        text(c, 30.0, 780.0, "Форма по КНД 1152017", bold=True, font_size=9.0)

    # ИНН + КПП — справа в 2 строки
    # Первая строка: "ИНН" + 12 клеточек
    text(c, 160.0, 814.0, "ИНН", font_size=9.0)
    draw_cell_row(c, 182.0, 810.0, n=12, value=data["inn"].ljust(12))

    # Вторая строка: "КПП" + 9 клеток + "Стр." + 3 клетки
    text(c, 160.0, 792.0, "КПП", font_size=9.0)
    draw_cell_row(c, 182.0, 788.0, n=9, value=(data.get("kpp") or "").ljust(9))
    text(c, 362.0, 792.0, "Стр.", font_size=9.0)
    draw_cell_row(c, 385.0, 788.0, n=3, value=f"{page_num:03d}")

    # "Приложение №1 к приказу ФНС России..." (только стр.1) справа вверху
    if page_num == 1:
        text(c, 465.0, 820.0, "Приложение №1", font_size=8.0)
        text(c, 465.0, 810.0, "к приказу ФНС России", font_size=8.0)
        text(c, 465.0, 800.0, "от «2» октября 2024 г", font_size=8.0)
        text(c, 465.0, 790.0, "№ ЕД-7-3/813@", font_size=8.0)


def _draw_page_1(c, data: dict) -> None:
    """Стр.1 — Титульный лист декларации.

    ВАЖНО: нижняя часть (подпись/дата/реквизиты документа) СДВИНУТА
    вверх относительно эталона ФНС ~на 100pt чтобы освободить место
    для штампа ЭДО оператора внизу страницы (y=60..160pt).
    """
    _draw_header_ink_kpp(c, data, 1)

    # Заголовок — название формы (по центру)
    text(c, PAGE_W / 2, 750.0,
         "Налоговая декларация по налогу, уплачиваемому",
         bold=True, font_size=11.0, align="center")
    text(c, PAGE_W / 2, 737.0,
         "в связи с применением упрощенной системы налогообложения",
         bold=True, font_size=11.0, align="center")

    # Номер корректировки / Налоговый период / Отчётный год
    y = 710.0
    text(c, 30.0, y + 4, "Номер корректировки", font_size=9.0)
    corr = str(data.get("correction_number", 0))
    draw_cell_row(c, 140.0, y, n=3, value=corr.ljust(3))

    text(c, 250.0, y + 4, "Налоговый период (код)", font_size=9.0)
    draw_cell_row(c, 360.0, y, n=2, value="34")

    text(c, 420.0, y + 4, "Отчётный год", font_size=9.0)
    draw_cell_row(c, 490.0, y, n=4, value=str(data["year"]))

    # "Представляется в налоговый орган (код) + по месту нахождения (учёта) (код)"
    y = 690.0
    text(c, 30.0, y + 4, "Представляется в налоговый орган (код)", font_size=9.0)
    draw_cell_row(c, 220.0, y, n=4, value=data["ifns_code"])
    text(c, 290.0, y + 4, "по месту нахождения (учёта) (код)", font_size=9.0)
    draw_cell_row(c, 455.0, y, n=3, value="120")  # 120 = ИП

    # ФИО налогоплательщика — 4 строки клеток по 40 позиций
    y = 668.0
    fio_parts = _split_fio_to_lines(data.get("fio", ""), max_per_line=40)
    for i in range(4):
        line_y = y - i * (CELL_H + 2)
        val = fio_parts[i] if i < len(fio_parts) else ""
        draw_cell_row(c, 30.0, line_y, n=40, value=val.ljust(40))
    # Подпись под полем
    text(c, PAGE_W / 2, y - 4 * (CELL_H + 2) - 8,
         "(фамилия, имя, отчество* полностью / наименование организации)",
         font_size=7.5, align="center")

    # Форма реорганизации / ИНН/КПП — одна строка
    y = 570.0
    text(c, 30.0, y + 4, "Форма реорганизации (ликвидации) (код)", font_size=8.5)
    draw_cell_row(c, 210.0, y, n=1)
    text(c, 230.0, y + 4, "ИНН/КПП реорганизованной организации", font_size=8.5)
    draw_cell_row(c, 395.0, y, n=10)
    text(c, 525.0, y + 4, "/", font_size=9.0)
    draw_cell_row(c, 532.0, y, n=9)

    # Номер контактного телефона
    y = 548.0
    text(c, 30.0, y + 4, "Номер контактного телефона", font_size=9.0)
    draw_cell_row(c, 165.0, y, n=20)

    # Объект налогообложения
    y = 526.0
    text(c, 30.0, y + 4, "Объект налогообложения:", font_size=9.0)
    draw_cell_row(c, 155.0, y, n=1, value="1")
    text(c, 175.0, y + 8, "1 – доходы", font_size=8.5)
    text(c, 175.0, y - 2, "2 – доходы, уменьшенные на величину расходов", font_size=8.5)

    # "На X страницах"
    y = 504.0
    text(c, 30.0, y + 4, "На", font_size=9.0)
    draw_cell_row(c, 47.0, y, n=3, value="4  ")
    text(c, 100.0, y + 4, "страницах с приложением подтверждающих документов или их копий на",
         font_size=9.0)
    draw_cell_row(c, 430.0, y, n=3)
    text(c, 475.0, y + 4, "листах", font_size=9.0)

    # ============================================================
    # НИЖНЯЯ ЧАСТЬ — сдвинута ВВЕРХ для освобождения места под штамп
    # Эталон: эта секция занимает y=185..430. Мы её двигаем в y=285..470.
    # Итоговая свободная зона для штампа: y=30..180 (150pt).
    # ============================================================

    # Разделитель перед блоком "Достоверность и полноту сведений..."
    y = 470.0
    hline(c, 30.0, y, PAGE_W - 30.0)

    # Блок "Достоверность" (левая колонка) + "Заполняется работником НО" (правая)
    # Левая колонка
    text(c, 30.0, y - 15, "Достоверность и полноту сведений, указанных",
         bold=True, font_size=9.0)
    text(c, 30.0, y - 25, "в настоящей декларации, подтверждаю:",
         bold=True, font_size=9.0)
    draw_cell_row(c, 105.0, y - 47, n=1, value="2")
    text(c, 128.0, y - 43, "1 - налогоплательщик,", font_size=8.0)
    text(c, 128.0, y - 52, "2 - представитель налогоплательщика", font_size=8.0)

    # ФИО подписанта — 4 строки клеток
    yp = y - 70
    for i in range(4):
        draw_cell_row(c, 30.0, yp - i * (CELL_H + 2), n=20)
    text(c, 140.0, yp - 4 * (CELL_H + 2) - 8,
         "(фамилия, имя, отчество* полностью)", font_size=7.5, align="center")

    # Название организации-представителя
    yn = yp - 4 * (CELL_H + 2) - 20
    for i in range(3):
        draw_cell_row(c, 30.0, yn - i * (CELL_H + 2), n=20)
    text(c, 140.0, yn - 3 * (CELL_H + 2) - 8,
         "(наименование организации - представителя налогоплательщика)",
         font_size=7.0, align="center")

    # Подпись + Дата
    ys = yn - 3 * (CELL_H + 2) - 30
    text(c, 30.0, ys + 4, "Подпись", font_size=9.0)
    text(c, 160.0, ys + 4, "Дата", font_size=9.0)
    sd = data["signing_date"]
    date_str = sd.strftime("%d%m%Y") if hasattr(sd, "strftime") else ""
    # 2 клетки дн + . + 2 клетки мм + . + 4 клетки гггг
    draw_cell_row(c, 190.0, ys, n=2, value=date_str[:2])
    text(c, 219.0, ys + 4, ".", font_size=10.0)
    draw_cell_row(c, 224.0, ys, n=2, value=date_str[2:4])
    text(c, 253.0, ys + 4, ".", font_size=10.0)
    draw_cell_row(c, 258.0, ys, n=4, value=date_str[4:8])

    # Правая колонка "Заполняется работником налогового органа"
    rx = 320.0
    text(c, rx, y - 15, "Заполняется работником налогового органа",
         bold=True, font_size=9.0)
    text(c, rx + 45, y - 30, "Сведения о представлении декларации",
         font_size=8.5)
    text(c, rx, y - 50, "Данная декларация представлена (код)", font_size=8.5)
    draw_cell_row(c, rx + 180, y - 54, n=2)
    text(c, rx, y - 70, "на", font_size=8.5)
    draw_cell_row(c, rx + 20, y - 74, n=3)
    text(c, rx + 65, y - 70, "страницах", font_size=8.5)
    text(c, rx, y - 90, "с приложением подтверждающих документов", font_size=8.5)
    text(c, rx, y - 100, "или их копий на", font_size=8.5)
    draw_cell_row(c, rx + 90, y - 104, n=3)
    text(c, rx + 135, y - 100, "листах", font_size=8.5)
    text(c, rx, y - 120, "Дата представления", font_size=8.5)
    text(c, rx, y - 130, "декларации", font_size=8.5)
    draw_cell_row(c, rx + 80, y - 124, n=2)
    text(c, rx + 109, y - 120, ".", font_size=10.0)
    draw_cell_row(c, rx + 114, y - 124, n=2)
    text(c, rx + 143, y - 120, ".", font_size=10.0)
    draw_cell_row(c, rx + 148, y - 124, n=4)
    # Фамилия И.О. / Подпись
    hline(c, rx, y - 175, rx + 120)
    hline(c, rx + 140, y - 175, rx + 230)
    text(c, rx + 60, y - 185, "Фамилия, И.О.*", font_size=7.5, align="center")
    text(c, rx + 185, y - 185, "Подпись", font_size=7.5, align="center")

    # Маркеры по углам (как в эталоне)
    _draw_corner_markers(c)


def _draw_corner_markers(c) -> None:
    """Чёрные квадратные маркеры по 4 углам страницы (как у ФНС)."""
    size = 8.0
    for x, y in [(30, 15), (PAGE_W - 30 - size, 15),
                 (30, PAGE_H - 15 - size), (PAGE_W - 30 - size, PAGE_H - 15 - size)]:
        c.saveState()
        c.setFillColorRGB(0, 0, 0)
        c.rect(x, y, size, size, stroke=0, fill=1)
        c.restoreState()


def _split_fio_to_lines(fio: str, max_per_line: int = 40) -> list[str]:
    """Дробим ФИО по словам так чтобы на строку — целое слово, без переноса внутри."""
    words = fio.upper().split()
    lines = []
    cur = ""
    for w in words:
        test = f"{cur} {w}".strip()
        if len(test) <= max_per_line:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    # Разделяем символы с пробелами — каждая клетка один символ
    return [_to_cells(line, max_per_line) for line in lines[:4]]


def _to_cells(s: str, n: int) -> str:
    """Кладёт каждый символ в отдельную клетку. Пробелы между словами —
    пустые клетки. Возвращает строку ровно n символов."""
    return s.ljust(n)[:n]


# ============================================================
# Стр.2 — Раздел 1.1 (сумма налога к уплате/уменьшению)
# ============================================================

def _draw_page_2(c, data: dict) -> None:
    _draw_header_ink_kpp(c, data, 2)

    # Заголовок раздела
    text(c, PAGE_W / 2, 770.0,
         "Раздел 1.1. Сумма налога (авансового платежа по налогу), уплачиваемого в связи с применением упрощенной",
         bold=True, font_size=9.0, align="center")
    text(c, PAGE_W / 2, 760.0,
         "системы налогообложения (объект налогообложения - доходы), подлежащая уплате (уменьшению),",
         bold=True, font_size=9.0, align="center")
    text(c, PAGE_W / 2, 750.0, "по данным налогоплательщика",
         bold=True, font_size=9.0, align="center")

    # Колонки-заголовки
    y = 720.0
    text(c, 30.0, y, "Показатели", bold=True, font_size=8.5)
    text(c, 390.0, y, "Код", bold=True, font_size=8.5)
    text(c, 390.0, y - 10, "строки", bold=True, font_size=8.5)
    text(c, 490.0, y, "Значения показателей (в рублях)",
         bold=True, font_size=8.5, align="center")
    text(c, 30.0, y - 20, "1", font_size=8.0)
    text(c, 395.0, y - 20, "2", font_size=8.0)
    text(c, 490.0, y - 20, "3", font_size=8.0, align="center")

    # Строки таблицы Section 1.1 — помесячные/квартальные суммы + ОКТМО
    rows = [
        ("Код по ОКТМО", "010", data.get("oktmo", ""), "oktmo"),
        ("Сумма авансового платежа к уплате по сроку не позднее\n"
         "двадцать восьмого апреля отчетного года\n"
         "(стр.130 - стр.140 разд. 2.1) разд.2.1.1 - стр.160 разд.2.1.2,\n"
         "если (стр.130 - стр.140 разд. 2.1) разд.2.1.1 - стр.160 разд.2.1.2 >= 0",
         "020", _fmt_int_12(data.get("advance_q1")), "amount"),
        ("Код по ОКТМО", "030", data.get("oktmo_h1", ""), "oktmo"),
        ("Сумма авансового платежа к уплате по сроку не позднее\n"
         "двадцать восьмого июля отчетного года",
         "040", _fmt_int_12(data.get("advance_h1")), "amount"),
        ("Сумма авансового платежа к уменьшению по сроку не позднее\n"
         "двадцать восьмого июля отчетного года",
         "050", _fmt_int_12(data.get("advance_h1_reduction")), "amount"),
        ("Код по ОКТМО", "060", data.get("oktmo_9m", ""), "oktmo"),
        ("Сумма авансового платежа к уплате по сроку не позднее\n"
         "двадцать восьмого октября отчетного года",
         "070", _fmt_int_12(data.get("advance_9m")), "amount"),
        ("Сумма авансового платежа к уменьшению по сроку не позднее\n"
         "двадцать восьмого октября отчетного года",
         "080", _fmt_int_12(data.get("advance_9m_reduction")), "amount"),
        ("Код по ОКТМО", "090", data.get("oktmo_y", ""), "oktmo"),
        ("Сумма налога, подлежащая доплате за налоговый период\n"
         "(календарный год) по сроку*",
         "100", _fmt_int_12(data.get("tax_year_payable")), "amount"),
        ("Сумма налога, уплаченная в связи с применением патентной\n"
         "системы налогообложения, подлежащая зачету",
         "101", _fmt_int_12(data.get("patent_offset")), "amount"),
        ("Сумма налога к уменьшению за налоговый период\n"
         "(календарный год) по сроку*",
         "110", _fmt_int_12(data.get("tax_year_reduction")), "amount"),
    ]

    row_y = 680.0
    row_h = 38.0
    for label, code, value, kind in rows:
        # Метка строки (с переносами)
        lines = label.split("\n")
        for i, line in enumerate(lines):
            text(c, 30.0, row_y + (len(lines) - 1 - i) * 9 + 3, line, font_size=8.0)
        # Код строки
        text(c, 395.0, row_y + 3, code, font_size=8.5, align="left")
        # Значение
        if kind == "oktmo":
            draw_cell_row(c, 420.0, row_y, n=11, value=value.ljust(11))
        else:  # amount — 12 клеток align=right
            draw_cell_row(c, 420.0, row_y, n=12, value=value, align="right")

        # Следующая строка выше (идём вниз-вверх? PDF — снизу. Иду вниз по номеру)
        row_y -= row_h

    # Маркеры по углам
    _draw_corner_markers(c)

    # Сноска внизу
    text(c, 30.0, 50.0,
         "* для организаций - не позднее 28 марта года, следующего за истекшим налоговым периодом;",
         font_size=7.0)
    text(c, 30.0, 42.0,
         "для индивидуальных предпринимателей - не позднее 28 апреля года, следующего за истекшим налоговым периодом",
         font_size=7.0)


# ============================================================
# Стр.3 — Раздел 2.1.1 (расчёт налога)
# ============================================================

def _draw_page_3(c, data: dict) -> None:
    _draw_header_ink_kpp(c, data, 3)

    text(c, PAGE_W / 2, 760.0,
         "Раздел 2.1.1. Расчет налога, уплачиваемого в связи с применением упрощенной системы",
         bold=True, font_size=9.0, align="center")
    text(c, PAGE_W / 2, 750.0,
         "налогообложения (объект налогообложения – доходы)",
         bold=True, font_size=9.0, align="center")

    # Колонки-заголовки
    y = 720.0
    text(c, 30.0, y, "Показатели", bold=True, font_size=8.5)
    text(c, 390.0, y, "Код", bold=True, font_size=8.5)
    text(c, 390.0, y - 10, "строки", bold=True, font_size=8.5)
    text(c, 490.0, y, "Значения показателей (в рублях)",
         bold=True, font_size=8.5, align="center")

    # Код признака применения ставки (строка 101)
    y = 690.0
    wrap_text(c, 30.0, y, "Код признака применения налоговой ставки:",
              max_w=340, font_size=8.0, bold=True, line_h=9.0)
    text(c, 395.0, y - 40, "101", font_size=8.5)
    draw_cell_row(c, 420.0, y - 43, n=1, value=str(data.get("tax_rate_code", 1)))

    # Признак налогоплательщика (строка 102)
    y = 610.0
    wrap_text(c, 30.0, y, "Признак налогоплательщика:",
              max_w=340, font_size=8.0, bold=True, line_h=9.0)
    text(c, 395.0, y - 25, "102", font_size=8.5)
    sign = data.get("taxpayer_sign", 2)
    draw_cell_row(c, 420.0, y - 28, n=1, value=str(sign))

    # Сумма полученных доходов (стр 110..113)
    y = 560.0
    text(c, 30.0, y, "Сумма полученных доходов (налоговая база для исчисления налога",
         bold=True, font_size=8.0)
    text(c, 30.0, y - 9, "(авансового платежа по налогу)) нарастающим итогом:",
         bold=True, font_size=8.0)

    income_rows = [
        ("за первый квартал", "110", data.get("income_q1")),
        ("за полугодие", "111", data.get("income_h1")),
        ("за девять месяцев", "112", data.get("income_9m")),
        ("за налоговый период", "113", data.get("income_y")),
    ]
    ry = 540.0
    for label, code, val in income_rows:
        text(c, 30.0, ry + 3, label, font_size=8.0)
        text(c, 395.0, ry + 3, code, font_size=8.5)
        draw_cell_row(c, 420.0, ry, n=12, value=_fmt_int_12(val), align="right")
        ry -= 17

    # Налоговая ставка (%) — строки 120..123
    y = 460.0
    text(c, 30.0, y, "Налоговая ставка (%):", bold=True, font_size=8.0)
    rate_rows = [
        ("за первый квартал", "120", data.get("tax_rate_q1", Decimal("6.0"))),
        ("за полугодие", "121", data.get("tax_rate_h1", Decimal("6.0"))),
        ("за девять месяцев", "122", data.get("tax_rate_9m", Decimal("6.0"))),
        ("за налоговый период", "123", data.get("tax_rate_y", Decimal("6.0"))),
    ]
    ry = 440.0
    for label, code, val in rate_rows:
        text(c, 30.0, ry + 3, label, font_size=8.0)
        text(c, 395.0, ry + 3, code, font_size=8.5)
        rate = _fmt_rate(val)
        # Формат: integer.decimal — 1 клетка + точка + 1 клетка
        draw_cell_row(c, 420.0, ry, n=1, value=rate[0])
        text(c, 437.0, ry + 3, ".", font_size=10.0)
        draw_cell_row(c, 442.0, ry, n=1, value=rate[1])
        ry -= 17

    # Обоснование пониженной ставки (строка 124) — составное поле XXXXXXX/YYYYYYYYYYYY
    y = 370.0
    wrap_text(c, 30.0, y, "Обоснование применения налоговой ставки, установленной законом субъекта Российской Федерации",
              max_w=340, font_size=8.0, bold=True, line_h=9.0)
    text(c, 395.0, y - 6, "124", font_size=8.5)
    draw_cell_row(c, 420.0, y - 9, n=7)
    text(c, 514.0, y - 6, "/", font_size=10.0)
    draw_cell_row(c, 520.0, y - 9, n=6)

    # Сумма исчисленного налога (130..133)
    y = 340.0
    text(c, 30.0, y, "Сумма исчисленного налога (авансового платежа по налогу):",
         bold=True, font_size=8.0)
    calc_rows = [
        ("за первый квартал", "130", data.get("tax_calc_q1")),
        ("за полугодие", "131", data.get("tax_calc_h1")),
        ("за девять месяцев", "132", data.get("tax_calc_9m")),
        ("за налоговый период", "133", data.get("tax_calc_y")),
    ]
    ry = 320.0
    for label, code, val in calc_rows:
        text(c, 30.0, ry + 3, label, font_size=8.0)
        text(c, 395.0, ry + 3, code, font_size=8.5)
        draw_cell_row(c, 420.0, ry, n=12, value=_fmt_int_12(val), align="right")
        ry -= 17

    _draw_corner_markers(c)


# ============================================================
# Стр.4 — Продолжение Р.2.1.1 (страховые взносы 140..143)
# ============================================================

def _draw_page_4(c, data: dict) -> None:
    _draw_header_ink_kpp(c, data, 4)

    # Колонки-заголовки (повтор)
    y = 775.0
    text(c, 30.0, y, "Показатели", bold=True, font_size=8.5)
    text(c, 390.0, y, "Код", bold=True, font_size=8.5)
    text(c, 390.0, y - 10, "строки", bold=True, font_size=8.5)
    text(c, 490.0, y, "Значения показателей (в рублях)",
         bold=True, font_size=8.5, align="center")

    # Шапка раздела про страховые взносы
    y = 750.0
    intro = (
        "Сумма страховых взносов, выплаченных работникам пособий по "
        "временной нетрудоспособности и платежей (взносов) по договорам "
        "добровольного личного страхования (нарастающим итогом), "
        "предусмотренных пунктом 3.1 статьи 346.21 Налогового кодекса "
        "Российской Федерации, уменьшающая сумму исчисленного за "
        "налоговый (отчетный) период налога (авансового платежа по "
        "налогу):"
    )
    wrap_text(c, 30.0, y, intro, max_w=340, font_size=8.0, bold=True, line_h=10.0)

    # Строки 140..143
    contrib_rows = [
        ("за первый квартал", "140", data.get("contrib_q1")),
        ("за полугодие", "141", data.get("contrib_h1")),
        ("за девять месяцев", "142", data.get("contrib_9m")),
        ("за налоговый период", "143", data.get("contrib_y")),
    ]
    ry = 650.0
    for label, code, val in contrib_rows:
        text(c, 30.0, ry + 3, label, font_size=8.0)
        text(c, 395.0, ry + 3, code, font_size=8.5)
        draw_cell_row(c, 420.0, ry, n=12, value=_fmt_int_12(val), align="right")
        ry -= 22

    _draw_corner_markers(c)
