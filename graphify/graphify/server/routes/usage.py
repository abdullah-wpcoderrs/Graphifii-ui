"""Phase 4 — the signed-in user's own token/cost consumption.

The user-scoped counterpart to /api/admin/usage. Every query here is
constrained to current_user.id; there is no parameter that widens the scope,
so this endpoint cannot be coaxed into reporting another account's spend.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.db import get_db
from graphify.server.models import Project, UsageEvent, User
from graphify.server.sessions import get_current_user

router = APIRouter(prefix="/api", tags=["usage"])

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30


@router.get("/usage")
async def my_usage(
    days: int = Query(DEFAULT_RANGE_DAYS),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if days < 1 or days > MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"days must be between 1 and {MAX_RANGE_DAYS}")

    since = datetime.now(timezone.utc) - timedelta(days=days)

    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
                func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
                func.coalesce(func.sum(UsageEvent.cost_estimate), 0),
                func.count(UsageEvent.id),
            ).where(UsageEvent.user_id == user.id, UsageEvent.created_at >= since)
        )
    ).one()

    by_project = (
        await db.execute(
            select(
                UsageEvent.project_id,
                Project.repo_name,
                func.coalesce(func.sum(UsageEvent.cost_estimate), 0),
                func.count(UsageEvent.id),
            )
            .outerjoin(Project, Project.id == UsageEvent.project_id)
            .where(UsageEvent.user_id == user.id, UsageEvent.created_at >= since)
            .group_by(UsageEvent.project_id, Project.repo_name)
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
        "by_project": [
            {
                "project_id": str(row[0]) if row[0] else None,
                "repo_name": row[1] or "(deleted project)",
                "cost_estimate": float(row[2]),
                "calls": int(row[3]),
            }
            for row in by_project
        ],
    }
