"""Детектор чёрных квадратных fiducial-меток в углах страницы."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image
from scipy.ndimage import find_objects, label


# Параметры по умолчанию для 150 DPI A4 (метка ~5×5 мм ≈ 30 px)
DEFAULT_MARK_MIN_PX = 18
DEFAULT_MARK_MAX_PX = 70
DEFAULT_BLACK_THRESHOLD = 80  # порог яркости (0=чёрный, 255=белый)
DEFAULT_FILL_RATIO = 0.85     # компонент должен быть >85% залит чёрным
DEFAULT_ASPECT_TOLERANCE = (0.7, 1.4)  # допуск квадратности (h/w)
DEFAULT_SEARCH_ZONE_PCT = 0.18  # искать в углах 18% от размера страницы


def find_corner_marks(
    image_path: Path | str,
    *,
    mark_min_px: int = DEFAULT_MARK_MIN_PX,
    mark_max_px: int = DEFAULT_MARK_MAX_PX,
    black_threshold: int = DEFAULT_BLACK_THRESHOLD,
    fill_ratio: float = DEFAULT_FILL_RATIO,
    aspect_tolerance: Tuple[float, float] = DEFAULT_ASPECT_TOLERANCE,
    search_zone_pct: float = DEFAULT_SEARCH_ZONE_PCT,
) -> Tuple[Dict[str, Tuple[float, float]], Tuple[int, int]]:
    """Находит чёрные квадратные метки в 4 углах изображения.

    Args:
        image_path: путь к PNG/JPG странице.
        mark_min_px / mark_max_px: диапазон допустимых размеров метки в пикселях.
        black_threshold: порог бинаризации (пиксели < этого = чёрные).
        fill_ratio: минимальная доля чёрных пикселей внутри bbox компонента.
        aspect_tolerance: (min, max) для отношения высоты к ширине компонента.
        search_zone_pct: размер зоны поиска в каждом углу (доля от стороны).

    Returns:
        Кортеж ``(marks, (width, height))`` где:
            - ``marks`` — словарь ``{tag: (cx, cy)}`` с найденными метками
              (``tag`` ∈ ``TL/TR/BL/BR``); углы без метки в словаре отсутствуют.
            - ``(width, height)`` — размер изображения в пикселях.
    """
    img = np.array(Image.open(image_path).convert("L"))
    h, w = img.shape
    zone_w = int(w * search_zone_pct)
    zone_h = int(h * search_zone_pct)

    corners_data = {
        "TL": (slice(0, zone_h), slice(0, zone_w), 0, 0),
        "TR": (slice(0, zone_h), slice(w - zone_w, w), 0, w - zone_w),
        "BL": (slice(h - zone_h, h), slice(0, zone_w), h - zone_h, 0),
        "BR": (slice(h - zone_h, h), slice(w - zone_w, w), h - zone_h, w - zone_w),
    }

    results: Dict[str, Tuple[float, float]] = {}
    a_min, a_max = aspect_tolerance
    for tag, (rs, cs, off_y, off_x) in corners_data.items():
        binary = img[rs, cs] < black_threshold
        labeled, _ = label(binary)
        candidates = []
        for slc in find_objects(labeled):
            r0, r1 = slc[0].start, slc[0].stop
            c0, c1 = slc[1].start, slc[1].stop
            sh, sw = r1 - r0, c1 - c0
            if not (mark_min_px <= sh <= mark_max_px and mark_min_px <= sw <= mark_max_px):
                continue
            if sw == 0:
                continue
            aspect = sh / sw
            if not (a_min < aspect < a_max):
                continue
            fill = binary[r0:r1, c0:c1].mean()
            if fill < fill_ratio:
                continue
            cy = (r0 + r1) / 2 + off_y
            cx = (c0 + c1) / 2 + off_x
            candidates.append((cx, cy))

        if candidates:
            sign_x = 1 if "L" in tag else -1
            sign_y = 1 if "T" in tag else -1
            best = min(candidates, key=lambda c: sign_x * c[0] + sign_y * c[1])
            results[tag] = best

    return results, (w, h)
