"""Configuration for the FundBot application.

This module loads environment variables from a ``.env`` file via python-dotenv
and exposes a single ``settings`` instance with all configuration values.  The
``FINANCIER_TG_IDS`` environment variable is parsed into a list of integers.

Examples
--------

Set up a ``.env`` file in the project root with at least the following values::

    TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
    DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/fundbot
    FINANCIER_TG_IDS=123456789,987654321

The :class:`Settings` dataclass will read these values when imported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Immediately load environment variables from .env if present.  This happens at
# import time so that other modules can safely import ``settings`` without
# manually calling load_dotenv() again.
load_dotenv()


def _parse_financiers() -> list[int]:
    """Parse the ``FINANCIER_TG_IDS`` environment variable into a list of ints.

    Returns an empty list if the variable is empty or not set.  Any values
    that cannot be converted to integers are silently ignored.
    """
    raw = os.getenv("FINANCIER_TG_IDS", "").strip()
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            # ignore malformed IDs
            continue
    return out


@dataclass
class Settings:
    """Simple dataclass for accessing application configuration."""

    BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    FINANCIERS: list[int] = field(default_factory=_parse_financiers)
    # Maximum number of users to include in a single broadcast batch.  Telegram
    # imposes strict rate limits on bots; sending messages in batches with
    # pauses in between helps avoid hitting those limits.
    BATCH: int = int(os.getenv("BROADCAST_BATCH", "80"))


# Expose a single settings instance to be imported elsewhere.  Since the
# dataclass fields default to reading from environment variables, simply
# instantiating Settings will capture the current environment.
settings = Settings()
