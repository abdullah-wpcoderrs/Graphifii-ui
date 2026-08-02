"""Database readiness checks for the unified API role."""

from __future__ import annotations

import pytest

from graphify.server import readiness


async def test_database_is_ready_requires_a_successful_probe(monkeypatch) -> None:
    async def successful_probe() -> None:
        return None

    monkeypatch.setattr(readiness, "probe_database", successful_probe)

    assert await readiness.database_is_ready() is True


async def test_database_is_not_ready_when_the_probe_fails(monkeypatch) -> None:
    disposed = []

    async def failed_probe() -> None:
        raise OSError("unreachable")

    class FakeEngine:
        async def dispose(self) -> None:
            disposed.append(True)

    monkeypatch.setattr(readiness, "probe_database", failed_probe)
    monkeypatch.setattr(readiness, "get_engine", lambda: FakeEngine())

    assert await readiness.database_is_ready() is False
    assert disposed == [True]


async def test_startup_retries_until_neon_is_ready(monkeypatch) -> None:
    attempts = 0
    sleeps: list[float] = []
    disposed = []

    async def eventually_ready() -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("branch is waking")

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    class FakeEngine:
        async def dispose(self) -> None:
            disposed.append(True)

    monkeypatch.setattr(readiness, "probe_database", eventually_ready)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(readiness, "get_engine", lambda: FakeEngine())

    await readiness.wait_for_database(max_attempts=3, retry_seconds=0.25)

    assert attempts == 3
    assert sleeps == [0.25, 0.25]
    assert disposed == [True, True]


async def test_startup_fails_after_bounded_retries(monkeypatch) -> None:
    attempts = 0
    disposed = []

    async def never_ready() -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("unreachable")

    async def fake_sleep(_seconds: float) -> None:
        return None

    class FakeEngine:
        async def dispose(self) -> None:
            disposed.append(True)

    monkeypatch.setattr(readiness, "probe_database", never_ready)
    monkeypatch.setattr(readiness.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(readiness, "get_engine", lambda: FakeEngine())

    with pytest.raises(RuntimeError, match="after 3 startup attempts"):
        await readiness.wait_for_database(max_attempts=3, retry_seconds=0)

    assert attempts == 3
    assert disposed == [True, True, True]


async def test_startup_rejects_an_empty_retry_budget() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await readiness.wait_for_database(max_attempts=0)
