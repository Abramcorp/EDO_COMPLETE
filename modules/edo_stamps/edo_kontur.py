"""
edo_kontur.py — рендер штампа Контур.Эльба.

Публичный API:
    render_kontur_page(cfg, page_index, page_width, page_height) → BytesIO
    gen_cert_kontur() → str
"""

from __future__ import annotations
import secrets
from io import BytesIO

from reportlab.lib.colors import white
from reportlab.pdfgen import canvas

from edo_core import (
    StampConfig, Party,
    _fonts, _trunc,
    C_K,
)

# ─── Константы Контура (595.3×841.9pt) ───────────────────────────────────────
# Измерено из КОНТУР_ТОЛЬКО_ОТМЕТКА.pdf. lw=2 → pdfplumber видит CENTER линии.
#
# Стр. 1 — горизонтальные H-линии (center):
#   Box1 top y=200.876, bot y=134.076
#   Box2 top y=100.876, bot y= 50.876
#   H-линии: x=314.101–583.101 (outer edges of 2pt stroke)
#
# Вертикальные V-линии (center):
#   x=315.101 (лево) и x=582.101 (право) = K_P1X+1 и RX-1
#   V span выходит за H на 1pt с каждой стороны (corners закрыты)
#
# Knockout rect: x=324.101–557.101 = HX-4 = 328.1-4
#
# Стр. 2+:
#   top H center y=37.377, bot H center y=9.577
#   V center: x=295.102 (лево), x=562.102 (право) = K_RX+1, K_RX+K_BW-1

# Стр. 1
K_P1X  = 314.1   # x OUTER LEFT края рамки (H-линии идут от него)
K_P1W  = 269.0   # ширина (правая граница outer = 583.1)
K_P1CX = 339.9   # x содержимого (имя, роль, сертификат, срок)
K_P1HX = 328.1   # x заголовков («Принято», «Документ», «через», «Имя файла»)
K_P1KO = K_P1HX - 4  # x knockout rect = 324.1 (HX - 4 = оригинал)

# Стр. 2+
K_RX   = 294.1   # x outer left края рамки
K_BW   = 269.0   # ширина (правая граница outer = 563.1)

# Box y — center of lw=2 horizontal lines (стр. 1)
K_B1_TOP = 200.9   # измерено: 200.876
K_B1_BOT = 134.1   # измерено: 134.076

K_B2_TOP = 100.9   # измерено: 100.876
K_B2_BOT =  50.9   # измерено:  50.876

# Box P (стр. 2+) — center of lw=2 lines
K_P_TOP  =  37.4   # измерено: 37.377 (было 38.0)
K_P_BOT  =   9.6   # измерено:  9.577 (было 10.0)

LW = 2.0   # толщина рамки


# ─── Генератор сертификата Контура ───────────────────────────────────────────
def gen_cert_kontur() -> str:
    """
    Контур: SHA-1 (40 hex), нижний регистр.
    Иногда 39 символов (ведущий 0 опускается) — 1/3 шанс.
    """
    h = secrets.token_hex(20)  # 40 символов, нижний регистр
    if h.startswith("0") and secrets.randbelow(3) == 0:
        h = h[1:]   # 39 символов, имитирует SHA-1 без ведущего нуля
    return h


# ─── Иконка Контура (медаль с лентой) ────────────────────────────────────────
def _kontur_icon(c: canvas.Canvas, x: float, y: float, size: float = 5.5) -> None:
    """
    Иконка Контур.Эльба — медаль с лентой.

    Ножки ленты рисуются ДО кругов — круги перекрывают их сверху.
    Нет маленькой точки в центре.
    """
    w = h = size
    cx = x + w * 0.50
    cy = y + h * 0.56

    r_out = w * 0.44   # внешний синий круг
    r_wh  = w * 0.335  # белое кольцо
    r_in  = w * 0.22   # внутренний синий круг

    c.setFillColor(C_K)

    # Левая ножка
    pl = c.beginPath()
    pl.moveTo(x + w * 0.00, y + h * 0.00)
    pl.lineTo(x + w * 0.43, y + h * 0.00)
    pl.lineTo(cx - w * 0.05, y + h * 0.30)
    pl.lineTo(cx - r_out,   cy - r_out * 0.5)
    pl.close()
    c.drawPath(pl, fill=1, stroke=0)

    # Правая ножка
    pr = c.beginPath()
    pr.moveTo(x + w * 0.57, y + h * 0.00)
    pr.lineTo(x + w * 1.00, y + h * 0.00)
    pr.lineTo(cx + r_out,   cy - r_out * 0.5)
    pr.lineTo(cx + w * 0.05, y + h * 0.30)
    pr.close()
    c.drawPath(pr, fill=1, stroke=0)

    # Круги поверх ножек
    c.setFillColor(C_K);   c.circle(cx, cy, r_out, fill=1, stroke=0)
    c.setFillColor(white); c.circle(cx, cy, r_wh,  fill=1, stroke=0)
    c.setFillColor(C_K);   c.circle(cx, cy, r_in,  fill=1, stroke=0)


# ─── Перенос и отрисовка имени файла ────────────────────────────────────────
def _draw_fn(c: canvas.Canvas, text: str, x: float, y: float,
             font: str, size: float, max_w: float, gap: float = 8.4) -> int:
    """
    Рисует строку text в позиции (x, y), автоматически перенося на вторую строку.
    
    Стратегии (в порядке приоритета):
      1. Natural split: последний «_» → первый «-» после него.
         Это точно соответствует формату Контур.Эльба: NO_USN_..._UUID.
         Допуск +20pt на случай что Segoe UI шире Liberation (метрика шрифта).
      2. Fallback: бинарный поиск + rfind «-» влево. Для нестандартных имён.
    
    Возвращает количество нарисованных строк (1 или 2).
    """
    c.setFont(font, size)

    # Если всё влезает на одну строку — рисуем без переноса
    if c.stringWidth(text, font, size) <= max_w:
        c.drawString(x, y, text)
        return 1

    # ── Стратегия 1: natural split (приоритет) ────────────────────────────────
    # Ищем: последний «_» (перед UUID) → первый «-» (после UUID-segment).
    # Допуск max_w + 20pt — Segoe UI может быть на 5-10% шире Liberation.
    last_under = text.rfind("_")
    if last_under > 0:
        nat_dash = text.find("-", last_under + 1)
        if nat_dash > 0:
            nat_w = c.stringWidth(text[:nat_dash], font, size)
            if nat_w <= max_w + 20:          # generous tolerance for any TTF
                c.drawString(x, y, text[:nat_dash])
                c.setFont(font, size)
                c.drawString(x, y - gap, text[nat_dash:])
                return 2

    # ── Стратегия 2: fallback — бинарный поиск + rfind «-» влево ─────────────
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if c.stringWidth(text[:mid], font, size) <= max_w:
            lo = mid
        else:
            hi = mid - 1

    cut = lo
    dash_left = text.rfind("-", 1, lo + 1)
    if dash_left > 0:
        cut = dash_left

    c.drawString(x, y, text[:cut])
    c.setFont(font, size)
    c.drawString(x, y - gap, text[cut:])
    return 2

    c.drawString(x, y, text[:cut])
    c.setFont(font, size)
    c.drawString(x, y - gap, text[cut:])
    return 2


# ─── Рендер страницы ─────────────────────────────────────────────────────────
def render_kontur_page(
    cfg: StampConfig,
    pi: int,
    pw: float,
    ph: float,
) -> BytesIO:
    """
    Генерирует PDF-оверлей штампа Контур.Эльба для страницы pi.
    Страница 0 — два больших блока (отправитель + получатель).
    Страницы 1+ — компактная рамка «Принято» у нижнего края.
    """
    fr, fb = _fonts()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(pw, ph))
    fn = cfg.kontur_filename

    if pi == 0:
        _render_kontur_page1(c, cfg, fn, fr, fb, pw, ph)
    else:
        _render_kontur_page_n(c, cfg, fn, fr, fb, pw, ph)

    c.save()
    buf.seek(0)
    return buf


def _render_kontur_page1(
    c: canvas.Canvas,
    cfg: StampConfig,
    fn: str,
    fr: str, fb: str,
    pw: float, ph: float,
) -> None:
    """Первая страница: Box 2 (получатель) + Box 1 (отправитель).
    Все смещения измерены из КОНТУР_ТОЛЬКО_ОТМЕТКА.pdf."""
    HX = K_P1HX          # x заголовков = 328.1
    CX = K_P1CX          # x содержимого = 339.9
    RX = K_P1X + K_P1W   # правая граница = 583.1

    # ── BOX 2: ПОЛУЧАТЕЛЬ (нижний) ────────────────────────────────────────────
    recv_dt = cfg.receiver.datetime_msk if cfg.receiver else ""
    t2 = f"Принято {recv_dt}"

    c.setStrokeColor(C_K); c.setLineWidth(LW)
    c.line(K_P1X, K_B2_TOP, RX, K_B2_TOP)

    # Заголовок «Принято» на линии: baseline = K_B2_TOP - 2.2
    # Segoe UI Bold 8pt descent=1.688pt → drawString y = etalon_y_bot + descent = 97.004+1.688 = 98.692
    # K_B2_TOP - 98.692 = 100.9 - 98.692 = 2.208 ≈ 2.2
    c.setFont(fb, 8)
    tw2 = c.stringWidth(t2, fb, 8)
    c.setFillColorRGB(1, 1, 1)
    c.rect(K_P1KO, K_B2_TOP - LW/2, tw2 + (HX - K_P1KO) + 2, LW, fill=1, stroke=0)
    c.setFont(fb, 8); c.setFillColor(C_K)
    c.drawString(HX, K_B2_TOP - 2.2, t2)

    c.setStrokeColor(C_K); c.setLineWidth(LW)
    c.line(K_P1X,       K_B2_BOT, K_P1X + K_P1W, K_B2_BOT)            # bottom H
    c.line(K_P1X + 1,   K_B2_BOT - 1, K_P1X + 1, K_B2_TOP + 1)        # left V (center+1, corners)
    c.line(K_P1X + K_P1W - 1, K_B2_BOT - 1, K_P1X + K_P1W - 1, K_B2_TOP + 1)  # right V

    # Содержимое Box2: start = K_B2_TOP - 15.5 (orig «Управление» y_bot=83.88)
    iy2 = K_B2_TOP - 15.5
    _kontur_icon(c, HX, iy2)
    if cfg.receiver:
        c.setFont(fr, 7); c.setFillColor(C_K)          # Regular 7pt — имя
        c.drawString(CX, iy2, _trunc(cfg.receiver.name, 50))
        if cfg.receiver.role:
            iy2 -= 10.4
            c.setFont(fr, 7); c.setFillColor(C_K)      # Regular 7pt — роль
            c.drawString(CX, iy2, _trunc(cfg.receiver.role, 65))
        if cfg.receiver.certificate:
            iy2 -= 8.0
            c.setFont(fr, 7); c.setFillColor(C_K)      # Regular 7pt — сертификат
            c.drawString(CX, iy2, _trunc(f"Сертификат: {cfg.receiver.certificate}", 74))
        if cfg.receiver.cert_valid_from and cfg.receiver.cert_valid_to:
            iy2 -= 9.1
            c.setFont(fr, 7); c.setFillColor(C_K)      # Regular 7pt — срок
            c.drawString(CX, iy2,
                         f"Действует с {cfg.receiver.cert_valid_from} до {cfg.receiver.cert_valid_to}")

    # ── BOX 1: ОТПРАВИТЕЛЬ (верхний) ──────────────────────────────────────────
    send_dt = cfg.sender.datetime_msk if cfg.sender else ""
    t1a = "Документ подписан электронной подписью и отправлен"
    t1b = f"через  Контур.Эльба  {send_dt}"

    c.setStrokeColor(C_K); c.setLineWidth(LW)
    c.line(K_P1X, K_B1_TOP, RX, K_B1_TOP)

    # Заголовок «Документ подписан» на линии: baseline = K_B1_TOP - 1.2
    # Segoe UI Bold 8pt descent=1.688pt → drawString y = 198.004+1.688=199.692 → offset=1.2
    c.setFont(fb, 8)
    tw1a = c.stringWidth(t1a, fb, 8)
    c.setFillColorRGB(1, 1, 1)
    c.rect(K_P1KO, K_B1_TOP - LW/2, tw1a + (HX - K_P1KO) + 2, LW, fill=1, stroke=0)
    c.setFont(fb, 8); c.setFillColor(C_K)
    c.drawString(HX, K_B1_TOP - 1.2, t1a)

    c.setStrokeColor(C_K); c.setLineWidth(LW)
    c.line(K_P1X,       K_B1_BOT, K_P1X + K_P1W, K_B1_BOT)            # bottom H
    c.line(K_P1X + 1,   K_B1_BOT - 1, K_P1X + 1, K_B1_TOP + 1)        # left V
    c.line(K_P1X + K_P1W - 1, K_B1_BOT - 1, K_P1X + K_P1W - 1, K_B1_TOP + 1)  # right V

    # «через Контур.Эльба»: iy = K_B1_TOP - 10.8
    # Segoe UI Bold 8pt descent=1.688pt → drawString y = 188.404+1.688=190.092 → offset=10.808≈10.8
    iy = K_B1_TOP - 10.8
    c.setFont(fb, 8); c.setFillColor(C_K)              # Bold 8pt
    c.drawString(HX, iy, t1b)

    iy -= 13.6
    c.setFillColor(C_K)
    fn_lines = _draw_fn(c, f"Имя файла «{fn}»", HX, iy, fb, 7,
                        max_w=RX - HX, gap=8.4)
    if fn_lines > 1:
        iy -= 8.4   # сдвигаем только если была вторая строка

    iy -= 10.3
    _kontur_icon(c, HX, iy)
    if cfg.sender:
        c.setFont(fr, 7); c.setFillColor(C_K)          # Regular 7pt — имя
        c.drawString(CX, iy, _trunc(cfg.sender.name, 50))
        if cfg.sender.certificate:
            iy -= 7.9
            c.setFont(fr, 7); c.setFillColor(C_K)      # Regular 7pt — сертификат
            c.drawString(CX, iy, _trunc(f"Сертификат: {cfg.sender.certificate}", 74))
        if cfg.sender.cert_valid_from and cfg.sender.cert_valid_to:
            iy -= 9.0
            c.setFont(fr, 7); c.setFillColor(C_K)      # Regular 7pt — срок
            c.drawString(CX, iy,
                         f"Действует с {cfg.sender.cert_valid_from} до {cfg.sender.cert_valid_to}")


def _render_kontur_page_n(
    c: canvas.Canvas,
    cfg: StampConfig,
    fn: str,
    fr: str, fb: str,
    pw: float, ph: float,
) -> None:
    """Страницы 2+: компактная рамка «Принято» у нижнего края.
    Все смещения измерены из КОНТУР_ТОЛЬКО_ОТМЕТКА.pdf."""
    recv_dt = cfg.receiver.datetime_msk if cfg.receiver else ""
    tp = f"Принято {recv_dt}"

    txp = K_RX + 14.0   # x текста = 308.1 (K_RX=294.1 + 14.0)

    c.setStrokeColor(C_K); c.setLineWidth(LW)
    c.line(K_RX, K_P_TOP, K_RX + K_BW, K_P_TOP)

    # «Принято» на линии рамки: baseline = K_P_TOP - 2.2
    # Segoe UI Bold 8pt descent=1.688pt → drawString y = 33.505+1.688=35.193 → offset=2.207≈2.2
    c.setFont(fb, 8)
    twp = c.stringWidth(tp, fb, 8)
    c.setFillColorRGB(1, 1, 1)
    c.rect(txp - 4, K_P_TOP - LW/2, twp + 6, LW, fill=1, stroke=0)   # knockout x=304.1 ≈ orig
    c.setFont(fb, 8); c.setFillColor(C_K)
    c.drawString(txp, K_P_TOP - 2.2, tp)

    c.setStrokeColor(C_K); c.setLineWidth(LW)
    c.line(K_RX,           K_P_BOT, K_RX + K_BW, K_P_BOT)              # bottom H
    c.line(K_RX + 1,       K_P_BOT - 1, K_RX + 1,       K_P_TOP + 1)  # left V
    c.line(K_RX + K_BW - 1, K_P_BOT - 1, K_RX + K_BW - 1, K_P_TOP + 1)  # right V

    iy3 = K_P_TOP - 14.576  # Segoe Bold 7pt descent=1.477pt → drawString y=21.347+1.477=22.824
    c.setFillColor(C_K)
    _draw_fn(c, f"Имя файла «{fn}»", txp, iy3, fb, 7,
             max_w=K_RX + K_BW - txp, gap=8.4)        # max_w = 563.1-308.1 = 255pt
