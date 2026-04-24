"""
Stub для legacy `from app.services import pdf_overlay`.

В EDO_COMPLETE этот модуль не используется — вместо него
modules.declaration_filler.pdf_overlay_filler.PdfOverlayFiller.
"""
def __getattr__(name):
    raise AttributeError(
        f"app.services.pdf_overlay.{name} недоступен в EDO_COMPLETE. "
        f"Используйте modules.declaration_filler.pdf_overlay_filler"
    )
