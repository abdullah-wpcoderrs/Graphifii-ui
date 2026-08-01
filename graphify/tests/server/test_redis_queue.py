from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from graphify.server.redis_queue import RedisRunQueue, RunQueueMessage
from graphify.server.run_worker import DispatchOutcome, run_queue_worker


class FakeRedis:
    def __init__(self) -> None:
        self.calls = []
        self.claimed = ["0-0", [], []]
        self.entries = []

    async def ping(self):
        self.calls.append(("ping",))

    async def xgroup_create(self, **kwargs):
        self.calls.append(("xgroup_create", kwargs))

    async def xadd(self, *args, **kwargs):
        self.calls.append(("xadd", args, kwargs))
        return "1-0"

    async def xautoclaim(self, *args, **kwargs):
        self.calls.append(("xautoclaim", args, kwargs))
        return self.claimed

    async def xreadgroup(self, **kwargs):
        self.calls.append(("xreadgroup", kwargs))
        return self.entries

    async def xack(self, *args):
        self.calls.append(("xack", args))

    async def aclose(self):
        self.calls.append(("aclose",))


def queue_with(client: FakeRedis) -> RedisRunQueue:
    return RedisRunQueue(
        "redis://unused",
        stream="runs",
        group="workers",
        block_ms=2_000,
        reclaim_idle_ms=60_000,
        max_length=10_000,
        client=client,
    )


async def test_queue_enqueues_only_the_immutable_run_id() -> None:
    client = FakeRedis()
    queue = queue_with(client)
    run_id = uuid.uuid4()

    assert await queue.enqueue(run_id) == "1-0"
    call = next(call for call in client.calls if call[0] == "xadd")
    assert call[1] == ("runs", {"run_id": str(run_id)})
    assert call[2] == {"maxlen": 10_000, "approximate": True}


async def test_queue_reclaims_abandoned_message_before_reading_new_work() -> None:
    client = FakeRedis()
    run_id = uuid.uuid4()
    client.claimed = ["0-0", [("7-0", {"run_id": str(run_id)})], []]
    queue = queue_with(client)

    message = await queue.read("worker-a")

    assert message == RunQueueMessage(stream_id="7-0", run_id=run_id)
    assert not any(call[0] == "xreadgroup" for call in client.calls)


async def test_queue_reads_new_consumer_group_message_and_acknowledges_it() -> None:
    client = FakeRedis()
    run_id = uuid.uuid4()
    client.entries = [["runs", [("8-0", {"run_id": str(run_id)})]]]
    queue = queue_with(client)

    message = await queue.read("worker-a")
    assert message is not None
    await queue.acknowledge(message.stream_id)

    assert message.run_id == run_id
    assert ("xack", ("runs", "workers", "8-0")) in client.calls


@pytest.mark.parametrize(
    "outcome,expected_acknowledgements",
    [
        (DispatchOutcome.ACKNOWLEDGE, ["9-0"]),
        (DispatchOutcome.RETRY, []),
        (DispatchOutcome.RETAIN, []),
    ],
)
async def test_worker_acknowledges_only_safely_completed_delivery(
    monkeypatch, outcome, expected_acknowledgements
) -> None:
    from graphify.server import run_worker

    run_id = uuid.uuid4()

    class OneMessageQueue:
        def __init__(self):
            self.reads = 0
            self.acknowledged = []

        async def read(self, _consumer):
            self.reads += 1
            if self.reads == 1:
                return RunQueueMessage("9-0", run_id)
            raise asyncio.CancelledError

        async def acknowledge(self, stream_id):
            self.acknowledged.append(stream_id)

    queue = OneMessageQueue()

    async def no_reconciliation():
        return False

    async def dispatch(_run_id, _worker_id):
        return outcome

    monkeypatch.setattr(run_worker, "get_settings", lambda: SimpleNamespace(run_worker_poll_seconds=1))
    monkeypatch.setattr(run_worker, "reconcile_expired_active_run", no_reconciliation)
    monkeypatch.setattr(run_worker, "dispatch_run", dispatch)

    with pytest.raises(asyncio.CancelledError):
        await run_queue_worker(queue)  # type: ignore[arg-type]

    assert queue.acknowledged == expected_acknowledgements


async def test_worker_scans_postgres_when_redis_disconnects(monkeypatch) -> None:
    from graphify.server import run_worker

    class DisconnectingQueue:
        def __init__(self):
            self.reads = 0

        async def read(self, _consumer):
            self.reads += 1
            if self.reads == 1:
                raise OSError("Redis disconnected")
            raise asyncio.CancelledError

    database_scans = []

    async def no_reconciliation():
        return False

    async def scan_database(_worker_id):
        database_scans.append(True)
        return False

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(run_worker, "get_settings", lambda: SimpleNamespace(run_worker_poll_seconds=1))
    monkeypatch.setattr(run_worker, "reconcile_expired_active_run", no_reconciliation)
    monkeypatch.setattr(run_worker, "dispatch_next_run", scan_database)
    monkeypatch.setattr(run_worker.asyncio, "sleep", no_sleep)

    with pytest.raises(asyncio.CancelledError):
        await run_queue_worker(DisconnectingQueue())  # type: ignore[arg-type]

    assert database_scans == [True]
