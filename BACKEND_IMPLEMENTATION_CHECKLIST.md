# Graphify Cloud IDE - Backend Implementation Checklist

**Status:** Phase 0/1 complete; Phase 2 code complete, pending live E2E verification
**Database:** Neon (PostgreSQL)
**Backend:** Python 3.12 / FastAPI, hosted on Railway (single service — not a separate Node.js orchestrator)
**Frontend:** Next.js 16 (Vercel)
**Last Updated:** 2026-07-31

---

## Architecture correction (read this first)

An earlier draft of this checklist assumed a Node.js orchestrator + Prisma +
Redis/BullMQ, based on the PRD's illustrative architecture. The project's
own docs (`graphify/docs/github-app-setup.md`,
`frontend/docs/local-development.md`) lock in something more specific and
simpler, and that's what we're building to:

- **One backend service**: Python/FastAPI at `graphify/server/app.py`,
  living inside the `graphify` repo (not a separate Node.js project).
- **No Redis, BullMQ, object storage, or AI-provider credentials yet** —
  these are explicitly deferred "before the corresponding feature exists."
  Sandbox job queuing (Phase 4) will need a decision when we get there —
  likely FastAPI `BackgroundTasks` for v1, revisit Redis only if that's
  insufficient.
- **SQLAlchemy 2.0 (async) + Alembic**, not Prisma — Prisma is JS-only and
  doesn't apply to a Python backend. `psycopg[binary]` (v3) is the driver.
- **Session-cookie auth** (`SESSION_SECRET` signs it), not JWT.
- **GitHub App** (not a broad-scope OAuth App) — installation-based access,
  JWT-signed with `GITHUB_PRIVATE_KEY` to mint short-lived installation
  tokens. User tokens (`GITHUB_CLIENT_ID`/`SECRET`) are separate and expire,
  requiring refresh-token rotation.
- GitHub user tokens are encrypted at rest with `TOKEN_ENCRYPTION_KEY`
  (AES-256-GCM, server-side only) — different from the PRD's client-side
  PBKDF2 flow, which only applies to admin-configured LLM provider keys
  (Phase 9, not yet built).

**Database:** `DATABASE_URL` uses the `postgresql+psycopg://` scheme so
SQLAlchemy's async engine selects the psycopg3 async driver against Neon's
pooled connection endpoint.

---

## Phase 0 — Infrastructure & environment

- [x] **0.1** Generate `SESSION_SECRET` and `TOKEN_ENCRYPTION_KEY`
  (`openssl rand -base64 32` each, confirmed distinct) — written to
  `graphify/.env`.
- [x] **0.2** Generate `GITHUB_WEBHOOK_SECRET` (`openssl rand -hex 32`) —
  written to `graphify/.env`; must also be set on the GitHub App's webhook
  config page.
- [x] **0.3** Document the Neon `DATABASE_URL` shape and scheme requirement
  in `graphify/.env` and `.env.example`.
- [x] **0.4** User pasted real values into `graphify/.env`:
  - [x] Neon pooled `DATABASE_URL` (prefixed `postgresql+psycopg://`)
  - [x] `GITHUB_APP_ID`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`
  - [x] `GITHUB_PRIVATE_KEY` (full PEM) — broke twice on unquoted multi-line
    paste (dotenv truncates to the first line, rest becomes bogus keys);
    fixed by hand-escaping into one quoted `\n`-escaped line, verified it
    loads as a real 2048-bit RSA key via `cryptography`. Added
    `scripts/set_github_private_key.py` (reads a `.pem` file directly, no
    manual paste) and a `config.py` validator that now rejects this shape
    of corruption at startup with a clear message instead of failing later
    inside JWT signing.
- [x] **0.5** Add a `server` optional-dependency group to
  `graphify/pyproject.toml`: `fastapi`, `uvicorn[standard]`,
  `sqlalchemy[asyncio]`, `alembic`, `psycopg[binary]`, `pydantic-settings`,
  `itsdangerous`, `PyJWT[crypto]`, `httpx`.
- [x] **0.6** `uv sync --extra server` succeeds.

**Phase 0: complete.**

---

## Phase 1 — Database schema & models

- [x] **1.1** `graphify/server/config.py` — `pydantic-settings` `Settings`
  class, validates all required env vars on first access, rejects
  placeholder values, enforces `SESSION_SECRET != TOKEN_ENCRYPTION_KEY`.
- [x] **1.2** `graphify/server/db.py` — async engine + session factory +
  `Base` declarative class + `get_db()` FastAPI dependency.
- [x] **1.3** `graphify/server/models.py` — minimal schema for the current
  scope only (auth + GitHub sync + provisioning):
  - `User` — GitHub identity, role (`ADMIN`/`USER`), encrypted access +
    refresh token pair with expiry timestamps.
  - `GitHubInstallation` — GitHub App installation records, linked to the
    installing `User`.
  - `Project` — repo reference, provisioning `status`
    (`CLONING`/`INDEXING`/`READY`/`FAILED`), sandbox id, graph artifact URLs.
  - Enums stored as `VARCHAR` + CHECK constraint (`native_enum=False`) so
    adding a value later is a plain migration, not a Postgres `ALTER TYPE`.
  - **Deferred:** `SystemCredential` (admin LLM keys) — lands with Phase 9,
    not before that feature is built.
- [x] **1.4** `graphify/server/crypto.py` — AES-256-GCM encrypt/decrypt
  helpers for GitHub tokens at rest, keyed by `TOKEN_ENCRYPTION_KEY`.
- [x] **1.5** `graphify/server/app.py` — FastAPI app, CORS locked to
  `FRONTEND_URL` with credentials (never `*`), `/health` endpoint.
- [x] **1.6** Alembic initialized (`alembic init -t async alembic`),
  `env.py` wired to `graphify.server.config.get_settings()` for the
  connection string (single source of truth, not duplicated in
  `alembic.ini`) and `graphify.server.db.Base.metadata` for autogenerate.
- [x] **1.7** Structural verification: app/models import cleanly, Alembic
  reaches the DB connection attempt (fails only on "connection refused" to
  a nonexistent local Postgres — expected, confirms the whole chain works).
- [x] **1.8** `uv run alembic revision --autogenerate -m "initial schema"`
  → generated `alembic/versions/1e03398ce9dd_initial_schema.py`. Reviewed:
  correct tables, FKs (`users`→`github_installations`/`projects` CASCADE,
  `github_installations`→`projects` SET NULL), indexes, and the
  `uq_project_user_repo` unique constraint. `uv run alembic upgrade head`
  applied cleanly; confirmed via direct query that `users`,
  `github_installations`, `projects`, and `alembic_version` all exist in
  Neon.
- [x] **1.9** `uv run uvicorn graphify.server.app:app --port 8000` boots;
  `GET /health` → `200 {"status":"ok"}`. CORS verified: preflight from
  `http://localhost:3000` gets `access-control-allow-origin` back, an
  arbitrary origin gets nothing (browser blocks it).

**Phase 0 and 1: complete.**

---

## Phase 2 — Authentication endpoints

- [x] **2.1** `graphify/server/github_client.py` — `httpx`-based GitHub OAuth
  client: `exchange_code_for_token` (code → access/refresh token pair) and
  `fetch_github_user` (token → profile). Separate `GitHubAuthError` /
  `GitHubUnavailableError` so callers can map failures to the right
  frontend error code. Kept as its own module (not inlined in the route) so
  Phase 3 (repo listing) can reuse it instead of duplicating httpx/error
  handling.
- [x] **2.2** `graphify/server/sessions.py` — session-cookie and OAuth-state
  helpers. Session cookie is `itsdangerous`-signed (`URLSafeTimedSerializer`,
  carries only `user_id`, re-verified with a max-age on every read — no
  server-side session store). OAuth `state` uses the double-submit-cookie
  pattern (`secrets.token_urlsafe` set as a short-lived cookie by
  `/login`, compared via `secrets.compare_digest` against the callback's
  `?state=`) since Redis is still deferred. `get_current_user` FastAPI
  dependency raises 401 on missing/expired/invalid session or unknown user.
- [x] **2.3** `graphify/server/routes/auth.py` — the four endpoints:
  - `GET /api/auth/github/login` — sets the state cookie, redirects to
    GitHub's authorize URL.
  - `GET /api/auth/github/callback` — verifies `state`, exchanges `code`,
    fetches the profile, encrypts tokens via `crypto.py`, upserts `User` by
    `github_user_id`, sets the session cookie, redirects to
    `FRONTEND_URL/dashboard`. Every failure path redirects to
    `FRONTEND_URL/auth/error?code=...` using one of the frontend's known
    codes (`access_denied`, `invalid_state`, `github_unavailable`,
    `callback_failed` — matches `frontend/app/lib/auth-errors.ts`
    exactly); unexpected errors are logged server-side with a short random
    `ref` and only that ref is exposed in the redirect, never raw error
    text.
  - `GET /api/session` — returns the current user as JSON via
    `get_current_user`, or a plain 401.
  - `POST /api/auth/logout` — clears the session cookie.
- [x] **2.4** Wired `auth_router` into `graphify/server/app.py`.
- [x] **2.5** Verified via FastAPI `TestClient` (no real GitHub calls):
  `/api/session` with no cookie → 401; `/api/auth/github/login` → 302 to
  GitHub with the state cookie set; `/api/auth/logout` → 200 and clears the
  cookie; `/api/auth/github/callback` with a bad/missing state → redirects
  to `.../auth/error?code=invalid_state`; with `?error=` present →
  `.../auth/error?code=access_denied`. `ruff check` and `pyright` pass on
  all new files.
- [ ] **2.6** Not yet verified: the full success path (real GitHub `code` →
  token exchange → profile fetch → DB upsert → session cookie →
  `/dashboard`) and refresh-token rotation. Needs a real GitHub OAuth round
  trip against `http://localhost:8000`, which weren't run against the live
  Neon DB in this session to avoid writing test data outside an explicit
  ask. Do this next with both servers running locally.

**Phase 2: code complete, needs a live end-to-end browser pass.**

---

## Frontend mock endpoints still to replace (unchanged scope)

Tracked in full in the original planning conversation; restated briefly here
since this file is the durable record. Each will be crossed off as its
backend phase lands and the frontend is repointed from
`frontend/lib/mocks/handlers.ts` to `NEXT_PUBLIC_API_URL`:

| Endpoint | Phase |
|---|---|
| `GET /api/session` | 2 |
| `POST /api/auth/logout` | 2 |
| `GET /api/github/repositories` | 3 |
| `GET /api/github/installations` | 3 |
| `POST/GET /api/projects` | 4 |
| `WS /ws/projects/:projectId` | 4 |
| `GET /api/projects/:projectId/files` | 6 |
| `GET /api/projects/:projectId/graph` | 6 |
| `POST /api/projects/:projectId/agent/messages` | 7 |
| `GET /api/projects/:projectId/changes` | 7 |
| `POST /api/projects/:projectId/pull-requests` | 8 |
| `/api/admin/credentials` (CRUD + verify) | 9 |

---

## Files created this session

```
graphify/.env                                          (real secrets + credentials, gitignored)
graphify/.env.example                                  (documents scheme + generation commands)
graphify/pyproject.toml                                (`server` extra, setuptools packages)
graphify/graphify/server/__init__.py
graphify/graphify/server/config.py                     (env validation, incl. PEM shape check)
graphify/graphify/server/db.py
graphify/graphify/server/models.py
graphify/graphify/server/crypto.py
graphify/graphify/server/app.py
graphify/scripts/set_github_private_key.py             (safe .pem -> .env writer)
graphify/alembic.ini                                   (url stripped in favor of env.py)
graphify/alembic/env.py                                (wired to Settings + Base.metadata)
graphify/alembic/script.py.mako
graphify/alembic/versions/1e03398ce9dd_initial_schema.py  (applied to Neon)
```
