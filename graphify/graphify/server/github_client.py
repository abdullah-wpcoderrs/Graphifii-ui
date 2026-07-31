"""Minimal GitHub OAuth client used by the auth callback.

Kept separate from server/app.py because Phase 3 (repository listing) and
later phases also need authenticated calls to the GitHub API and should
reuse the same error taxonomy instead of duplicating httpx boilerplate.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from graphify.server.config import get_settings

GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

_TIMEOUT = 10.0


class GitHubAuthError(Exception):
    """The GitHub API responded, but rejected or could not complete the request."""


class GitHubUnavailableError(GitHubAuthError):
    """GitHub could not be reached, or returned a server error."""


@dataclass
class GitHubTokenResponse:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    refresh_token_expires_in: int | None


async def exchange_code_for_token(code: str, redirect_uri: str) -> GitHubTokenResponse:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise GitHubUnavailableError(f"token exchange request failed: {exc}") from exc

    if response.status_code >= 500:
        raise GitHubUnavailableError(f"GitHub returned {response.status_code} during token exchange")

    data = response.json()
    if "access_token" not in data:
        raise GitHubAuthError(data.get("error_description") or data.get("error") or "token exchange failed")

    return GitHubTokenResponse(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_in=data.get("expires_in"),
        refresh_token_expires_in=data.get("refresh_token_expires_in"),
    )


async def fetch_github_user(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except httpx.HTTPError as exc:
            raise GitHubUnavailableError(f"user profile request failed: {exc}") from exc

    if response.status_code >= 500:
        raise GitHubUnavailableError(f"GitHub returned {response.status_code} fetching the user profile")
    if response.status_code != 200:
        raise GitHubAuthError(f"GitHub user profile fetch failed with {response.status_code}")

    return response.json()
