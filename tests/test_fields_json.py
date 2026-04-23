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

    def test_ifns_full_name_is_multiline(self, fields_1166002):
        """
        REGRESSION: в эталоне ТЕНЗОРа 'УФНС России по Владимирской области' занимает
        2 строки (y≈643 и y≈634). В PR #1 было указано одной координатой — make_blank
        не стирал первую строку. См. ADR-003.
        """
        fields = fields_1166002["pages_def"]["1"]["fields"]
        assert "ifns_full_name_line1" in fields, (
            "ifns_full_name должен быть разбит на line1/line2 — "
            "в эталоне он занимает две строки"
        )
        assert "ifns_full_name_line2" in fields
        y1 = fields["ifns_full_name_line1"]["cells"][0][1]
        y2 = fields["ifns_full_name_line2"]["cells"][0][1]
        assert y1 > y2, "line1 должна быть выше line2"
        # line1 на y≈643 согласно эталону
        assert 640 < y1 < 650, f"line1 Y={y1} — ожидается 643±3 (эталон)"
        # line2 на y≈634
        assert 630 < y2 < 637, f"line2 Y={y2} — ожидается 634±3 (эталон)"

    def test_title_heading_not_in_dynamic_fields(self, fields_1166002):
        """
        REGRESSION: 'Квитанция' — это заголовок формы (константа), должен быть в
        _static_fields. В PR #1 был в динамических под именем 'title_name' — скрипт
        make_blank_from_reference.py стирал его, blank терял заголовок.
        """
        fields = fields_1166002["pages_def"]["1"]["fields"]
        # Ни одного поля с sample_value == "Квитанция" не должно быть в динамических
        problems = [
            k for k, v in fields.items()
            if v.get("sample_value", "").strip() == "Квитанция"
        ]
        assert not problems, (
            f"Поля с sample_value='Квитанция' найдены в dynamic fields: {problems}. "
            "'Квитанция' — заголовок формы, должен быть в _static_fields."
        )
        # И наоборот — в _static_fields должен упоминаться заголовок
        static = fields_1166002["pages_def"]["1"].get("_static_fields", {})
        has_title = any(
            "Квитанция" in v.get("value", "") if isinstance(v, dict) else False
            for v in static.values()
        )
        assert has_title, "_static_fields должен содержать 'Квитанция' как заголовок"


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
            "declaration_name_line1",       # был declaration_name_knd с неверной Y — разбит на 2 строки
            "declaration_name_line2",
            "file_name_line1",
            "file_name_line2",
            "ifns_full_name_and_code",
        }
        missing = required - set(fields.keys())
        assert not missing, f"Отсутствуют ключи: {missing}"

    def test_declaration_name_is_multiline(self, fields_1166007):
        """
        REGRESSION: в PR #2 было declaration_name_knd с y=587. Реально в эталоне
        название декларации занимает 2 строки на y≈576 (начало) и y≈567 (продолжение).
        Из-за неверной Y make_blank не стирал название со стр. blank.pdf.
        """
        fields = fields_1166007["pages_def"]["1"]["fields"]
        assert "declaration_name_line1" in fields, "Название декларации должно быть multiline"
        assert "declaration_name_line2" in fields
        assert "declaration_name_knd" not in fields, (
            "Старое имя declaration_name_knd (PR #2) должно быть удалено — оно имело "
            "неправильную Y=587"
        )
        y1 = fields["declaration_name_line1"]["cells"][0][1]
        y2 = fields["declaration_name_line2"]["cells"][0][1]
        assert y1 > y2
        # line1 на y≈576
        assert 573 < y1 < 580, f"line1 Y={y1} — ожидается 576±3 (эталон)"
        # line2 на y≈567
        assert 563 < y2 < 570, f"line2 Y={y2} — ожидается 567±3 (эталон)"

    def test_ifns_full_name_x_matches_reference(self, fields_1166007):
        """
        REGRESSION: в PR #2 было X=170, но реальный текст 'УПРАВЛЕНИЕ ФЕДЕРАЛЬНОЙ...'
        начинается с X=116.9. make_blank не стирал левую часть строки.
        """
        fields = fields_1166007["pages_def"]["1"]["fields"]
        spec = fields["ifns_full_name_and_code"]
        x = spec["cells"][0][0]
        assert 115 < x < 120, f"X={x} — ожидается 116.9±3 (эталон, начало 'УПРАВЛЕНИЕ')"

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
