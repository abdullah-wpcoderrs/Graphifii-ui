"""OAuth clients for GitHub, GitLab, and GitBucket.

Kept separate from server/app.py because repository listing and the
integrations routes need authenticated calls to each provider's API and
should reuse the same error taxonomy instead of duplicating httpx
boilerplate. Each provider gets its own exception pair (AuthError /
UnavailableError) so callers can map failures to the right frontend error
code, mirroring the GitHub client that Phase 2 established.
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


GITLAB_TOKEN_URL = "https://gitlab.com/oauth/token"
GITLAB_USER_URL = "https://gitlab.com/api/v4/user"


class GitLabAuthError(Exception):
    """The GitLab API responded, but rejected or could not complete the request."""


class GitLabUnavailableError(GitLabAuthError):
    """GitLab could not be reached, or returned a server error."""


@dataclass
class GitLabTokenResponse:
    access_token: str
    refresh_token: str | None
    expires_in: int | None


class GitLabOAuthClient:
    """OAuth2 client for gitlab.com (not a self-hosted GitLab instance)."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> GitLabTokenResponse:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                response = await client.post(
                    GITLAB_TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "code": code,
                        "grant_type": "authorization_code",
                        "redirect_uri": redirect_uri,
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise GitLabUnavailableError(f"token exchange request failed: {exc}") from exc

        if response.status_code >= 500:
            raise GitLabUnavailableError(f"GitLab returned {response.status_code} during token exchange")

        data = response.json()
        if "access_token" not in data:
            raise GitLabAuthError(data.get("error_description") or data.get("error") or "token exchange failed")

        return GitLabTokenResponse(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
        )

    async def fetch_gitlab_user(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                response = await client.get(
                    GITLAB_USER_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.HTTPError as exc:
                raise GitLabUnavailableError(f"user profile request failed: {exc}") from exc

        if response.status_code >= 500:
            raise GitLabUnavailableError(f"GitLab returned {response.status_code} fetching the user profile")
        if response.status_code != 200:
            raise GitLabAuthError(f"GitLab user profile fetch failed with {response.status_code}")

        return response.json()


GITBUCKET_USER_PATH = "/api/v3/user"
GITBUCKET_TOKEN_PATH = "/login/oauth/access_token"


class GitBucketAuthError(Exception):
    """The GitBucket API responded, but rejected or could not complete the request."""


class GitBucketUnavailableError(GitBucketAuthError):
    """GitBucket could not be reached, or returned a server error."""


@dataclass
class GitBucketTokenResponse:
    access_token: str


class GitBucketOAuthClient:
    """OAuth2 client for a self-hosted GitBucket instance.

    GitBucket's OAuth implementation follows GitHub's API shape (it's
    designed as a GitHub-compatible self-hosted server), so this mirrors
    exchange_code_for_token/fetch_github_user above but against a
    configurable instance_url rather than a hardcoded github.com host.
    """

    def __init__(self, instance_url: str, client_id: str, client_secret: str) -> None:
        self._instance_url = instance_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> GitBucketTokenResponse:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{self._instance_url}{GITBUCKET_TOKEN_PATH}",
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise GitBucketUnavailableError(f"token exchange request failed: {exc}") from exc

        if response.status_code >= 500:
            raise GitBucketUnavailableError(f"GitBucket returned {response.status_code} during token exchange")

        data = response.json()
        if "access_token" not in data:
            raise GitBucketAuthError(data.get("error_description") or data.get("error") or "token exchange failed")

        return GitBucketTokenResponse(access_token=data["access_token"])

    async def fetch_gitbucket_user(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                response = await client.get(
                    f"{self._instance_url}{GITBUCKET_USER_PATH}",
                    headers={"Authorization": f"token {access_token}"},
                )
            except httpx.HTTPError as exc:
                raise GitBucketUnavailableError(f"user profile request failed: {exc}") from exc

        if response.status_code >= 500:
            raise GitBucketUnavailableError(f"GitBucket returned {response.status_code} fetching the user profile")
        if response.status_code != 200:
            raise GitBucketAuthError(f"GitBucket user profile fetch failed with {response.status_code}")

        return response.json()
