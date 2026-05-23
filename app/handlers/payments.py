"""Handlers for payment-related callback queries.

Flow:
- A participant taps "Я перевёл" (``pay:<cid>:claim``) -> status becomes
  ``claimed`` and every financier is notified with a confirm button.
- The participant may undo while not yet confirmed (``pay:<cid>:unclaim``).
- A financier taps "Подтвердить получение" (``confirm:<cid>:<uid>``) ->
  status becomes ``confirmed`` and the participant is notified.
"""

from __future__ import annotations

import html
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from ..config import settings
from ..db import Session
from ..repo import claim_payment, unclaim_payment, confirm_payment, get_user, get_active_campaign
from ..keyboards import payment_kb, confirm_kb
from ..models import PAYMENT_NONE, PAYMENT_CLAIMED, PAYMENT_CONFIRMED


logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data == "noop")
async def noop_callback(query: CallbackQuery) -> None:
    await query.answer()


@router.callback_query(F.data.startswith("pay:"))
async def handle_payment_callback(query: CallbackQuery) -> None:
    """Participant claims or un-claims a payment."""
    try:
        _, camp_id_str, action = query.data.split(":")
        camp_id = int(camp_id_str)
    except Exception:
        await query.answer("Неверный формат данных.", show_alert=True)
        return

    async with Session() as db:
        if action == "claim":
            ok = await claim_payment(db, camp_id, query.from_user.id)
            new_status = PAYMENT_CLAIMED
        elif action == "unclaim":
            ok = await unclaim_payment(db, camp_id, query.from_user.id)
            new_status = PAYMENT_NONE
        else:
            await query.answer("Неизвестное действие.", show_alert=True)
            return

    if not ok:
        await query.answer("Не удалось обновить статус (возможно, оплата уже подтверждена).", show_alert=True)
        return

    await query.message.edit_reply_markup(reply_markup=payment_kb(camp_id, new_status))

    if action == "claim":
        await query.answer("Отмечено. Финансист подтвердит получение.")
        await _notify_financiers(query, camp_id)
    else:
        await query.answer("Отметка снята.")


async def _notify_financiers(query: CallbackQuery, camp_id: int) -> None:
    """Tell financiers that a participant reported a payment."""
    async with Session() as db:
        camp = await get_active_campaign(db)
        u = await get_user(db, query.from_user.id)
    if not camp or camp.id != camp_id:
        return
    name = (u.full_name if u and u.full_name else None) or query.from_user.full_name or str(query.from_user.id)
    text = (
        f"💸 <b>{html.escape(name)}</b> отметил оплату по сбору "
        f"«{html.escape(camp.title)}» ({camp.per_user_amount}₽).\n"
        "Подтвердите получение:"
    )
    for fin_id in settings.FINANCIERS:
        try:
            await query.bot.send_message(
                fin_id, text, reply_markup=confirm_kb(camp_id, query.from_user.id)
            )
        except Exception as exc:
            logger.warning("could not notify financier %s: %s", fin_id, exc)


@router.callback_query(F.data.startswith("confirm:"))
async def handle_confirm_callback(query: CallbackQuery) -> None:
    """Financier confirms receipt of a participant's payment."""
    if query.from_user.id not in set(settings.FINANCIERS):
        await query.answer("Только финансист может подтверждать оплату.", show_alert=True)
        return
    try:
        _, camp_id_str, uid_str = query.data.split(":")
        camp_id = int(camp_id_str)
        uid = int(uid_str)
    except Exception:
        await query.answer("Неверный формат данных.", show_alert=True)
        return

    async with Session() as db:
        ok = await confirm_payment(db, camp_id, uid)
        u = await get_user(db, uid)

    if not ok:
        await query.answer("Не удалось подтвердить (участник не найден).", show_alert=True)
        return

    name = (u.full_name if u and u.full_name else None) or str(uid)
    await query.message.edit_text(f"✅ Оплата подтверждена: {html.escape(name)}")
    await query.answer("Подтверждено.")
    try:
        await query.bot.send_message(uid, "✅ Ваша оплата подтверждена финансистом. Спасибо!")
    except Exception as exc:
        logger.warning("could not notify participant %s: %s", uid, exc)
