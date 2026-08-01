"""Phase 6 — agent conversations, editable proposed changes, and PR dispatch.

    WS   /ws/projects/{id}/agent                    ask a question, watch it answer
    GET  /api/projects/{id}/agent/messages          conversation history
    GET  /api/projects/{id}/agent/changes           proposed changes + rendered diffs
    PUT  /api/projects/{id}/agent/changes/{cid}     save a user edit
    POST /api/projects/{id}/agent/changes/{cid}/dismiss
    POST /api/projects/{id}/pull-request            branch → commit → PR/MR

The agent runs here, in the main backend process — not in a sandbox. It
reads file contents through the provider's API (see repo_api.py) instead of
from a checkout, so a conversation costs LLM tokens and nothing else: no
container, no clone, no idle compute between messages.

Proposed changes are stored as before/after content pairs rather than patch
text, which is what makes them editable. The diff the editor renders is
derived from that pair on every read, so it stays truthful after the user
edits the "after" side, and dispatch writes exactly what the user approved.
"""

from __future__ import annotations

import difflib
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.agent_llm import (
    AgentLLMError,
    FileDelta,
    FileEnd,
    FileStart,
    StreamDemultiplexer,
    StreamUsage,
    TextDelta,
    stream_completion,
)
from graphify.server.agent_retrieval import RetrievalError, candidate_paths, retrieve_context
from graphify.server.budget import BudgetExceededError, check_budget
from graphify.server.crypto import decrypt
from graphify.server.db import get_db, get_session_factory
from graphify.server.models import (
    AgentMessage,
    AgentSession,
    ChangeStatus,
    MessageRole,
    Project,
    ProjectAgentChange,
    User,
)
from graphify.server.repo_api import (
    FileChange,
    RepoAuthError,
    RepoConflictError,
    RepoError,
    build_repo_client,
    provider_change_request_noun,
)
from graphify.server.routes.admin import _PROVIDER_DEFAULTS
from graphify.server.routes.launch import _active_llm_credential, _decrypt_repo_token
from graphify.server.routes.projects import _fetch_json_artifact, _get_owned_project
from graphify.server.sessions import SESSION_COOKIE_NAME, get_current_user, read_session_user_id
from graphify.server.usage import record_usage

logger = logging.getLogger("graphify.server.agent")

router = APIRouter(tags=["agent"])

# Turns of prior conversation replayed into each prompt. Every message here
# is re-sent (and re-billed) on every question, so this is a direct cost
# multiplier, not just a context-window concern.
_MAX_HISTORY_MESSAGES = 20

# Files whose full contents get attached to a prompt.
_MAX_CONTEXT_FILES = 6

# Cap on one question, to stop a pasted logfile becoming a prompt.
_MAX_PROMPT_CHARS = 8000

_SYSTEM_PROMPT = """\
You are Graphify's code assistant for the repository {repo}.

You are given retrieved knowledge-graph context about this codebase, and the \
full contents of the files most relevant to the question. Answer the user \
directly and concisely, grounded in what you were given. If the context is \
insufficient to answer confidently, say so rather than guessing.

If — and only if — the user asks for a code change, propose it by emitting the \
COMPLETE new contents of each file you want to change, wrapped exactly like this:

<<<FILE: path/to/file.py>>>
...the entire new contents of the file...
<<<END FILE>>>

Rules for file blocks:
- Emit the ENTIRE file, never a fragment, snippet, or diff. What you put \
between the markers replaces that file wholesale.
- Only emit a block for a file whose current contents you were given, or for \
a genuinely new file you are creating.
- Never wrap a file block in a markdown code fence.
- Explain your reasoning in prose before and after the blocks.
- If you are only answering a question, emit no file blocks at all.
"""


# --------------------------------------------------------------------------
# Serialization helpers
# --------------------------------------------------------------------------


def _unified_diff(path: str, before: str | None, after: str) -> str:
    """The diff shown in the editor — derived, never stored.

    Recomputed on every read so a user edit to `after` is reflected
    immediately; a stored patch would go stale the moment they typed.
    """
    return "".join(
        difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}" if before is not None else "/dev/null",
            tofile=f"b/{path}",
        )
    )


def _serialize_change(change: ProjectAgentChange) -> dict:
    return {
        "id": str(change.id),
        "path": change.path,
        "before_content": change.before_content,
        "after_content": change.after_content,
        "diff": _unified_diff(change.path, change.before_content, change.after_content),
        "status": change.status.value,
        "edited_by_user": change.edited_by_user,
        "is_new_file": change.before_content is None,
        "updated_at": change.updated_at.isoformat() if change.updated_at else None,
    }


def _serialize_message(message: AgentMessage) -> dict:
    return {
        "id": str(message.id),
        "role": message.role.value,
        "content": message.content,
        "error": message.error,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


# --------------------------------------------------------------------------
# Session / history / change queries
# --------------------------------------------------------------------------


async def _get_or_create_session(db: AsyncSession, project_id: uuid.UUID) -> AgentSession:
    result = await db.execute(select(AgentSession).where(AgentSession.project_id == project_id))
    session = result.scalar_one_or_none()
    if session is None:
        session = AgentSession(project_id=project_id)
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return session


async def _recent_messages(db: AsyncSession, session_id: uuid.UUID, limit: int) -> list[AgentMessage]:
    result = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def _open_changes(db: AsyncSession, project_id: uuid.UUID) -> list[ProjectAgentChange]:
    result = await db.execute(
        select(ProjectAgentChange)
        .where(
            ProjectAgentChange.project_id == project_id,
            ProjectAgentChange.status == ChangeStatus.PROPOSED,
        )
        .order_by(ProjectAgentChange.created_at)
    )
    return list(result.scalars().all())


async def _project_file_list(project: Project) -> list[str]:
    """Paths from the project's files.json, or [] if it is unavailable.

    Used both to choose which files to attach to a prompt and to validate a
    path before it is fetched — a path the extraction never saw is never
    requested from the provider.
    """
    if not project.graph_json_url:
        return []
    location = project.graph_json_url.rsplit("/", 1)[0] + "/files.json"
    try:
        data = await _fetch_json_artifact(location)
    except HTTPException:
        return []
    return [entry.get("path", "") for entry in data.get("files", []) if entry.get("path")]


# --------------------------------------------------------------------------
# REST: history, changes, edits
# --------------------------------------------------------------------------


@router.get("/api/projects/{project_id}/agent/messages")
async def get_agent_messages(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await _get_owned_project(project_id, user, db)
    session = await _get_or_create_session(db, project.id)
    messages = await _recent_messages(db, session.id, _MAX_HISTORY_MESSAGES * 5)
    changes = await _open_changes(db, project.id)
    return {
        "session_id": str(session.id),
        "messages": [_serialize_message(m) for m in messages],
        "changes": [_serialize_change(c) for c in changes],
    }


@router.get("/api/projects/{project_id}/agent/changes")
async def get_agent_changes(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    project = await _get_owned_project(project_id, user, db)
    return [_serialize_change(c) for c in await _open_changes(db, project.id)]


class SaveChangeRequest(BaseModel):
    after_content: str


@router.put("/api/projects/{project_id}/agent/changes/{change_id}")
async def save_agent_change(
    project_id: str,
    change_id: uuid.UUID,
    payload: SaveChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Overwrite the proposed content with the user's own edit.

    This is what makes the diff a draft rather than a read-only suggestion:
    whatever is stored here is exactly what a later dispatch commits.
    """
    project = await _get_owned_project(project_id, user, db)
    change = await _get_owned_change(db, project.id, change_id)

    if change.status is not ChangeStatus.PROPOSED:
        raise HTTPException(status_code=409, detail="this change is no longer editable")

    change.after_content = payload.after_content
    change.edited_by_user = True
    await db.commit()
    await db.refresh(change)
    return _serialize_change(change)


@router.post("/api/projects/{project_id}/agent/changes/{change_id}/dismiss")
async def dismiss_agent_change(
    project_id: str,
    change_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await _get_owned_project(project_id, user, db)
    change = await _get_owned_change(db, project.id, change_id)
    change.status = ChangeStatus.DISMISSED
    await db.commit()
    return {"ok": True}


async def _get_owned_change(
    db: AsyncSession, project_id: uuid.UUID, change_id: uuid.UUID
) -> ProjectAgentChange:
    result = await db.execute(
        select(ProjectAgentChange).where(
            ProjectAgentChange.id == change_id,
            ProjectAgentChange.project_id == project_id,
        )
    )
    change = result.scalar_one_or_none()
    if change is None:
        raise HTTPException(status_code=404, detail="change not found")
    return change


# --------------------------------------------------------------------------
# Prompt assembly
# --------------------------------------------------------------------------


async def _gather_file_context(
    project: Project, user: User, paths: list[str]
) -> tuple[str, dict[str, tuple[str | None, str | None]]]:
    """Fetch each path's current content from the provider.

    Returns the prompt fragment plus {path: (content, blob_sha)} so a change
    proposed against a file records the exact revision it was written from —
    that sha is what conflict detection compares at dispatch time.
    """
    token = _decrypt_repo_token(user, project.provider)
    if not token or not paths:
        return "", {}

    client = build_repo_client(project.provider, token, project.repo_name)
    fetched: dict[str, tuple[str | None, str | None]] = {}
    sections: list[str] = []

    for path in paths:
        try:
            file = await client.get_file(path, project.default_branch)
        except RepoError as exc:
            # One unreadable file must not fail the whole question — the
            # model can still answer from graph context alone.
            logger.info("skipping unreadable file %s: %s", path, exc)
            continue
        fetched[path] = (file.content, file.sha)
        sections.append(f"--- FILE: {path} ---\n{file.content}")

    if not sections:
        return "", fetched
    return "\n\n".join(sections), fetched


def _build_messages(
    history: list[AgentMessage], question: str, graph_context: str, file_context: str
) -> list[dict]:
    """Prior turns plus this question, with retrieved context attached.

    Context rides on the current question rather than being replayed for
    every historical turn — re-sending stale context each time would grow
    the prompt (and the bill) without making the answer better.
    """
    messages: list[dict] = []
    for message in history:
        if message.error:
            continue
        messages.append({"role": message.role.value, "content": message.content})

    parts = [f"## Knowledge graph context\n\n{graph_context}" if graph_context else ""]
    if file_context:
        parts.append(f"## Current file contents\n\n{file_context}")
    parts.append(f"## Question\n\n{question}")

    messages.append({"role": "user", "content": "\n\n".join(p for p in parts if p)})
    return messages


# --------------------------------------------------------------------------
# WebSocket: the conversation itself
# --------------------------------------------------------------------------


async def _authenticate_ws(websocket: WebSocket, project_id: uuid.UUID) -> tuple[Project, User] | None:
    """Resolve the session cookie and project ownership, mirroring launch.py.

    Same close-code taxonomy (4401/4403/4404) and the same deliberate
    conflation of "no such project" with "someone else's project", so this
    endpoint cannot be used to enumerate project ids either.
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

        if project is None:
            await websocket.close(code=4404, reason="project not found")
            return None

        # Detached from the session below, so force-load what is used later.
        db.expunge(project)
        db.expunge(user)

    return project, user


@router.websocket("/ws/projects/{project_id}/agent")
async def agent_ws(websocket: WebSocket, project_id: uuid.UUID) -> None:
    await websocket.accept()

    authenticated = await _authenticate_ws(websocket, project_id)
    if authenticated is None:
        return
    project, user = authenticated

    session_factory = get_session_factory()

    # Replay history on connect, for the same reason the launch socket sends
    # current state on frame one: a refresh must show the real conversation,
    # not an empty panel.
    async with session_factory() as db:
        session = await _get_or_create_session(db, project.id)
        messages = await _recent_messages(db, session.id, _MAX_HISTORY_MESSAGES * 5)
        changes = await _open_changes(db, project.id)
        await websocket.send_json(
            {
                "type": "history",
                "session_id": str(session.id),
                "messages": [_serialize_message(m) for m in messages],
                "changes": [_serialize_change(c) for c in changes],
            }
        )

    try:
        while True:
            payload = await websocket.receive_json()
            if payload.get("type") != "user_message":
                await websocket.send_json({"type": "error", "message": "unknown message type"})
                continue

            question = (payload.get("content") or "").strip()
            if not question:
                await websocket.send_json({"type": "error", "message": "message cannot be empty"})
                continue
            if len(question) > _MAX_PROMPT_CHARS:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"message is too long (limit {_MAX_PROMPT_CHARS} characters)",
                    }
                )
                continue

            await _handle_question(websocket, session_factory, project, user, question)

    except WebSocketDisconnect:
        # Normal: the user navigated away or closed the workspace.
        return
    except Exception:
        logger.exception("agent socket failed for project %s", project.id)
        try:
            await websocket.send_json(
                {"type": "error", "message": "The agent session hit an unexpected error."}
            )
        except Exception:
            pass


async def _handle_question(
    websocket: WebSocket,
    session_factory,
    project: Project,
    user: User,
    question: str,
) -> None:
    """One full turn: budget → retrieve → stream → persist."""
    async with session_factory() as db:
        # Budget first: no retrieval, no provider call, nothing billable
        # happens for a user who is already over their allowance.
        try:
            spent, limit = await check_budget(db, user.id)
        except BudgetExceededError as exc:
            await websocket.send_json({"type": "error", "message": str(exc), "code": "budget_exceeded"})
            return

        session = await _get_or_create_session(db, project.id)
        user_message = AgentMessage(
            session_id=session.id, role=MessageRole.USER, content=question
        )
        db.add(user_message)
        await db.commit()
        await db.refresh(user_message)
        await websocket.send_json({"type": "user_message", "message": _serialize_message(user_message)})

        history = await _recent_messages(db, session.id, _MAX_HISTORY_MESSAGES)
        # Drop the turn just written — it is added explicitly with context.
        history = [m for m in history if m.id != user_message.id]

        credential = await _active_llm_credential(db)
        api_key = decrypt(credential.key_ciphertext, credential.key_iv)
        defaults = _PROVIDER_DEFAULTS.get(credential.provider, _PROVIDER_DEFAULTS["openai"])
        model = credential.model or defaults["default_model"]

    # Retrieval and file fetching happen outside a DB session — both are
    # network-bound and would otherwise hold a pooled connection idle.
    graph_context = ""
    if project.graph_json_url:
        try:
            graph_context = await retrieve_context(
                project.graph_json_url, question, cache_key=str(project.id)
            )
        except RetrievalError as exc:
            logger.info("retrieval unavailable for project %s: %s", project.id, exc)

    known_files = await _project_file_list(project)
    paths = candidate_paths(graph_context, known_files, limit=_MAX_CONTEXT_FILES)
    file_context, fetched = await _gather_file_context(project, user, paths)

    messages = _build_messages(history, question, graph_context, file_context)
    system = _SYSTEM_PROMPT.format(repo=project.repo_name)

    usage = StreamUsage()
    demux = StreamDemultiplexer()
    prose: list[str] = []
    file_buffers: dict[str, list[str]] = {}
    failure: str | None = None

    await websocket.send_json({"type": "message_start"})

    try:
        async for chunk in stream_completion(
            provider=credential.provider,
            base_url=defaults["base_url"],
            model=model,
            api_key=api_key,
            system=system,
            messages=messages,
            usage=usage,
        ):
            for event in demux.feed(chunk):
                await _emit_event(websocket, event, prose, file_buffers, fetched)

        for event in demux.finish():
            await _emit_event(websocket, event, prose, file_buffers, fetched)

    except AgentLLMError as exc:
        failure = str(exc)
    except Exception:
        logger.exception("agent generation failed for project %s", project.id)
        failure = "The agent hit an unexpected error while answering."

    # Persist whatever was produced, even on failure — a partial answer plus
    # a visible error beats losing the turn entirely.
    async with session_factory() as db:
        assistant = AgentMessage(
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content="".join(prose).strip(),
            error=failure,
        )
        db.add(assistant)
        await db.commit()
        await db.refresh(assistant)

        serialized_changes = []
        if not failure:
            serialized_changes = await _persist_changes(
                db, project.id, assistant.id, file_buffers, fetched
            )

        # Usage is recorded even on failure: a stream that died partway
        # still consumed the prompt tokens the provider reported.
        if usage.prompt_tokens or usage.completion_tokens:
            await record_usage(
                db,
                provider=credential.provider,
                model=model,
                operation="agent",
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                user_id=user.id,
                project_id=project.id,
            )

        spent_now, limit_now = await _safe_budget_snapshot(db, user.id)

    if failure:
        await websocket.send_json({"type": "error", "message": failure})

    await websocket.send_json(
        {
            "type": "message_end",
            "message": _serialize_message(assistant),
            "changes": serialized_changes,
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            },
            "budget": {"spent": str(spent_now), "limit": str(limit_now)},
        }
    )


async def _safe_budget_snapshot(db: AsyncSession, user_id: uuid.UUID):
    """Current spend/limit for display, tolerating an over-budget state."""
    from graphify.server.budget import get_daily_budget, spent_today

    return await spent_today(db, user_id), await get_daily_budget(db)


async def _emit_event(
    websocket: WebSocket,
    event,
    prose: list[str],
    file_buffers: dict[str, list[str]],
    fetched: dict[str, tuple[str | None, str | None]],
) -> None:
    """Route one parsed event to the client and to the right accumulator."""
    if isinstance(event, TextDelta):
        prose.append(event.text)
        await websocket.send_json({"type": "text_token", "text": event.text})
    elif isinstance(event, FileStart):
        file_buffers.setdefault(event.path, [])
        before, _ = fetched.get(event.path, (None, None))
        await websocket.send_json(
            {
                "type": "file_start",
                "path": event.path,
                # Sent so the editor can render the left-hand side of the
                # diff while the right-hand side is still streaming in.
                "before_content": before,
                "is_new_file": before is None,
            }
        )
    elif isinstance(event, FileDelta):
        file_buffers.setdefault(event.path, []).append(event.text)
        await websocket.send_json({"type": "file_token", "path": event.path, "text": event.text})
    elif isinstance(event, FileEnd):
        await websocket.send_json({"type": "file_end", "path": event.path})


async def _persist_changes(
    db: AsyncSession,
    project_id: uuid.UUID,
    message_id: uuid.UUID,
    file_buffers: dict[str, list[str]],
    fetched: dict[str, tuple[str | None, str | None]],
) -> list[dict]:
    """Store this turn's proposals, superseding any earlier one per path."""
    serialized = []

    for path, parts in file_buffers.items():
        after = "".join(parts)
        if not after.strip():
            continue

        existing = await db.execute(
            select(ProjectAgentChange).where(
                ProjectAgentChange.project_id == project_id,
                ProjectAgentChange.path == path,
                ProjectAgentChange.status == ChangeStatus.PROPOSED,
            )
        )
        for stale in existing.scalars().all():
            # Kept rather than deleted so the user can see an earlier answer
            # proposed something different for this file.
            stale.status = ChangeStatus.SUPERSEDED

        before, sha = fetched.get(path, (None, None))
        change = ProjectAgentChange(
            project_id=project_id,
            message_id=message_id,
            path=path,
            before_content=before,
            after_content=after,
            base_sha=sha,
            status=ChangeStatus.PROPOSED,
        )
        db.add(change)
        await db.commit()
        await db.refresh(change)
        serialized.append(_serialize_change(change))

    return serialized


# --------------------------------------------------------------------------
# PR dispatch
# --------------------------------------------------------------------------


class PullRequestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = ""
    change_ids: list[uuid.UUID] = Field(default_factory=list)
    # Explicit, server-checked confirmation. The frontend also confirms, but
    # this endpoint mutates someone's real repository through a real API
    # call — it must not rely on a dialog the client could skip.
    confirm: bool = False


_BRANCH_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _branch_name(project: Project) -> str:
    """A fresh branch per dispatch, never the default branch.

    The random suffix means a second attempt after a partial failure gets a
    clean branch instead of colliding with the half-finished one.
    """
    slug = _BRANCH_SAFE.sub("-", project.repo_name.split("/")[-1]).strip("-").lower()[:32]
    return f"graphify/agent-{slug or 'change'}-{secrets.token_hex(3)}"


@router.post("/api/projects/{project_id}/pull-request")
async def create_pull_request(
    project_id: str,
    payload: PullRequestRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await _get_owned_project(project_id, user, db)
    noun = provider_change_request_noun(project.provider)

    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail=f"confirmation is required before opening a {noun}",
        )

    changes = await _open_changes(db, project.id)
    if payload.change_ids:
        wanted = set(payload.change_ids)
        changes = [c for c in changes if c.id in wanted]
    if not changes:
        raise HTTPException(status_code=400, detail="there are no proposed changes to submit")

    token = _decrypt_repo_token(user, project.provider)
    if not token:
        raise HTTPException(
            status_code=401,
            detail=f"connect your {project.provider} account before opening a {noun}",
        )

    client = build_repo_client(project.provider, token, project.repo_name)
    branch = _branch_name(project)
    file_changes = [
        FileChange(path=c.path, content=c.after_content, before_sha=c.base_sha) for c in changes
    ]

    # Three steps that can each fail independently. The response names which
    # one failed so a partial failure (branch created, commit refused) is
    # actionable rather than an opaque 500 — and the proposed changes are
    # deliberately left PROPOSED so nothing the user wrote is lost.
    try:
        await client.create_branch(project.default_branch, branch)
    except RepoConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RepoAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RepoError as exc:
        raise HTTPException(status_code=502, detail=f"could not create the branch: {exc}") from exc

    try:
        await client.commit_files(
            branch,
            file_changes,
            payload.title,
            base_branch=project.default_branch,
        )
    except RepoConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"{exc} (branch {branch} was created and is safe to delete)",
        ) from exc
    except RepoError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"could not commit the changes: {exc} (branch {branch} was created)",
        ) from exc

    try:
        result = await client.open_pull_request(
            title=payload.title,
            body=payload.body,
            head=branch,
            base=project.default_branch,
        )
    except RepoError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"the changes were committed to {branch}, but the {noun} could not be "
                f"opened: {exc}. You can open it manually from that branch."
            ),
        ) from exc

    for change in changes:
        change.status = ChangeStatus.COMMITTED
    await db.commit()

    return {
        "ok": True,
        "number": result.number,
        "url": result.url,
        "branch": result.branch,
        "kind": noun,
        "committed_files": [c.path for c in changes],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
