"""
Низкоуровневые helpers для рисования клеточек-полей и текста.

Единица: pt (1/72 inch). Размер страницы A4: 595.28 × 841.89 pt
(в эталоне ФНС 594.96 × 841.92 — допустимая разница).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


# ============================================================
# Константы страницы и шаблона
# ============================================================

PAGE_W = 595.28
PAGE_H = 841.89

# Поля страницы (в эталоне ФНС ~30pt слева/справа, ~20pt сверху)
MARGIN_L = 30.0
MARGIN_R = 30.0
MARGIN_T = 20.0
MARGIN_B = 20.0

# Размеры клеток ИНН/ОКТМО/сумм — точно как в эталоне ФНС
CELL_W = 13.4
CELL_H = 14.0

# Шрифты (registered only once)
FONT_REGULAR = "CyrR"
FONT_BOLD = "CyrB"
_fonts_registered = False


def _font_paths() -> list[tuple[Path, Path]]:
    """Возможные пути к Tahoma / Segoe / Liberation шрифтам.
    Приоритет: Tahoma (эталон ФНС) → Segoe UI → Liberation Sans → DejaVu."""
    here = Path(__file__).resolve().parent
    fonts_dir = here.parent / "edo_stamps" / "fonts"
    candidates = [
        (fonts_dir / "tahoma.ttf", fonts_dir / "tahomabd.ttf"),
        (fonts_dir / "segoeui.ttf", fonts_dir / "segoeuib.ttf"),
        (Path("C:/Windows/Fonts/tahoma.ttf"), Path("C:/Windows/Fonts/tahomabd.ttf")),
        (Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
         Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    return candidates


def register_fonts() -> None:
    """Регистрирует первый доступный TTF-пакет как CyrR + CyrB."""
    global _fonts_registered
    if _fonts_registered:
        return
    registered = pdfmetrics.getRegisteredFontNames()
    for r_path, b_path in _font_paths():
        if r_path.exists() and b_path.exists():
            if FONT_REGULAR not in registered:
                pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(r_path)))
            if FONT_BOLD not in registered:
                pdfmetrics.registerFont(TTFont(FONT_BOLD, str(b_path)))
            _fonts_registered = True
            return
    raise RuntimeError(
        "Шрифт не найден. Установите fonts-liberation (apt-get install) "
        "или положите tahoma.ttf/tahomabd.ttf в modules/edo_stamps/fonts/."
    )


# ============================================================
# Клеточки
# ============================================================

def draw_cell_row(
    c: Canvas,
    x: float, y: float,
    n: int,
    cell_w: float = CELL_W,
    cell_h: float = CELL_H,
    value: str = "",
    align: str = "left",
    font_size: float = 10.0,
) -> None:
    """Рисует строку из n смежных клеточек с рамками, заполняет value.

    Args:
        x, y: левый нижний угол первой клетки (PDF-координаты)
        n: число клеток
        value: строка для заполнения; если длина > n — обрезается,
               если меньше — дополняется пробелами по выравниванию
        align: 'left' | 'right' | 'center'
        font_size: размер шрифта для текста

    Пример:
        draw_cell_row(c, x=100, y=700, n=12, value="330573397709")
        — рисует 12 клеточек слева направо и пишет ИНН
    """
    c.saveState()
    c.setFont(FONT_REGULAR, font_size)
    c.setLineWidth(0.5)
    c.setStrokeColorRGB(0.1, 0.1, 0.1)

    # Рамки
    for i in range(n):
        cx = x + i * cell_w
        c.rect(cx, y, cell_w, cell_h, stroke=1, fill=0)

    # Значение
    s = value
    if align == "right":
        s = s.rjust(n)[-n:]
    elif align == "center":
        pad = max(0, (n - len(s)) // 2)
        s = (" " * pad + s).ljust(n)[:n]
    else:
        s = s.ljust(n)[:n]

    # Центрирование символа в клетке: baseline = y + 3 (для font 10pt ~ высота глифа 7pt)
    baseline_y = y + 3.5
    for i, ch in enumerate(s):
        if ch.strip():
            ch_w = c.stringWidth(ch, FONT_REGULAR, font_size)
            # По центру клетки
            cx = x + i * cell_w + (cell_w - ch_w) / 2
            c.drawString(cx, baseline_y, ch)

    c.restoreState()


def draw_cell_row_with_separators(
    c: Canvas,
    x: float, y: float,
    groups: list[int],
    separator: str = " ",
    separator_w: float = 3.0,
    cell_w: float = CELL_W,
    cell_h: float = CELL_H,
    value: str = "",
    align: str = "left",
    font_size: float = 10.0,
) -> None:
    """Клеточки сгруппированные (напр. ИНН 12 цифр группами 2-3-5-2 с визуальными пробелами).
    Для простоты — единая строка без разделителей (most common case)."""
    # Пока — как обычная строка. Расширим при необходимости.
    total = sum(groups)
    draw_cell_row(c, x, y, total, cell_w, cell_h, value, align, font_size)


def text(
    c: Canvas,
    x: float, y: float,
    s: str,
    *,
    font_size: float = 8.5,
    bold: bool = False,
    align: str = "left",  # 'left' | 'right' | 'center'
) -> None:
    """Упрощённая обёртка над drawString с выравниванием."""
    font = FONT_BOLD if bold else FONT_REGULAR
    c.setFont(font, font_size)
    if align == "left":
        c.drawString(x, y, s)
    elif align == "right":
        c.drawRightString(x, y, s)
    elif align == "center":
        c.drawCentredString(x, y, s)


def wrap_text(
    c: Canvas,
    x: float, y: float,
    s: str,
    max_w: float,
    *,
    font_size: float = 8.5,
    bold: bool = False,
    line_h: float = 10.0,
) -> float:
    """Рисует текст с word-wrap в заданной ширине. Возвращает высоту занятой области."""
    font = FONT_BOLD if bold else FONT_REGULAR
    c.setFont(font, font_size)
    words = s.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        test = f"{cur} {w}".strip()
        if c.stringWidth(test, font, font_size) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    for i, line in enumerate(lines):
        c.drawString(x, y - i * line_h, line)
    return len(lines) * line_h


def hline(c: Canvas, x0: float, y: float, x1: float, width: float = 0.5) -> None:
    """Горизонтальная линия."""
    c.saveState()
    c.setLineWidth(width)
    c.line(x0, y, x1, y)
    c.restoreState()


def barcode_image(c: Canvas, page_num: int, x: float, y: float, width: float = 60.0) -> None:
    """Вставляет PNG штрих-кода из templates/barcodes/ на заданные координаты.

    Args:
        page_num: 1..4 (номер страницы декларации)
        x, y: нижний левый угол изображения в pt
        width: ширина рендера в pt (высота пропорциональна)
    """
    from reportlab.lib.utils import ImageReader
    # Путь к PNG относительно проекта
    here = Path(__file__).resolve().parent.parent.parent
    png_path = here / "templates" / "barcodes" / f"barcode_p{page_num}.png"
    if not png_path.exists():
        return  # silently skip
    img = ImageReader(str(png_path))
    iw, ih = img.getSize()
    height = width * ih / iw
    c.drawImage(img, x, y, width, height, mask="auto")
