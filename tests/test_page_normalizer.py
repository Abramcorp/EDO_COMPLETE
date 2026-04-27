"""Тесты для modules.page_normalizer."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.page_normalizer import (  # noqa: E402
    ETALON_MARKS_150DPI,
    find_corner_marks,
    normalize_declaration_pdf,
)
from modules.page_normalizer.normalizer import _compute_page_transform  # noqa: E402


HAS_SOFFICE = shutil.which("soffice") is not None or shutil.which("libreoffice") is not None
HAS_PDFTOPPM = shutil.which("pdftoppm") is not None
DECLARATION_TEMPLATE = ROOT / "templates" / "knd_1152017" / "declaration_template_2024.xlsx"


# ---------------------------------------------------------------------------
# _compute_page_transform — чисто математика, без I/O
# ---------------------------------------------------------------------------

class TestComputePageTransform:
    def test_identity_when_marks_match(self):
        """Если найденные метки = эталонным → identity transform."""
        marks = {"TL": (100, 100), "BR": (1000, 1000)}
        sx, sy, tx, ty = _compute_page_transform(marks, marks, (1240, 1754))
        assert sx == pytest.approx(1.0)
        assert sy == pytest.approx(1.0)
        assert tx == pytest.approx(0.0)
        assert ty == pytest.approx(0.0)

    def test_uniform_scale(self):
        """Найдены метки в 2× больше эталонных → sx=sy=0.5."""
        detected = {"TL": (200, 200), "BR": (2000, 2000)}
        target = {"TL": (100, 100), "BR": (1000, 1000)}
        sx, sy, tx, ty = _compute_page_transform(detected, target, (1240, 1754))
        assert sx == pytest.approx(0.5)
        assert sy == pytest.approx(0.5)

    def test_anisotropic_scale(self):
        """Разные scale по осям."""
        detected = {"TL": (100, 100), "BR": (1100, 1900)}
        target = {"TL": (100, 100), "BR": (1000, 1500)}
        sx, sy, _tx, _ty = _compute_page_transform(detected, target, (1240, 1754))
        # Δx: detected=1000, target=900 → sx=0.9
        # Δy: detected=1800, target=1400 → sy=14/18 ≈ 0.7778
        assert sx == pytest.approx(0.9)
        assert sy == pytest.approx(1400 / 1800)

    def test_returns_none_when_insufficient_marks(self):
        """Только TL — transform не определён."""
        detected = {"TL": (100, 100)}
        target = {"TL": (100, 100), "BR": (1000, 1000)}
        result = _compute_page_transform(detected, target, (1240, 1754))
        assert result is None

    def test_tl_bl_fallback(self):
        """Если есть TL+BL (но не BR), используется вертикаль (sx=sy)."""
        detected = {"TL": (100, 100), "BL": (100, 1100)}
        target = {"TL": (100, 100), "BL": (100, 900)}
        sx, sy, _tx, _ty = _compute_page_transform(detected, target, (1240, 1754))
        # Δy: detected=1000, target=800 → sy=0.8, sx=sy
        assert sy == pytest.approx(0.8)
        assert sx == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# ETALON_MARKS_150DPI — структура и инварианты
# ---------------------------------------------------------------------------

class TestEtalonMarks:
    def test_pages_1_to_4_present(self):
        for p in (1, 2, 3, 4):
            assert p in ETALON_MARKS_150DPI

    def test_page_1_has_three_marks(self):
        marks = ETALON_MARKS_150DPI[1]
        assert {"TL", "BL", "BR"}.issubset(marks)

    def test_pages_2_to_4_have_diagonal(self):
        for p in (2, 3, 4):
            marks = ETALON_MARKS_150DPI[p]
            assert "TL" in marks and "BR" in marks

    def test_marks_within_a4_at_150dpi(self):
        for p, marks in ETALON_MARKS_150DPI.items():
            for tag, (x, y) in marks.items():
                assert 0 <= x <= 1240, f"стр.{p} {tag}: x={x} вне A4"
                assert 0 <= y <= 1754, f"стр.{p} {tag}: y={y} вне A4"


# ---------------------------------------------------------------------------
# find_corner_marks — детектор на синтетическом изображении
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_marked_image(tmp_path):
    """A4 @ 150 DPI с 4 чёрными квадратными метками 30x30 в углах."""
    from PIL import Image, ImageDraw
    img = Image.new("L", (1240, 1754), color=255)
    draw = ImageDraw.Draw(img)
    margin = 50
    size = 30
    for cx, cy in [
        (margin, margin),                        # TL
        (1240 - margin, margin),                 # TR
        (margin, 1754 - margin),                 # BL
        (1240 - margin, 1754 - margin),          # BR
    ]:
        draw.rectangle([cx - size // 2, cy - size // 2,
                        cx + size // 2, cy + size // 2], fill=0)
    out = tmp_path / "synthetic.png"
    img.save(out)
    return out


class TestDetector:
    def test_finds_all_four_marks_on_synthetic(self, synthetic_marked_image):
        marks, size = find_corner_marks(synthetic_marked_image)
        assert size == (1240, 1754)
        assert set(marks) == {"TL", "TR", "BL", "BR"}

    def test_mark_positions_within_tolerance(self, synthetic_marked_image):
        marks, _ = find_corner_marks(synthetic_marked_image)
        # TL должен быть около (50, 50)
        assert abs(marks["TL"][0] - 50) < 3
        assert abs(marks["TL"][1] - 50) < 3
        # BR должен быть около (1190, 1704)
        assert abs(marks["BR"][0] - 1190) < 3
        assert abs(marks["BR"][1] - 1704) < 3


# ---------------------------------------------------------------------------
# Интеграционный тест: нормализация реального PDF (требует soffice + pdftoppm)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (HAS_SOFFICE and HAS_PDFTOPPM and DECLARATION_TEMPLATE.exists()),
    reason="Требует LibreOffice + poppler-utils + declaration_template_2024.xlsx",
)
class TestNormalizeIntegration:
    def test_marks_align_with_etalon_after_normalization(self, tmp_path):
        # 1. xlsx → PDF
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf",
             "--outdir", str(tmp_path), str(DECLARATION_TEMPLATE)],
            capture_output=True, timeout=60, check=True,
        )
        input_pdf = next(tmp_path.glob("*.pdf"))

        # 2. Нормализация
        output_pdf = tmp_path / "normalized.pdf"
        normalize_declaration_pdf(input_pdf, output_pdf)
        assert output_pdf.exists()

        # 3. Растеризация и проверка позиций
        out_dir = tmp_path / "after"
        out_dir.mkdir()
        subprocess.run(
            ["pdftoppm", "-r", "150", str(output_pdf), str(out_dir / "p"), "-png"],
            capture_output=True, timeout=60, check=True,
        )

        # На страницах 1-4 метки должны совпадать с эталоном (Δ ≤ 5 px)
        for p in range(1, 5):
            png = list(out_dir.glob(f"p-{p:02d}.png")) or list(out_dir.glob(f"p-{p}.png"))
            assert png, f"PNG для стр.{p} не сгенерирован"
            detected, _ = find_corner_marks(png[0])
            target = ETALON_MARKS_150DPI[p]
            for tag, (ex, ey) in target.items():
                assert tag in detected, f"стр.{p}: метка {tag} не найдена после нормализации"
                dx, dy = detected[tag][0] - ex, detected[tag][1] - ey
                assert abs(dx) <= 5, f"стр.{p}/{tag}: Δx={dx} > 5"
                assert abs(dy) <= 5, f"стр.{p}/{tag}: Δy={dy} > 5"
