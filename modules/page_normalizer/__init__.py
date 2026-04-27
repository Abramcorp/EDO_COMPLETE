"""Нормализация PDF-страниц декларации УСН по чёрным fiducial-меткам.

Эталон Романова УСН 2025 определяет канонические позиции 4 чёрных квадратных
меток в углах каждой страницы декларации (стр.1-4). После рендера xlsx → PDF
позиции этих меток у нашего шаблона могут отличаться от эталонных. Этот модуль:

1. Детектирует фактические позиции меток на каждой странице сгенерированного PDF.
2. Сравнивает с :data:`.constants.ETALON_MARKS_150DPI`.
3. Вычисляет affine transform (scale + translate) для совмещения.
4. Применяет transform через :class:`pypdf.PdfWriter`.

После нормализации :mod:`modules.edo_stamps` накладывает штампы по
фиксированным координатам — эти координаты совпадают для всех документов,
независимо от исходного шаблона декларации.
"""
from .constants import ETALON_MARKS_150DPI
from .detector import find_corner_marks
from .normalizer import normalize_declaration_pdf, normalize_declaration_pdf_bytes

__all__ = [
    "ETALON_MARKS_150DPI",
    "find_corner_marks",
    "normalize_declaration_pdf",
    "normalize_declaration_pdf_bytes",
]
