"""
pixel_diff.py — harness для pixel-perfect сравнения PDF.

Используется:
  - Рендер квитанций vs эталонные страницы ТЕНЗОРа/КОНТУРа
  - Рендер декларации vs эталонные страницы
  - Будущие сравнения подписей/штампов

Метрики:
  - diff_pixels — любое расхождение цвета (включая антиалиасинг)
  - strong_diff_pixels — max канал > threshold (по умолчанию 30)
  - diff_ratio — strong_diff_pixels / total_pixels

Tolerance guidance (150 DPI):
  < 1%   — pixel-perfect
  < 5%   — приемлемо для MVP
  > 10%  — регрессия
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Union

import pypdfium2 as pdfium
from PIL import Image, ImageChops


PdfSource = Union[bytes, str, Path]


def _load_page_as_image(source: PdfSource, page_idx: int, dpi: int) -> Image.Image:
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
    else:
        data = source
    pdf = pdfium.PdfDocument(data)
    if page_idx >= len(pdf):
        raise IndexError(f"PDF содержит {len(pdf)} страниц, запрошен индекс {page_idx}")
    page = pdf[page_idx]
    scale = dpi / 72.0
    img = page.render(scale=scale).to_pil().convert("RGB")
    pdf.close()
    return img


@dataclass
class DiffResult:
    width: int
    height: int
    total_pixels: int
    diff_pixels: int
    strong_diff_pixels: int
    strong_threshold: int

    @property
    def diff_ratio(self) -> float:
        return self.strong_diff_pixels / self.total_pixels if self.total_pixels else 0.0

    @property
    def raw_diff_ratio(self) -> float:
        return self.diff_pixels / self.total_pixels if self.total_pixels else 0.0


class PdfPixelDiff:
    def __init__(
        self,
        pdf_a: PdfSource,
        pdf_b: PdfSource,
        page_a: int = 0,
        page_b: int = 0,
        dpi: int = 150,
        strong_threshold: int = 30,
    ):
        self.img_a = _load_page_as_image(pdf_a, page_a, dpi)
        self.img_b = _load_page_as_image(pdf_b, page_b, dpi)
        self.dpi = dpi
        self.strong_threshold = strong_threshold

        # Нормализация размеров
        if self.img_a.size != self.img_b.size:
            target = (
                max(self.img_a.width, self.img_b.width),
                max(self.img_a.height, self.img_b.height),
            )
            if self.img_a.size != target:
                self.img_a = self.img_a.resize(target, Image.LANCZOS)
            if self.img_b.size != target:
                self.img_b = self.img_b.resize(target, Image.LANCZOS)

    def compare(self) -> DiffResult:
        diff = ImageChops.difference(self.img_a, self.img_b)
        w, h = diff.size
        total = w * h
        diff_bytes = diff.tobytes()

        diff_pixels = 0
        strong_pixels = 0
        thr = self.strong_threshold

        for i in range(0, len(diff_bytes), 3):
            r, g, b = diff_bytes[i], diff_bytes[i + 1], diff_bytes[i + 2]
            max_ch = max(r, g, b)
            if max_ch > 0:
                diff_pixels += 1
            if max_ch > thr:
                strong_pixels += 1

        return DiffResult(
            width=w,
            height=h,
            total_pixels=total,
            diff_pixels=diff_pixels,
            strong_diff_pixels=strong_pixels,
            strong_threshold=thr,
        )

    def save_diff_image(self, path: Path, amplify: int = 1) -> None:
        diff = ImageChops.difference(self.img_a, self.img_b)
        if amplify != 1:
            diff = Image.eval(diff, lambda x: min(255, x * amplify))
        diff.save(str(path))
