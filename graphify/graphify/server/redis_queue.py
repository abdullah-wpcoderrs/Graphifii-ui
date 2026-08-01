"""Redis Streams delivery for extraction-run IDs.

PostgreSQL remains the source of truth for run state and mutual exclusion.
Redis only provides immediate, durable delivery to workers; a database scan
remains the recovery path when Redis is unavailable or a notification is lost.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

logger = logging.getLogger("graphify.server.redis_queue")


@dataclass(frozen=True)
class RunQueueMessage:
    stream_id: str
    run_id: uuid.UUID | None


class RedisRunQueue:
    def __init__(
        self,
        url: str,
        *,
        stream: str,
        group: str,
        block_ms: int,
        reclaim_idle_ms: int,
        max_length: int,
        client: Any | None = None,
    ) -> None:
        self.stream = stream
        self.group = group
        self.block_ms = block_ms
        self.reclaim_idle_ms = reclaim_idle_ms
        self.max_length = max_length
        self._client = client or Redis.from_url(
            url,
            decode_responses=True,
            health_check_interval=30,
            socket_connect_timeout=2,
            socket_timeout=max(5.0, block_ms / 1_000 + 2.0),
            retry_on_timeout=False,
        )

    async def start(self) -> None:
        """Connect and create the consumer group once, safely across replicas."""
        await self._client.ping()
        try:
            await self._client.xgroup_create(
                name=self.stream,
                groupname=self.group,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def close(self) -> None:
        await self._client.aclose()

    async def enqueue(self, run_id: uuid.UUID) -> str:
        return str(
            await self._client.xadd(
                self.stream,
                {"run_id": str(run_id)},
                maxlen=self.max_length,
                approximate=True,
            )
        )

    @staticmethod
    def _message(stream_id: Any, fields: Any) -> RunQueueMessage:
        if isinstance(stream_id, bytes):
            stream_id = stream_id.decode("utf-8", errors="replace")
        raw_run_id = fields.get("run_id", fields.get(b"run_id", ""))
        if isinstance(raw_run_id, bytes):
            raw_run_id = raw_run_id.decode("utf-8", errors="replace")
        try:
            run_id = uuid.UUID(raw_run_id)
        except (TypeError, ValueError):
            logger.error("Redis run queue contains invalid run_id at %s", stream_id)
            run_id = None
        return RunQueueMessage(stream_id=str(stream_id), run_id=run_id)

    async def read(self, consumer: str) -> RunQueueMessage | None:
        """Reclaim one abandoned delivery, otherwise block for one new item."""
        claimed: Any = await self._client.xautoclaim(
            self.stream,
            self.group,
            consumer,
            min_idle_time=self.reclaim_idle_ms,
            start_id="0-0",
            count=1,
        )
        claimed_messages = claimed[1] if len(claimed) > 1 else []
        if claimed_messages:
            stream_id, fields = claimed_messages[0]
            return self._message(stream_id, fields)

        entries: Any = await self._client.xreadgroup(
            groupname=self.group,
            consumername=consumer,
            streams={self.stream: ">"},
            count=1,
            block=self.block_ms,
        )
        if not entries:
            return None
        _stream_name, messages = entries[0]
        if not messages:
            return None
        stream_id, fields = messages[0]
        return self._message(stream_id, fields)

    async def acknowledge(self, stream_id: str) -> None:
        await self._client.xack(self.stream, self.group, stream_id)


def build_redis_run_queue(settings: Any) -> RedisRunQueue | None:
    if not settings.redis_url:
        return None
    return RedisRunQueue(
        settings.redis_url,
        stream=settings.redis_run_queue_stream,
        group=settings.redis_run_queue_group,
        block_ms=settings.redis_run_queue_block_ms,
        reclaim_idle_ms=settings.redis_run_queue_reclaim_seconds * 1_000,
        max_length=settings.redis_run_queue_max_length,
    )
