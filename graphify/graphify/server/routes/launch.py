"""Phase 4 — project launch, sandbox status callback, and progress WebSocket.

Three pieces that share one state machine:

  POST /api/projects                      user starts an extraction
  POST /api/projects/{id}/cancel          user aborts one mid-flight
  POST /api/internal/projects/{id}/status the sandbox job reports progress
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
import hmac
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.config import get_settings
from graphify.server.crypto import decrypt
from graphify.server.db import get_db, get_session_factory
from graphify.server.models import Project, ProjectStatus, SystemCredential, User
from graphify.server.sandbox import (
    RailwayError,
    RailwayNotConfiguredError,
    launch_project_on_railway,
)
from graphify.server.sessions import (
    SESSION_COOKIE_NAME,
    get_current_user,
    read_session_user_id,
)
from graphify.server.usage import record_usage

logger = logging.getLogger("graphify.server.launch")

router = APIRouter(tags=["launch"])

# Terminal states — nothing further is streamed once a project reaches one.
_TERMINAL = {ProjectStatus.READY, ProjectStatus.FAILED}
_IN_FLIGHT = {ProjectStatus.CLONING, ProjectStatus.INDEXING}

_POLL_INTERVAL_SECONDS = 1.0
# Stop streaming a project that never terminates rather than holding the
# socket (and a DB session) open forever.
_MAX_STREAM_SECONDS = 60 * 30

_VALID_PROVIDERS = {"github", "gitlab", "gitbucket"}

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
    payload: LaunchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if payload.provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"unknown provider {payload.provider!r}")

    existing = (
        await db.execute(
            select(Project).where(
                Project.user_id == user.id, Project.repo_name == payload.repo_full_name
            )
        )
    ).scalar_one_or_none()

    # projects has a UNIQUE(user_id, repo_name) constraint, so a repo maps to
    # at most one project per user. Re-launching therefore reuses that row
    # rather than creating a second one — but never interrupts a run already
    # in flight, which would orphan the running Railway job.
    if existing is not None and existing.status in _IN_FLIGHT:
        raise HTTPException(
            status_code=409,
            detail="this repository is already being indexed",
            headers={"X-Project-Id": str(existing.id)},
        )

    credential = await _active_llm_credential(db)
    llm_key = decrypt(credential.key_ciphertext, credential.key_iv)
    repo_token = _decrypt_repo_token(user, payload.provider)

    if existing is not None:
        project = existing
        project.status = ProjectStatus.CLONING
        project.repo_url = payload.repo_url
        project.default_branch = payload.default_branch
    else:
        project = Project(
            user_id=user.id,
            repo_name=payload.repo_full_name,
            repo_url=payload.repo_url,
            default_branch=payload.default_branch,
            status=ProjectStatus.CLONING,
        )
        db.add(project)

    # Reset progress from any previous run so the UI never shows stale
    # percentages or a prior failure's error text.
    project.progress_percent = 0
    project.status_message = "Queued for provisioning"
    project.error_message = None
    project.graph_json_url = None
    project.started_at = datetime.now(timezone.utc)
    project.finished_at = None

    # Commit before calling Railway so the project id exists for the job's
    # callback URL, and so a Railway timeout cannot lose the row entirely.
    await db.commit()
    await db.refresh(project)

    try:
        result = await launch_project_on_railway(
            project_id=str(project.id),
            repo_url=payload.repo_url,
            active_llm_provider=credential.provider,
            active_llm_key=llm_key,
            repo_token=repo_token,
        )
    except RailwayNotConfiguredError as exc:
        project.status = ProjectStatus.FAILED
        project.error_message = str(exc)
        project.finished_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RailwayError as exc:
        logger.error("Railway launch failed for project %s: %s", project.id, exc)
        project.status = ProjectStatus.FAILED
        project.error_message = "Could not start the extraction sandbox"
        project.finished_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=502, detail="Could not start the extraction sandbox") from exc

    project.sandbox_id = str(result.get("id") or "") or None
    project.status_message = "Sandbox starting"
    await db.commit()
    await db.refresh(project)

    return _serialize_progress(project)


@router.post("/api/projects/{project_id}/cancel")
async def cancel_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = (
        await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user.id)
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    if project.status in _TERMINAL:
        raise HTTPException(status_code=409, detail="project has already finished")

    # Marks the project failed so the UI stops waiting. The Railway job is
    # not torn down here — sandbox teardown is Phase 7 scope; the job will
    # run to completion and its callback will be ignored (see below).
    project.status = ProjectStatus.FAILED
    project.error_message = "Canceled by user"
    project.status_message = None
    project.finished_at = datetime.now(timezone.utc)
    await db.commit()

    return {"ok": True, "project_id": str(project_id)}


class SandboxStatusUpdate(BaseModel):
    status: str  # CLONING | INDEXING | READY | FAILED
    progress_percent: int | None = None
    message: str | None = None
    error: str | None = None
    graph_json_url: str | None = None


@router.post("/api/internal/projects/{project_id}/status")
async def sandbox_status_callback(
    project_id: uuid.UUID,
    payload: SandboxStatusUpdate,
    x_sandbox_secret: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Progress callback for the sandbox job.

    Authenticated by a shared secret, not a user session — the caller is a
    Railway container, not a browser. Without this check anyone could drive
    any project to READY and point graph_json_url at a URL of their choosing,
    which the workspace would then fetch and render.
    """
    settings = get_settings()
    if not settings.sandbox_callback_secret:
        raise HTTPException(status_code=503, detail="sandbox callbacks are not configured")

    # compare_digest: a plain == leaks the secret one byte at a time to a
    # caller who can measure response timing.
    if not hmac.compare_digest(x_sandbox_secret, settings.sandbox_callback_secret):
        raise HTTPException(status_code=401, detail="invalid sandbox secret")

    try:
        status = ProjectStatus(payload.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown status {payload.status!r}") from None

    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    # A canceled or already-finished project ignores late callbacks, so a job
    # that keeps running after cancellation cannot resurrect it.
    if project.status in _TERMINAL:
        return {"ok": True, "ignored": "project already in a terminal state"}

    project.status = status
    if payload.progress_percent is not None:
        project.progress_percent = max(0, min(100, payload.progress_percent))
    if payload.message is not None:
        project.status_message = payload.message
    if payload.error is not None:
        project.error_message = payload.error
    if payload.graph_json_url is not None:
        project.graph_json_url = payload.graph_json_url

    if status is ProjectStatus.READY:
        project.progress_percent = 100
        project.finished_at = datetime.now(timezone.utc)
    elif status is ProjectStatus.FAILED:
        project.finished_at = datetime.now(timezone.utc)

    await db.commit()
    return {"ok": True}


@router.post("/api/internal/projects/{project_id}/artifacts")
async def upload_artifacts(
    project_id: uuid.UUID,
    graph: UploadFile = File(...),
    files: UploadFile | None = File(default=None),
    x_sandbox_secret: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive graph.json (+ optional files.json) from a finished sandbox run.

    The sandbox container is ephemeral, so anything it writes to its own disk
    disappears with it — the artifacts have to come back over the wire. Both
    land in one directory per project so routes/projects.py can keep reading
    files.json from alongside graph.json.

    Authenticated by the same shared secret as the status callback, for the
    same reason: without it, anyone could overwrite any project's graph.
    """
    settings = get_settings()
    if not settings.sandbox_callback_secret:
        raise HTTPException(status_code=503, detail="sandbox callbacks are not configured")
    if not hmac.compare_digest(x_sandbox_secret, settings.sandbox_callback_secret):
        raise HTTPException(status_code=401, detail="invalid sandbox secret")

    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    target_dir = Path(settings.workspace_storage_dir).resolve() / str(project_id)
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

    project.graph_json_url = str(graph_path)
    await db.commit()

    return {"ok": True, "graph_json_url": str(graph_path)}


class SandboxUsageReport(BaseModel):
    provider: str
    model: str
    operation: str = "extraction"
    prompt_tokens: int = 0
    completion_tokens: int = 0


@router.post("/api/internal/projects/{project_id}/usage")
async def sandbox_usage_report(
    project_id: uuid.UUID,
    payload: SandboxUsageReport,
    x_sandbox_secret: str = Header(default=""),
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
    settings = get_settings()
    if not settings.sandbox_callback_secret:
        raise HTTPException(status_code=503, detail="sandbox callbacks are not configured")
    if not hmac.compare_digest(x_sandbox_secret, settings.sandbox_callback_secret):
        raise HTTPException(status_code=401, detail="invalid sandbox secret")

    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    await record_usage(
        db,
        provider=payload.provider,
        model=payload.model,
        operation=payload.operation,
        prompt_tokens=payload.prompt_tokens,
        completion_tokens=payload.completion_tokens,
        user_id=project.user_id,
        project_id=project.id,
    )
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
