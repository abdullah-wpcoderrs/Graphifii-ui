"""Database readiness helpers shared by startup and the health endpoint."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from graphify.server.db import get_engine

logger = logging.getLogger("graphify.server.readiness")


async def probe_database() -> None:
    """Open a real connection and execute a trivial query.

    Constructing SQLAlchemy's engine does not touch the network. A readiness
    check must therefore acquire a connection and run a statement or it can
    report healthy while Neon is unreachable.
    """
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def database_is_ready() -> bool:
    """Return readiness without leaking connection details to the caller."""
    try:
        await probe_database()
    except Exception:  # noqa: BLE001 - every connection failure means not ready
        # A failed async connect can leave pool state tied to the failed
        # attempt. Dispose it so the next health request starts cleanly.
        await get_engine().dispose()
        return False
    return True


async def wait_for_database(
    *,
    max_attempts: int = 12,
    retry_seconds: float = 5.0,
) -> None:
    """Wait for a suspended or briefly unavailable Neon branch to accept SQL.

    Exhaustion raises so the container exits. The platform restart policy can
    then make a fresh attempt instead of leaving an API process alive that has
    never established database connectivity.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(1, max_attempts + 1):
        try:
            await probe_database()
            return
        except Exception as exc:  # noqa: BLE001 - database drivers vary
            # Make the retry a new connection attempt, not a checkout from a
            # pool whose first connect failed while a Neon branch was waking.
            await get_engine().dispose()
            if attempt == max_attempts:
                raise RuntimeError(
                    f"database unavailable after {max_attempts} startup attempts"
                ) from exc
            logger.warning(
                "database not ready (attempt %d/%d, %s); retrying in %.1fs",
                attempt,
                max_attempts,
                type(exc).__name__,
                retry_seconds,
            )
            await asyncio.sleep(retry_seconds)
