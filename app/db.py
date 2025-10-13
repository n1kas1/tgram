"""Database connection setup for FundBot.

This module exposes a global SQLAlchemy async engine and session factory.
The engine uses the ``asyncpg`` driver and is configured to automatically
ping the database before each checkout to prevent broken connections.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from .config import settings
from .models import Base

# Create the async engine using the DATABASE_URL from settings.  We set
# ``echo=False`` to suppress verbose SQL logging and ``pool_pre_ping=True`` to
# ensure stale connections are detected and refreshed automatically.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    future=True,
)

# Each handler/request should obtain its own session instance.  The
# ``expire_on_commit=False`` flag ensures objects remain usable after the
# transaction commits.
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_models() -> None:
    """Create all database tables if they do not already exist.

    This function should be called once at application startup.  If you later
    migrate away from ``create_all`` in favour of Alembic migrations, you can
    remove or modify this function accordingly.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
