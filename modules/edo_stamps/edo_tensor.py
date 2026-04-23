"""
edo_tensor.py — рендер штампа Тензор/СБИС.

Публичный API:
    render_tensor_page(cfg, page_index, page_width, page_height) → BytesIO
    gen_cert_send_tensor() → str
    gen_cert_ifns_tensor() → str

Все константы измерены из ТЕНЗОР_ТОЛЬКО_ОТМЕТКА.pdf (чистый эталон без формы).
Шрифт: Tahoma 7pt Regular + Bold (fallback: LiberationSans / DejaVu).
"""

from __future__ import annotations
import secrets
from io import BytesIO

from reportlab.pdfgen import canvas

from edo_core import (
    StampConfig, Party,
    _fonts, _trunc,
)
from reportlab.lib.colors import HexColor
# Тензор: ВСЕ линии и текст — один чистый синий #0000FF (измерено из эталона)
_C_BLUE = HexColor('#0000FF')

# ─── Геометрия рамки (измерено из эталона) ───────────────────────────────────
T_TOP  = 86.939   # y верхней горизонтальной линии
T_MID  = 67.142   # y средней горизонтальной линии
T_BOT  = 11.999   # y нижней горизонтальной линии
T_LV   = 30.530   # x левой вертикальной линии
T_RV   = 579.961  # x правой вертикальной линии
T_COL  = 303.031  # x вертикального разделителя колонок
T_LW   = 0.25     # толщина линий

# ─── X-координаты текста ─────────────────────────────────────────────────────
T_LX   = 38.28    # x текста заголовка (ДОКУМЕНТ ПОДПИСАН, ДЕКЛАРАЦИЯ)
T_NX   = 96.97    # x имён подписантов (левая колонка)
T_DX   = 310.53   # x даты (правая колонка)
T_CX   = 397.54   # x слова «Сертификат»
T_HX   = 438.40   # x хэша сертификата
T_IDX  = 382.87   # x слова «Идентификатор:» (эталон x=382.868)

# ─── Y drawString (baseline = y_bot_эталона + descent_Tahoma_7pt=1.477) ──────
_D = 1.477
T_OP   = 83.994 + _D   # «Оператор ЭДО...»
T_HDR  = 72.571 + _D   # «ДОКУМЕНТ ПОДПИСАН...» + Идентификатор
T_S1   = 53.623 + _D   # отправитель строка 1
T_S2   = 45.174 + _D   # отправитель строка 2
T_R1   = 33.225 + _D   # получатель строка 1
T_R2   = 24.777 + _D   # получатель строка 2
T_R3   = 16.328 + _D   # получатель строка 3


def gen_cert_send_tensor() -> str:
    """Тензор, отправитель: '02' + 32 hex = 34 символа."""
    return "02" + secrets.token_hex(16).upper()


def gen_cert_ifns_tensor() -> str:
    """Тензор, ИФНС: 32 символа."""
    return secrets.token_hex(16).upper()


def _split_name(c: canvas.Canvas, name: str, font: str, size: float,
                max_w: float) -> tuple:
    """Разбивает имя на два сегмента по пробелу, не превышая max_w."""
    words = name.split()
    line1 = ""
    for i, w in enumerate(words):
        candidate = " ".join(words[:i + 1])
        if c.stringWidth(candidate, font, size) <= max_w:
            line1 = candidate
        else:
            break
    line2 = name[len(line1):].strip()
    return line1, line2


def render_tensor_page(cfg: StampConfig, pi: int, pw: float, ph: float) -> BytesIO:
    """Генерирует PDF-оверлей штампа Тензора. Возвращает BytesIO."""
    fr, fb = _fonts()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(pw, ph))

    # Единственный цвет штампа — чистый синий #0000FF
    c.setStrokeColor(_C_BLUE)
    c.setFillColor(_C_BLUE)

    # ── «Оператор ЭДО...» + динамический разрыв в верхней линии ─────────────
    _op_text = 'Оператор ЭДО ООО "Компания "Тензор"'
    _op_w    = c.stringWidth(_op_text, fr, 7)
    _GAP     = 7.5     # pt — отступ текст↔линия (измерено: 7.499pt)
    _RSEG    = 26.722  # pt — длина правого сегмента верхней линии (фикс.)
    _anchor  = T_RV - _RSEG - _GAP       # правый край текста ≈ 545.74
    _left_end = _anchor - _op_w - _GAP   # конец левого сегмента (динамически)

    # ── Линии рамки ──────────────────────────────────────────────────────────
    c.setLineWidth(T_LW)
    c.line(T_LV,          T_TOP, _left_end,     T_TOP)  # верх — левая (динам.)
    c.line(T_RV - _RSEG,  T_TOP, T_RV,          T_TOP)  # верх — правая (фикс.)
    c.line(T_LX,          T_MID, T_COL,         T_MID)  # середина — левая
    c.line(T_COL,         T_MID, 572.211,       T_MID)  # середина — правая
    c.line(T_LV,          T_BOT, T_RV,          T_BOT)  # низ
    c.line(T_LV,          T_BOT, T_LV,          T_TOP)  # левая вертикаль
    c.line(T_RV,          T_BOT, T_RV,          T_TOP)  # правая вертикаль

    # ── Строка 1: «Оператор ЭДО...» ──────────────────────────────────────────
    c.setFont(fr, 7)
    c.drawRightString(_anchor, T_OP, _op_text)

    # ── Строка 2: «ДОКУМЕНТ ПОДПИСАН...» | Идентификатор ─────────────────────
    c.setFont(fr, 7)
    c.drawString(T_LX, T_HDR, "ДОКУМЕНТ ПОДПИСАН ЭЛЕКТРОННОЙ ПОДПИСЬЮ")
    if cfg.identifier:
        c.drawString(T_IDX, T_HDR, f"Идентификатор: {cfg.identifier}")

    # ── Отправитель ───────────────────────────────────────────────────────────
    if cfg.sender:
        name_max_w = T_COL - T_NX - 4  # ширина левой колонки
        # Тензор: «наименование, ФИО физлица» — оба поля через запятую (ALL CAPS)
        org_name = (cfg.sender.name or "").upper().strip()
        fio_name = (cfg.sender.role or "").upper().strip()
        if fio_name:
            name_full = org_name + ", " + fio_name  # всегда добавляем ФИО (как в оригинале Тензора)
        else:
            name_full = org_name

        # Разбиваем позицию запятой: до — Bold, после — Regular
        comma_idx = name_full.find(',')
        if comma_idx > 0:
            name_bold_str = name_full[:comma_idx + 1]  # с запятой включительно
            name_reg_str  = name_full[comma_idx + 1:].strip()
        else:
            name_bold_str = name_full
            name_reg_str  = ""

        # Рендерим в ЛЕВОЙ колонке (до T_COL) — Bold до запятой, Regular после
        # L1: Bold-часть (обрезаем если не влезает)
        bold_l1, bold_rest = _split_name(c, name_bold_str, fb, 7, name_max_w)
        c.setFont(fb, 7)
        c.drawString(T_NX, T_S1, bold_l1)

        if bold_rest:
            # Bold ещё не закончился на L2
            bold_l2, bold_l3 = _split_name(c, bold_rest, fb, 7, name_max_w)
            c.drawString(T_NX, T_S2, bold_l2)
            # Regular (ФИО) начнётся с L3 если осталось место
            if name_reg_str and not bold_l3:
                c.setFont(fr, 7)
                reg_l3, _ = _split_name(c, name_reg_str, fr, 7, name_max_w)
                c.drawString(T_NX, T_R3, reg_l3)
        else:
            # Bold закончился на L1 — Regular на той же строке если влезает, или L2
            if name_reg_str:
                x_after_bold = T_NX + c.stringWidth(bold_l1 + " ", fb, 7)
                reg_max_w = name_max_w - c.stringWidth(bold_l1 + " ", fb, 7)
                c.setFont(fr, 7)
                reg_l1, reg_rest = _split_name(c, name_reg_str, fr, 7, reg_max_w)
                if reg_l1:
                    c.drawString(x_after_bold, T_S1, reg_l1)
                if reg_rest:
                    reg_l2, _ = _split_name(c, reg_rest, fr, 7, name_max_w)
                    c.drawString(T_NX, T_S2, reg_l2)

        # Дата Bold, время Regular (эталон: "06.05.25" Bold, "18:50 (MSK)" Regular)
        if cfg.sender.datetime_msk:
            _dt_parts = cfg.sender.datetime_msk.split(' ', 1)
            _dt_date  = _dt_parts[0]
            _dt_time  = _dt_parts[1] if len(_dt_parts) > 1 else ''
            c.setFont(fb, 7)
            c.drawString(T_DX, T_S1, _dt_date)
            if _dt_time:
                _x_time = T_DX + c.stringWidth(_dt_date + ' ', fb, 7)
                c.setFont(fr, 7)
                c.drawString(_x_time, T_S1, _dt_time)
        if cfg.sender.certificate:
            c.setFont(fr, 7)
            c.drawString(T_CX, T_S1, "Сертификат")
            c.drawString(T_HX, T_S1, cfg.sender.certificate)

    # ── Получатель ────────────────────────────────────────────────────────────
    if cfg.receiver:
        name_max_w = T_COL - T_NX - 4

        # Метка типа (ДЕКЛАРАЦИЯ / ОТПРАВЛЕНО)
        if cfg.action_label:
            c.setFont(fr, 7)
            c.drawString(T_LX, T_R1, cfg.action_label)

        # Имя ИФНС (ALL CAPS) — Bold; роль/должность (mixed case) — Regular
        recv_name = (cfg.receiver.name or "").upper()
        recv_role = (cfg.receiver.role or "")

        # Разбиваем имя на строки (только CAPS, Bold)
        name_l1, name_rest = _split_name(c, recv_name, fb, 7, name_max_w)
        name_l2, name_l3   = _split_name(c, name_rest, fb, 7, name_max_w) if name_rest else ("", "")

        c.setFont(fb, 7)
        c.drawString(T_NX, T_R1, name_l1)

        # Определяем строку и x где начинается роль
        _role_y = None; _role_x = T_NX

        if name_l2:
            c.drawString(T_NX, T_R2, name_l2)
            if name_l3:
                # Имя продолжается на L3 — роль не помещается
                c.drawString(T_NX, T_R3, name_l3)
                # Роль отдельно не рендерим (не хватает строк)
            else:
                # Роль начинается на L3
                _role_y = T_R3; _role_x = T_NX
        else:
            # Имя влезло в L1 — роль с L2 или в конце L1
            # Пробуем поставить роль после запятой на L1 если влезает
            _name_end_x = T_NX + c.stringWidth(name_l1 + ", ", fb, 7)
            _role_w = c.stringWidth(recv_role, fr, 7) if recv_role else 0
            if recv_role and _name_end_x + _role_w <= T_COL - 4:
                # Роль влезает на L1 после имени
                c.setFont(fr, 7)
                c.drawString(_name_end_x, T_R1, recv_role)
                _role_y = None  # уже нарисовали
            else:
                # Роль с L2
                _role_y = T_R2; _role_x = T_NX

        # Рисуем роль (Regular) если не нарисована
        if _role_y and recv_role:
            c.setFont(fr, 7)
            # Роль может занять несколько строк
            role_l1, role_rest = _split_name(c, recv_role, fr, 7, name_max_w)
            c.drawString(_role_x, _role_y, role_l1)
            if role_rest and _role_y == T_R2:
                role_l2, _ = _split_name(c, role_rest, fr, 7, name_max_w)
                c.drawString(T_NX, T_R3, role_l2)

        # Дата Bold, время Regular
        if cfg.receiver.datetime_msk:
            _dt_parts = cfg.receiver.datetime_msk.split(' ', 1)
            _dt_date  = _dt_parts[0]
            _dt_time  = _dt_parts[1] if len(_dt_parts) > 1 else ''
            c.setFont(fb, 7)
            c.drawString(T_DX, T_R1, _dt_date)
            if _dt_time:
                _x_time = T_DX + c.stringWidth(_dt_date + ' ', fb, 7)
                c.setFont(fr, 7)
                c.drawString(_x_time, T_R1, _dt_time)
        if cfg.receiver.certificate:
            c.setFont(fr, 7)
            c.drawString(T_CX, T_R1, "Сертификат")
            c.drawString(T_HX, T_R1, cfg.receiver.certificate)

    c.save()
    buf.seek(0)
    return buf
