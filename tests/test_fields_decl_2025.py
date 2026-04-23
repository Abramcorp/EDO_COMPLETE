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
            "taxpayer_fio_full",  # PR #15: заменён taxpayer_name_line1..4 на одну строку 40 клеток
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

    def test_taxpayer_fio_full_40_cells(self, fields):
        """
        REGRESSION PR #15: ФИО было 4 text_line (taxpayer_name_line1..4),
        теперь одна строка char_cells 40 знакомест (taxpayer_fio_full).
        Соответствует эталону ТЕНЗОРа где ФИО занимает одну строку
        клеток на y=651.5 (pdfplumber).
        """
        f = self._p1(fields)
        assert "taxpayer_fio_full" in f
        spec = f["taxpayer_fio_full"]
        assert spec["type"] == "char_cells"
        assert len(spec["cells"]) == 40, f"ФИО должно быть 40 клеток, найдено {len(spec['cells'])}"
        # Старые поля удалены
        for old in ("taxpayer_name_line1", "taxpayer_name_line2",
                    "taxpayer_name_line3", "taxpayer_name_line4"):
            assert old not in f, f"Старое поле {old} должно быть удалено"

    def test_signer_name_3_lines_char_cells(self, fields):
        """PR #15: ФИО представителя — 3 строки по 40 char_cells."""
        f = self._p1(fields)
        for i in (1, 2, 3):
            key = f"signer_name_line{i}"
            assert key in f, f"Отсутствует {key}"
            spec = f[key]
            assert spec["type"] == "char_cells"
            assert len(spec["cells"]) == 40

    def test_representative_document_2_lines(self, fields):
        """PR #15: reprensentative_document — 2 строки (текст + дата)."""
        f = self._p1(fields)
        for key in ("representative_document_line1", "representative_document_line2"):
            assert key in f, f"Отсутствует {key}"
            assert f[key]["type"] == "char_cells"
            assert len(f[key]["cells"]) == 40


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


# ============================================================
# Страницы 2, 3, 4 — разметка разделов декларации
# ============================================================

class TestPage2_Section_1_1:
    """Р.1.1 — УСН-доходы, суммы налога."""

    def _p2(self, fields):
        return fields["pages_def"]["2"]["fields"]

    def test_page_2_defined(self, fields):
        assert "2" in fields["pages_def"]

    def test_header_fields_present(self, fields):
        """Колонтитул на всех data-страницах: ИНН, КПП, номер страницы."""
        f = self._p2(fields)
        for key in ("inn_header", "kpp_header", "page_number_header"):
            assert key in f

    def test_page_number_is_002(self, fields):
        assert self._p2(fields)["page_number_header"]["sample_value"] == "002"

    def test_has_all_oktmo_fields(self, fields):
        """4 позиции ОКТМО (для квартала, полугодия, 9мес, года)."""
        f = self._p2(fields)
        for key in ("oktmo_q1", "oktmo_h1", "oktmo_9m", "oktmo_y"):
            assert key in f, f"Отсутствует {key}"
            assert len(f[key]["cells"]) == 11, f"{key} должен иметь 11 клеток"

    def test_has_advance_payment_fields(self, fields):
        f = self._p2(fields)
        for key in (
            "advance_q1",
            "advance_h1", "advance_h1_reduction",
            "advance_9m", "advance_9m_reduction",
            "tax_year_payable", "tax_year_reduction",
        ):
            assert key in f, f"Отсутствует {key}"
            assert len(f[key]["cells"]) == 12, f"{key}: ожидается 12 клеток (сумма)"
            assert f[key]["align"] == "right", f"{key} должен быть выровнен вправо"


class TestPage3_Section_2_1_1:
    """Р.2.1.1 — расчёт налога УСН-доходы."""

    def _p3(self, fields):
        return fields["pages_def"]["3"]["fields"]

    def test_page_3_defined(self, fields):
        assert "3" in fields["pages_def"]
        assert self._p3(fields)["page_number_header"]["sample_value"] == "003"

    def test_has_income_quarterly_fields(self, fields):
        """Доходы по кварталам — 4 поля."""
        f = self._p3(fields)
        for key in ("income_q1", "income_h1", "income_9m", "income_y"):
            assert key in f
            assert len(f[key]["cells"]) == 12

    def test_has_tax_rate_fields(self, fields):
        """Ставки налога — 4 поля."""
        f = self._p3(fields)
        for key in ("tax_rate_q1", "tax_rate_h1", "tax_rate_9m", "tax_rate_y"):
            assert key in f
            assert len(f[key]["cells"]) == 4, f"{key}: 4 клетки для '6.0'"

    def test_has_tax_calc_fields(self, fields):
        """Исчисленный налог."""
        f = self._p3(fields)
        for key in ("tax_calc_q1", "tax_calc_h1", "tax_calc_9m", "tax_calc_y"):
            assert key in f
            assert len(f[key]["cells"]) == 12

    def test_taxpayer_sign_1_cell(self, fields):
        assert len(self._p3(fields)["taxpayer_sign"]["cells"]) == 1

    def test_reference_income_values(self, fields):
        """sample_values для income — из эталона (409517 для 9мес и года)."""
        f = self._p3(fields)
        assert f["income_9m"]["sample_value"] == "409517"
        assert f["income_y"]["sample_value"] == "409517"


class TestPage4_Section_2_1_1_Continued:
    """Р.2.1.1 (продолжение) — страховые взносы."""

    def _p4(self, fields):
        return fields["pages_def"]["4"]["fields"]

    def test_page_4_defined(self, fields):
        assert "4" in fields["pages_def"]
        assert self._p4(fields)["page_number_header"]["sample_value"] == "004"

    def test_has_insurance_fields(self, fields):
        f = self._p4(fields)
        for key in ("insurance_q1", "insurance_h1", "insurance_9m", "insurance_y"):
            assert key in f
            assert len(f[key]["cells"]) == 12
            assert f[key]["align"] == "right"

    def test_reference_insurance_values(self, fields):
        """В эталоне: взносы 9мес=24571, годовые=24571."""
        f = self._p4(fields)
        assert f["insurance_9m"]["sample_value"] == "24571"
        assert f["insurance_y"]["sample_value"] == "24571"


class TestAllPagesConsistency:
    """Общие проверки по всем 4 страницам."""

    def test_every_page_has_header(self, fields):
        """Страницы 2-4 должны иметь колонтитул ИНН/КПП/№стр."""
        for page in ("2", "3", "4"):
            fs = fields["pages_def"][page]["fields"]
            assert "inn_header" in fs, f"Стр.{page} без inn_header"
            assert "kpp_header" in fs
            assert "page_number_header" in fs

    def test_inn_header_consistent_y_across_pages(self, fields):
        """ИНН в колонтитуле — одна Y на всех стр. 2-4."""
        ys = set()
        for page in ("2", "3", "4"):
            y = fields["pages_def"][page]["fields"]["inn_header"]["cells"][0][1]
            ys.add(round(y, 1))
        assert len(ys) == 1, f"inn_header на разных Y: {ys}"

    def test_all_coords_in_a4_all_pages(self, fields):
        A4_W, A4_H = 595.0, 842.0
        for page_num, page_def in fields["pages_def"].items():
            for key, spec in page_def.get("fields", {}).items():
                if key.startswith("_"):
                    continue
                for cell in spec.get("cells", []):
                    x, y = cell
                    assert 0 <= x <= A4_W, f"стр.{page_num}/{key}: X={x}"
                    assert 0 <= y <= A4_H, f"стр.{page_num}/{key}: Y={y}"

