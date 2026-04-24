"""
Table-based PDF renderer для декларации УСН и квитанций ФНС.

Альтернатива старому modules/declaration_filler/pdf_overlay_filler который
накладывал overlay поверх растровой/векторной подложки ФНС. Новый
рендерер рисует всё с нуля через reportlab Canvas + Table — нет
проблемы наложения текста на предзаполненные значения эталона.

Архитектура:
- declaration.py — рендер 4 страниц декларации КНД 1152017
- receipts.py — рендер квитанций КНД 1166002 и 1166007
- _cells.py — helpers для рисования клеточек и текста в них
"""
from .declaration import render_declaration_pdf
from .receipts import render_receipt_pages

__all__ = ["render_declaration_pdf", "render_receipt_pages"]
