"""Inline keyboard utilities for FundBot."""

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


def payment_kb(campaign_id: int, has_paid: bool) -> InlineKeyboardMarkup:
    """Return an inline keyboard with a single button to mark/unmark payment."""
    kb = InlineKeyboardBuilder()
    if not has_paid:
        kb.button(text="✅ Я перевёл", callback_data=f"pay:{campaign_id}:mark")
    else:
        kb.button(text="↩️ Отменить", callback_data=f"pay:{campaign_id}:unmark")
    return kb.as_markup()
