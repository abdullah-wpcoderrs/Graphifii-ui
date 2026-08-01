"""SQLAlchemy models.

Phase 3 adds SystemCredential (admin-configured LLM provider keys) and
gitlab_*/gitbucket_* integration token fields on User, alongside the Phase
0-2 auth/GitHub-sync/provisioning tables.

Enums use native_enum=False (stored as VARCHAR + CHECK constraint) so adding
a new value is a plain Alembic migration instead of a Postgres ALTER TYPE.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, true

from graphify.server.db import Base


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    USER = "USER"


class RepositorySelection(str, enum.Enum):
    ALL = "all"
    SELECTED = "selected"


class ProjectStatus(str, enum.Enum):
    CLONING = "CLONING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()

    # GitHub identity. github_user_id is GitHub's stable numeric ID; login can
    # change (renames), so it is not used as the join key elsewhere.
    github_user_id: Mapped[int] = mapped_column(unique=True, index=True)
    github_login: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, validate_strings=True), default=Role.USER
    )

    # Phase 4: admin suspension. Checked in get_current_user, so suspending a
    # user invalidates their existing session cookie on the next request
    # rather than at its 30-day expiry.
    #
    # Note: Role.ADMIN no longer grants any authorization — admins are a
    # separate principal in the `admin` table with their own login (see
    # admin_sessions.py). This column is retained as historical/informational
    # data only.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    # GitHub App user-to-server tokens expire and rotate via a refresh token
    # (default behavior for apps created after 2026 unless explicitly
    # disabled). Both are encrypted at rest with TOKEN_ENCRYPTION_KEY
    # (AES-GCM: ciphertext + iv stored separately, see server/crypto.py).
    github_access_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_access_token_iv: Mapped[str | None] = mapped_column(String(64), nullable=True)
    github_access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    github_refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_refresh_token_iv: Mapped[str | None] = mapped_column(String(64), nullable=True)
    github_refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # GitLab OAuth token (encrypted at rest, same AES-GCM scheme as GitHub
    # above). GitLab access tokens also expire and rotate via refresh_token;
    # refresh rotation is deferred to Phase 5 like GitHub's.
    gitlab_access_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    gitlab_access_token_iv: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gitlab_access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    gitlab_refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    gitlab_refresh_token_iv: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gitlab_user_id: Mapped[int | None] = mapped_column(nullable=True)
    gitlab_login: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # GitBucket OAuth token (encrypted at rest).
    gitbucket_access_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    gitbucket_access_token_iv: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gitbucket_access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    gitbucket_user_id: Mapped[int | None] = mapped_column(nullable=True)
    gitbucket_login: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    installations: Mapped[list["GitHubInstallation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class GitHubInstallation(Base):
    __tablename__ = "github_installations"

    id: Mapped[uuid.UUID] = _uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # GitHub's numeric installation ID — used for the installation-token
    # exchange (GITHUB_APP_ID + GITHUB_PRIVATE_KEY sign a JWT, then this ID
    # requests a short-lived installation access token).
    installation_id: Mapped[int] = mapped_column(unique=True, index=True)
    account_login: Mapped[str] = mapped_column(String(255))
    account_type: Mapped[str] = mapped_column(String(32))  # "User" | "Organization"
    repository_selection: Mapped[RepositorySelection] = mapped_column(
        Enum(RepositorySelection, native_enum=False, validate_strings=True)
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="installations")
    projects: Mapped[list["Project"]] = relationship(back_populates="installation")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("user_id", "repo_name", name="uq_project_user_repo"),)

    id: Mapped[uuid.UUID] = _uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    installation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("github_installations.id", ondelete="SET NULL"), nullable=True
    )

    repo_name: Mapped[str] = mapped_column(String(512))  # "owner/repository"
    repo_url: Mapped[str] = mapped_column(String(1024))
    default_branch: Mapped[str] = mapped_column(String(255), default="main")

    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False, validate_strings=True),
        default=ProjectStatus.CLONING,
    )
    sandbox_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    graph_json_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    graph_html_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Phase 4 provisioning progress. Persisted rather than held in memory so a
    # client reconnecting to /ws/projects/:id mid-extraction can be sent the
    # current state immediately, and so progress survives a backend restart.
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="projects")
    installation: Mapped["GitHubInstallation | None"] = relationship(back_populates="projects")


class SystemCredential(Base):
    """Admin-configured LLM provider API key, encrypted at rest.

    Encrypted the same way as User's GitHub/GitLab/GitBucket tokens
    (server-side AES-256-GCM via TOKEN_ENCRYPTION_KEY, see crypto.py) rather
    than the browser-side PBKDF2 scheme the original PRD sketched — this
    key must be decryptable by the backend on its own, both to verify it
    (POST /api/admin/credentials/verify) and to use it later when running
    an extraction sandbox job (Phase 4), neither of which can wait for an
    admin to re-supply a master secret. A "the backend never sees the
    plaintext key" model is incompatible with the backend needing to
    autonomously call the LLM API with it.
    """

    __tablename__ = "system_credentials"

    id: Mapped[uuid.UUID] = _uuid_pk()

    provider: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_ciphertext: Mapped[str] = mapped_column(Text)
    key_iv: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageEvent(Base):
    """One billable LLM call, recorded for the admin spend log and per-user usage.

    Written from the extraction and agent paths. Token counts and pricing
    come from graphify/llm.py's existing registry rather than being
    recomputed here, so the cost shown matches what the engine actually used.

    user_id/project_id are nullable and use SET NULL: deleting a user or
    project must not erase the platform's historical spend record, since
    these rows are the basis for cost reporting. Aggregates therefore need
    to tolerate NULLs and treat them as "deleted".

    cost_estimate is Numeric, not Float — summing float dollars across many
    rows accumulates representation error.
    """

    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = _uuid_pk()

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )

    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(64))  # "extraction" | "agent" | "verify"

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Admin(Base):
    """Platform administrator — a separate principal from User.

    Phase 4 moves the admin area behind its own email/password login instead
    of Phase 3's `User.role == ADMIN` check on the GitHub session. Admins are
    deliberately NOT users with a flag: an admin has no GitHub identity, no
    projects, and no integrations, and a self-registered or compromised
    GitHub account must not be able to become one. The two principals also
    carry independently-signed cookies (see admin_sessions.py), so neither
    session can be forged from the other's secret.

    Only the argon2 hash is stored; the plaintext password exists solely in
    the body of POST /api/admin/login and in the environment of the seed
    command — never in the database, a migration, or the repo.
    """

    __tablename__ = "admin"

    id: Mapped[uuid.UUID] = _uuid_pk()

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
