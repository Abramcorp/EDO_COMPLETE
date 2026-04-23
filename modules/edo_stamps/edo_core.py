"""
edo_core.py — общее ядро: модели, шрифты, наложение штампов, метаданные.

Импортируется операторами:
    from edo_core import Party, StampConfig, apply_stamps, _fonts, _trunc
"""

from __future__ import annotations
import argparse, json, os, re, secrets
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor, black, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ─── Размер страницы по умолчанию ────────────────────────────────────────────
PAGE_W, PAGE_H = 595.0, 842.0

# ─── Шрифты ──────────────────────────────────────────────────────────────────
import os as _os

# Пути к шрифтам — проверяем все варианты расположения:
#   Локально: рядом с файлом (edo_app/fonts/)
#   Railway:  edo_core.py в корне /app/, шрифты в /app/edo_app/fonts/
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_FONTS_DIRS = [
    _os.path.join(_HERE, "fonts"),             # рядом с edo_core.py
    _os.path.join(_HERE, "edo_app", "fonts"),  # Railway: /app/edo_app/fonts/
    "/app/edo_app/fonts",                       # Railway: абсолютный путь
]

_FONT_PATHS = []
for _d in _FONTS_DIRS:
    # Tahoma — высший приоритет (точный шрифт Тензора, 7pt)
    _FONT_PATHS.append((
        _os.path.join(_d, "tahoma.ttf"),
        _os.path.join(_d, "tahomabd.ttf"),
    ))
for _d in _FONTS_DIRS:
    # Segoe UI — запасной (Контур, близкий к Tahoma)
    _FONT_PATHS.append((
        _os.path.join(_d, "segoeui.ttf"),
        _os.path.join(_d, "segoeuib.ttf"),
    ))
_FONT_PATHS += [
    # Liberation Sans — системный запасной
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/freefont/FreeSans.ttf",
     "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
_fonts_ok = False


def _fonts() -> tuple[str, str]:
    """
    Регистрирует CyrR / CyrB при первом вызове.
    Приоритет: bundled Segoe UI > Liberation Sans > FreeSans > DejaVu.
    """
    global _fonts_ok
    if _fonts_ok:
        return "CyrR", "CyrB"
    registered = pdfmetrics.getRegisteredFontNames()
    for r_path, b_path in _FONT_PATHS:
        if os.path.exists(r_path) and os.path.exists(b_path):
            if "CyrR" not in registered:
                pdfmetrics.registerFont(TTFont("CyrR", r_path))
            if "CyrB" not in registered:
                pdfmetrics.registerFont(TTFont("CyrB", b_path))
            _fonts_ok = True
            import logging
            logging.getLogger(__name__).info("Шрифт загружен: %s", r_path)
            return "CyrR", "CyrB"
    raise RuntimeError(
        "Шрифт не найден. Положите segoeui.ttf / segoeuib.ttf в edo_app/fonts/ "
        "или установите пакет fonts-liberation."
    )


# ─── Общие цвета ─────────────────────────────────────────────────────────────
C_K   = HexColor("#00459C")   # Контур — синий (измерено: RGB 0, 0.271, 0.612)
C_GL  = HexColor("#1D9E75")   # Тензор — зелёная линия
C_GT  = HexColor("#0F6E56")   # Тензор — тёмно-зелёный текст
C_BL  = HexColor("#185FA5")   # Тензор — синий текст
C_FBG = HexColor("#F8FFFD")   # Тензор — фон полосы
C_DK  = HexColor("#1A1A1A")   # Почти чёрный
C_GR  = HexColor("#555555")   # Серый
C_DV  = HexColor("#C8E8DF")   # Тензор — разделитель


# ─── Вспомогательные функции ──────────────────────────────────────────────────
def _trunc(t: str, n: int) -> str:
    """Обрезает строку до n символов."""
    return t[:n] if len(t) > n else t


# ─── Модели данных ────────────────────────────────────────────────────────────
@dataclass
class Party:
    name: str
    role: str = ""
    datetime_msk: str = ""
    certificate: str = ""
    cert_valid_from: str = ""
    cert_valid_to: str = ""


@dataclass
class StampConfig:
    operator: str
    filename: str = ""
    tax_office_code: str = ""
    inn: str = ""
    send_date: str = ""
    doc_uuid: str = ""
    identifier: str = ""
    sender: Optional[Party] = None
    receiver: Optional[Party] = None
    action_label: str = "ДЕКЛАРАЦИЯ"

    @property
    def kontur_filename(self) -> str:
        if self.filename:
            return self.filename
        uid = self.doc_uuid or self.identifier or ""
        return f"NO_USN_{self.tax_office_code}_{self.tax_office_code}_{self.inn}_{self.send_date}_{uid}"

    @classmethod
    def from_dict(cls, d: dict) -> "StampConfig":
        if "operator" not in d:
            raise ValueError("Поле 'operator' обязательно в конфиге")
        s = Party(**d["sender"])   if d.get("sender")   else None
        r = Party(**d["receiver"]) if d.get("receiver") else None
        d2 = {k: v for k, v in d.items() if k not in ("sender", "receiver")}
        return cls(sender=s, receiver=r, **d2)

    @classmethod
    def from_json(cls, path: str) -> "StampConfig":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# ─── Метаданные PDF ───────────────────────────────────────────────────────────
def _parse_pdf_date(dt_str: str, operator: str) -> str:
    """Конвертирует строку даты в формат PDF /CreationDate."""
    if not dt_str:
        return ""
    if operator == "tensor":
        m = re.match(r"(\d{1,2})\.(\d{2})\.(\d{2,4})\s+(\d{2}):(\d{2})", dt_str)
        if m:
            d, mo, y, h, mi = m.groups()
            if len(y) == 2:
                y = "20" + y
            return f"D:{y}{mo}{int(d):02d}{h}{mi}00+03'00'"
    else:
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})\s+в\s+(\d{2}):(\d{2})", dt_str)
        if m:
            d, mo, y, h, mi = m.groups()
            return f"D:{y}{mo}{d}{h}{mi}00+03'00'"
    return ""


def _build_metadata(cfg: StampConfig) -> dict:
    creator  = 'Оператор ЭДО ООО "Компания "Тензор"' if cfg.operator == "tensor" else "Контур.Эльба"
    producer = "СБИС"                                  if cfg.operator == "tensor" else "Контур"
    author   = cfg.sender.name if cfg.sender else ""
    if cfg.sender and cfg.sender.role:
        author += f", {cfg.sender.role}"
    return {
        "/Title":        cfg.kontur_filename,
        "/Author":       author,
        "/Subject":      "Налоговая декларация по налогу, уплачиваемому в связи с применением упрощённой системы налогообложения",
        "/Creator":      creator,
        "/Producer":     producer,
        "/CreationDate": _parse_pdf_date(cfg.sender.datetime_msk   if cfg.sender   else "", cfg.operator),
        "/ModDate":      _parse_pdf_date(cfg.receiver.datetime_msk if cfg.receiver else "", cfg.operator),
    }


# ─── Основная функция наложения ───────────────────────────────────────────────
def apply_stamps(inp: str, out: str, cfg: StampConfig) -> None:
    """
    Накладывает штамп оператора на каждую страницу PDF.
    Поддерживаемые операторы: 'tensor', 'kontur'.
    """
    if cfg.operator not in ("tensor", "kontur"):
        raise ValueError(f"Неизвестный оператор: {cfg.operator!r}. Допустимы: 'tensor', 'kontur'")

    _fonts()

    # Импорт рендеров здесь чтобы избежать циклических зависимостей
    from edo_tensor import render_tensor_page
    from edo_kontur import render_kontur_page
    fn = render_tensor_page if cfg.operator == "tensor" else render_kontur_page

    reader = PdfReader(inp)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        box = page.mediabox
        ovl = PdfReader(fn(cfg, i, float(box.width), float(box.height))).pages[0]
        page.merge_page(ovl)
        writer.add_page(page)

    meta = _build_metadata(cfg)
    writer.add_metadata({k: v for k, v in meta.items() if v})

    with open(out, "wb") as f:
        writer.write(f)
    print(f"✓ Готово: {out} ({len(reader.pages)} стр., {cfg.operator})")
