"""SQLAlchemy models.

Scope is deliberately minimal: only tables needed for auth, GitHub sync, and
project provisioning exist today. Credential/AI-provider tables land with
Phase 9 (admin credentials) — see BACKEND_IMPLEMENTATION_CHECKLIST.md.

Enums use native_enum=False (stored as VARCHAR + CHECK constraint) so adding
a new value is a plain Alembic migration instead of a Postgres ALTER TYPE.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="projects")
    installation: Mapped["GitHubInstallation | None"] = relationship(back_populates="projects")
