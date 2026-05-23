"""Inline keyboard utilities for FundBot."""

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

from .models import PAYMENT_NONE, PAYMENT_CLAIMED, PAYMENT_CONFIRMED


def payment_kb(campaign_id: int, status: str) -> InlineKeyboardMarkup:
    """Keyboard shown to a participant for their payment, based on ``status``."""
    kb = InlineKeyboardBuilder()
    if status == PAYMENT_CONFIRMED:
        kb.button(text="✅ Оплата подтверждена", callback_data="noop")
    elif status == PAYMENT_CLAIMED:
        kb.button(text="↩️ Отменить (ожидает подтверждения)", callback_data=f"pay:{campaign_id}:unclaim")
    else:
        kb.button(text="✅ Я перевёл", callback_data=f"pay:{campaign_id}:claim")
    return kb.as_markup()


def confirm_kb(campaign_id: int, user_id: int) -> InlineKeyboardMarkup:
    """Keyboard shown to a financier to confirm receipt of a payment."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить получение", callback_data=f"confirm:{campaign_id}:{user_id}")
    return kb.as_markup()
