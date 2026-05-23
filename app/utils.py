"""Shared helpers for FundBot handlers."""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from .config import settings

logger = logging.getLogger(__name__)


async def broadcast(
    bot: Bot,
    user_ids: Iterable[int],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> int:
    """Send ``text`` to every id in ``user_ids`` with rate-limit handling.

    Messages are sent in batches (size from ``settings.BATCH``) with a short
    pause between batches to respect Telegram's limits.  ``TelegramRetryAfter``
    is honoured; other per-recipient errors (blocked bot, deleted account) are
    logged and skipped.  Returns the number of messages successfully sent.
    """
    ids = list(user_ids)
    sent = 0
    batch_size = max(1, settings.BATCH)
    for i, uid in enumerate(ids, start=1):
        try:
            await bot.send_message(uid, text, reply_markup=reply_markup)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(uid, text, reply_markup=reply_markup)
                sent += 1
            except Exception as exc:
                logger.warning("broadcast: failed to deliver to %s after retry: %s", uid, exc)
        except Exception as exc:
            logger.warning("broadcast: failed to deliver to %s: %s", uid, exc)
        if i % batch_size == 0:
            await asyncio.sleep(0.5)
    return sent
