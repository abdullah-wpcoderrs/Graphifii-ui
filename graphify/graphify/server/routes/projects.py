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
from graphify.server.models import Project, User
from graphify.server.sessions import get_current_user

router = APIRouter(prefix="/api", tags=["projects"])

_FETCH_TIMEOUT = 10.0


def _serialize(project: Project) -> dict:
    return {
        "id": str(project.id),
        "repo_name": project.repo_name,
        "repo_url": project.repo_url,
        "status": project.status.value,
        "graph_json_url": project.graph_json_url,
        "graph_html_url": project.graph_html_url,
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
