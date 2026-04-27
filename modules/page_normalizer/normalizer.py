"""Нормализация PDF-страниц декларации по детектированным меткам.

Алгоритм:

1. Сгенерированный PDF (после xlsx → PDF через soffice) рендерится
   постранично в PNG в DPI :data:`.constants.ETALON_DPI` через ``pdftoppm``.
2. На каждой странице 1..4 детектятся чёрные метки.
3. Из ``ETALON_MARKS_150DPI[page_num]`` берётся целевое положение тех же
   меток. Считается affine transform (раздельный sx, sy + translate),
   приводящий найденные метки к эталонным.
4. Через :class:`pypdf.PdfWriter` к странице применяется матрица.
5. Страницы 5-6 (квитанции из docx) пропускаются — у них нет меток.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject

from .constants import ETALON_DPI, ETALON_MARKS_150DPI, PageMarks
from .detector import find_corner_marks

logger = logging.getLogger(__name__)


def _rasterize_pdf_pages(
    pdf_path: Path, out_dir: Path, dpi: int = ETALON_DPI
) -> List[Path]:
    """Рендерит каждую страницу PDF в PNG через ``pdftoppm``.

    Returns: список путей к PNG-файлам в порядке страниц (1..N).
    """
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm is None:
        raise RuntimeError(
            "pdftoppm не найден в PATH. В Dockerfile должен быть установлен "
            "пакет poppler-utils."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / "page"
    result = subprocess.run(
        [pdftoppm, "-r", str(dpi), str(pdf_path), str(prefix), "-png"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftoppm failed: {result.stderr}")
    return sorted(out_dir.glob("page-*.png"))


def _compute_page_transform(
    detected: PageMarks,
    target: PageMarks,
    page_size_px: Tuple[int, int],
) -> Optional[Tuple[float, float, float, float]]:
    """Из найденных и эталонных меток вычисляет ``(sx, sy, tx_px, ty_px)``.

    Использует диагональ TL—BR как опорную (если есть). Если только TL—BL —
    sx копируется из sy (равномерный по осям).

    Returns: ``(sx, sy, tx_px, ty_px)`` в пиксельных координатах @ ETALON_DPI,
        или ``None`` если данных недостаточно.
    """
    common = set(detected) & set(target)

    # Лучший случай: TL + BR (диагональ)
    if {"TL", "BR"}.issubset(common):
        d_tl, d_br = detected["TL"], detected["BR"]
        t_tl, t_br = target["TL"], target["BR"]
        d_dx = d_br[0] - d_tl[0]
        d_dy = d_br[1] - d_tl[1]
        t_dx = t_br[0] - t_tl[0]
        t_dy = t_br[1] - t_tl[1]
        if d_dx == 0 or d_dy == 0:
            return None
        sx = t_dx / d_dx
        sy = t_dy / d_dy
        # translate так, чтобы TL после трансформации совпала с эталонной TL
        tx = t_tl[0] - sx * d_tl[0]
        ty = t_tl[1] - sy * d_tl[1]
        return sx, sy, tx, ty

    # Альтернатива: TL + BL (одна вертикальная линия)
    if {"TL", "BL"}.issubset(common):
        d_tl, d_bl = detected["TL"], detected["BL"]
        t_tl, t_bl = target["TL"], target["BL"]
        d_dy = d_bl[1] - d_tl[1]
        t_dy = t_bl[1] - t_tl[1]
        if d_dy == 0:
            return None
        sy = t_dy / d_dy
        sx = sy  # равномерно
        tx = t_tl[0] - sx * d_tl[0]
        ty = t_tl[1] - sy * d_tl[1]
        return sx, sy, tx, ty

    return None


def _apply_transform_to_page(
    page,
    sx: float,
    sy: float,
    tx_px: float,
    ty_px: float,
    page_size_px: Tuple[int, int],
    dpi: int,
) -> None:
    """Применяет affine transform к странице PDF in-place.

    Координаты PDF: начало в нижнем-левом углу, Y вверх.
    Координаты пикселей: начало в верхнем-левом углу, Y вниз.

    Конвертация: ``y_pdf = page_height_pt - y_px * pt_per_px``.
    """
    pt_per_px = 72.0 / dpi
    _, page_h_px = page_size_px
    page_h_pt = page_h_px * pt_per_px

    # Преобразуем translate из пиксельной системы (origin top-left) в PDF (origin bottom-left).
    # Transform в пикселях: x_new_px = sx * x_px + tx_px; y_new_px = sy * y_px + ty_px
    # В PDF: x_new_pt = sx * x_pt + tx_pt; y_new_pt = sy * y_pt + (page_h_pt*(1 - sy) - ty_px*pt_per_px)
    tx_pt = tx_px * pt_per_px
    ty_pt = page_h_pt * (1 - sy) - ty_px * pt_per_px

    transform = Transformation().scale(sx, sy).translate(tx_pt, ty_pt)
    page.add_transformation(transform)

    # MediaBox / CropBox оставляем прежними (A4) — содержимое сожато внутри
    # тех же границ, штамп будет ложиться по абсолютным координатам страницы.


def normalize_declaration_pdf(
    input_pdf: Path,
    output_pdf: Path,
    *,
    pages_to_normalize: Optional[List[int]] = None,
    work_dir: Optional[Path] = None,
    dpi: int = ETALON_DPI,
) -> Path:
    """Нормализует страницы декларации в PDF по чёрным меткам.

    Args:
        input_pdf: исходный PDF (декларация + опционально квитанции).
        output_pdf: путь к нормализованному PDF.
        pages_to_normalize: список 1-based номеров страниц для нормализации.
            По умолчанию — ``[1, 2, 3, 4]`` (страницы декларации).
            Страницы вне списка копируются как есть.
        work_dir: каталог для промежуточных PNG. Если None — временный.
        dpi: DPI растеризации для детекции (по умолчанию 150).

    Returns:
        Путь к нормализованному PDF (равен ``output_pdf``).

    Behaviour:
        Если на странице из ``pages_to_normalize`` метки не найдены или их
        недостаточно для расчёта transform — страница копируется без изменений
        и логируется предупреждение.
    """
    if pages_to_normalize is None:
        pages_to_normalize = [1, 2, 3, 4]

    cleanup_work_dir = work_dir is None
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="page_normalizer_"))
    else:
        work_dir.mkdir(parents=True, exist_ok=True)

    try:
        png_paths = _rasterize_pdf_pages(input_pdf, work_dir, dpi=dpi)

        reader = PdfReader(str(input_pdf))
        writer = PdfWriter()

        for i, page in enumerate(reader.pages):
            page_num = i + 1
            if page_num in pages_to_normalize and page_num <= len(png_paths):
                target = ETALON_MARKS_150DPI.get(page_num)
                if target is None:
                    logger.warning("Стр.%d: нет эталонных меток в ETALON_MARKS, пропускаю", page_num)
                    writer.add_page(page)
                    continue

                detected, page_size_px = find_corner_marks(png_paths[i])
                transform = _compute_page_transform(detected, target, page_size_px)
                if transform is None:
                    logger.warning(
                        "Стр.%d: не удалось вычислить transform (detected=%s, target=%s)",
                        page_num, list(detected.keys()), list(target.keys()),
                    )
                    writer.add_page(page)
                    continue

                sx, sy, tx, ty = transform
                logger.info(
                    "Стр.%d: transform sx=%.4f sy=%.4f tx=%.1f ty=%.1f (px @%dDPI)",
                    page_num, sx, sy, tx, ty, dpi,
                )
                _apply_transform_to_page(page, sx, sy, tx, ty, page_size_px, dpi)
            writer.add_page(page)

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with open(output_pdf, "wb") as f:
            writer.write(f)

        return output_pdf
    finally:
        if cleanup_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


def normalize_declaration_pdf_bytes(
    input_pdf_bytes: bytes,
    *,
    pages_to_normalize: Optional[List[int]] = None,
    dpi: int = ETALON_DPI,
) -> bytes:
    """In-memory обёртка над :func:`normalize_declaration_pdf` для pipeline.

    Принимает PDF как байты, возвращает нормализованный PDF как байты.
    Внутри использует временный каталог для растеризации страниц через pdftoppm
    (избежать его на этом этапе нельзя — pypdf не умеет растеризировать).

    Args:
        input_pdf_bytes: исходный PDF-документ.
        pages_to_normalize: список 1-based номеров страниц (по умолчанию [1,2,3,4]).
        dpi: DPI растеризации для детекции (по умолчанию 150).

    Returns:
        Нормализованный PDF-документ.

    Behaviour:
        Семантика идентична :func:`normalize_declaration_pdf` — страницы без
        найденных меток или вне ``pages_to_normalize`` копируются как есть.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="page_normalizer_bytes_"))
    try:
        input_path = work_dir / "input.pdf"
        output_path = work_dir / "output.pdf"
        input_path.write_bytes(input_pdf_bytes)
        normalize_declaration_pdf(
            input_pdf=input_path,
            output_pdf=output_path,
            pages_to_normalize=pages_to_normalize,
            work_dir=work_dir / "raster",
            dpi=dpi,
        )
        return output_path.read_bytes()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
