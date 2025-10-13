"""Entry point for FundBot when running via polling.

This module initializes the database, configures the Telegram bot, and
registers all routers before starting the polling loop.

Previous versions of this file attempted to customise the underlying
aiohttp session in order to force IPv4 resolution on macOS.  As of
aiogram 3.7, passing a custom connector or session is no longer
supported, so the bot now uses aiogram's default session configuration.
"""

from __future__ import annotations

import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
# Note: We no longer import AiohttpSession because session customisation is unsupported in aiogram 3.7
from aiogram.fsm.storage.memory import MemoryStorage

from .config import settings
from .db import init_models
from .handlers import common, admin, payments


async def main() -> None:
    # Load environment variables from .env (redundant if already loaded in config)
    load_dotenv()
    # Validate critical configuration values
    if not settings.BOT_TOKEN or not settings.DATABASE_URL:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and DATABASE_URL must be set in .env"
        )
    # Initialise the database schema
    await init_models()
    # Create the bot; do not pass a custom session because aiogram 3.7 no longer accepts it
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(payments.router)
    print("Bot started (polling).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
