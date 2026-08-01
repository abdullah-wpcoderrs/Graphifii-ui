"""Database-backed dispatcher for the singleton Railway sandbox service."""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from graphify.server.config import get_settings
from graphify.server.crypto import decrypt
from graphify.server.db import get_session_factory
from graphify.server.token_refresh import get_valid_access_token
from graphify.server.models import (
    ExtractionRun,
    ExtractionRunStatus,
    Project,
    SystemCredential,
    User,
)
from graphify.server.run_service import (
    ACTIVE_RUN_STATUSES,
    finish_run,
    hash_callback_secret,
    new_callback_secret,
    project_from_run,
)
from graphify.server.redis_queue import RedisRunQueue, build_redis_run_queue
from graphify.server.sandbox import (
    RailwayError,
    RailwayLaunchUncertainError,
    cancel_deployment_on_railway,
    clear_sandbox_variables_on_railway,
    launch_project_on_railway,
)

logger = logging.getLogger("graphify.server.run_worker")


class DispatchOutcome(str, Enum):
    ACKNOWLEDGE = "acknowledge"
    RETRY = "retry"
    RETAIN = "retain"


def _worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


async def _claim_run(
    worker_id: str, run_id: uuid.UUID | None = None
) -> tuple[uuid.UUID, str] | None:
    settings = get_settings()
    session_factory = get_session_factory()
    callback_secret = new_callback_secret()
    now = datetime.now(timezone.utc)

    async with session_factory() as db:
        query = select(ExtractionRun).where(
            ExtractionRun.status == ExtractionRunStatus.QUEUED
        )
        if run_id is not None:
            query = query.where(ExtractionRun.id == run_id)
        else:
            query = query.order_by(ExtractionRun.created_at, ExtractionRun.id)
        run = (
            await db.execute(query.with_for_update(skip_locked=True).limit(1))
        ).scalar_one_or_none()
        if run is None:
            return None

        run.status = ExtractionRunStatus.STARTING
        run.active_slot = 1
        run.callback_secret_hash = hash_callback_secret(callback_secret)
        run.lease_owner = worker_id
        run.lease_expires_at = now + timedelta(seconds=settings.run_worker_lease_seconds)
        run.started_at = now
        run.status_message = "Sandbox starting"
        try:
            await db.commit()
        except IntegrityError:
            # Another replica owns active_slot=1. The queued row remains
            # untouched after rollback and will be retried later.
            await db.rollback()
            return None
        return run.id, callback_secret


async def _claim_next_run(worker_id: str) -> tuple[uuid.UUID, str] | None:
    return await _claim_run(worker_id)


async def _load_launch_inputs(run_id: uuid.UUID):
    session_factory = get_session_factory()
    async with session_factory() as db:
        run = await db.get(ExtractionRun, run_id)
        if run is None or run.status is not ExtractionRunStatus.STARTING:
            return None
        project = await db.get(Project, run.project_id)
        if project is None or project.current_run_id != run.id:
            return None
        user = await db.get(User, project.user_id)
        credential = (
            await db.execute(
                select(SystemCredential).where(SystemCredential.provider == run.llm_provider)
            )
        ).scalar_one_or_none()
        if user is None or credential is None:
            return None

        # get_valid_access_token refreshes an expired GitHub/GitLab token in
        # place (persisting the rotation via this same `db` session) before
        # a launch is allowed to fail on a stale token it didn't need to.
        repo_token = await get_valid_access_token(user, run.provider, db)
        return {
            "project_id": str(project.id),
            "run_id": str(run.id),
            "repo_url": run.repo_url,
            "default_branch": run.default_branch,
            "active_llm_provider": credential.provider,
            "active_llm_key": decrypt(credential.key_ciphertext, credential.key_iv),
            "repo_token": repo_token,
        }


async def _mark_launch_failed(run_id: uuid.UUID, message: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        run = (
            await db.execute(
                select(ExtractionRun).where(ExtractionRun.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if run is None or run.status not in ACTIVE_RUN_STATUSES:
            return
        finish_run(run, ExtractionRunStatus.FAILED, message)
        project = await db.get(Project, run.project_id)
        if project is not None:
            project_from_run(project, run)
        await db.commit()


async def _release_canceled_run(run_id: uuid.UUID) -> None:
    """Release the global slot only after remote cancellation and cleanup."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        run = (
            await db.execute(
                select(ExtractionRun).where(ExtractionRun.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if run is None or run.status is not ExtractionRunStatus.CANCELED:
            return
        run.active_slot = None
        run.lease_owner = None
        run.lease_expires_at = None
        await db.commit()


async def _dispatch_claimed(claimed: tuple[uuid.UUID, str]) -> DispatchOutcome:
    run_id, callback_secret = claimed
    try:
        inputs = await _load_launch_inputs(run_id)
    except Exception:  # noqa: BLE001 - no external launch has happened yet
        logger.exception("could not load immutable launch inputs for run %s", run_id)
        await _mark_launch_failed(run_id, "Run inputs could not be loaded")
        return DispatchOutcome.ACKNOWLEDGE
    if inputs is None:
        await _mark_launch_failed(run_id, "Run inputs are no longer available")
        return DispatchOutcome.ACKNOWLEDGE

    try:
        result = await launch_project_on_railway(**inputs, callback_secret=callback_secret)
        deployment_id = str(result["id"])
    except RailwayLaunchUncertainError:
        # Do not release active_slot: a deployment may be running with the
        # just-written variables. Availability yields to cross-run isolation.
        logger.critical(
            "Railway launch outcome is uncertain for run %s; queue remains fail-closed",
            run_id,
            exc_info=True,
        )
        return DispatchOutcome.RETAIN
    except RailwayError:
        logger.exception("Railway launch failed for run %s", run_id)
        try:
            await clear_sandbox_variables_on_railway()
        except RailwayError:
            logger.critical(
                "could not clear Railway variables for failed run %s; queue remains fail-closed",
                run_id,
                exc_info=True,
            )
            return DispatchOutcome.RETAIN
        await _mark_launch_failed(run_id, "Could not start the extraction sandbox")
        return DispatchOutcome.ACKNOWLEDGE

    cancel_after_launch = False
    session_factory = get_session_factory()
    async with session_factory() as db:
        run = (
            await db.execute(
                select(ExtractionRun).where(ExtractionRun.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if run is None or run.status is ExtractionRunStatus.CANCELED:
            cancel_after_launch = True
        elif run.status in {
            ExtractionRunStatus.STARTING,
            ExtractionRunStatus.CLONING,
            ExtractionRunStatus.INDEXING,
            ExtractionRunStatus.READY,
            ExtractionRunStatus.FAILED,
        }:
            run.deployment_id = deployment_id
            if run.status is ExtractionRunStatus.STARTING:
                run.status = ExtractionRunStatus.CLONING
                run.progress_percent = 0
                run.status_message = "Sandbox starting"
            project = await db.get(Project, run.project_id)
            if project is not None:
                project_from_run(project, run)
            await db.commit()
        else:
            cancel_after_launch = True

    if cancel_after_launch:
        try:
            await cancel_deployment_on_railway(deployment_id)
            await clear_sandbox_variables_on_railway()
        except RailwayError:
            logger.exception(
                "could not cancel or clean deployment %s after concurrent run cancellation",
                deployment_id,
            )
            return DispatchOutcome.RETAIN
        await _release_canceled_run(run_id)
    return DispatchOutcome.ACKNOWLEDGE


async def _unclaimed_delivery_outcome(run_id: uuid.UUID) -> DispatchOutcome:
    """Decide whether a redelivered stream item is complete or must wait."""
    session_factory = get_session_factory()
    async with session_factory() as db:
        run = await db.get(ExtractionRun, run_id)
        if run is None or run.status in {
            ExtractionRunStatus.READY,
            ExtractionRunStatus.FAILED,
            ExtractionRunStatus.CANCELED,
        }:
            return DispatchOutcome.ACKNOWLEDGE
        if run.deployment_id:
            return DispatchOutcome.ACKNOWLEDGE
        if run.status is ExtractionRunStatus.QUEUED:
            return DispatchOutcome.RETRY
        # STARTING/CLONING/INDEXING without an exact deployment id is the
        # uncertain trigger window. Never acknowledge or launch it again.
        return DispatchOutcome.RETAIN


async def dispatch_run(run_id: uuid.UUID, worker_id: str) -> DispatchOutcome:
    claimed = await _claim_run(worker_id, run_id)
    if claimed is None:
        return await _unclaimed_delivery_outcome(run_id)
    return await _dispatch_claimed(claimed)


async def dispatch_next_run(worker_id: str) -> bool:
    """PostgreSQL fallback for deployments without Redis or missed messages."""
    claimed = await _claim_next_run(worker_id)
    if claimed is None:
        return False
    await _dispatch_claimed(claimed)
    return True


async def reconcile_expired_active_run() -> bool:
    """Stop and fail a leased deployment before releasing the global slot.

    A STARTING run without a persisted deployment id stays fail-closed: the
    process may have crashed in the narrow post-trigger/pre-commit window, so
    starting another run could overwrite a still-running job's variables.
    """
    now = datetime.now(timezone.utc)
    session_factory = get_session_factory()
    async with session_factory() as db:
        run = (
            await db.execute(
                select(ExtractionRun)
                .where(
                    ExtractionRun.active_slot == 1,
                    ExtractionRun.lease_expires_at.is_not(None),
                    ExtractionRun.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if run is None:
            return False
        deployment_id = run.deployment_id
        run_id = run.id

    if not deployment_id:
        logger.critical(
            "run %s lease expired before deployment correlation; queue remains fail-closed",
            run_id,
        )
        return False

    try:
        await cancel_deployment_on_railway(deployment_id)
        await clear_sandbox_variables_on_railway()
    except RailwayError:
        logger.exception("could not reconcile expired Railway deployment %s", deployment_id)
        return False

    await _mark_launch_failed(run_id, "Sandbox lease expired and the deployment was stopped")
    return True


async def run_queue_worker(run_queue: RedisRunQueue | None = None) -> None:
    settings = get_settings()
    worker_id = _worker_id()
    logger.info(
        "extraction dispatcher started as %s (%s)",
        worker_id,
        "Redis Streams + PostgreSQL fallback" if run_queue else "PostgreSQL polling",
    )
    try:
        while True:
            try:
                await reconcile_expired_active_run()
                if run_queue is None:
                    await dispatch_next_run(worker_id)
                    await asyncio.sleep(settings.run_worker_poll_seconds)
                    continue

                try:
                    message = await run_queue.read(worker_id)
                except Exception:  # noqa: BLE001 - Redis may recover independently
                    logger.exception("Redis run queue unavailable; scanning PostgreSQL")
                    await dispatch_next_run(worker_id)
                    await asyncio.sleep(settings.run_worker_poll_seconds)
                    continue
                if message is None:
                    # The transactional run row is authoritative. This scan
                    # recovers a commit whose Redis notification failed.
                    await dispatch_next_run(worker_id)
                    continue
                if message.run_id is None:
                    await run_queue.acknowledge(message.stream_id)
                    continue

                logger.info(
                    "received extraction run %s from Redis entry %s",
                    message.run_id,
                    message.stream_id,
                )
                outcome = await dispatch_run(message.run_id, worker_id)
                if outcome is DispatchOutcome.ACKNOWLEDGE:
                    await run_queue.acknowledge(message.stream_id)
            except Exception:  # noqa: BLE001 - keep the durable worker alive
                # Any run claimed before an unexpected failure retains its
                # active slot and lease, so reconciliation remains fail-closed.
                logger.exception("unexpected extraction dispatcher failure")
                await asyncio.sleep(settings.run_worker_poll_seconds)
    except asyncio.CancelledError:
        logger.info("extraction dispatcher %s stopping", worker_id)
        raise


async def _run_dedicated_worker() -> None:
    settings = get_settings()
    run_queue = build_redis_run_queue(settings)
    if run_queue is not None:
        try:
            await run_queue.start()
        except Exception:  # noqa: BLE001 - retain PostgreSQL recovery mode
            logger.exception("Redis unavailable; dedicated worker using PostgreSQL polling")
            await run_queue.close()
            run_queue = None
    try:
        await run_queue_worker(run_queue)
    finally:
        if run_queue is not None:
            await run_queue.close()


def run() -> None:
    """CLI entrypoint for the dedicated Railway worker service."""
    asyncio.run(_run_dedicated_worker())
