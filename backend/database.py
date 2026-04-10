"""
NSE Market Intelligence Platform - Database Layer
==================================================
Async SQLAlchemy setup with SQLite + aiosqlite.
WAL mode is enabled for concurrent read access during market hours.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings

logger = logging.getLogger(__name__)

_DB_URL = f"sqlite+aiosqlite:///{settings.resolved_db_path}"

engine: AsyncEngine = create_async_engine(
    _DB_URL,
    echo=False,
    future=True,
    # SQLite does not support pool_size / max_overflow in the traditional
    # sense, but StaticPool is the default for file-based SQLite with
    # async drivers.  We keep connect_args for PRAGMA setup.
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, _connection_record):
    """Enable WAL mode and other performance PRAGMAs on every new connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA busy_timeout = 5000;")
    cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a scoped async session.

    Usage::

        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_ctx() -> AsyncGenerator[AsyncSession, None]:
    """Standalone async context manager for non-FastAPI code (scheduler jobs, scripts).

    Usage::

        async with get_db_ctx() as db:
            result = await db.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables that don't exist yet.

    Safe to call on every startup (``checkfirst=True`` is the SQLAlchemy default).
    """
    from backend.models import Base  # noqa: F811 – deferred import to avoid circular deps

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables initialised at %s", settings.resolved_db_path)


async def close_db() -> None:
    """Dispose of the engine's connection pool (call at shutdown)."""
    await engine.dispose()
    logger.info("Database engine disposed.")
