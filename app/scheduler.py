"""Background auto-reminder loop for active campaigns with a deadline.

Once per ``REMIND_INTERVAL_HOURS`` the loop checks the active campaign: if it
has a deadline and unconfirmed participants, it reminds them (at most once per
interval) and notifies financiers when the deadline has passed.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from .config import settings
from .db import Session
from .repo import get_active_campaign, list_outstanding, get_setting, mark_reminded
from .utils import broadcast

logger = logging.getLogger(__name__)

CHECK_EVERY_SECONDS = 3600  # how often the loop wakes up


def _interval_hours() -> int:
    try:
        return max(1, int(os.getenv("REMIND_INTERVAL_HOURS", "24")))
    except ValueError:
        return 24


async def _run_once(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    interval = timedelta(hours=_interval_hours())
    async with Session() as db:
        camp = await get_active_campaign(db)
        if not camp or not camp.due_date:
            return
        last = camp.last_reminded_at
        if last is not None and (now - last) < interval:
            return
        outstanding = await list_outstanding(db, camp.id)
        requisites = await get_setting(db, "requisites")
        if not outstanding:
            return
        title = html.escape(camp.title)
        per_user = camp.per_user_amount
        due_str = camp.due_date.strftime("%d.%m.%Y")
        overdue = now > camp.due_date
        await mark_reminded(db, camp.id)

    if overdue:
        text = (
            f"⚠️ Срок сбора <b>{title}</b> ({due_str}) истёк, а оплата ещё не подтверждена.\n"
            f"Пожалуйста, переведите {per_user}₽ и отметьте кнопкой в боте."
        )
    else:
        text = (
            f"⏰ Напоминание: сбор <b>{title}</b>, срок до {due_str}.\n"
            f"Переведите {per_user}₽ и отметьте кнопкой в боте."
        )
    if requisites:
        text += f"\nРеквизиты:\n{html.escape(requisites)}"

    sent = await broadcast(bot, outstanding, text)
    logger.info("auto-reminder: sent %d/%d for campaign %s", sent, len(outstanding), camp.id)

    if overdue and settings.FINANCIERS:
        note = f"⚠️ Срок сбора «{title}» истёк. Не подтверждено: {len(outstanding)}."
        await broadcast(bot, settings.FINANCIERS, note)


async def reminder_loop(bot: Bot) -> None:
    """Run the reminder check forever."""
    while True:
        try:
            await _run_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("auto-reminder loop error: %s", exc)
        await asyncio.sleep(CHECK_EVERY_SECONDS)
