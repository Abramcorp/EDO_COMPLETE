"""
Тесты blank_2025.pdf для декларации КНД 1152017.

Проверяет что pre-rendered бланк существует, корректен, и готов служить
подложкой для overlay-рендера (см. ADR-004).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BLANK_2025 = PROJECT_ROOT / "templates" / "knd_1152017" / "blank_2025.pdf"


@pytest.fixture
def blank_reader() -> PdfReader:
    if not BLANK_2025.exists():
        pytest.skip(f"blank_2025.pdf отсутствует: {BLANK_2025}")
    return PdfReader(str(BLANK_2025))


class TestBlank2025:
    def test_exists(self):
        assert BLANK_2025.exists(), f"Должен существовать: {BLANK_2025}"

    def test_size_reasonable(self):
        """Raster blank со статическими лейблами: >100KB и <3MB."""
        size_kb = BLANK_2025.stat().st_size / 1024
        assert 100 < size_kb < 3000, f"Размер {size_kb:.0f} KB вне диапазона 100-3000 KB"

    def test_has_4_pages(self, blank_reader):
        """Декларация КНД 1152017 УСН-доходы для ИП = 4 страницы."""
        assert len(blank_reader.pages) == 4

    def test_all_pages_are_a4(self, blank_reader):
        """Все страницы — A4 портретная ориентация."""
        for i, page in enumerate(blank_reader.pages):
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            assert 590 < w < 600, f"стр.{i+1}: ширина {w} вне A4"
            assert 835 < h < 850, f"стр.{i+1}: высота {h} вне A4"
            # Проверяем портретная ориентация
            assert h > w, f"стр.{i+1}: должна быть портретная (h>w), но {h} <= {w}"

    def test_has_field_labels(self, blank_reader):
        """
        Vector blank должен сохранять текстовые подписи полей (клеточки и
        подписи — часть эталона ФНС). Проверяем наличие ключевых маркеров.
        """
        all_text = "\n".join(
            (page.extract_text() or "")
            for page in blank_reader.pages
        )
        # Ключевые маркеры формы КНД 1152017
        expected = ["КНД 1152017", "Номер корректировки", "ИНН"]
        for marker in expected:
            assert marker in all_text, (
                f"Blank не содержит ожидаемый маркер {marker!r}. "
                f"Возможно, файл повреждён или используется не тот источник."
            )

    def test_no_empty_pages(self, blank_reader):
        """Каждая страница должна содержать embedded image (быть не пустой)."""
        for i, page in enumerate(blank_reader.pages):
            resources = page.get("/Resources", {})
            # Для страницы с вставленным изображением должен быть XObject
            # (хотя pypdf API слегка кривой)
            has_xobject = "/XObject" in resources or bool(page.images)
            assert has_xobject, f"стр.{i+1}: нет embedded image"
