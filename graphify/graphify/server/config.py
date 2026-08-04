"""Environment configuration for the Graphify backend.

Validates on first access so the server fails fast with a clear error
instead of surfacing a confusing failure deep in a request handler.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# graphify/server/config.py -> graphify/server -> graphify (package) -> graphify (repo root)
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Hosts where plain HTTP is legitimate. Browsers grant these "secure context"
# status despite the scheme, which is precisely why local development works
# without TLS — and why the same non-https value is a real defect anywhere else.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1", "0.0.0.0"})


def _is_loopback(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host in _LOOPBACK_HOSTS or host.endswith(".localhost")


def _same_host(a: str, b: str) -> bool:
    """Whether two URLs share an exact hostname — NOT real cookie same-site.

    Real "same-site" is scheme + eTLD+1 (registrable domain), which needs the
    public suffix list to compute correctly: a naive "last two labels"
    approximation would call `app.vercel.app` and `api.vercel.app` same-site,
    when `vercel.app` is itself a public suffix and those are two unrelated,
    genuinely cross-site deployments — exactly the broken case this validator
    exists to catch. Hostname equality is deliberately stricter than the real
    rule: it can false-negative on a legitimate same-registrable-domain
    sibling-subdomain deployment (`app.box.lan` + `api.box.lan`), forcing that
    case onto https or a loopback host too. It can never false-positive a
    cross-site pair into passing, which is the failure mode that matters here.
    """
    return (urlsplit(a).hostname or "") == (urlsplit(b).hostname or "")


def normalize_database_url(value: str) -> str:
    """Make a pasted PostgreSQL URL usable by this codebase.

    Two corrections, both for mistakes that only surface after deployment:

    1. Strip a matching pair of surrounding quotes. `DATABASE_URL="..."` is
       valid .env syntax; python-dotenv unquotes it, Docker's `env_file`
       parser does not.
    2. Rewrite the bare `postgresql://` scheme to `postgresql+psycopg://`.
       Neon's console emits the bare form, which SQLAlchemy maps to psycopg2 —
       a driver this project neither depends on nor installs.

    Shared by Settings and alembic/env.py: the migration role reads
    DATABASE_URL straight from the environment without constructing Settings,
    so normalizing in only one of them leaves the other broken.
    """
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    if text.startswith("postgresql://"):
        text = text.replace("postgresql://", "postgresql+psycopg://", 1)
    return text


def resolve_migration_database_url(raw_env_value: str | None) -> str:
    """Pick the migration URL from the environment, falling back to Settings.

    Used by ``alembic/env.py``. The bare `DATABASE_URL` environment variable
    takes precedence when present (`SERVICE_ROLE=migrate` promotes Neon's
    *direct* URL into it, and that process has none of the GitHub App or
    session secrets a full `Settings` object requires). A whitespace-only
    value must fall back to `Settings.database_url` rather than normalizing
    to an empty string, which would hand Alembic an invalid `sqlalchemy.url`.
    """
    stripped = (raw_env_value or "").strip()
    return normalize_database_url(stripped) if stripped else get_settings().database_url


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

    @model_validator(mode="before")
    @classmethod
    def _strip_env_quoting(cls, data):
        """Remove shell quoting the environment loader left behind.

        `DATABASE_URL="postgresql+psycopg://..."` in .env is valid and common.
        python-dotenv strips those quotes, so running from a checkout works.
        Docker's `env_file` parser does not, so the container receives a value
        that literally begins with a double quote — and SQLAlchemy then fails
        with "Could not parse SQLAlchemy URL", which points nowhere near the
        actual cause.

        Stripping here makes one .env behave identically under uvicorn,
        Compose, and Railway, instead of requiring a differently formatted
        copy per loader. Only a *matching* leading and trailing quote is
        removed; quotes inside a value are left alone, and a secret cannot
        begin and end with a quote character by accident (base64, hex, and URL
        alphabets contain none).
        """
        if not isinstance(data, dict):
            return data
        cleaned = {}
        for key, value in data.items():
            if isinstance(value, str) and len(value) >= 2:
                stripped = value.strip()
                if stripped[0] == stripped[-1] and stripped[0] in "\"'":
                    value = stripped[1:-1]
            cleaned[key] = value
        return cleaned

    @field_validator("database_url", mode="before")
    @classmethod
    def _require_psycopg3_driver(cls, value):
        """Force SQLAlchemy onto psycopg3 regardless of how the URL was pasted.

        Neon's console hands out `postgresql://...`, and SQLAlchemy maps that
        bare scheme to psycopg2 — a driver this project does not depend on and
        does not install (pyproject pins psycopg[binary], i.e. psycopg3). A
        checkout can still limp along if psycopg2 happens to be present in the
        virtualenv transitively; the container cannot, so the mistake shows up
        only after deployment as `ModuleNotFoundError: No module named
        'psycopg2'` from deep inside engine creation.

        Rewriting the scheme here is safe: `postgresql+psycopg://` is the only
        combination this codebase supports. An explicit non-psycopg driver is
        left alone so the error stays honest if someone genuinely wants one.
        """
        return normalize_database_url(value) if isinstance(value, str) else value

    @field_validator("github_private_key", mode="before")
    @classmethod
    def _normalize_pem(cls, value):
        """Accept the PEM in whichever shape the environment loader produced.

        The same .env file yields two different strings depending on who read
        it, and both have to work:

        - python-dotenv (used when the app runs from a checkout) understands
          shell quoting: it strips the surrounding quotes and turns the
          two-character sequence \\n into a real newline.
        - Docker's `env_file` parser does neither. The container receives the
          literal quotes and the literal backslash-n, which then fails PEM
          validation below with a message pointing at a problem that isn't
          there.

        Normalizing here rather than asking every deployment to store the key
        differently keeps one .env working for `uvicorn`, Compose, and Railway
        alike. Railway's own multi-line variables arrive already correct and
        pass through this untouched.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1]
        if "\\n" in text and "\n" not in text:
            text = text.replace("\\n", "\n")
        return text

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

    @model_validator(mode="after")
    def _cookies_must_be_deliverable(self) -> "Settings":
        """Reject a BACKEND_URL that would issue cookies the browser discards.

        `sessions.is_secure_cookie()` derives the cookie's `Secure` flag — and
        through it `SameSite` — from this setting rather than from the incoming
        request's scheme. That is fine when BACKEND_URL is accurate and
        silently catastrophic when it is not: a deployment where the frontend
        and API are different sites (Vercel + Railway) but BACKEND_URL is still
        `http://...` issues every session cookie as `Secure=false;
        SameSite=Lax`, which the browser then refuses to send back on the
        cross-site fetch that immediately follows.

        Nothing about that failure looks like a configuration error from the
        outside. `POST /api/admin/login` returns 200, the very next
        `/api/admin/me` returns 401, and the frontend bounces between the login
        page and the dashboard forever. Failing at startup, where the message
        can name the variable, is worth more than any amount of later
        debugging.

        Loopback hosts are exempt: browsers treat `http://localhost` as a
        secure context, frontend and backend are same-site there, and
        `session_cookie_samesite()` already falls back to `Lax` for it.
        """
        if self.backend_url.startswith("https://") or _is_loopback(self.backend_url):
            return self

        # Plain HTTP on a same-site deployment (a LAN host serving both halves,
        # say) is unglamorous but genuinely works: the cookie needs neither
        # Secure nor SameSite=None, and Lax carries it. Only the cross-site
        # combination is unconditionally broken, so only that one is fatal.
        if _same_host(self.frontend_url, self.backend_url):
            return self

        raise ValueError(
            f"BACKEND_URL is {self.backend_url!r} — plain http:// on a host that is not "
            f"loopback, while FRONTEND_URL ({self.frontend_url!r}) is a different site. "
            "Cookie-based login cannot work in that combination: cross-site cookies need "
            "SameSite=None, and browsers only accept SameSite=None together with Secure, "
            "which requires https. Set BACKEND_URL to the API's real public https:// origin "
            "(the value a browser sees, not Railway's internal *.railway.internal hostname). "
            "For local development it must stay http://localhost:8000. Sibling subdomains on "
            "one registrable domain (e.g. app.example.lan + api.example.lan) are also blocked "
            "here even though they'd work in a real browser — this check only recognizes an "
            "exact hostname match, not eTLD+1; use https:// or a loopback host to unblock that."
        )

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
