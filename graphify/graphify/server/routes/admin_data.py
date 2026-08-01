"""Phase 4 — admin spend log, platform analytics, and user management.

All routes require an Admin principal (email/password cookie), not a GitHub
session — see admin_sessions.py. Kept separate from routes/admin.py so
credential management and platform reporting stay independently reviewable;
both mount under /api/admin.

Aggregations run in Postgres rather than in Python: these tables grow with
every LLM call, and pulling rows into the process to sum them would stop
working long before the numbers get interesting.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.admin_sessions import get_current_admin
from graphify.server.db import get_db
from graphify.server.models import (
    Admin,
    Project,
    ProjectStatus,
    UsageEvent,
    User,
)

router = APIRouter(prefix="/api/admin", tags=["admin-data"])

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30


def _resolve_range(days: int) -> datetime:
    if days < 1 or days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=400, detail=f"days must be between 1 and {MAX_RANGE_DAYS}"
        )
    return datetime.now(timezone.utc) - timedelta(days=days)


# --------------------------------------------------------------------------
# Spend / usage
# --------------------------------------------------------------------------


@router.get("/usage")
async def usage_summary(
    days: int = Query(DEFAULT_RANGE_DAYS),
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate spend for the window, broken down by provider and by user."""
    since = _resolve_range(days)

    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
                func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
                func.coalesce(func.sum(UsageEvent.cost_estimate), 0),
                func.count(UsageEvent.id),
            ).where(UsageEvent.created_at >= since)
        )
    ).one()

    by_provider = (
        await db.execute(
            select(
                UsageEvent.provider,
                func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
                func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
                func.coalesce(func.sum(UsageEvent.cost_estimate), 0),
                func.count(UsageEvent.id),
            )
            .where(UsageEvent.created_at >= since)
            .group_by(UsageEvent.provider)
            .order_by(func.sum(UsageEvent.cost_estimate).desc())
        )
    ).all()

    # Outer join so spend from a since-deleted user still appears (user_id is
    # SET NULL on delete) rather than silently dropping out of the totals.
    by_user = (
        await db.execute(
            select(
                UsageEvent.user_id,
                User.github_login,
                func.coalesce(func.sum(UsageEvent.cost_estimate), 0),
                func.count(UsageEvent.id),
            )
            .outerjoin(User, User.id == UsageEvent.user_id)
            .where(UsageEvent.created_at >= since)
            .group_by(UsageEvent.user_id, User.github_login)
            .order_by(func.sum(UsageEvent.cost_estimate).desc())
            .limit(100)
        )
    ).all()

    return {
        "range_days": days,
        "since": since.isoformat(),
        "totals": {
            "prompt_tokens": int(totals[0]),
            "completion_tokens": int(totals[1]),
            "cost_estimate": float(totals[2]),
            "calls": int(totals[3]),
        },
        "by_provider": [
            {
                "provider": row[0],
                "prompt_tokens": int(row[1]),
                "completion_tokens": int(row[2]),
                "cost_estimate": float(row[3]),
                "calls": int(row[4]),
            }
            for row in by_provider
        ],
        "by_user": [
            {
                "user_id": str(row[0]) if row[0] else None,
                "github_login": row[1] or "(deleted user)",
                "cost_estimate": float(row[2]),
                "calls": int(row[3]),
            }
            for row in by_user
        ],
    }


@router.get("/usage/events")
async def usage_events(
    days: int = Query(DEFAULT_RANGE_DAYS),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Raw spend log, newest first — the drill-down behind the summary."""
    since = _resolve_range(days)

    total = (
        await db.execute(
            select(func.count(UsageEvent.id)).where(UsageEvent.created_at >= since)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(UsageEvent, User.github_login)
            .outerjoin(User, User.id == UsageEvent.user_id)
            .where(UsageEvent.created_at >= since)
            .order_by(UsageEvent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "events": [
            {
                "id": str(event.id),
                "github_login": login or "(deleted user)",
                "project_id": str(event.project_id) if event.project_id else None,
                "provider": event.provider,
                "model": event.model,
                "operation": event.operation,
                "prompt_tokens": event.prompt_tokens,
                "completion_tokens": event.completion_tokens,
                "cost_estimate": float(event.cost_estimate),
                "created_at": event.created_at.isoformat(),
            }
            for event, login in rows
        ],
    }


# --------------------------------------------------------------------------
# Platform analytics
# --------------------------------------------------------------------------


@router.get("/analytics")
async def analytics(
    days: int = Query(DEFAULT_RANGE_DAYS),
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    since = _resolve_range(days)

    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    new_users = (
        await db.execute(select(func.count(User.id)).where(User.created_at >= since))
    ).scalar_one()

    # "Active" = has launched at least one project in the window. A weaker
    # proxy than real session tracking, but it uses data we actually have
    # rather than inventing an events table for a number nobody has asked to
    # be precise yet.
    active_users = (
        await db.execute(
            select(func.count(func.distinct(Project.user_id))).where(Project.created_at >= since)
        )
    ).scalar_one()

    status_rows = (
        await db.execute(
            select(Project.status, func.count(Project.id))
            .where(Project.created_at >= since)
            .group_by(Project.status)
        )
    ).all()
    by_status = {status.value if hasattr(status, "value") else str(status): int(count) for status, count in status_rows}

    launched = sum(by_status.values())
    ready = by_status.get(ProjectStatus.READY.value, 0)
    failed = by_status.get(ProjectStatus.FAILED.value, 0)
    terminal = ready + failed

    avg_seconds = (
        await db.execute(
            select(
                func.avg(
                    func.extract("epoch", Project.finished_at) - func.extract("epoch", Project.started_at)
                )
            ).where(
                Project.created_at >= since,
                Project.started_at.is_not(None),
                Project.finished_at.is_not(None),
                Project.status == ProjectStatus.READY,
            )
        )
    ).scalar_one()

    return {
        "range_days": days,
        "since": since.isoformat(),
        "users": {
            "total": int(total_users),
            "new_in_range": int(new_users),
            "active_in_range": int(active_users),
        },
        "projects": {
            "launched_in_range": launched,
            "by_status": by_status,
            # Rate over terminal projects only — counting still-running ones
            # as failures would make the number drift with current load.
            "success_rate": round(ready / terminal, 4) if terminal else None,
            "avg_indexing_seconds": round(float(avg_seconds), 1) if avg_seconds is not None else None,
        },
    }


# --------------------------------------------------------------------------
# User management
# --------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    total = (await db.execute(select(func.count(User.id)))).scalar_one()

    project_counts = {
        row[0]: int(row[1])
        for row in (
            await db.execute(
                select(Project.user_id, func.count(Project.id)).group_by(Project.user_id)
            )
        ).all()
    }

    users = (
        (
            await db.execute(
                select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "users": [
            {
                "id": str(u.id),
                "github_login": u.github_login,
                "email": u.email,
                "role": u.role.value if hasattr(u.role, "value") else str(u.role),
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat(),
                "project_count": project_counts.get(u.id, 0),
                # Presence of a token, never the token itself.
                "integrations": {
                    "github": bool(u.github_access_token_ciphertext),
                    "gitlab": bool(u.gitlab_access_token_ciphertext),
                    "gitbucket": bool(u.gitbucket_access_token_ciphertext),
                },
            }
            for u in users
        ],
    }


@router.get("/users/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    projects = (
        (await db.execute(select(Project).where(Project.user_id == user_id).order_by(Project.created_at.desc())))
        .scalars()
        .all()
    )
    spend = (
        await db.execute(
            select(func.coalesce(func.sum(UsageEvent.cost_estimate), 0)).where(
                UsageEvent.user_id == user_id
            )
        )
    ).scalar_one()

    return {
        "id": str(user.id),
        "github_login": user.github_login,
        "email": user.email,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
        "lifetime_cost_estimate": float(spend),
        "projects": [
            {
                "id": str(p.id),
                "repo_name": p.repo_name,
                "status": p.status.value if hasattr(p.status, "value") else str(p.status),
                "created_at": p.created_at.isoformat(),
            }
            for p in projects
        ],
    }


class UpdateUserRequest(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Suspend or reactivate a user.

    Suspension takes effect on the user's very next request — get_current_user
    rejects inactive accounts — so it does not wait for their session cookie
    to expire.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    user.is_active = payload.is_active
    await db.commit()
    return {"ok": True, "id": str(user_id), "is_active": user.is_active}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a user and their projects.

    Cascade behavior, made explicit because it is destructive and
    irreversible: projects are removed via the users.id FK's ON DELETE
    CASCADE, while usage_events.user_id is ON DELETE SET NULL so the
    platform's historical spend record survives the deletion (it just stops
    being attributable to a named account).
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    return {"ok": True, "deleted": str(user_id)}
