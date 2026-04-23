"""
Тесты валидности templates/*/fields.json.

Проверяют:
  - JSON парсится
  - Все координаты в границах A4 (0..595, 0..842)
  - Нет дубликатов logical-keys
  - sample_value присутствует для всех динамических полей
  - Все fields имеют валидный type
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

A4_W = 595.0
A4_H = 842.0
VALID_TYPES = {"char_cells", "text_line", "checkbox", "composite"}


def _load_fields_json(form_dir: str) -> dict:
    path = TEMPLATES_DIR / form_dir / "fields.json"
    if not path.exists():
        pytest.skip(f"{path} не найден")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def fields_1166002() -> dict:
    return _load_fields_json("knd_1166002")


@pytest.fixture
def fields_1166007() -> dict:
    return _load_fields_json("knd_1166007")


class TestFields1166002:
    def test_json_parses(self, fields_1166002):
        assert fields_1166002["form_version"] == "1166002"
        assert fields_1166002["pages"] == 1

    def test_has_required_keys(self, fields_1166002):
        fields = fields_1166002["pages_def"]["1"]["fields"]
        required = {
            "representative_fio_line1",
            "representative_inn",
            "submission_date",
            "submission_time",
            "file_name_line1",
            "registration_number",
            "reception_date",
            "acceptance_date",
        }
        missing = required - set(fields.keys())
        assert not missing, f"Отсутствуют ключи: {missing}"

    def test_all_coords_in_a4(self, fields_1166002):
        fields = fields_1166002["pages_def"]["1"]["fields"]
        for key, spec in fields.items():
            if spec.get("type") == "composite":
                continue
            for cell in spec.get("cells", []):
                x, y = cell
                assert 0 <= x <= A4_W, f"{key}: X={x} вне 0..{A4_W}"
                assert 0 <= y <= A4_H, f"{key}: Y={y} вне 0..{A4_H}"

    def test_all_types_valid(self, fields_1166002):
        fields = fields_1166002["pages_def"]["1"]["fields"]
        for key, spec in fields.items():
            ftype = spec.get("type")
            assert ftype in VALID_TYPES, f"{key}: unknown type {ftype!r}"

    def test_dynamic_fields_have_sample_value(self, fields_1166002):
        """Все не-composite поля должны иметь sample_value для верификации рендера."""
        fields = fields_1166002["pages_def"]["1"]["fields"]
        missing_samples = []
        for key, spec in fields.items():
            if spec.get("type") == "composite":
                continue
            if key.startswith("_"):
                continue
            if "sample_value" not in spec:
                missing_samples.append(key)
        assert not missing_samples, f"Без sample_value: {missing_samples}"

    def test_font_sizes_reasonable(self, fields_1166002):
        """Шрифты должны быть в разумном диапазоне 6-14pt."""
        fields = fields_1166002["pages_def"]["1"]["fields"]
        for key, spec in fields.items():
            if spec.get("type") == "composite":
                continue
            fs = spec.get("font_size")
            if fs is None:
                continue
            assert 6 <= fs <= 14, f"{key}: font_size={fs} вне разумных границ"

    def test_registration_number_coords_match_reference(self, fields_1166002):
        """Sanity: координата регистрационного номера должна быть там где мы её нашли (±5pt)."""
        fields = fields_1166002["pages_def"]["1"]["fields"]
        spec = fields["registration_number"]
        x, y = spec["cells"][0]
        # Из эталона: [237.0, 485.9]
        assert abs(x - 237.0) < 5, f"X={x} не совпадает с эталоном 237.0"
        assert abs(y - 485.9) < 5, f"Y={y} не совпадает с эталоном 485.9"

    def test_file_name_is_multiline(self, fields_1166002):
        """Имя файла переносится — должно быть 2 поля."""
        fields = fields_1166002["pages_def"]["1"]["fields"]
        assert "file_name_line1" in fields
        assert "file_name_line2" in fields
        # Line 2 должна быть ниже Line 1
        y1 = fields["file_name_line1"]["cells"][0][1]
        y2 = fields["file_name_line2"]["cells"][0][1]
        assert y2 < y1, "Line 2 должна быть ниже Line 1 (меньшая Y в reportlab-системе)"


class TestFields1166007:
    def test_json_parses(self, fields_1166007):
        assert fields_1166007["form_version"] == "1166007"
        assert fields_1166007["pages"] == 1

    def test_has_required_keys(self, fields_1166007):
        fields = fields_1166007["pages_def"]["1"]["fields"]
        required = {
            "representative_fio_line1",
            "representative_inn",
            "ifns_code_header",
            "declarant_fio_and_inn_line",
            "declaration_name_knd",
            "file_name_line1",
            "file_name_line2",
            "ifns_full_name_and_code",
        }
        missing = required - set(fields.keys())
        assert not missing, f"Отсутствуют ключи: {missing}"

    def test_all_coords_in_a4(self, fields_1166007):
        fields = fields_1166007["pages_def"]["1"]["fields"]
        for key, spec in fields.items():
            if spec.get("type") == "composite":
                continue
            for cell in spec.get("cells", []):
                x, y = cell
                assert 0 <= x <= A4_W, f"{key}: X={x} вне 0..{A4_W}"
                assert 0 <= y <= A4_H, f"{key}: Y={y} вне 0..{A4_H}"

    def test_all_types_valid(self, fields_1166007):
        fields = fields_1166007["pages_def"]["1"]["fields"]
        for key, spec in fields.items():
            ftype = spec.get("type")
            assert ftype in VALID_TYPES, f"{key}: unknown type {ftype!r}"

    def test_dynamic_fields_have_sample_value(self, fields_1166007):
        fields = fields_1166007["pages_def"]["1"]["fields"]
        missing_samples = []
        for key, spec in fields.items():
            if spec.get("type") == "composite":
                continue
            if key.startswith("_"):
                continue
            if "sample_value" not in spec:
                missing_samples.append(key)
        assert not missing_samples, f"Без sample_value: {missing_samples}"

    def test_font_sizes_reasonable(self, fields_1166007):
        fields = fields_1166007["pages_def"]["1"]["fields"]
        for key, spec in fields.items():
            if spec.get("type") == "composite":
                continue
            fs = spec.get("font_size")
            if fs is None:
                continue
            assert 6 <= fs <= 14, f"{key}: font_size={fs} вне разумных границ"

    def test_file_name_is_multiline(self, fields_1166007):
        """Как и в 1166002 — имя файла на две строки."""
        fields = fields_1166007["pages_def"]["1"]["fields"]
        assert "file_name_line1" in fields
        assert "file_name_line2" in fields
        y1 = fields["file_name_line1"]["cells"][0][1]
        y2 = fields["file_name_line2"]["cells"][0][1]
        assert y2 < y1

    def test_reference_ifns_code(self, fields_1166007):
        """Sanity: код ИФНС в шапке должен быть примерно там, где мы нашли в эталоне."""
        fields = fields_1166007["pages_def"]["1"]["fields"]
        spec = fields["ifns_code_header"]
        x, y = spec["cells"][0]
        # Из эталона: [244.3, 629.6]
        assert abs(x - 244.3) < 5
        assert abs(y - 629.6) < 5

    def test_has_fewer_fields_than_1166002(self, fields_1166007, fields_1166002):
        """Sanity: 1166007 проще формы 1166002 и должна иметь меньше полей."""
        n1 = len(fields_1166007["pages_def"]["1"]["fields"])
        n2 = len(fields_1166002["pages_def"]["1"]["fields"])
        assert n1 < n2, f"1166007 ({n1}) должна быть проще 1166002 ({n2})"
