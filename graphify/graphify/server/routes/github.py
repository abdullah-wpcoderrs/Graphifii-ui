"""Phase 3 — GitHub repository listing for the authenticated user.

Phase 5 added transparent refresh: an expired access token is silently
rotated via the stored refresh token (token_refresh.py) before this route
gives up and 401s.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.db import get_db
from graphify.server.models import User
from graphify.server.sessions import get_current_user
from graphify.server.token_refresh import get_valid_access_token

router = APIRouter(prefix="/api", tags=["github"])

GITHUB_REPOS_URL = "https://api.github.com/user/repos"
_TIMEOUT = 10.0

# Every load of the Repositories page hit GitHub live and took 2-3 seconds
# (measured), because nothing was ever remembered between requests. A repo
# list doesn't change second-to-second, so a short cache turns every load
# after the first into an instant one without meaningfully staling the data.
#
# In-process, keyed per user — same shape and same single-instance caveat as
# the admin login rate limiter in admin_auth.py: fine for one replica, and a
# multi-replica deployment just falls back to more cache misses (never wrong
# data), since a miss re-fetches from GitHub rather than trusting a stale
# local dict.
_REPO_CACHE_TTL_SECONDS = 60


@dataclass
class _CachedRepos:
    repos: list[dict]
    expires_at: float


_repo_cache: dict[uuid.UUID, _CachedRepos] = {}


def _cache_get(user_id: uuid.UUID) -> list[dict] | None:
    entry = _repo_cache.get(user_id)
    if entry is None or entry.expires_at <= time.monotonic():
        return None
    return entry.repos


def _cache_set(user_id: uuid.UUID, repos: list[dict]) -> None:
    _repo_cache[user_id] = _CachedRepos(
        repos=repos, expires_at=time.monotonic() + _REPO_CACHE_TTL_SECONDS
    )


@router.get("/repositories")
async def list_repositories(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    cached = _cache_get(user.id)
    if cached is not None:
        return cached

    access_token = await get_valid_access_token(user, "github", db)
    if access_token is None:
        raise HTTPException(status_code=401, detail="GitHub connection expired, please reconnect")

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.get(
                GITHUB_REPOS_URL,
                params={"per_page": 100, "sort": "updated"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"GitHub request failed: {exc}") from exc

    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="GitHub connection expired, please reconnect")
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"GitHub returned {response.status_code}")

    repos = [
        {
            "id": repo["id"],
            "name": repo["name"],
            "full_name": repo["full_name"],
            "html_url": repo["html_url"],
            "description": repo.get("description"),
            "default_branch": repo.get("default_branch", "main"),
            "stargazers_count": repo.get("stargazers_count", 0),
            "private": repo.get("private", False),
            "language": repo.get("language"),
            "pushed_at": repo.get("pushed_at"),
            "owner_login": (repo.get("owner") or {}).get("login"),
            "owner_type": (repo.get("owner") or {}).get("type", "User"),
        }
        for repo in response.json()
    ]
    _cache_set(user.id, repos)
    return repos
