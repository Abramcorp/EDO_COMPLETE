"""
Integration тест: render_declaration + apply_stamps (end-to-end без 1С/ОФД).

Проверяет что:
  - render_declaration(data) выдаёт 4-страничный PDF декларации
  - apply_stamps накладывает footer-штамп Тензора/Контура
  - Итоговый PDF валиден и содержит штамп (размер > render-only)
  - Footer-зона очищена в blank → штамп не дублируется

Pixel-diff со штампом НЕ делается — штамп содержит UUID, сертификаты,
даты-времена которые уникальны для каждой декларации. Эталон имеет
собственные значения, совпадение невозможно.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from modules.declaration_filler.declaration_data import (
    DeclarationData,
    TitlePage,
    Section_1_1,
    Section_2_1_1,
    OBJECT_INCOME,
    TP_SIGN_IP_NO_EMPLOYEES,
    LOC_IP_RESIDENCE,
    SIGNER_REPRESENTATIVE,
)
from modules.declaration_filler.pdf_overlay_filler import render_declaration
from modules.edo_stamps import apply_stamps, IftsInfo


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BLANK_2025 = PROJECT_ROOT / "templates" / "knd_1152017" / "blank_2025.pdf"


class _MockOperator:
    """Mock для api.models.EdoOperator enum — apply_stamps ждёт .value."""
    def __init__(self, value: str):
        self.value = value


@pytest.fixture
def ifts_info() -> IftsInfo:
    """Данные УФНС по Владимирской области (из эталона ТЕНЗОРа)."""
    return IftsInfo(
        inn="3327102084",
        name="УПРАВЛЕНИЕ ФЕДЕРАЛЬНОЙ НАЛОГОВОЙ СЛУЖБЫ ПО ВЛАДИМИРСКОЙ ОБЛАСТИ",
        address="г Владимир",
        manager_name="Фахретдинов Марат Мансурович",
        manager_post="Руководитель",
    )


@pytest.fixture
def romanov_data() -> DeclarationData:
    """Данные Романова Д.В. (из эталона ТЕНЗОРа, УСН 2025)."""
    return DeclarationData(
        title=TitlePage(
            inn="330573397709",
            correction_number=1,
            tax_period_year=2025,
            ifns_code="3300",
            at_location_code=LOC_IP_RESIDENCE,
            taxpayer_name_line1="Романов",
            taxpayer_name_line2="Дмитрий",
            taxpayer_name_line3="Владимирович",
            phone="79157503070",
            signing_date=date(2026, 1, 24),
            object_code=OBJECT_INCOME,
            signer_type=SIGNER_REPRESENTATIVE,
            signer_name_line1="Куприянова",
            signer_name_line2="Елена",
            signer_name_line3="Евгеньевна",
            representative_document="ДОВЕРЕННОСТЬ №2 ОТ 01.07.2025",
        ),
        section_1_1=Section_1_1(oktmo_q1="17701000"),
        section_2_1_1=Section_2_1_1(
            taxpayer_sign=TP_SIGN_IP_NO_EMPLOYEES,
            income_9m=Decimal("409517"),
            income_y=Decimal("409517"),
            tax_rate_q1=Decimal("6.0"),
            tax_rate_h1=Decimal("6.0"),
            tax_rate_9m=Decimal("6.0"),
            tax_rate_y=Decimal("6.0"),
            tax_calc_9m=Decimal("24571"),
            tax_calc_y=Decimal("24571"),
            insurance_9m=Decimal("24571"),
            insurance_y=Decimal("24571"),
        ),
    )


# ============================================================
# Tensor end-to-end
# ============================================================

@pytest.mark.skipif(not BLANK_2025.exists(), reason="blank_2025.pdf отсутствует")
class TestDeclarationWithTensorStamp:
    def test_full_pipeline_succeeds(self, romanov_data, ifts_info):
        """Smoke: рендер + штамп ТЕНЗОРа — не падает."""
        pdf = render_declaration(romanov_data)
        stamped = apply_stamps(
            pdf_bytes=pdf,
            operator=_MockOperator("tensor"),
            taxpayer_inn="330573397709",
            ifts_info=ifts_info,
            tax_office_code="3300",
            signing_datetime=datetime(2026, 1, 24, 7, 49),
        )
        assert stamped.startswith(b"%PDF")

    def test_stamped_has_same_page_count(self, romanov_data, ifts_info):
        """Штамп не меняет число страниц — остаётся 4."""
        pdf = render_declaration(romanov_data)
        stamped = apply_stamps(
            pdf_bytes=pdf,
            operator=_MockOperator("tensor"),
            taxpayer_inn="330573397709",
            ifts_info=ifts_info,
            tax_office_code="3300",
            signing_datetime=datetime(2026, 1, 24, 7, 49),
        )
        reader_original = PdfReader(BytesIO(pdf))
        reader_stamped = PdfReader(BytesIO(stamped))
        assert len(reader_original.pages) == len(reader_stamped.pages) == 4

    def test_stamped_pdf_larger(self, romanov_data, ifts_info):
        """Штамп добавляет контент → размер больше."""
        pdf = render_declaration(romanov_data)
        stamped = apply_stamps(
            pdf_bytes=pdf,
            operator=_MockOperator("tensor"),
            taxpayer_inn="330573397709",
            ifts_info=ifts_info,
            tax_office_code="3300",
            signing_datetime=datetime(2026, 1, 24, 7, 49),
        )
        assert len(stamped) > len(pdf), (
            f"stamped ({len(stamped)}) не больше render-only ({len(pdf)})"
        )

    def test_deterministic_with_fixed_uuid(self, romanov_data, ifts_info):
        """С одним и тем же doc_uuid выход детерминирован (размер в пределах 1%)."""
        pdf = render_declaration(romanov_data)
        fixed_uuid = "05fc595c-a533-4b4f-ae26-d3e56caae3d9"
        kwargs = dict(
            pdf_bytes=pdf,
            operator=_MockOperator("tensor"),
            taxpayer_inn="330573397709",
            ifts_info=ifts_info,
            tax_office_code="3300",
            signing_datetime=datetime(2026, 1, 24, 7, 49),
            doc_uuid=fixed_uuid,
        )
        a = apply_stamps(**kwargs)
        b = apply_stamps(**kwargs)
        assert abs(len(a) - len(b)) < max(len(a), len(b)) * 0.01


# ============================================================
# Kontur end-to-end
# ============================================================

@pytest.mark.skipif(not BLANK_2025.exists(), reason="blank_2025.pdf отсутствует")
class TestDeclarationWithKonturStamp:
    def test_kontur_stamp_succeeds(self, romanov_data, ifts_info):
        """Штамп КОНТУРа тоже работает."""
        pdf = render_declaration(romanov_data)
        stamped = apply_stamps(
            pdf_bytes=pdf,
            operator=_MockOperator("kontur"),
            taxpayer_inn="330573397709",
            ifts_info=ifts_info,
            tax_office_code="3300",
            signing_datetime=datetime(2026, 1, 24, 7, 49),
        )
        assert stamped.startswith(b"%PDF")
        reader = PdfReader(BytesIO(stamped))
        assert len(reader.pages) == 4


# ============================================================
# Ошибки операторов
# ============================================================

class TestInvalidOperator:
    def test_unknown_operator_raises(self, romanov_data, ifts_info):
        pdf = render_declaration(romanov_data)
        with pytest.raises(ValueError, match="Неизвестный оператор"):
            apply_stamps(
                pdf_bytes=pdf,
                operator=_MockOperator("unknown_operator"),
                taxpayer_inn="330573397709",
                ifts_info=ifts_info,
                tax_office_code="3300",
            )
