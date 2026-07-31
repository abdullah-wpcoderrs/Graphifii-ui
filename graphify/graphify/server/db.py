"""Async SQLAlchemy engine/session setup.

Expects DATABASE_URL to use the "postgresql+psycopg://" scheme so
create_async_engine selects psycopg3's native async support (works against
Neon's pooled connection endpoint without a separate connection pooler).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from graphify.server.config import get_settings


class Base(DeclarativeBase):
    pass


def _build_engine():
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a request-scoped session."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
