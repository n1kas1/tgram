"""Entry point for FundBot when running via polling.

This module configures logging, initializes the database, seeds the surname
allowlist on first run, registers all routers, and starts the polling loop.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from .config import settings
from .db import init_models, Session, engine
from .repo import seed_allowed_names
from .seed_names import SEED_NAMES
from .handlers import common, admin, payments


logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not settings.BOT_TOKEN or not settings.DATABASE_URL:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and DATABASE_URL must be set in .env")
    if not settings.FINANCIERS:
        logger.warning("FINANCIER_TG_IDS is empty: financier commands will be unavailable.")

    await init_models()
    async with Session() as db:
        inserted = await seed_allowed_names(db, SEED_NAMES)
    if inserted:
        logger.info("Seeded %d allowed surnames.", inserted)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception("Unhandled error while processing update: %s", event.exception)
        return True

    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(payments.router)

    logger.info("Bot started (polling).")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()
        logger.info("Bot stopped; connections closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).info("Shutdown requested.")
