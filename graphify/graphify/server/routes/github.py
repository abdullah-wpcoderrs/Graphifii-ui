"""Phase 3 — GitHub repository listing for the authenticated user.

Phase 5 added transparent refresh: an expired access token is silently
rotated via the stored refresh token (token_refresh.py) before this route
gives up and 401s.
"""

from __future__ import annotations

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


@router.get("/repositories")
async def list_repositories(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
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

    return [
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
