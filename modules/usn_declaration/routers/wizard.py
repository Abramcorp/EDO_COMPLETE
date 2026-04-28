"""
Wizard endpoints for the simplified 4-step flow:
    1. Upload (bank + OFD)
    2. Revenue split by quarters (with OFD-cash dedupe)
    3. Personnel & contributions (for tax reduction)
    4. Generate declaration for the requested period
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, Dict, Any, List
import tempfile
import subprocess

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
import shutil

from app.database import get_db
from app.models import BankOperation, OfdReceipt, Project
from app.services.parser import BankStatementParser
from app.services.classifier import OperationClassifier
from app.services.revenue_calculator import (
    compute_quarterly_revenue,
    compute_tax_by_period,
)
from app.services.excel_declaration import fill_declaration, get_template_for_year
from app.services.xlsx_to_pdf import convert_xlsx_to_pdf, XlsxToPdfError

router = APIRouter(prefix="/api/wizard", tags=["wizard"])


# ----------- Pydantic models --------------------------------------------

class QuickProjectRequest(BaseModel):
    inn: str
    fio: str
    tax_period_year: int = 2024
    oktmo: Optional[str] = None
    ifns_code: Optional[str] = None


class PersonnelRequest(BaseModel):
    has_employees: bool
    employee_start_quarter: Optional[int] = None  # 1..4 or null

    # Insurance contributions paid this year (in rubles).
    # User enters cumulative amounts paid up to each period.
    contributions_q1: float = 0
    contributions_half_year: float = 0
    contributions_nine_months: float = 0
    contributions_year: float = 0


class SummaryResponse(BaseModel):
    project: Dict[str, Any]
    quarters: Dict[str, Any]      # bank / ofd_cash / total / cumulative
    recommendation: str


class DeclarationTaxResponse(BaseModel):
    cumulative: Dict[str, float]
    tax: Dict[str, Dict[str, float]]
    rate: float
    has_employees: bool
    reduction_limit_pct: int  # 50 or 100


# ----------- Endpoints ---------------------------------------------------

@router.post("/bank-first")
def bank_first_upload(
    tax_period_year: int = Query(..., description="Год декларации"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    First-step endpoint for the wizard.

    The user just drops a bank statement and we:
      • parse it,
      • extract ИНН/ФИО владельца счёта,
      • create a Project (or reuse by ИНН+год),
      • import and classify operations.

    The caller gets back project_id + extracted owner info, so Step 1
    can auto-fill those read-only fields.
    """
    if not file.filename.endswith(".txt"):
        raise HTTPException(400, "Поддерживаются только файлы .txt (формат 1С)")

    # Save temp file
    uploads_dir = Path(__file__).resolve().parent.parent.parent / "data" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"bankfirst_{stamp}_{file.filename}"
    file_path = uploads_dir / safe_name
    with open(file_path, "wb") as fh:
        shutil.copyfileobj(file.file, fh)

    # Parse to extract owner info
    parser = BankStatementParser()
    parse_result = parser.parse(str(file_path))
    if not parse_result or "operations" not in parse_result:
        raise HTTPException(400, "Не удалось распарсить файл банковской выписки")

    owner_inn = (parse_result.get("owner_inn") or "").strip()
    owner_name = (parse_result.get("owner_name") or "").strip()
    if not owner_inn:
        raise HTTPException(
            400,
            "Не удалось извлечь ИНН владельца из выписки. "
            "Проверьте, что файл в формате 1С ClientBank.",
        )
    if not owner_name:
        owner_name = "ИП"

    # Find / create project
    project = (
        db.query(Project)
        .filter(Project.inn == owner_inn, Project.tax_period_year == tax_period_year)
        .first()
    )
    if project:
        project.fio = owner_name or project.fio
        # Wipe existing operations so import is idempotent
        db.query(BankOperation).filter(BankOperation.project_id == project.id).delete()
        db.commit()
    else:
        project = Project(
            inn=owner_inn,
            fio=owner_name,
            tax_period_year=tax_period_year,
            has_employees=False,
            uses_ens=True,
            contribution_input_mode="total",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

    # Classify & save operations
    classifier = OperationClassifier(project.id, db)
    ops = parse_result.get("operations", [])
    to_classify = [
        {
            "amount": Decimal(str(op.get("amount", 0))),
            "direction": op.get("direction", "income"),
            "purpose": op.get("purpose", ""),
            "counterparty": op.get("counterparty", ""),
            "counterparty_inn": op.get("counterparty_inn", ""),
        }
        for op in ops
    ]
    classifications = classifier.classify_batch(to_classify)

    income_count = 0
    income_amount = Decimal("0")
    for idx, op in enumerate(ops):
        cls = classifications[idx] if idx < len(classifications) else {}
        bank_op = BankOperation(
            project_id=project.id,
            operation_date=op.get("operation_date"),
            posting_date=op.get("posting_date"),
            amount=Decimal(str(op.get("amount", 0))),
            direction=op.get("direction", "income"),
            purpose=op.get("purpose", ""),
            counterparty=op.get("counterparty", ""),
            counterparty_inn=op.get("counterparty_inn", ""),
            counterparty_account=op.get("counterparty_account", ""),
            document_number=op.get("document_number", ""),
            classification=cls.get("classification", "disputed"),
            classification_rule=cls.get("rule", ""),
            classification_confidence=cls.get("confidence", 0.0),
            included_in_tax_base=cls.get("classification") == "income",
        )
        db.add(bank_op)
        if cls.get("classification") == "income":
            income_count += 1
            income_amount += Decimal(str(op.get("amount", 0)))
    db.commit()

    return {
        "project_id":    project.id,
        "inn":           project.inn,
        "fio":           project.fio,
        "year":          project.tax_period_year,
        "oktmo":         project.oktmo or "",
        "ifns_code":     project.ifns_code or "",
        "account_number":parse_result.get("account_number"),
        "period_start":  str(parse_result.get("period_start", "")) if parse_result.get("period_start") else None,
        "period_end":    str(parse_result.get("period_end", "")) if parse_result.get("period_end") else None,
        "operations_saved":  len(ops),
        "income_operations": income_count,
        "income_amount":     str(income_amount),
    }


class SaveTaxDetailsRequest(BaseModel):
    oktmo: Optional[str] = None
    ifns_code: Optional[str] = None


@router.post("/tax-details/{project_id}")
def save_tax_details(
    project_id: int,
    payload: SaveTaxDetailsRequest,
    db: Session = Depends(get_db),
):
    """Save ОКТМО and код ИФНС entered by user in Step 1."""
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Проект не найден")
    if payload.oktmo is not None:
        proj.oktmo = payload.oktmo.strip() or None
    if payload.ifns_code is not None:
        proj.ifns_code = payload.ifns_code.strip() or None
    db.commit()
    return {"ok": True}


@router.post("/quick-project")
def quick_create_project(payload: QuickProjectRequest, db: Session = Depends(get_db)):
    """Create or replace a wizard project with a minimal set of fields."""
    existing = (
        db.query(Project)
        .filter(Project.inn == payload.inn, Project.tax_period_year == payload.tax_period_year)
        .first()
    )
    if existing:
        # Update basic fields only; keep its data.
        existing.fio = payload.fio
        if payload.oktmo:
            existing.oktmo = payload.oktmo
        if payload.ifns_code:
            existing.ifns_code = payload.ifns_code
        db.commit()
        db.refresh(existing)
        return {"project_id": existing.id, "reused": True}

    proj = Project(
        inn=payload.inn,
        fio=payload.fio,
        tax_period_year=payload.tax_period_year,
        oktmo=payload.oktmo,
        ifns_code=payload.ifns_code,
        has_employees=False,
        uses_ens=True,
        contribution_input_mode="total",
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return {"project_id": proj.id, "reused": False}


@router.get("/summary/{project_id}", response_model=SummaryResponse)
def wizard_summary(project_id: int, db: Session = Depends(get_db)):
    """Return revenue per quarter + cumulative periods for the wizard step 2."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Проект не найден")

    data = compute_quarterly_revenue(db, project_id)

    if data["has_ofd"]:
        recommendation = (
            "Из ОФД учтена только наличная выручка (sale − refund). "
            "Безналичные чеки ОФД игнорированы, т. к. они уже попадают в банк как эквайринг."
        )
    else:
        recommendation = (
            "Файл ОФД не загружен — учтены только банковские поступления. "
            "Если были наличные продажи, загрузите ОФД, чтобы включить их в выручку."
        )

    return SummaryResponse(
        project={
            "id":       project.id,
            "inn":      project.inn,
            "fio":      project.fio,
            "year":     project.tax_period_year,
            "oktmo":    project.oktmo or "",
            "ifns_code":project.ifns_code or "",
        },
        quarters=data,
        recommendation=recommendation,
    )


@router.post("/personnel/{project_id}", response_model=DeclarationTaxResponse)
def personnel_and_tax(
    project_id: int,
    payload: PersonnelRequest,
    db: Session = Depends(get_db),
):
    """
    Save personnel info + compute tax for every period, applying the correct
    reduction limit (100 % for solo IP, 50 % if has_employees).
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Проект не найден")

    # Save on project
    project.has_employees = payload.has_employees
    project.employee_start_quarter = payload.employee_start_quarter
    db.commit()

    # Compute revenue
    rev = compute_quarterly_revenue(db, project_id)
    cum = rev["cumulative"]
    rate = float(project.tax_rate or 6.0)

    # Apply reduction limit: 50 % if employees, 100 % otherwise
    limit_pct = 50 if payload.has_employees else 100
    limit_factor = Decimal(limit_pct) / Decimal(100)

    contributions = {
        "q1":          payload.contributions_q1,
        "half_year":   payload.contributions_half_year,
        "nine_months": payload.contributions_nine_months,
        "year":        payload.contributions_year,
    }

    # Cap contributions at limit_factor * tax for each period
    tax_block = compute_tax_by_period(cum, rate, contributions)
    for period, row in tax_block.items():
        max_reduction = row["tax"] * float(limit_factor)
        if row["reduction"] > max_reduction:
            row["reduction"] = round(max_reduction, 2)
            row["payable"]   = round(row["tax"] - row["reduction"], 2)

    return DeclarationTaxResponse(
        cumulative=cum,
        tax=tax_block,
        rate=rate,
        has_employees=payload.has_employees,
        reduction_limit_pct=limit_pct,
    )


# ----------- Declaration generation --------------------------------------

_ENS_QUARTER_TO_PERIOD = {
    "q1":          {"line_020_key": "q1",          "line_040_key": None,          "line_070_key": None,        "line_100_key": None,        "period_code": "21", "pages": 4},
    "half_year":   {"line_020_key": "q1",          "line_040_key": "half_year",   "line_070_key": None,        "line_100_key": None,        "period_code": "31", "pages": 4},
    "nine_months": {"line_020_key": "q1",          "line_040_key": "half_year",   "line_070_key": "nine_months","line_100_key": None,        "period_code": "33", "pages": 4},
    "year":        {"line_020_key": "q1",          "line_040_key": "half_year",   "line_070_key": "nine_months","line_100_key": "year",      "period_code": "34", "pages": 4},
}


class DeclarationRequest(BaseModel):
    period: str  # "q1" | "half_year" | "nine_months" | "year"
    contributions_q1: float = 0
    contributions_half_year: float = 0
    contributions_nine_months: float = 0
    contributions_year: float = 0
    date_presented: Optional[str] = None  # "DD.MM.YYYY"


def _advance_diff(tax_block: Dict, prev_key: Optional[str], this_key: str) -> Decimal:
    """Разница накопленных к уплате сумм между соседними периодами.

    Положительная разница → «к уплате» (строки 020/040/070/100).
    Отрицательная разница → «к уменьшению» (строки 050/080/110) по модулю.
    """
    this_payable = Decimal(str(tax_block[this_key]["payable"]))
    if not prev_key:
        return this_payable
    prev_payable = Decimal(str(tax_block[prev_key]["payable"]))
    return this_payable - prev_payable


def _split_to_pay_reduce(diff: Decimal) -> (int, int):
    """Разделить разницу на пару (к уплате, к уменьшению)."""
    if diff >= 0:
        return int(diff), 0
    return 0, int(-diff)


@router.post("/declaration/{project_id}")
def generate_declaration(
    project_id: int,
    payload: DeclarationRequest,
    db: Session = Depends(get_db),
):
    """Generate filled declaration PDF + XLSX and return paths."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Проект не найден")
    if payload.period not in _ENS_QUARTER_TO_PERIOD:
        raise HTTPException(400, f"Неверный период: {payload.period}")

    # Revenue & tax
    rev = compute_quarterly_revenue(db, project_id)
    cum = rev["cumulative"]
    rate = float(project.tax_rate or 6.0)
    contributions = {
        "q1":          payload.contributions_q1,
        "half_year":   payload.contributions_half_year,
        "nine_months": payload.contributions_nine_months,
        "year":        payload.contributions_year,
    }
    limit_pct = 50 if project.has_employees else 100
    limit_factor = Decimal(limit_pct) / Decimal(100)
    tax_block = compute_tax_by_period(cum, rate, contributions)
    for period, row in tax_block.items():
        max_reduction = row["tax"] * float(limit_factor)
        if row["reduction"] > max_reduction:
            row["reduction"] = round(max_reduction, 2)
            row["payable"]   = round(row["tax"] - row["reduction"], 2)

    # Build Section 1.1 (advances / due per period, cumulative form)
    #   line_020 — авансовый платёж к уплате за Q1 (не может быть отрицательным,
    #              т.к. payable(Q1) ≥ 0)
    #   line_040 — авансовый платёж к уплате за полугодие;
    #   line_050 — к УМЕНЬШЕНИЮ за полугодие (если накопленный payable снизился)
    #   line_070 — авансовый платёж к уплате за 9 месяцев;
    #   line_080 — к УМЕНЬШЕНИЮ за 9 месяцев
    #   line_100 — налог к уплате за год;
    #   line_110 — к УМЕНЬШЕНИЮ за год
    #   line_101 — сумма патента к зачёту (для чистого УСН = 0)
    diff_q1   = _advance_diff(tax_block, None,          "q1")
    diff_h1   = _advance_diff(tax_block, "q1",          "half_year")
    diff_9m   = _advance_diff(tax_block, "half_year",   "nine_months")
    diff_year = _advance_diff(tax_block, "nine_months", "year")

    pay_020, _         = _split_to_pay_reduce(diff_q1)    # line_050 относится к полугодию
    pay_040, red_050   = _split_to_pay_reduce(diff_h1)
    pay_070, red_080   = _split_to_pay_reduce(diff_9m)
    pay_100, red_110   = _split_to_pay_reduce(diff_year)

    sec_1_1: Dict[str, Any] = {
        "line_020": pay_020,
        "line_040": pay_040,
        "line_050": red_050,
        "line_070": pay_070,
        "line_080": red_080,
        "line_100": pay_100,
        "line_110": red_110,
        "line_101": 0,
    }

    # Build Section 2.1.1
    sec_2_1_1: Dict[str, Any] = {
        "line_101": "2" if project.has_employees else "1",
        "line_110": int(Decimal(str(cum["q1"]))),
        "line_111": int(Decimal(str(cum["half_year"]))),
        "line_112": int(Decimal(str(cum["nine_months"]))),
        "line_113": int(Decimal(str(cum["year"]))),
        "line_120": rate, "line_121": rate, "line_122": rate, "line_123": rate,
        "line_130": int(Decimal(str(tax_block["q1"]["tax"]))),
        "line_131": int(Decimal(str(tax_block["half_year"]["tax"]))),
        "line_132": int(Decimal(str(tax_block["nine_months"]["tax"]))),
        "line_133": int(Decimal(str(tax_block["year"]["tax"]))),
        "line_140": int(Decimal(str(tax_block["q1"]["reduction"]))),
        "line_141": int(Decimal(str(tax_block["half_year"]["reduction"]))),
        "line_142": int(Decimal(str(tax_block["nine_months"]["reduction"]))),
        "line_143": int(Decimal(str(tax_block["year"]["reduction"]))),
    }

    project_data = {
        "inn":             project.inn,
        "tax_period_year": project.tax_period_year,
        "ifns_code":       project.ifns_code or "0000",
        "oktmo":           project.oktmo or "00000000",
        "fio":             project.fio,
        "phone":           "",
    }
    decl_data = {
        "date_presented": payload.date_presented or date.today().strftime("%d.%m.%Y"),
        "period_code":    _ENS_QUARTER_TO_PERIOD[payload.period]["period_code"],
        "section_1_1":    sec_1_1,
        "section_2_1_1":  sec_2_1_1,
    }

    # Для формы 2025 (приказ Минфина №58н) — формируем другую структуру:
    # section_1 (Раздел 1) и section_2 (Раздел 2) с годовыми итогами.
    # Строки 030/040/050 = инкрементальные авансовые платежи за Q1/H1/9M,
    # 060 = налог к доплате за год, 070 = налог к уменьшению за год.
    year_tax = int(Decimal(str(tax_block["year"]["tax"])))
    year_reduction = int(Decimal(str(tax_block["year"]["reduction"])))
    year_income = int(Decimal(str(cum["year"])))
    year_tax_base = year_income  # для объекта «Доходы» база = доход
    year_computed_tax = year_tax
    advances_sum = sec_1_1["line_020"] + sec_1_1["line_040"] - sec_1_1.get("line_050", 0) \
                 + sec_1_1["line_070"] - sec_1_1.get("line_080", 0)
    year_payable = int(Decimal(str(tax_block["year"]["payable"])))
    year_to_pay = max(0, year_payable - advances_sum)
    year_to_reduce = max(0, advances_sum - year_payable)

    decl_data["section_1"] = {
        "line_030": sec_1_1["line_020"],  # advance Q1
        "line_040": sec_1_1["line_040"],  # advance H1 (incremental)
        "line_050": sec_1_1["line_070"],  # advance 9M (incremental)
        "line_060": year_to_pay,
        "line_070": year_to_reduce,
    }
    decl_data["section_2"] = {
        "rate":     rate,
        "line_210": year_income,
        "line_240": year_tax_base,
        "line_260": year_computed_tax,
        "line_280": year_reduction,
    }

    # Fill Excel
    out_dir = Path(__file__).resolve().parent.parent.parent / "data" / "declarations"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    xlsx_name = f"declaration_{project_id}_{payload.period}_{stamp}.xlsx"
    pdf_name  = xlsx_name.replace(".xlsx", ".pdf")
    out_xlsx = out_dir / xlsx_name
    out_pdf  = out_dir / pdf_name

    try:
        template = get_template_for_year(project.tax_period_year)
        fill_declaration(template, out_xlsx, project_data, decl_data)
    except Exception as exc:
        raise HTTPException(500, f"Ошибка при заполнении XLSX: {exc}")

    # PDF формируем путём конвертации уже заполненного XLSX, чтобы визуально
    # получился тот же официальный бланк ФНС, что и в Excel.
    # Требует установленного LibreOffice (или Excel на Windows).
    pdf_ok = False
    pdf_error: Optional[str] = None
    try:
        convert_xlsx_to_pdf(out_xlsx, out_pdf)
        pdf_ok = True
    except XlsxToPdfError as exc:
        pdf_error = str(exc)
    except Exception as exc:
        pdf_error = f"PDF: {exc}"

    result = {
        "xlsx_url":      f"/api/wizard/download/{xlsx_name}",
        "cumulative":    cum,
        "tax":           tax_block,
        "section_1_1":   sec_1_1,
        "section_2_1_1": sec_2_1_1,
    }
    if pdf_ok:
        result["pdf_url"] = f"/api/wizard/download/{pdf_name}"
    else:
        result["pdf_url"] = None
        result["pdf_error"] = pdf_error
    return result


@router.get("/download/{filename}")
def download_file(filename: str):
    """Download a generated declaration file (xlsx or pdf)."""
    # sanity check
    if "/" in filename or "\\" in filename:
        raise HTTPException(400, "Некорректное имя файла")
    out_dir = Path(__file__).resolve().parent.parent.parent / "data" / "declarations"
    path = out_dir / filename
    if not path.exists():
        raise HTTPException(404, "Файл не найден")
    media = "application/pdf" if filename.endswith(".pdf") else \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(str(path), media_type=media, filename=filename)
