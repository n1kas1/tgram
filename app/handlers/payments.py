"""Handlers for payment-related callback queries."""

from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

from ..db import Session
from ..repo import toggle_payment
from ..keyboards import payment_kb


router = Router()


@router.callback_query(F.data.startswith("pay:"))
async def handle_payment_callback(query: CallbackQuery) -> None:
    """Handle inline button clicks to mark or unmark a payment."""
    try:
        _, camp_id_str, action = query.data.split(":")
        camp_id = int(camp_id_str)
    except Exception:
        await query.answer("Неверный формат callback data.", show_alert=True)
        return
    mark = action == "mark"
    async with Session() as db:
        ok = await toggle_payment(db, camp_id, query.from_user.id, mark)
    if ok:
        await query.message.edit_reply_markup(reply_markup=payment_kb(camp_id, has_paid=mark))
        await query.answer("Статус обновлён.")
    else:
        await query.answer("Не удалось обновить статус.", show_alert=True)
