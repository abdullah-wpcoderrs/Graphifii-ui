"""Phase 4 — project launch, sandbox status callback, and progress WebSocket.

Three pieces that share one state machine:

  POST /api/projects                      user starts an extraction
  POST /api/projects/{id}/cancel          user aborts one mid-flight
  POST /api/internal/projects/{id}/runs/{run_id}/status reports progress
  WS   /ws/projects/{id}                  the browser watches it happen

Progress is persisted on Project (progress_percent/status_message/...) and
the WebSocket polls that row rather than holding an in-memory pub/sub
registry. That is a deliberate trade: polling costs one indexed primary-key
lookup per second per watching client, and in exchange a client reconnecting
mid-extraction — or connecting to a different replica than the one that
handled the callback — sees correct state immediately. An in-process event
bus would be cheaper per tick but silently wrong the moment this service
runs more than one instance.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.config import get_settings
from graphify.server.crypto import decrypt
from graphify.server.db import get_db, get_session_factory
from graphify.server.models import (
    ExtractionCallbackEvent,
    ExtractionRun,
    ExtractionRunStatus,
    Project,
    ProjectStatus,
    SystemCredential,
    UsageEvent,
    User,
)
from graphify.server.run_service import (
    OPEN_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    callback_secret_matches,
    finish_run,
    project_from_run,
    transition_allowed,
)
from graphify.server.sandbox import (
    RailwayError,
    cancel_deployment_on_railway,
    clear_sandbox_variables_on_railway,
)
from graphify.server.sessions import (
    SESSION_COOKIE_NAME,
    get_current_user,
    read_session_user_id,
)
from graphify.server.usage import estimate_cost

logger = logging.getLogger("graphify.server.launch")

router = APIRouter(tags=["launch"])

# Terminal states — nothing further is streamed once a project reaches one.
_TERMINAL = {ProjectStatus.READY, ProjectStatus.FAILED}

_POLL_INTERVAL_SECONDS = 1.0
# Stop streaming a project that never terminates rather than holding the
# socket (and a DB session) open forever.
_MAX_STREAM_SECONDS = 60 * 30

_VALID_PROVIDERS = {"github", "gitlab", "gitbucket"}

# Serializes queue admission across app replicas so quotas and the
# per-repository current-run check cannot be raced by parallel requests.
_LAUNCH_ADVISORY_LOCK = 2_026_080_101

# Cap per uploaded artifact. A graph for a very large repo is a few MB; 256MB
# is generous while still bounding what one sandbox can write to disk.
_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024


class LaunchRequest(BaseModel):
    repo_full_name: str  # "owner/repository"
    repo_url: str
    provider: str = "github"
    default_branch: str = "main"


def _serialize_progress(project: Project) -> dict:
    return {
        "project_id": str(project.id),
        "run_id": str(project.current_run_id) if project.current_run_id else None,
        "status": project.status.value,
        "progress_percent": project.progress_percent,
        "message": project.status_message,
        "error": project.error_message,
        "graph_json_url": project.graph_json_url,
        "terminal": project.status in _TERMINAL,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


async def _active_llm_credential(db: AsyncSession) -> SystemCredential:
    """Pick the LLM credential the sandbox will use.

    There is no explicit "active provider" selector in the admin UI yet, so
    this takes the most recently updated configured credential. When such a
    selector is added, this is the single place that changes.
    """
    result = await db.execute(
        select(SystemCredential).order_by(SystemCredential.updated_at.desc()).limit(1)
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No LLM provider is configured — an administrator must add one "
                "before projects can be indexed"
            ),
        )
    return credential


def _decrypt_repo_token(user: User, provider: str) -> str | None:
    """The user's git token, needed inside the sandbox to clone private repos."""
    pairs = {
        "github": (user.github_access_token_ciphertext, user.github_access_token_iv),
        "gitlab": (user.gitlab_access_token_ciphertext, user.gitlab_access_token_iv),
        "gitbucket": (user.gitbucket_access_token_ciphertext, user.gitbucket_access_token_iv),
    }
    ciphertext, iv = pairs.get(provider, (None, None))
    if not ciphertext or not iv:
        return None
    return decrypt(ciphertext, iv)


@router.post("/api/projects")
async def launch_project(
    request: Request,
    payload: LaunchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if payload.provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"unknown provider {payload.provider!r}")

    settings = get_settings()
    if not settings.railway_configured:
        raise HTTPException(
            status_code=503, detail="Railway sandbox provisioning is not configured"
        )

    await db.execute(select(func.pg_advisory_xact_lock(_LAUNCH_ADVISORY_LOCK)))

    # Queue limits are enforced from trusted database state, not a client
    # counter. They cap both accidental storms and deliberate spend abuse.
    global_open = (
        await db.execute(
            select(func.count())
            .select_from(ExtractionRun)
            .where(ExtractionRun.status.in_(OPEN_RUN_STATUSES))
        )
    ).scalar_one()
    if global_open >= settings.max_queued_runs_global:
        raise HTTPException(status_code=429, detail="the extraction queue is full")

    user_open = (
        await db.execute(
            select(func.count())
            .select_from(ExtractionRun)
            .join(Project, Project.id == ExtractionRun.project_id)
            .where(Project.user_id == user.id, ExtractionRun.status.in_(OPEN_RUN_STATUSES))
        )
    ).scalar_one()
    if user_open >= settings.max_queued_runs_per_user:
        raise HTTPException(status_code=429, detail="too many extraction runs are queued")

    existing = (
        await db.execute(
            select(Project)
            .where(Project.user_id == user.id, Project.repo_name == payload.repo_full_name)
            .with_for_update()
        )
    ).scalar_one_or_none()

    # projects has a UNIQUE(user_id, repo_name) constraint, so a repo maps to
    # at most one project per user. Re-launching therefore reuses that row
    # rather than creating a second one — but never interrupts a run already
    # in flight, which would orphan the running Railway job.
    if existing is not None and existing.current_run_id is not None:
        current = await db.get(ExtractionRun, existing.current_run_id)
        if current is not None and current.status in OPEN_RUN_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="this repository is already queued or being indexed",
                headers={"X-Project-Id": str(existing.id)},
            )

    credential = await _active_llm_credential(db)

    if existing is not None:
        project = existing
        project.status = ProjectStatus.CLONING
        project.repo_url = payload.repo_url
        project.default_branch = payload.default_branch
        project.provider = payload.provider
    else:
        project = Project(
            user_id=user.id,
            repo_name=payload.repo_full_name,
            repo_url=payload.repo_url,
            default_branch=payload.default_branch,
            provider=payload.provider,
            status=ProjectStatus.CLONING,
        )
        db.add(project)

    await db.flush()

    run = ExtractionRun(
        project_id=project.id,
        status=ExtractionRunStatus.QUEUED,
        repo_url=payload.repo_url,
        repo_full_name=payload.repo_full_name,
        provider=payload.provider,
        default_branch=payload.default_branch,
        llm_provider=credential.provider,
        llm_model=credential.model,
        progress_percent=0,
        status_message="Queued for provisioning",
    )
    db.add(run)
    await db.flush()
    project.current_run_id = run.id

    # Reset progress from any previous run so the UI never shows stale
    # percentages or a prior failure's error text.
    project.progress_percent = 0
    project.status_message = "Queued for provisioning"
    project.error_message = None
    project.graph_json_url = None
    project.started_at = None
    project.finished_at = None
    await db.commit()
    await db.refresh(project)

    # Redis is delivery acceleration, not the source of truth. If enqueueing
    # fails, the committed QUEUED row is still discovered by the worker's
    # PostgreSQL fallback scan.
    run_queue = getattr(request.app.state, "run_queue", None)
    if run_queue is not None:
        try:
            await run_queue.enqueue(run.id)
        except Exception:  # noqa: BLE001 - durable DB fallback is intentional
            logger.exception("could not notify Redis about queued run %s", run.id)

    return _serialize_progress(project)


@router.post("/api/projects/{project_id}/cancel")
async def cancel_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = (
        await db.execute(
            select(Project)
            .where(Project.id == project_id, Project.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if project.current_run_id is None:
        raise HTTPException(status_code=409, detail="project has already finished")

    run = (
        await db.execute(
            select(ExtractionRun)
            .where(ExtractionRun.id == project.current_run_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None or run.status in TERMINAL_RUN_STATUSES:
        raise HTTPException(status_code=409, detail="project has already finished")

    deployment_id = run.deployment_id
    run.cancel_requested_at = datetime.now(timezone.utc)
    run.callback_secret_hash = None
    run.status_message = None
    if run.status is ExtractionRunStatus.QUEUED:
        finish_run(run, ExtractionRunStatus.CANCELED, "Canceled by user")
    else:
        # Keep active_slot while the remote deployment is being terminated;
        # otherwise another worker could overwrite its service variables.
        run.status = ExtractionRunStatus.CANCELED
        run.error_message = "Canceled by user"
        run.finished_at = datetime.now(timezone.utc)
    project_from_run(project, run)
    await db.commit()

    if deployment_id:
        try:
            await cancel_deployment_on_railway(deployment_id)
            await clear_sandbox_variables_on_railway()
        except RailwayError as exc:
            logger.error("Railway cancellation failed for run %s: %s", run.id, exc)
            raise HTTPException(
                status_code=502,
                detail=(
                    "the run was canceled locally but remote cleanup failed; "
                    "the extraction queue remains locked for safety"
                ),
            ) from exc

        async with get_session_factory()() as cleanup_db:
            persisted = (
                await cleanup_db.execute(
                    select(ExtractionRun).where(ExtractionRun.id == run.id).with_for_update()
                )
            ).scalar_one()
            persisted.active_slot = None
            persisted.lease_owner = None
            persisted.lease_expires_at = None
            await cleanup_db.commit()
    elif run.active_slot is not None:
        # STARTING with no id is the uncertain trigger window. Releasing the
        # slot could start a second deployment over the same mutable service.
        raise HTTPException(
            status_code=502,
            detail=(
                "the run was canceled locally but its deployment identity is unknown; "
                "the extraction queue remains locked for manual reconciliation"
            ),
        )

    return {"ok": True, "project_id": str(project_id), "run_id": str(run.id)}


class SandboxStatusUpdate(BaseModel):
    status: Literal["CLONING", "INDEXING", "READY", "FAILED"]
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    message: str | None = Field(default=None, max_length=512)
    error: str | None = Field(default=None, max_length=4096)


async def _authenticated_run(
    db: AsyncSession,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    secret: str,
) -> tuple[Project, ExtractionRun]:
    run = (
        await db.execute(
            select(ExtractionRun)
            .where(ExtractionRun.id == run_id, ExtractionRun.project_id == project_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if not callback_secret_matches(run, secret):
        raise HTTPException(status_code=401, detail="invalid run callback secret")
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if project.current_run_id != run.id:
        raise HTTPException(status_code=409, detail="stale run callback rejected")
    return project, run


async def _claim_callback_event(
    db: AsyncSession, run_id: uuid.UUID, event_id: uuid.UUID, event_type: str
) -> bool:
    statement = (
        insert(ExtractionCallbackEvent)
        .values(run_id=run_id, event_id=event_id, event_type=event_type)
        .on_conflict_do_nothing(index_elements=["run_id", "event_id"])
        .returning(ExtractionCallbackEvent.id)
    )
    return (await db.execute(statement)).scalar_one_or_none() is not None


@router.post("/api/internal/projects/{project_id}/runs/{run_id}/status")
async def sandbox_status_callback(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: SandboxStatusUpdate,
    x_sandbox_secret: str = Header(default=""),
    x_sandbox_event_id: uuid.UUID = Header(),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project, run = await _authenticated_run(db, project_id, run_id, x_sandbox_secret)
    if not await _claim_callback_event(db, run.id, x_sandbox_event_id, "status"):
        return {"ok": True, "duplicate": True}

    status = ExtractionRunStatus(payload.status)
    if not transition_allowed(run.status, status):
        raise HTTPException(
            status_code=409,
            detail=f"invalid run transition {run.status.value} -> {status.value}",
        )

    run.status = status
    run.lease_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=get_settings().run_worker_lease_seconds
    )
    if payload.progress_percent is not None:
        run.progress_percent = payload.progress_percent
    if payload.message is not None:
        run.status_message = payload.message
    if payload.error is not None:
        run.error_message = payload.error

    if status is ExtractionRunStatus.READY:
        try:
            await clear_sandbox_variables_on_railway()
        except RailwayError as exc:
            logger.error("Railway variable cleanup failed for run %s: %s", run.id, exc)
            raise HTTPException(status_code=502, detail="sandbox cleanup failed") from exc
        run.progress_percent = 100
        finish_run(run, status)
    elif status is ExtractionRunStatus.FAILED:
        try:
            await clear_sandbox_variables_on_railway()
        except RailwayError as exc:
            logger.error("Railway variable cleanup failed for run %s: %s", run.id, exc)
            raise HTTPException(status_code=502, detail="sandbox cleanup failed") from exc
        finish_run(run, status, payload.error or "Sandbox failed")

    project_from_run(project, run)
    await db.commit()
    return {"ok": True}


@router.post("/api/internal/projects/{project_id}/runs/{run_id}/artifacts")
async def upload_artifacts(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    graph: UploadFile = File(...),
    files: UploadFile | None = File(default=None),
    x_sandbox_secret: str = Header(default=""),
    x_sandbox_event_id: uuid.UUID = Header(),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive graph.json (+ optional files.json) from a finished sandbox run.

    The sandbox container is ephemeral, so anything it writes to its own disk
    disappears with it — the artifacts have to come back over the wire. Both
    land in one directory per project so routes/projects.py can keep reading
    files.json from alongside graph.json.

    Authenticated by a per-run secret. Artifacts land under the run id, so a
    stale process cannot overwrite another attempt's files.
    """
    settings = get_settings()
    project, run = await _authenticated_run(db, project_id, run_id, x_sandbox_secret)
    if run.status is not ExtractionRunStatus.INDEXING:
        raise HTTPException(status_code=409, detail="run is not accepting artifacts")
    if not await _claim_callback_event(db, run.id, x_sandbox_event_id, "artifacts"):
        return {"ok": True, "duplicate": True, "graph_json_url": run.graph_json_url}
    run.lease_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.run_worker_lease_seconds
    )

    target_dir = Path(settings.workspace_storage_dir).resolve() / str(project_id) / str(run_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    async def _save(upload: UploadFile, name: str) -> Path:
        destination = target_dir / name
        written = 0
        with destination.open("wb") as handle:
            # Streamed in chunks with a running cap: reading an untrusted
            # upload into memory whole is how a large graph takes the server
            # down.
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > _MAX_ARTIFACT_BYTES:
                    handle.close()
                    destination.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"{name} exceeds the {_MAX_ARTIFACT_BYTES // (1024 * 1024)}MB limit",
                    )
                handle.write(chunk)
        return destination

    graph_path = await _save(graph, "graph.json")
    if files is not None:
        await _save(files, "files.json")

    run.graph_json_url = str(graph_path)
    project_from_run(project, run)
    await db.commit()

    return {"ok": True, "graph_json_url": str(graph_path)}


class SandboxUsageReport(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=255)
    operation: Literal["extraction"] = "extraction"
    prompt_tokens: int = Field(default=0, ge=0, le=100_000_000)
    completion_tokens: int = Field(default=0, ge=0, le=100_000_000)


@router.post("/api/internal/projects/{project_id}/runs/{run_id}/usage")
async def sandbox_usage_report(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: SandboxUsageReport,
    x_sandbox_secret: str = Header(default=""),
    x_sandbox_event_id: uuid.UUID = Header(),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record the tokens a sandbox job actually spent on community labeling.

    The sandbox reads this from GRAPH_REPORT.md's "Token cost:" line (graphify
    already tracks it internally via label_communities()'s usage_out
    parameter; this just surfaces what was already being computed) and posts
    it here once, after labeling finishes. Same shared-secret auth as the
    status/artifacts callbacks — this is sandbox-to-backend traffic, not a
    browser request.

    Attributed to the project's owner so it rolls up into both the admin
    spend log and that user's own /api/usage view.
    """
    project, run = await _authenticated_run(db, project_id, run_id, x_sandbox_secret)
    if run.status not in {ExtractionRunStatus.CLONING, ExtractionRunStatus.INDEXING}:
        raise HTTPException(status_code=409, detail="run is not accepting usage events")
    if not await _claim_callback_event(db, run.id, x_sandbox_event_id, "usage"):
        return {"ok": True, "duplicate": True}
    run.lease_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=get_settings().run_worker_lease_seconds
    )

    db.add(
        UsageEvent(
            provider=payload.provider,
            model=payload.model,
            operation=payload.operation,
            prompt_tokens=payload.prompt_tokens,
            completion_tokens=payload.completion_tokens,
            user_id=project.user_id,
            project_id=project.id,
            run_id=run.id,
            cost_estimate=estimate_cost(
                payload.provider, payload.model, payload.prompt_tokens, payload.completion_tokens
            ),
        )
    )
    await db.commit()
    return {"ok": True}


async def _authenticate_ws(websocket: WebSocket, project_id: uuid.UUID) -> Project | None:
    """Resolve the session cookie and project ownership for a WebSocket.

    Returns None after closing the socket if auth fails. WebSockets cannot
    carry a normal 401 body, so failures are signalled with close codes:
    4401 unauthenticated, 4403 suspended, 4404 not found / not owned.
    """
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        await websocket.close(code=4401, reason="not authenticated")
        return None

    user_id = read_session_user_id(token)
    if user_id is None:
        await websocket.close(code=4401, reason="session expired or invalid")
        return None

    session_factory = get_session_factory()
    async with session_factory() as db:
        user = await db.get(User, user_id)
        if user is None:
            await websocket.close(code=4401, reason="user not found")
            return None
        if not user.is_active:
            await websocket.close(code=4403, reason="account is suspended")
            return None

        project = (
            await db.execute(
                select(Project).where(Project.id == project_id, Project.user_id == user_id)
            )
        ).scalar_one_or_none()

    # Deliberately identical treatment for "does not exist" and "belongs to
    # someone else" — otherwise this endpoint reports which project ids exist.
    if project is None:
        await websocket.close(code=4404, reason="project not found")
        return None

    return project


@router.websocket("/ws/projects/{project_id}")
async def project_progress_ws(websocket: WebSocket, project_id: uuid.UUID) -> None:
    await websocket.accept()

    project = await _authenticate_ws(websocket, project_id)
    if project is None:
        return

    # Send current state immediately: a client reconnecting mid-extraction
    # gets the truth on frame one instead of waiting for the next change.
    last_payload = _serialize_progress(project)
    await websocket.send_json(last_payload)
    if project.status in _TERMINAL:
        await websocket.close()
        return

    session_factory = get_session_factory()
    elapsed = 0.0

    try:
        while elapsed < _MAX_STREAM_SECONDS:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            elapsed += _POLL_INTERVAL_SECONDS

            # A fresh session per tick: a long-lived one would serve this
            # loop a cached snapshot and never observe the callback's commit.
            async with session_factory() as db:
                current = await db.get(Project, project_id)

            if current is None:
                await websocket.close(code=4404, reason="project deleted")
                return

            payload = _serialize_progress(current)
            # Only send on change — an idle extraction should not generate
            # one frame per second forever.
            if payload != last_payload:
                await websocket.send_json(payload)
                last_payload = payload

            if current.status in _TERMINAL:
                await websocket.close()
                return

        await websocket.close(code=4408, reason="progress stream timed out")
    except WebSocketDisconnect:
        # Normal: the user navigated away mid-provisioning.
        return
