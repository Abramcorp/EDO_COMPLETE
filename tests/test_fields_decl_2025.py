"""
Тесты валидации templates/knd_1152017/fields_2025.json.

PR #11 покрывает только страницу 1 (Титульный лист). Следующие PR добавят
страницы 2-4 и соответствующие тесты.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIELDS_PATH = PROJECT_ROOT / "templates" / "knd_1152017" / "fields_2025.json"

A4_W = 595.0
A4_H = 842.0
VALID_TYPES = {"char_cells", "text_line", "checkbox", "composite"}


@pytest.fixture
def fields() -> dict:
    if not FIELDS_PATH.exists():
        pytest.skip(f"{FIELDS_PATH} не найден")
    with FIELDS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


class TestMetadata:
    def test_form_version(self, fields):
        assert fields["form_version"] == "1152017"

    def test_form_year(self, fields):
        assert fields["form_year"] == 2025

    def test_has_4_pages(self, fields):
        assert fields["pages"] == 4

    def test_page_size_a4(self, fields):
        w, h = fields["page_size_pt"]
        assert 590 < w < 600
        assert 835 < h < 850


class TestPage1_TitlePage:
    """Титульный лист — основные поля из DeclarationData.TitlePage."""

    def _p1(self, fields):
        return fields["pages_def"]["1"]["fields"]

    def test_page_1_defined(self, fields):
        assert "1" in fields["pages_def"]
        assert "fields" in fields["pages_def"]["1"]

    def test_required_fields_present(self, fields):
        required = {
            "inn",
            "kpp",
            "page_number",
            "correction_number",
            "tax_period_code",
            "tax_period_year",
            "ifns_code",
            "at_location_code",
            "taxpayer_name_line1",
            "phone",
            "signing_date_day",
            "signing_date_month",
            "signing_date_year",
        }
        missing = required - set(self._p1(fields).keys())
        assert not missing, f"Отсутствуют поля: {missing}"

    def test_all_types_valid(self, fields):
        for key, spec in self._p1(fields).items():
            if key.startswith("_"):
                continue
            ftype = spec.get("type")
            assert ftype in VALID_TYPES, f"{key}: unknown type {ftype!r}"

    def test_all_coords_in_a4(self, fields):
        for key, spec in self._p1(fields).items():
            if key.startswith("_"):
                continue
            for cell in spec.get("cells", []):
                x, y = cell
                assert 0 <= x <= A4_W, f"{key}: X={x} вне 0..{A4_W}"
                assert 0 <= y <= A4_H, f"{key}: Y={y} вне 0..{A4_H}"

    # ===== ИНН: 12 клеток =====

    def test_inn_has_12_cells(self, fields):
        inn = self._p1(fields)["inn"]
        assert inn["type"] == "char_cells"
        assert len(inn["cells"]) == 12, "ИНН должен иметь 12 знакомест"

    def test_inn_cells_are_on_same_y(self, fields):
        """Все 12 клеток ИНН — одна Y координата."""
        cells = self._p1(fields)["inn"]["cells"]
        ys = {round(c[1], 1) for c in cells}
        assert len(ys) == 1, f"ИНН клетки на разных Y: {ys}"

    def test_inn_cells_monotonic_x(self, fields):
        """X-координаты ИНН идут слева направо."""
        xs = [c[0] for c in self._p1(fields)["inn"]["cells"]]
        assert xs == sorted(xs)

    def test_inn_cells_roughly_equal_step(self, fields):
        """Шаг X между клетками ИНН одинаковый (±0.5pt)."""
        xs = [c[0] for c in self._p1(fields)["inn"]["cells"]]
        deltas = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        avg = sum(deltas) / len(deltas)
        for d in deltas:
            assert abs(d - avg) < 0.5, f"Нерегулярный шаг X: {deltas}"

    def test_inn_sample_value_matches_reference(self, fields):
        """ИНН Романова из эталона ТЕНЗОРа."""
        inn = self._p1(fields)["inn"]
        assert inn["sample_value"] == "330573397709"

    # ===== КПП: 9 клеток =====

    def test_kpp_has_9_cells(self, fields):
        kpp = self._p1(fields)["kpp"]
        assert kpp["type"] == "char_cells"
        assert len(kpp["cells"]) == 9

    def test_kpp_empty_for_ip(self, fields):
        """В эталоне ИП Романов — КПП пустой."""
        assert self._p1(fields)["kpp"]["sample_value"] == ""

    # ===== Номер корректировки: 3 клетки =====

    def test_correction_number_has_3_cells(self, fields):
        c = self._p1(fields)["correction_number"]
        assert len(c["cells"]) == 3

    # ===== Налоговый период: 2 клетки =====

    def test_tax_period_code_2_cells(self, fields):
        c = self._p1(fields)["tax_period_code"]
        assert len(c["cells"]) == 2
        assert c["sample_value"] == "34"

    # ===== Отчётный год: 4 клетки =====

    def test_tax_period_year_4_cells(self, fields):
        c = self._p1(fields)["tax_period_year"]
        assert len(c["cells"]) == 4
        assert c["sample_value"] == "2025"

    # ===== Код ИФНС =====

    def test_ifns_code_4_cells(self, fields):
        c = self._p1(fields)["ifns_code"]
        assert len(c["cells"]) == 4
        assert c["sample_value"] == "3300"

    # ===== Код места =====

    def test_at_location_code_3_cells(self, fields):
        c = self._p1(fields)["at_location_code"]
        assert len(c["cells"]) == 3
        assert c["sample_value"] == "120"

    # ===== Дата подписания =====

    def test_signing_date_day_2_cells(self, fields):
        c = self._p1(fields)["signing_date_day"]
        assert len(c["cells"]) == 2

    def test_signing_date_year_4_cells(self, fields):
        c = self._p1(fields)["signing_date_year"]
        assert len(c["cells"]) == 4

    def test_signing_date_components_same_y(self, fields):
        """Все 3 части даты — на одной Y координате."""
        day = self._p1(fields)["signing_date_day"]["cells"][0][1]
        month = self._p1(fields)["signing_date_month"]["cells"][0][1]
        year = self._p1(fields)["signing_date_year"]["cells"][0][1]
        assert day == month == year, "Дата подписания — части на разных Y"

    # ===== Имя налогоплательщика =====

    def test_taxpayer_name_is_multiline(self, fields):
        """ФИО/наименование — 4 строки."""
        f = self._p1(fields)
        assert "taxpayer_name_line1" in f
        assert "taxpayer_name_line2" in f
        assert "taxpayer_name_line3" in f
        assert "taxpayer_name_line4" in f


class TestReferenceDataAlignment:
    """
    Проверка что разметка соответствует данным эталона ТЕНЗОРа:
      ИНН=330573397709, Корректировка=1, Период=34, Год=2025,
      ИФНС=3300, Код места=120, Дата=24.01.2026.
    """

    def _p1(self, fields):
        return fields["pages_def"]["1"]["fields"]

    def test_reference_values_in_samples(self, fields):
        expected = {
            "inn": "330573397709",
            "tax_period_code": "34",
            "tax_period_year": "2025",
            "ifns_code": "3300",
            "at_location_code": "120",
        }
        p1 = self._p1(fields)
        for key, expected_val in expected.items():
            actual = p1[key]["sample_value"]
            assert actual == expected_val, (
                f"{key}: sample_value={actual!r}, ожидалось {expected_val!r}"
            )

    def test_signing_date_24_01_2026(self, fields):
        p1 = self._p1(fields)
        assert p1["signing_date_day"]["sample_value"] == "24"
        assert p1["signing_date_month"]["sample_value"] == "01"
        assert p1["signing_date_year"]["sample_value"] == "2026"
