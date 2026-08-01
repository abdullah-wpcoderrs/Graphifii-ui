"""Phase 5 — transparent access-token refresh for GitHub/GitLab.

Wraps the three token-consuming call sites named in the phase scope
(`GET /api/repositories`, `GET /api/integrations/:provider/repos`, and the
sandbox launch's repo-token read in run_worker.py): each currently just
decrypts a stored access token and 401s once it's expired. This module
inserts a refresh attempt in front of that decrypt, so an expired token is
invisible to the caller as long as a refresh token is on file and the
provider accepts it.

GitBucket has no refresh flow at all (see the docstring on
GitBucketOAuthClient in git_clients.py) — its branch here is a plain
decrypt, not a missing refresh.

Concurrency: two requests racing a refresh for the same user both succeed
independently and the later `db.commit()` simply overwrites the earlier
one's rows with an equally-valid pair (both came from the same still-valid
refresh token, since neither commits until GitHub/GitLab has responded).
The window is one network round trip; not worth a row lock for that.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.config import get_settings
from graphify.server.crypto import decrypt, encrypt
from graphify.server.git_clients import (
    GitHubAuthError,
    GitHubUnavailableError,
    GitLabAuthError,
    GitLabOAuthClient,
    GitLabUnavailableError,
    refresh_github_token,
)
from graphify.server.models import User

logger = logging.getLogger("graphify.server.token_refresh")

# Refresh a little before the provider's own expiry so a slow request never
# starts with a token that dies mid-flight.
_EXPIRY_BUFFER = timedelta(seconds=60)


def _is_expiring(expires_at: datetime | None) -> bool:
    return expires_at is not None and expires_at <= datetime.now(timezone.utc) + _EXPIRY_BUFFER


async def get_valid_access_token(user: User, provider: str, db: AsyncSession) -> str | None:
    """Return a usable, decrypted access token for `provider`.

    Refreshes first if the stored token is expired/near-expiry and a
    refresh token is on file; persists the rotated tokens on success.
    Returns None when there is no connection, or refresh was needed but
    unavailable/failed — callers should treat that the same as today (401,
    "reconnect"), since both cases require the user to reconnect anyway.
    """
    if provider == "github":
        return await _github_token(user, db)
    if provider == "gitlab":
        return await _gitlab_token(user, db)
    if provider == "gitbucket":
        return _gitbucket_token(user)
    raise ValueError(f"unknown provider {provider!r}")


def _gitbucket_token(user: User) -> str | None:
    if not user.gitbucket_access_token_ciphertext or not user.gitbucket_access_token_iv:
        return None
    return decrypt(user.gitbucket_access_token_ciphertext, user.gitbucket_access_token_iv)


async def _github_token(user: User, db: AsyncSession) -> str | None:
    if not user.github_access_token_ciphertext or not user.github_access_token_iv:
        return None
    if not _is_expiring(user.github_access_token_expires_at):
        return decrypt(user.github_access_token_ciphertext, user.github_access_token_iv)
    if not user.github_refresh_token_ciphertext or not user.github_refresh_token_iv:
        # Expired with nothing to rotate — e.g. a GitHub App without token
        # expiration enabled never issues a refresh token in the first
        # place, so this path shouldn't normally be reached for those.
        return None

    refresh_token = decrypt(user.github_refresh_token_ciphertext, user.github_refresh_token_iv)
    try:
        token_data = await refresh_github_token(refresh_token)
    except (GitHubAuthError, GitHubUnavailableError) as exc:
        logger.warning("GitHub token refresh failed for user %s: %s", user.id, exc)
        return None

    now = datetime.now(timezone.utc)
    access_ciphertext, access_iv = encrypt(token_data.access_token)
    user.github_access_token_ciphertext = access_ciphertext
    user.github_access_token_iv = access_iv
    user.github_access_token_expires_at = (
        now + timedelta(seconds=token_data.expires_in) if token_data.expires_in else None
    )
    if token_data.refresh_token:
        refresh_ciphertext, refresh_iv = encrypt(token_data.refresh_token)
        user.github_refresh_token_ciphertext = refresh_ciphertext
        user.github_refresh_token_iv = refresh_iv
        user.github_refresh_token_expires_at = (
            now + timedelta(seconds=token_data.refresh_token_expires_in)
            if token_data.refresh_token_expires_in
            else None
        )
    await db.commit()
    return token_data.access_token


async def _gitlab_token(user: User, db: AsyncSession) -> str | None:
    if not user.gitlab_access_token_ciphertext or not user.gitlab_access_token_iv:
        return None
    if not _is_expiring(user.gitlab_access_token_expires_at):
        return decrypt(user.gitlab_access_token_ciphertext, user.gitlab_access_token_iv)
    if not user.gitlab_refresh_token_ciphertext or not user.gitlab_refresh_token_iv:
        return None

    settings = get_settings()
    if not settings.gitlab_configured:
        # The admin removed the OAuth app config after this user connected —
        # nothing to refresh against.
        return None

    client = GitLabOAuthClient(settings.gitlab_client_id, settings.gitlab_client_secret)  # type: ignore[arg-type]
    refresh_token = decrypt(user.gitlab_refresh_token_ciphertext, user.gitlab_refresh_token_iv)
    try:
        token_data = await client.refresh_access_token(refresh_token)
    except (GitLabAuthError, GitLabUnavailableError) as exc:
        logger.warning("GitLab token refresh failed for user %s: %s", user.id, exc)
        return None

    access_ciphertext, access_iv = encrypt(token_data.access_token)
    user.gitlab_access_token_ciphertext = access_ciphertext
    user.gitlab_access_token_iv = access_iv
    user.gitlab_access_token_expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=token_data.expires_in)
        if token_data.expires_in
        else None
    )
    if token_data.refresh_token:
        refresh_ciphertext, refresh_iv = encrypt(token_data.refresh_token)
        user.gitlab_refresh_token_ciphertext = refresh_ciphertext
        user.gitlab_refresh_token_iv = refresh_iv
    await db.commit()
    return token_data.access_token
