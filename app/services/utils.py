"""Shim для `from app.services.utils import round_rub`."""
from modules.declaration_filler.utils import round_rub  # noqa: F401

__all__ = ["round_rub"]
