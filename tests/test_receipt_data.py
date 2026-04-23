"""
Тесты генератора реквизитов квитанций.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from modules.edo_stamps.receipt_data import (
    MSK,
    ReceiptTimestamps,
    compute_receipt_timestamps,
    generate_document_uuid,
    generate_file_name,
    generate_registration_number,
)


# ============================================================
# UUID generators
# ============================================================

KONTUR_RE = re.compile(r"^[0-9a-f]{12}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TENSOR_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class TestDocumentUuid:
    def test_kontur_format(self):
        u = generate_document_uuid("kontur")
        assert KONTUR_RE.fullmatch(u), f"Kontur format broken: {u}"
        # Должны быть ровно 32 hex + 3 дефиса = 35 символов
        assert len(u) == 35
        # Дефисы в позициях 12, 17, 22
        assert u[12] == "-" and u[17] == "-" and u[22] == "-"

    def test_tensor_format(self):
        u = generate_document_uuid("tensor")
        assert TENSOR_RE.fullmatch(u), f"Tensor format broken: {u}"
        assert len(u) == 36  # стандартный UUID
        # Дефисы в позициях 8, 13, 18, 23
        assert u[8] == "-" and u[13] == "-" and u[18] == "-" and u[23] == "-"

    def test_kontur_matches_reference_pattern(self):
        """Эталон: 11d1af3ccff1-d445-dc47-a23025d6aa8a"""
        ref = "11d1af3ccff1-d445-dc47-a23025d6aa8a"
        assert KONTUR_RE.fullmatch(ref), "Reference Kontur UUID должен матчиться"

    def test_tensor_matches_reference_pattern(self):
        """Эталон: 12d6c8ca-4bf8-4df5-a370-ce44469d1650"""
        ref = "12d6c8ca-4bf8-4df5-a370-ce44469d1650"
        assert TENSOR_RE.fullmatch(ref), "Reference Tensor UUID должен матчиться"

    def test_unknown_operator_raises(self):
        with pytest.raises(ValueError):
            generate_document_uuid("sbis")  # type: ignore[arg-type]


# ============================================================
# File name
# ============================================================

class TestFileName:
    def test_kontur_format_matches_reference(self):
        """Эталон: NO_USN_5800_5800_583806352199_20250210_11d1af3ccff1-d445-dc47-a23025d6aa8a"""
        uuid = "11d1af3ccff1-d445-dc47-a23025d6aa8a"
        name = generate_file_name(
            operator="kontur",
            ifns_code="5800",
            declarant_inn="583806352199",
            date=datetime(2025, 2, 10, 14, 12),
            document_uuid=uuid,
        )
        assert name == f"NO_USN_5800_5800_583806352199_20250210_{uuid}"

    def test_tensor_format_matches_reference(self):
        """Эталон: NO_USN_3300_3300_330517711336_20260124_12d6c8ca-4bf8-4df5-a370-ce44469d1650"""
        uuid = "12d6c8ca-4bf8-4df5-a370-ce44469d1650"
        name = generate_file_name(
            operator="tensor",
            ifns_code="3300",
            declarant_inn="330517711336",
            date=datetime(2026, 1, 24, 7, 49),
            document_uuid=uuid,
        )
        assert name == f"NO_USN_3300_3300_330517711336_20260124_{uuid}"

    def test_rejects_short_inn(self):
        with pytest.raises(ValueError, match="declarant_inn"):
            generate_file_name(
                operator="tensor",
                ifns_code="7701",
                declarant_inn="12345",
                date=datetime(2025, 1, 1),
            )

    def test_rejects_bad_ifns(self):
        with pytest.raises(ValueError, match="ifns_code"):
            generate_file_name(
                operator="tensor",
                ifns_code="770",  # 3 цифры
                declarant_inn="770123456789",
                date=datetime(2025, 1, 1),
            )

    def test_starts_with_prefix(self):
        name = generate_file_name(
            operator="kontur",
            ifns_code="7701",
            declarant_inn="770123456789",
            date=datetime(2025, 1, 1),
        )
        assert name.startswith("NO_USN_")

    def test_accepts_10_digit_inn(self):
        # ЮЛ имеет 10-значный ИНН
        name = generate_file_name(
            operator="tensor",
            ifns_code="7701",
            declarant_inn="7701234567",
            date=datetime(2025, 1, 1),
        )
        assert "_7701234567_" in name


# ============================================================
# Registration number
# ============================================================

class TestRegistrationNumber:
    def test_length_is_20(self):
        n = generate_registration_number()
        assert len(n) == 20
        assert n.isdigit()

    def test_has_8_leading_zeros_by_default(self):
        """Эталон Тензора: 00000000002774176425 — 8 ведущих нулей."""
        n = generate_registration_number()
        assert n[:8] == "00000000"

    def test_deterministic_with_seed(self):
        n1 = generate_registration_number(seed=42)
        n2 = generate_registration_number(seed=42)
        assert n1 == n2

    def test_custom_leading_zeros(self):
        n = generate_registration_number(leading_zeros=12)
        assert n[:12] == "000000000000"
        assert len(n) == 20

    def test_rejects_bad_leading_zeros(self):
        with pytest.raises(ValueError):
            generate_registration_number(leading_zeros=-1)
        with pytest.raises(ValueError):
            generate_registration_number(leading_zeros=20)

    def test_reference_pattern_matches(self):
        """Проверяем что эталон 00000000002774176425 попадает в формат."""
        ref = "00000000002774176425"
        assert len(ref) == 20
        assert ref.isdigit()
        assert ref[:8] == "00000000"


# ============================================================
# Timestamps
# ============================================================

class TestComputeReceiptTimestamps:
    def test_tensor_deltas_within_bounds(self):
        signing = datetime(2026, 1, 24, 7, 49, 0, tzinfo=MSK)
        t = compute_receipt_timestamps(signing_datetime=signing, operator="tensor", seed=1)

        # submission: +5..90 секунд
        sub_delta = (t.submission - t.signing).total_seconds()
        assert 5 <= sub_delta <= 90

        # acceptance: +25..75 минут
        acc_delta = (t.acceptance - t.signing).total_seconds() / 60
        assert 25 <= acc_delta <= 75

        # processing: +2..10 минут после acceptance
        proc_delta = (t.processing - t.acceptance).total_seconds() / 60
        assert 2 <= proc_delta <= 10

    def test_kontur_deltas_within_bounds(self):
        signing = datetime(2025, 2, 10, 14, 12, 0, tzinfo=MSK)
        t = compute_receipt_timestamps(signing_datetime=signing, operator="kontur", seed=1)

        acc_delta_min = (t.acceptance - t.signing).total_seconds() / 60
        assert 60 <= acc_delta_min <= 180

    def test_ordering(self):
        signing = datetime(2026, 1, 1, 10, 0, tzinfo=MSK)
        t = compute_receipt_timestamps(signing_datetime=signing, operator="tensor", seed=7)
        assert t.signing <= t.submission <= t.acceptance <= t.processing

    def test_naive_datetime_treated_as_msk(self):
        naive = datetime(2026, 1, 1, 10, 0)          # без tzinfo
        t = compute_receipt_timestamps(signing_datetime=naive, operator="tensor", seed=1)
        assert t.signing.tzinfo is MSK

    def test_utc_datetime_converted_to_msk(self):
        utc = datetime(2026, 1, 1, 7, 0, tzinfo=ZoneInfo("UTC"))
        t = compute_receipt_timestamps(signing_datetime=utc, operator="tensor", seed=1)
        # 07:00 UTC = 10:00 MSK
        assert t.signing.hour == 10
        assert t.signing.tzinfo.key == "Europe/Moscow"  # type: ignore[union-attr]

    def test_seeded_deterministic(self):
        signing = datetime(2026, 1, 1, 10, 0, tzinfo=MSK)
        t1 = compute_receipt_timestamps(signing_datetime=signing, operator="tensor", seed=42)
        t2 = compute_receipt_timestamps(signing_datetime=signing, operator="tensor", seed=42)
        assert t1.submission == t2.submission
        assert t1.acceptance == t2.acceptance
        assert t1.processing == t2.processing

    def test_unknown_operator_raises(self):
        with pytest.raises(ValueError):
            compute_receipt_timestamps(
                signing_datetime=datetime(2026, 1, 1, tzinfo=MSK),
                operator="sbis",  # type: ignore[arg-type]
            )
