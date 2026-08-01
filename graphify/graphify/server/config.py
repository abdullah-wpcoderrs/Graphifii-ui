"""Environment configuration for the Graphify backend.

Validates on first access so the server fails fast with a clear error
instead of surfacing a confusing failure deep in a request handler.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# graphify/server/config.py -> graphify/server -> graphify (package) -> graphify (repo root)
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    frontend_url: str
    backend_url: str

    database_url: str

    session_secret: str
    token_encryption_key: str

    github_app_id: str
    github_client_id: str
    github_client_secret: str
    github_private_key: str
    github_webhook_secret: str

    # GitLab/GitBucket integrations and Railway sandbox provisioning are
    # optional: the admin may not have created those OAuth apps or a Railway
    # account yet, and the server must still boot and serve GitHub-only
    # traffic. Routes that need one of these check for None and report
    # "not_configured" rather than failing at startup like the required
    # GitHub settings above.
    gitlab_client_id: str | None = None
    gitlab_client_secret: str | None = None
    gitlab_webhook_secret: str | None = None

    gitbucket_instance_url: str | None = None
    gitbucket_client_id: str | None = None
    gitbucket_client_secret: str | None = None
    gitbucket_webhook_secret: str | None = None

    railway_api_token: str | None = None
    # Railway needs to know *which* service to deploy as a sandbox, not just
    # the account token. All three come from the Railway dashboard URL /
    # GraphQL API — see docs/railway-setup.md.
    railway_project_id: str | None = None
    railway_service_id: str | None = None
    railway_environment_id: str | None = None
    workspace_storage_type: str = "local"
    # Where uploaded sandbox artifacts land when workspace_storage_type is
    # "local". Each project gets a subdirectory holding graph.json and
    # files.json; Project.graph_json_url points at that graph.json, and
    # routes/projects.py reads files.json from alongside it.
    workspace_storage_dir: str = "./workspace-storage"

    # Public base URL the *sandbox container* uses to reach this backend.
    #
    # Deliberately separate from backend_url. In development they differ:
    # backend_url must stay http://localhost:8000 because it also drives
    # OAuth redirect URIs (registered with GitHub/GitLab) and the Secure
    # cookie flag (an https:// value there stops the browser sending session
    # cookies over plain-http localhost). Meanwhile a Railway container
    # cannot reach localhost at all and needs a tunnel URL.
    #
    # In production both are the same public origin and this can be left
    # unset — it falls back to backend_url.
    sandbox_callback_base_url: str | None = None

    # Redis Streams delivers queued run IDs to a worker immediately. PostgreSQL
    # remains authoritative and is also polled as a recovery path, so Redis may
    # be omitted for a single-process development deployment.
    redis_url: str | None = None
    redis_run_queue_stream: str = "graphify:extraction-runs"
    redis_run_queue_group: str = "graphify-dispatchers"
    redis_run_queue_block_ms: int = Field(default=2_000, ge=100, le=60_000)
    redis_run_queue_reclaim_seconds: int = Field(default=60, ge=30, le=3_600)
    redis_run_queue_max_length: int = Field(default=10_000, ge=100, le=1_000_000)

    # Enable only in the dedicated worker service in production. It may remain
    # enabled in the web process for local development. PostgreSQL row locks
    # and extraction_runs.active_slot remain the final singleton safety fence.
    run_worker_enabled: bool = True
    run_worker_poll_seconds: float = Field(default=2.0, ge=0.25, le=60.0)
    run_worker_lease_seconds: int = Field(default=4 * 60 * 60, ge=300, le=24 * 60 * 60)
    max_queued_runs_per_user: int = Field(default=3, ge=1, le=100)
    max_queued_runs_global: int = Field(default=100, ge=1, le=10_000)

    # Admin area (Phase 4). Signed with its own secret, deliberately separate
    # from session_secret so an admin cookie cannot be forged from the GitHub
    # session key or vice versa. Optional for the same reason as the
    # integrations above: a deployment that has not run `seed-admin` yet must
    # still boot and serve normal traffic — the admin auth routes report
    # not_configured instead of the app failing at startup.
    admin_session_secret: str | None = None

    @field_validator(
        "database_url",
        "session_secret",
        "token_encryption_key",
        "github_app_id",
        "github_client_id",
        "github_client_secret",
        "github_private_key",
        "github_webhook_secret",
    )
    @classmethod
    def _reject_placeholders(cls, value: str, info) -> str:
        if not value or value.upper().startswith("REPLACE_WITH") or "replace-with" in value.lower():
            raise ValueError(
                f"{info.field_name} is unset or still a placeholder — "
                f"fill in graphify/.env (see docs/github-app-setup.md)"
            )
        return value

    @field_validator("github_private_key")
    @classmethod
    def _validate_pem_shape(cls, value: str) -> str:
        # Catches the failure mode where a multi-line PEM was pasted into
        # .env unquoted: dotenv then only captures the first line ("-----
        # BEGIN ... KEY-----" with no body), which otherwise passes the
        # placeholder check above silently and fails much later, inside
        # GitHub App JWT signing, with a confusing cryptography error.
        # Use scripts/set_github_private_key.py to set this value correctly.
        if "BEGIN" not in value or "END" not in value or "\n" not in value:
            raise ValueError(
                "GITHUB_PRIVATE_KEY doesn't look like a complete PEM (missing "
                "BEGIN/END markers or real newlines) — this usually means it "
                "was pasted unquoted and got truncated to one line by dotenv. "
                "Run: python3 scripts/set_github_private_key.py /path/to/key.pem"
            )
        return value

    @model_validator(mode="after")
    def _secrets_must_differ(self) -> "Settings":
        if self.session_secret == self.token_encryption_key:
            raise ValueError("SESSION_SECRET and TOKEN_ENCRYPTION_KEY must be different values")
        # The whole point of a separate admin cookie is that compromising one
        # signing key does not yield the other. Reusing a value here would
        # silently collapse that isolation back into a single trust boundary.
        if self.admin_session_secret is not None and self.admin_session_secret in (
            self.session_secret,
            self.token_encryption_key,
        ):
            raise ValueError(
                "ADMIN_SESSION_SECRET must differ from SESSION_SECRET and TOKEN_ENCRYPTION_KEY — "
                "reusing one defeats the admin/user session isolation"
            )
        return self

    @property
    def gitlab_configured(self) -> bool:
        return bool(self.gitlab_client_id and self.gitlab_client_secret)

    @property
    def admin_auth_configured(self) -> bool:
        return bool(self.admin_session_secret)

    @property
    def callback_base_url(self) -> str:
        """Where the sandbox should POST progress. Falls back to backend_url."""
        return (self.sandbox_callback_base_url or self.backend_url).rstrip("/")

    @property
    def railway_configured(self) -> bool:
        return bool(
            self.railway_api_token
            and self.railway_project_id
            and self.railway_service_id
            and self.railway_environment_id
        )

    @property
    def gitbucket_configured(self) -> bool:
        return bool(
            self.gitbucket_instance_url
            and self.gitbucket_client_id
            and self.gitbucket_client_secret
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
