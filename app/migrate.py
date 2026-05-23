"""Lightweight, idempotent schema migration run at startup.

``Base.metadata.create_all`` creates missing *tables* but never alters existing
ones.  When upgrading a database that predates the payment-status / deadline /
requisites features, the new *columns* must be added.  This module performs
those additive, idempotent ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` steps
(PostgreSQL) and backfills the new ``status`` column from the legacy
``has_paid`` flag.  It is safe to run on every startup and on a fresh database.

Only PostgreSQL needs this in practice; on other dialects (e.g. SQLite used in
tests) a fresh ``create_all`` already produces the current schema, so the
migration is skipped.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

# (table, column definition) — added only if the column does not already exist.
_ADD_COLUMNS = [
    ("users", "tg_name VARCHAR(128)"),
    ("campaigns", "due_date TIMESTAMPTZ"),
    ("campaigns", "last_reminded_at TIMESTAMPTZ"),
    ("campaign_members", "status VARCHAR(16) NOT NULL DEFAULT 'none'"),
    ("campaign_members", "claimed_at TIMESTAMPTZ"),
    ("campaign_members", "confirmed_at TIMESTAMPTZ"),
]


async def run_migrations(conn: AsyncConnection) -> None:
    """Apply additive migrations. No-op on non-PostgreSQL dialects."""
    if conn.dialect.name != "postgresql":
        return

    for table, column_def in _ADD_COLUMNS:
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column_def}"))

    # Backfill status from the legacy boolean if it is still present.
    has_legacy = await conn.scalar(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'campaign_members' AND column_name = 'has_paid'"
    ))
    if has_legacy:
        await conn.execute(text(
            "UPDATE campaign_members "
            "SET status = 'confirmed', confirmed_at = paid_at "
            "WHERE has_paid = TRUE AND status = 'none'"
        ))
        logger.info("Backfilled payment status from legacy has_paid column.")
