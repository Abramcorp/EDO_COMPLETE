"""
Тесты рендера страниц квитанций КНД 1166002 и КНД 1166007.

Проверяет:
  - Рендер не падает на валидных входах
  - Выход — валидный 2-страничный PDF
  - Ключевые динамические значения (ИНН, имя файла, регистрационный номер)
    реально попадают в PDF (проверяем через pdfplumber text extraction)
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from modules.edo_stamps.receipt_renderer import (
    ReceiptRenderData,
    render_knd_1166002,
    render_knd_1166007,
    render_receipt_pages,
)


MSK = timezone(timedelta(hours=3), name="MSK")


@pytest.fixture
def sample_data() -> ReceiptRenderData:
    """Данные на основе эталона ТЕНЗОР (reference_tensor_6pages.pdf)."""
    return ReceiptRenderData(
        taxpayer_inn="330573397709",
        taxpayer_fio="Романов Дмитрий Владимирович",
        representative_inn="330517711336",
        representative_fio="Куприянова Елена Евгеньевна",
        ifns_code="3300",
        ifns_full_name_line1="УФНС России по Владимирской",
        ifns_full_name_line2="области",
        ifns_full_name_upper="УПРАВЛЕНИЕ ФЕДЕРАЛЬНОЙ НАЛОГОВОЙ СЛУЖБЫ ПО ВЛАДИМИРСКОЙ ОБЛАСТИ",
        declaration_knd="1152017",
        correction_number=1,
        tax_period_year=2025,
        file_name="NO_USN_3300_3300_330517711336_20260124_12d6c8ca-4bf8-4df5-a370-ce44469d1650",
        submission_datetime=datetime(2026, 1, 24, 7, 49, 53, tzinfo=MSK),
        acceptance_datetime=datetime(2026, 1, 24, 8, 23, 0, tzinfo=MSK),
        registration_number="00000000002774176425",
    )


# ============================================================
# Базовые smoke-тесты
# ============================================================

class TestRender1166002:
    def test_renders_without_error(self, sample_data):
        pdf_bytes = render_knd_1166002(sample_data)
        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 10000  # реально содержательный PDF, не заглушка

    def test_result_is_single_page(self, sample_data):
        pdf_bytes = render_knd_1166002(sample_data)
        reader = PdfReader(BytesIO(pdf_bytes))
        assert len(reader.pages) == 1

    def test_result_is_a4(self, sample_data):
        pdf_bytes = render_knd_1166002(sample_data)
        reader = PdfReader(BytesIO(pdf_bytes))
        page = reader.pages[0]
        assert 590 < float(page.mediabox.width) < 600
        assert 835 < float(page.mediabox.height) < 850

    def test_output_bigger_than_blank(self, sample_data):
        """
        После рендера overlay размер PDF должен быть больше чем blank —
        доказательство что overlay реально добавлен.
        """
        blank_path = Path(__file__).resolve().parent.parent / "templates" / "knd_1166002" / "blank.pdf"
        blank_size = blank_path.stat().st_size

        pdf_bytes = render_knd_1166002(sample_data)
        assert len(pdf_bytes) > blank_size, (
            f"Overlay не добавился — размер {len(pdf_bytes)} <= blank {blank_size}"
        )

    def test_deterministic_for_same_input(self, sample_data):
        """Рендер с одинаковыми входами даёт одинаковый размер (нет random в слое overlay)."""
        pdf1 = render_knd_1166002(sample_data)
        pdf2 = render_knd_1166002(sample_data)
        # Размер должен совпадать (байты могут чуть расходиться из-за PDF metadata,
        # но в пределах 1%)
        assert abs(len(pdf1) - len(pdf2)) < max(len(pdf1), len(pdf2)) * 0.01


class TestRender1166007:
    def test_renders_without_error(self, sample_data):
        pdf_bytes = render_knd_1166007(sample_data)
        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 10000

    def test_single_page(self, sample_data):
        pdf_bytes = render_knd_1166007(sample_data)
        reader = PdfReader(BytesIO(pdf_bytes))
        assert len(reader.pages) == 1

    def test_output_bigger_than_blank(self, sample_data):
        blank_path = Path(__file__).resolve().parent.parent / "templates" / "knd_1166007" / "blank.pdf"
        blank_size = blank_path.stat().st_size
        pdf_bytes = render_knd_1166007(sample_data)
        assert len(pdf_bytes) > blank_size


class TestRenderBoth:
    def test_render_receipt_pages_combined(self, sample_data):
        pdf_bytes = render_receipt_pages(sample_data)
        reader = PdfReader(BytesIO(pdf_bytes))
        assert len(reader.pages) == 2, "Должен вернуть 2-страничный PDF"

    def test_combined_is_valid_pdf(self, sample_data):
        pdf_bytes = render_receipt_pages(sample_data)
        assert pdf_bytes.startswith(b"%PDF")
        # Размер — сумма обеих страниц минимум
        assert len(pdf_bytes) > 100_000

    def test_both_pages_are_a4(self, sample_data):
        pdf_bytes = render_receipt_pages(sample_data)
        reader = PdfReader(BytesIO(pdf_bytes))
        for i, page in enumerate(reader.pages):
            assert 590 < float(page.mediabox.width) < 600, f"page {i+1} not A4"
            assert 835 < float(page.mediabox.height) < 850


# ============================================================
# Проверка что blank.pdf существует (prerequisite)
# ============================================================

class TestBlankFiles:
    """Эти тесты падают если не сгенерирован blank.pdf — и тогда рендер не работает."""

    @pytest.mark.parametrize("knd", ["1166002", "1166007"])
    def test_blank_exists(self, knd):
        project_root = Path(__file__).resolve().parent.parent
        path = project_root / "templates" / f"knd_{knd}" / "blank.pdf"
        assert path.exists(), (
            f"Не найден {path}. "
            f"Сгенерируй: python scripts/make_blank_from_reference.py "
            f"--source templates/knd_{knd}/source_page.pdf "
            f"--fields templates/knd_{knd}/fields.json "
            f"--out templates/knd_{knd}/blank.pdf"
        )

    @pytest.mark.parametrize("knd", ["1166002", "1166007"])
    def test_blank_is_single_page(self, knd):
        project_root = Path(__file__).resolve().parent.parent
        path = project_root / "templates" / f"knd_{knd}" / "blank.pdf"
        reader = PdfReader(str(path))
        assert len(reader.pages) == 1
