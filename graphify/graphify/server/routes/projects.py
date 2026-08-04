"""Phase 3 — project listing, detail, graph, and file-tree endpoints.

Graph/file-tree storage: Phase 3 scope is local-storage only (S3/R2 is a
Phase 3+ TBD, see frontend/docs/IMPLEMENTATION_PLAN.md "Open questions").
graph_json_url on Project is either an http(s) URL (fetched directly) or a
local filesystem path; the file tree is expected to sit alongside it as
files.json (same directory, same provisioning job writes both).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.db import get_db
from graphify.server.models import Project, ProjectStatus, User
from graphify.server.repo_api import (
    RepoAuthError,
    RepoError,
    RepoNotFoundError,
    RepoTooLargeError,
    build_repo_client,
)
from graphify.server.routes.launch import _decrypt_repo_token
from graphify.server.sessions import get_current_user

router = APIRouter(prefix="/api", tags=["projects"])

_FETCH_TIMEOUT = 10.0


def _workspace_missing(project: Project) -> bool:
    """True when a READY project's local artifact has been lost.

    Only meaningful for local storage: graph_json_url is a filesystem path
    there (see module docstring), and that path lives on the API service's
    disk, which is not guaranteed to survive a redeploy (no volume is
    currently attached — see docs/unified-railway-platform-plan.md's
    "Attach one Railway volume" item). An http(s) URL is left unchecked
    here — a network call per row in a list endpoint isn't worth it, and a
    future object-storage backend is expected to actually be durable.
    """
    if project.status != ProjectStatus.READY or not project.graph_json_url:
        return False
    if project.graph_json_url.startswith(("http://", "https://")):
        return False
    return not Path(project.graph_json_url).is_file()


def _serialize(project: Project) -> dict:
    return {
        "id": str(project.id),
        "repo_name": project.repo_name,
        "repo_url": project.repo_url,
        "provider": project.provider,
        "default_branch": project.default_branch,
        "status": project.status.value,
        "graph_json_url": project.graph_json_url,
        "graph_html_url": project.graph_html_url,
        "workspace_missing": _workspace_missing(project),
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


async def _get_owned_project(project_id: str, user: User, db: AsyncSession) -> Project:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="project not found") from None

    result = await db.execute(select(Project).where(Project.id == pid, Project.user_id == user.id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


async def _fetch_json_artifact(location: str) -> dict:
    if location.startswith("http://") or location.startswith("https://"):
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            try:
                response = await client.get(location)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=f"could not fetch artifact: {exc}") from exc
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="artifact not found")
        return response.json()

    path = Path(location)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return json.loads(path.read_text())


@router.get("/projects")
async def list_projects(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    result = await db.execute(
        select(Project).where(Project.user_id == user.id).order_by(Project.updated_at.desc())
    )
    return [_serialize(p) for p in result.scalars().all()]


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    project = await _get_owned_project(project_id, user, db)
    return _serialize(project)


@router.get("/projects/{project_id}/graph")
async def get_project_graph(
    project_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    project = await _get_owned_project(project_id, user, db)
    if not project.graph_json_url:
        raise HTTPException(status_code=404, detail="graph not yet generated")
    return await _fetch_json_artifact(project.graph_json_url)


@router.get("/projects/{project_id}/files")
async def get_project_files(
    project_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    project = await _get_owned_project(project_id, user, db)
    if not project.graph_json_url:
        raise HTTPException(status_code=404, detail="file tree not yet generated")
    files_location = project.graph_json_url.rsplit("/", 1)[0] + "/files.json"
    return await _fetch_json_artifact(files_location)


@router.get("/projects/{project_id}/files/{path:path}")
async def get_project_file_content(
    project_id: str,
    path: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One file's current content, read live from the git provider.

    Serves the editor's file viewer and, indirectly, the agent: both need
    real file bodies, which the extraction artifacts do not contain
    (files.json carries the tree, not the contents).

    Content comes from the provider rather than a stored copy so what the
    user reads is the repository's current state, not a snapshot frozen at
    extraction time.

    Path handling is allowlist-based, not sanitization-based: the requested
    path must appear verbatim in the project's own files.json. A traversal
    attempt ("../../etc/passwd") fails because it is not in that list, so
    correctness does not depend on catching every encoding of "..".
    """
    project = await _get_owned_project(project_id, user, db)
    if not project.graph_json_url:
        raise HTTPException(status_code=404, detail="file tree not yet generated")

    files_location = project.graph_json_url.rsplit("/", 1)[0] + "/files.json"
    tree = await _fetch_json_artifact(files_location)
    known = {entry.get("path") for entry in tree.get("files", [])}
    if path not in known:
        raise HTTPException(status_code=404, detail="file not found in this project")

    token = _decrypt_repo_token(user, project.provider)
    if not token:
        raise HTTPException(
            status_code=401,
            detail=f"connect your {project.provider} account to read file contents",
        )

    client = build_repo_client(project.provider, token, project.repo_name)
    try:
        file = await client.get_file(path, project.default_branch)
    except RepoTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except RepoAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RepoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RepoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"path": file.path, "content": file.content, "sha": file.sha, "size": file.size}
