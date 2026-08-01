# Phase 3 Implementation Checklist — Dashboard, Integrations (OAuth), Admin LLM Credentials, Real Data

**Status**: Backend and frontend both code-complete and verified (TestClient + live browser). Workspace real-data wiring explicitly deferred (see "Known Issues & Deferred Items").

**Last Updated**: 2026-07-31

**Note:** Before starting, agent must review `PHASE3_DISCOVERY.md` and existing `graphify/graphify/llm.py` codebase.

**Architecture decisions made during implementation (deviate from the original plan below — read before trusting the unchecked items in this file):**

1. **No separate `/repositories` screen.** The existing `dashboard-screen.tsx` (pre-Phase-3, fixture-based) already combined "recent projects" and "repository listing" into one polished, searchable/filterable view. Rather than build a redundant parallel screen, Dashboard was wired to real data (`GET /api/projects` + `GET /api/repositories` + connected integrations' repos, merged and cross-referenced by repo full name) and kept as the single home screen. Sidebar nav has three items: Dashboard, Integrations, Admin Settings.
2. **No client-side "master secret" encryption for LLM credentials.** The original plan had the browser PBKDF2-encrypt the API key with a secret the backend never learns — but the backend must decrypt the key later (verify endpoint, Phase 4 sandbox jobs), which is impossible without an admin present. Instead, the plaintext key is sent to the backend over HTTPS and encrypted server-side with `TOKEN_ENCRYPTION_KEY` (`crypto.py`), identical to how GitHub/GitLab/GitBucket tokens work. `app/lib/crypto.ts` was deleted; `SystemCredential.key_salt` was dropped via a follow-up migration (`a3ddef49fcac`).
3. **Workspace real-data wiring (workspace-fixtures.ts, workspace-shell.tsx) was out of scope this session** and still runs on fixtures — it's a separate, large immersive 3-pane IDE UI, not part of the sidebar-navigated screens this phase covers.

**Post-implementation fixes (found via manual testing / review, after the sections below were originally written):**

- [x] **Runtime error: `next/image` rejected `avatars.githubusercontent.com`.** Sidebar renders the signed-in user's GitHub avatar via `next/image`, which requires every remote image host to be allowlisted. Added `images.remotePatterns` to `frontend/next.config.ts` for `https://avatars.githubusercontent.com`.
- [x] **Security review (`security-review` skill)** run against the full Phase 3 diff (backend routes, OAuth clients, admin credentials, frontend screens). No HIGH/MEDIUM-confidence vulnerabilities found — OAuth CSRF protection, admin authorization, credential encryption, SSRF, path traversal, SQL injection, CORS, and XSS were all specifically checked against the new code and matched existing secure patterns from Phase 2.

---

## Backend Implementation (Python/FastAPI)

**Status: complete.** See `BACKEND_IMPLEMENTATION_CHECKLIST.md` Phase 3
section for full detail (files touched, migration id, verification
results). Summary below kept for cross-reference.

### Database Schema & Migrations

- [x] **Update `graphify/server/models.py`:**
  - [x] Add `SystemCredential` model with provider, key_ciphertext, key_iv, key_salt
  - [x] Extend `User` model with gitlab_* and gitbucket_* token fields
  - [x] Add unique constraint on provider per credential
  - [x] Index on provider (updated_at querying doesn't need a separate index — table is tiny, 3 rows max)

- [x] **Create Alembic migration:**
  - [x] `alembic revision --autogenerate -m "add system credentials and integration tokens"` → `9bb30a4ebf51`
  - [x] Reviewed generated migration for correctness
  - [x] `alembic upgrade head` against Neon database
  - [x] Verified tables exist: `system_credentials`, updated `users` schema

### OAuth Clients

- [x] **Refactor `graphify/server/github_client.py` → `graphify/server/git_clients.py`**
  - [x] Rename file
  - [x] Keep existing `GitHubOAuthClient` functions
  - [x] Update imports in `routes/auth.py`

- [x] **Add GitLab OAuth Client:**
  - [x] New class: `GitLabOAuthClient`
  - [x] Method: `exchange_code_for_token(code, redirect_uri)` → calls `https://gitlab.com/oauth/token`
  - [x] Method: `fetch_gitlab_user(access_token)` → calls `GET /api/v4/user`
  - [x] Exceptions: `GitLabAuthError`, `GitLabUnavailableError`
  - [x] Return schema: `{user_id, login, email, name, avatar_url, ...}` (raw GitLab profile dict)

- [x] **Add GitBucket OAuth Client:**
  - [x] New class: `GitBucketOAuthClient` (parameterized `instance_url` — self-hosted)
  - [x] Method: `exchange_code_for_token(code, redirect_uri)` → GitBucket OAuth endpoint
  - [x] Method: `fetch_gitbucket_user(access_token)` → GitBucket user profile
  - [x] Exceptions: `GitBucketAuthError`, `GitBucketUnavailableError`
  - [x] Return schema: `{user_id, login, email, ...}` (raw GitBucket profile dict)

- [x] **Update `graphify/server/config.py`:**
  - [x] Add `GITLAB_CLIENT_ID`, `GITLAB_CLIENT_SECRET`, `GITLAB_WEBHOOK_SECRET` as optional
  - [x] Add `GITBUCKET_INSTANCE_URL`, `GITBUCKET_CLIENT_ID`, `GITBUCKET_CLIENT_SECRET`, `GITBUCKET_WEBHOOK_SECRET` as optional
  - [x] `gitlab_configured`/`gitbucket_configured` properties gate the integration routes (routes report "not_configured" rather than crashing)
  - [x] Add `RAILWAY_API_TOKEN` as optional (for sandbox provisioning)

### Project Routes

- [x] **Create `graphify/server/routes/projects.py`:**
  - [x] `GET /api/projects` endpoint — query by current_user.id, order by updated_at DESC, tested with TestClient
  - [x] `GET /api/projects/:id` endpoint — fetch by id, verify ownership, 404 if not found/not owned, tested with TestClient
  - [x] `GET /api/projects/:id/graph` endpoint — fetches graph.json from http(s) URL or local path, 404 if not ready, tested with TestClient
  - [x] `GET /api/projects/:id/files` endpoint — fetches files.json alongside graph.json, 404 if not available, tested with TestClient

### GitHub Routes (Extended)

- [x] **Create `graphify/server/routes/github.py`:**
  - [x] `GET /api/repositories` endpoint — decrypts token via crypto.decrypt(), calls GET /user/repos?per_page=100
  - [x] Handles token expiry (401 with safe message; refresh rotation is Phase 5)
  - [x] Returns [{id, name, full_name, html_url, description, default_branch, stargazers_count}]
  - [x] Tested with TestClient (401-no-token path; real GitHub call untested, needs a live token)

### Integrations Routes (OAuth Flows)

- [x] **Create `graphify/server/routes/integrations.py`:**
  - [x] `GET /api/integrations` — statuses: "connected", "not_connected", "not_configured"; tested with TestClient
  - [x] `GET /api/integrations/:provider/login` (provider=gitlab|gitbucket) — 400 if not configured, else redirects with state cookie
  - [x] `GET /api/integrations/:provider/callback` — verifies state, exchanges code, encrypts + stores tokens, redirects with success/failure
  - [x] `POST /api/integrations/:provider/disconnect` — clears provider tokens, {"ok": true}, tested with TestClient
  - [x] `GET /api/integrations/:provider/repos` — GitLab `/api/v4/projects?owned=true`, GitBucket equivalent; 401 on expired/missing token

### Admin Credentials Routes

- [x] **Create `graphify/server/routes/admin.py`:**
  - [x] `GET /api/admin/credentials` (admin-only, 403 for non-admin) — metadata only, never actual keys; tested with TestClient
  - [x] `POST /api/admin/credentials` (admin-only) — stores ciphertext/iv/salt as sent by frontend; tested with TestClient
  - [x] `PUT /api/admin/credentials/:provider` (admin-only) — updates existing credential
  - [x] `DELETE /api/admin/credentials/:provider` (admin-only) — removes credential; tested with TestClient
  - [x] `POST /api/admin/credentials/verify` (admin-only) — decrypts + calls provider API with test prompt; tested with TestClient (no-key path; real key verification untested, needs a live API key)

### Sandbox Provisioning (Railway)

- [x] **Create `graphify/server/sandbox.py`:**
  - [x] Function: `launch_project_on_railway(project_id, repo_url, active_llm_provider, active_llm_key)` — calls Railway's GraphQL API (`backboard.railway.app/graphql/v2`)
  - [x] Raises `RailwayNotConfiguredError` if `RAILWAY_API_TOKEN` unset (not yet provided by user)
  - [ ] **Not wired to any route yet** — deliberate: actual "Launch Workspace" trigger + WebSocket progress streaming is Phase 4 scope, not Phase 3

- [x] **Add Railway env vars to config.py:**
  - [x] `RAILWAY_API_TOKEN` (optional, for sandbox provisioning)
  - [x] `WORKSPACE_STORAGE_TYPE` (default: local; S3 fields deferred — not needed until S3 is actually chosen, see Open Questions)

### Wiring & Testing

- [x] **Wire routers into `app.py`:**
  - [x] Import projects_router, github_router, integrations_router, admin_router
  - [x] app.include_router() for all four

- [x] **Code Quality:**
  - [x] `uv run ruff check graphify/server/` → no errors
  - [x] `uv run pyright graphify/server/` → no errors

- [x] **Backend TestClient Tests (17 checks, all passing):**
  - [x] GET /api/projects → 200 []
  - [x] GET /api/projects/:id → 404
  - [x] GET /api/repositories → 401
  - [x] GET /api/integrations → 200 with list, GitLab shows not_configured
  - [x] GET /api/integrations/gitlab/login → 400 (not configured)
  - [x] GET /api/integrations/bogus/login → 404 (unknown provider)
  - [x] POST /api/integrations/gitlab/disconnect → 200 {"ok": true}
  - [x] GET /api/integrations/gitlab/repos → 401
  - [x] GET /api/admin/credentials (non-admin) → 403
  - [x] GET /api/admin/credentials (admin) → 200 with 3 providers
  - [x] POST /api/admin/credentials → 200 {"ok": true}
  - [x] DELETE /api/admin/credentials/:provider → 200 {"ok": true}
  - [x] All routes verified via current_user dependency override
  - [x] Live boot against real Neon DB: `/health` 200, all 16 routes in `/openapi.json`

---

## Frontend Implementation (Next.js/React)

**Status: complete.** Summary below; see `BACKEND_IMPLEMENTATION_CHECKLIST.md` for backend detail and the architecture-decisions note above for what changed from the original plan.

### Route Organization & Layout

- [x] Created `app/(authenticated)/layout.tsx` — client component, wraps children in `SessionProvider` (fetches `/api/session` once, redirects to `/` on 401) and renders `<Sidebar />` + `<main>`.
- [x] Moved `app/dashboard/{page,loading}.tsx` → `app/(authenticated)/dashboard/`.
- [x] Created `app/(authenticated)/integrations/{page,loading}.tsx` and `app/(authenticated)/admin/settings/{page,loading}.tsx`.
- [x] No `/repositories` directory (see architecture decision #1). `/`, `/auth/error`, `/onboarding/github`, `/workspace/[projectId]`, `/projects/[projectId]/launch` stay outside `(authenticated)` (workspace wiring deferred, see Known Issues).

### Sidebar Component

- [x] `app/components/sidebar.tsx` — floating inset panel (6px border-radius, inset box-shadow), ~260px desktop / 72px collapsed.
- [x] Nav: Dashboard, Integrations, Admin Settings (hidden unless `session.role === "ADMIN"`), active-state highlighting via `usePathname()`.
- [x] Bottom card: avatar (falls back to a plain div if `avatarUrl` is null) + name/email from session context, Sign out (`POST /api/auth/logout` then redirect to `/`).
- [x] Collapse toggle persists to `localStorage["sidebar-collapsed"]`.
- [x] Mobile (<768px): sidebar becomes a fixed slide-out drawer behind a hamburger toggle + scrim, verified at 375×812.

### Dashboard Screen (Merged Dashboard + Repositories)

- [x] `app/lib/dashboard.ts` rewritten: dropped the `REPOSITORIES` fixture entirely; kept `DashboardFilters`/`Repository` types and `filterRepositories()`; added `mapRepository()` (merges a raw provider repo + matching `Project` record into the UI shape), `formatRelativeTime()`, and a deterministic `languageTone()` hash.
- [x] `app/components/dashboard-screen.tsx` rewritten as a client component: fetches `GET /api/projects` + `GET /api/repositories` + (for each `connected` non-GitHub integration) `GET /api/integrations/:provider/repos`, merges them, and renders the existing search/filter/row UI against real data.
- [x] Views: `list`, `no-repositories` (no connected provider has any repos), `error` (fetch failed), `unauthorized` (GitHub token expired/missing — distinct copy pointing at Integrations). Dropped `no-installation`/`syncing`/`rate-limited` — no backend signal produces them under the current session-cookie auth model (no GitHub App installation-selection step exists).
- [x] Removed the old header's nav/user-menu/admin-link (sidebar now owns branding, navigation, and logout).

### Integrations Screen

- [x] `app/(authenticated)/integrations/page.tsx` — fetches `GET /api/integrations`, renders one `IntegrationCard` per provider, handles the `?provider=&status=success` OAuth-return banner (clears the query string via `router.replace`), Connect (redirects to `${apiUrl}/api/integrations/:provider/login`) and Disconnect (`POST .../disconnect`, then refetch) flows.
- [x] `app/components/integration-card.tsx` — status badge (connected/not_connected/not_configured), shows `login` when connected, shows the backend's `message` when not configured (e.g. "Admin has not configured GitLab OAuth (missing GITLAB_CLIENT_ID)"). No separate "Manage Repos" button — connected repos already surface on the merged Dashboard.

### Admin Settings Screen

- [x] `app/(authenticated)/admin/settings/page.tsx` — redirects non-admins to `/dashboard` (client-side belt-and-suspenders; backend already 403s), fetches `GET /api/admin/credentials`, renders one `LLMCredentialCard` per provider (openai/anthropic/gemini), opens `LLMCredentialModal` to configure.
- [x] `app/components/llm-credential-card.tsx` — Configured/Not configured badge, model preview, Test Connection (calls `POST /api/admin/credentials/verify`, shows the live result inline), Delete. Verify result clears once the credential becomes unconfigured (fixed a bug caught during browser verification where a stale "API key is invalid" message persisted after Delete).
- [x] `app/components/llm-credential-modal.tsx` — API Key (password input) + optional Model field only. No "Master Secret" field (see architecture decision #2).

### Service Adapter Layer

- [x] `app/lib/api.ts` — `fetchProjects`, `fetchProject`, `fetchProjectGraph`, `fetchProjectFiles`, `fetchGitHubRepos`, `fetchIntegrationRepos`, `fetchIntegrations`, `integrationLoginUrl`, `disconnectIntegration`, `fetchAdminCredentials`, `saveAdminCredential`, `updateAdminCredential`, `verifyAdminCredential`, `deleteAdminCredential` — all built on the existing `apiGet`/`apiPost`/`apiPut`/`apiDelete` wrapper from `app/lib/api-client.ts` (Phase 3 frontend-foundation work), not a new `fetchWithAuth` helper.

### Session Context

- [x] `app/lib/session-context.tsx` (not in the original plan, added because three screens all needed the same session/redirect logic) — `SessionProvider` fetches `/api/session` once per `(authenticated)` mount, `useSessionContext()` hook exposes `{session, loading}` to `Sidebar` and any page needing role checks.

### Error Handling

- [x] `app/lib/auth-errors.ts` — added `integration_connection_failed` error code + copy, matching the backend's `_error_redirect()` in `routes/integrations.py`.

### Code Quality

- [x] `npm run lint` — clean (fixed four `react-hooks/set-state-in-effect` findings from the new experimental lint rule: three were legitimate fetch-on-mount effects given a scoped disable comment, one localStorage-read effect likewise).
- [x] `npx tsc --noEmit` — clean.
- [x] `npm run build` — production build succeeds; `/admin/settings`, `/integrations`, `/dashboard` all registered.

### Browser Verification (live, both servers running against real Neon DB)

- [x] Created a throwaway admin user directly in the DB (no real GitHub OAuth available in this sandbox), forged its session cookie via `sessions.create_session_cookie_value`, set it on the backend origin, and drove the actual app in-browser — **not** just TestClient. Deleted the user and reverted all temporary config afterward.
- [x] Confirmed: unauthenticated visits to `/dashboard` redirect to `/` (session guard fires before any DB call). Sidebar renders with correct nav (Admin Settings visible for the ADMIN test user), avatar fallback, and user info. Dashboard correctly shows the "unauthorized" empty state (test user has no real GitHub token → `GET /api/repositories` 401). Integrations screen shows GitHub "Not connected" + GitLab/GitBucket "Not configured" with the exact backend message. Admin Settings: full Configure → Save → Test Connection (real outbound call to OpenAI, correctly rejected the fake key with "API key is invalid or expired") → Delete round trip. Sidebar collapse toggle and the mobile hamburger drawer both verified at 375×812.

---

## Final Checklist

- [x] All backend tests pass (17/17 TestClient checks, `ruff`, `pyright`)
- [x] Frontend code quality checks pass (`lint`, `tsc --noEmit`, `build`)
- [x] Browser verification pass (desktop, collapsed sidebar, mobile 375×812) — see "Browser Verification" above
- [x] Security checks: LLM keys and GitHub/GitLab/GitBucket tokens encrypted at rest (AES-256-GCM, `TOKEN_ENCRYPTION_KEY`); non-admins get 403 from the backend and are redirected client-side; CORS locked to `FRONTEND_URL` with credentials, verified an arbitrary origin gets no `access-control-allow-origin` header
- [ ] Full OAuth E2E for GitLab/GitBucket — blocked on the admin providing real OAuth app credentials (not yet supplied)
- [ ] Documentation: this file + `BACKEND_IMPLEMENTATION_CHECKLIST.md` updated; `PHASE3_DISCOVERY.md` left as the historical planning record (not rewritten)
- [ ] Deployment to Railway/Vercel — not attempted this session, only verified locally

---

## Known Issues & Deferred Items

- **Workspace real-data wiring** — `app/(authenticated)/workspace/[projectId]/page.tsx` and `workspace-shell.tsx` still run on `workspace-fixtures.ts`; explicitly out of scope this session (see architecture decision #3 at the top of this file)
- **GitLab/GitBucket OAuth apps** — not yet created by the admin; routes correctly report `not_configured` in the meantime, verified live
- **Railway sandbox provisioning** — `sandbox.py` exists (basic Railway GraphQL job-creation client) but isn't wired to any route; `RAILWAY_API_TOKEN` isn't set
- **WebSocket streaming** (Phase 4) — provisioning progress not yet real-time
- **Token refresh** (Phase 5) — expired tokens handled gracefully but not auto-refreshed
- **Graph querying** (Phase 6) — agent queries not yet wired to graph engine
- **S3/R2 storage** (optional) — currently using local storage for outputs

---

# Phase 4: Sandbox Provisioning, Launch UX, Workspace Real-Data Wiring

**Status**: Not started.

**Scope** (per `IMPLEMENTATION_PLAN.md` → "Phase 3 Scope vs Phase 4" and "Follow-up phases"):
Wire `sandbox.py`'s Railway job creation into an actual "Launch Workspace" route, stream real provisioning progress over WebSocket, replace the launch screen's mock event playback with the real client, and connect the workspace shell (currently `workspace-fixtures.ts` / `workspace-shell.tsx`) to real project/graph/files data instead of fixtures.

**Note:** Before starting, review `graphify/graphify/server/sandbox.py` (existing Railway GraphQL client, currently unwired), `graphify/graphify/server/models.py::Project`/`ProjectStatus` (CLONING/INDEXING/READY/FAILED), `graphify/graphify/server/routes/projects.py` (existing `GET /api/projects/:id/graph` and `/files`, which assume `graph.json`/`files.json` already exist — this phase is what makes them actually get produced), and the frontend's `app/(authenticated)/workspace/[projectId]/page.tsx` + `app/components/workspace-shell.tsx` + `app/lib/workspace-fixtures.ts`.

## Backend Implementation (Python/FastAPI)

### Isolated Admin Environment (email/password auth — NOT GitHub auth)

**Decision (2026-07-31):** The admin area is a separate environment with its own credential store, its own session cookie, and its own FastAPI dependency. A valid GitHub session grants zero admin access, and an admin session grants zero access to the GitHub-authed app. This supersedes Phase 3's approach of gating `/admin/settings` on `User.role === "ADMIN"`.

- [x] **New `Admin` model in `models.py`** → table `admin`: `id`, `email` (unique), `password_hash`, `is_active`, `last_login_at`, `created_at`, `updated_at`. Deliberately NOT a column on `users`.
- [x] Alembic migration creating `admin` (`c7f2a91be4d3`) — **written, not yet applied** (needs a live DB).
- [x] Password hashing with argon2 via `argon2-cffi` (chosen over `passlib`: one algorithm, actively maintained, no legacy backend layer). Added to the `server` extra in `pyproject.toml` along with `email-validator`.
- [x] **Seed command** — `scripts/seed_admin.py` reads `ADMIN_EMAIL`/`ADMIN_PASSWORD` from the environment, enforces a 12-char minimum, hashes with argon2, and upserts into `admin` (re-running doubles as password reset). Documented in `.env.example`.
- [x] Added `ADMIN_SESSION_SECRET` to `config.py`, with a validator that **rejects startup** if it equals `SESSION_SECRET` or `TOKEN_ENCRYPTION_KEY`. Optional (like the GitLab/GitBucket settings) so an un-seeded deployment still boots; login returns 503 until set.
- [x] **New `routes/admin_auth.py`:** `POST /api/admin/login`, `POST /api/admin/logout`, `GET /api/admin/me`. Cookie is HttpOnly + SameSite=Lax + Secure-when-HTTPS, 12h expiry (vs 30d for users).
- [x] Brute-force protection: 5 attempts per email+IP then a 15-minute lockout, a uniform `"Invalid email or password"` for unknown-email / bad-password / disabled-account alike, and a dummy argon2 verify on the unknown-email path so response timing cannot enumerate admin emails. **Limitation: the limiter is in-process** — it does not hold across replicas; move to Redis before scaling horizontally.
- [x] **New `admin_sessions.py`** with `get_current_admin`, in a separate module from `sessions.py` so a cross-import is obvious in review. Isolation rests on three independent differences: separate secret, separate itsdangerous salt, separate cookie name. `is_active` is re-checked per request, so disabling an admin revokes their live cookie immediately.
- [x] **Re-gated all five routes in `routes/admin.py`** onto `get_current_admin`. `Role.ADMIN` is now **informational only** — it grants no authorization anywhere; recorded in a comment on the model field.
- [x] Added `users.is_active` + suspension enforcement in `get_current_user` (an admin suspending a user kills their existing session on the next request, not at cookie expiry).
- [ ] Update the existing Phase 3 TestClient admin tests, which assert 403-for-non-admin via the GitHub session — that contract has changed. **Not yet done.**

**Verified so far** (no DB required): argon2 hash/verify round trip; admin cookie rejected by the user reader and user cookie rejected by the admin reader (both directions); tampered cookie rejected; secret-reuse rejected at startup; `ruff` and `pyright` clean; app boots with all 29 HTTP routes registered.

### Admin Data Features

- [x] **`usage_events` table** + `usage.py` recording helper. `cost_estimate` is `Numeric(12,6)`, not float, since these values get summed as money. Pricing reuses `graphify/llm.py`'s `estimate_cost()` rather than a second price table, mapping the UI's `"anthropic"` to llm.py's `"claude"` backend key (without that mapping every Anthropic call would silently cost $0). `record_usage()` never raises — a failed usage write must not fail the user's request. **Caveat: llm.py prices per *backend*, not per model**, so a non-default model on the same backend is approximated — fine for a dashboard, not for invoicing.
- [x] `GET /api/admin/usage` (totals + by-provider + by-user) and `GET /api/admin/usage/events` (paginated raw log). Aggregation runs in Postgres, not Python. `user_id` is `ON DELETE SET NULL` so a deleted user's historical spend survives and still appears, attributed to `(deleted user)`.
- [x] `GET /api/admin/analytics` — signups, active users, projects launched, status breakdown, success rate, average indexing duration. Success rate is computed over *terminal* projects only, so it doesn't drift with in-flight load. "Active" is defined as "launched a project in the window" — a documented proxy, not real session tracking.
- [x] `GET /api/admin/users`, `GET /api/admin/users/:id`, `PATCH /api/admin/users/:id` (suspend/reactivate), `DELETE /api/admin/users/:id`. Integrations are reported as booleans (token present / not) — never the token. Cascade behavior documented on the delete handler: projects cascade, usage rows are retained via SET NULL.
- [x] `GET /api/usage` — per-user counterpart, hard-scoped to `current_user.id` with no parameter that can widen the scope.
- [x] **`record_usage()` wired into both real call sites, completed 2026-08-01.**
  - **Admin credential verify** (`routes/admin.py`) — the "Test Connection" button already made a real provider call; it now parses the real `usage` field from the OpenAI/Anthropic response and records it (`operation="verify"`, no `user_id`/`project_id` — platform-level, not attributable to an end-user). Verified live: a real verify call produced a real usage row (11 prompt / 1 completion tokens, correctly priced).
  - **Sandbox community labeling** — the harder one, since spend happens inside the ephemeral container, a separate process with no DB access. Solution: graphify already tracks token usage internally (`label_communities()`'s `usage_out` parameter) and writes it into `GRAPH_REPORT.md` as `Token cost: 1,234 input · 567 output` — the sandbox entrypoint now parses that line (`parse_token_cost()`) and POSTs it to a new endpoint, `POST /api/internal/projects/{id}/usage` (same shared-secret auth as the other sandbox callbacks), which records it against the project's owner. Verified both the parser (comma-formatted numbers, zero, missing-file, missing-line cases) and the live endpoint (wrong secret rejected, real report lands correctly attributed).
  - **Found and fixed along the way:** the sandbox image was missing the `openai`/`anthropic` SDKs entirely, so labeling silently fell back to placeholder names every single time — not a usage-recording bug, but discovered while chasing why a report showed zero cost. Fixed in `Dockerfile.sandbox` (`.[openai,anthropic,gemini]` extras), rebuilt, and re-pushed to GHCR.

### Launch Route

- [x] `POST /api/projects` in the new `routes/launch.py` — resolves the active LLM credential, decrypts it plus the user's git token (needed to clone private repos), creates/reuses the `Project`, and calls `launch_project_on_railway(...)`. `Project.sandbox_id` and `graph_json_url` already existed; no new columns needed for launch itself. Commits *before* calling Railway so the project id exists for the callback URL and a Railway timeout can't lose the row.
- [x] `RailwayNotConfiguredError` → 503, other `RailwayError` → 502, both marking the project FAILED with a safe message rather than leaving it stuck in CLONING.
- [x] Duplicate launch: **409 while in flight** (never interrupts a running job, which would orphan the Railway deploy); otherwise the existing row is reused and its progress reset, since `projects` has `UNIQUE(user_id, repo_name)`.
- [x] `POST /api/internal/projects/{id}/status` — the sandbox's progress callback, authenticated by `SANDBOX_CALLBACK_SECRET` via `hmac.compare_digest` (a plain `==` would leak the secret through response timing). Disabled with 503 when the secret is unset. Late callbacks against an already-terminal project are ignored, so a job still running after a cancel can't resurrect it.
- [x] `POST /api/projects/{id}/cancel` — marks the project failed so the UI stops waiting. **Does not stop the Railway job** (teardown is Phase 7); documented on the handler.
- [x] Added `progress_percent` / `status_message` / `error_message` / `started_at` / `finished_at` to `Project` (migration `d4e8b2317ac6`, also written-not-applied).

### WebSocket Streaming

- [x] `/ws/projects/{id}` — authenticates from the session cookie, verifies ownership, and streams `{status, progress_percent, message, error, graph_json_url, terminal, updated_at}`. Failures use close codes (4401 unauthenticated, 4403 suspended, 4404 not-found) since a WebSocket can't carry a 401 body. **"Not found" and "owned by someone else" are deliberately identical**, so the endpoint can't be used to probe which project ids exist.
- [x] Current state is sent on frame one, so a client reconnecting mid-extraction sees truth immediately rather than waiting for the next change. Only sends on change thereafter; closes on terminal state; 30-minute cap so a stuck job can't hold a socket forever; `WebSocketDisconnect` handled as the normal navigate-away case.
- [x] **Progress transport decision:** the sandbox pushes to the callback endpoint (not the backend polling Railway's GraphQL API), and the WebSocket polls the persisted `Project` row once a second. Rationale recorded in the module docstring: an in-process pub/sub bus would be cheaper per tick but silently wrong across replicas, whereas the DB row is correct for reconnects and multi-instance deployments alike.
- [x] Verified: unauthenticated and forged-cookie WebSocket connections are both closed 4401 without leaking any data.

### Storage

- [ ] Decide and implement where `graph.json`/`files.json` land after a successful `graphify extract` run — local storage path (dev) vs S3/R2 (`WORKSPACE_STORAGE_TYPE`, currently defaults to local).
- [ ] If S3/R2 is chosen: add `S3_BUCKET`/`S3_REGION`/credentials to `config.py`, implement upload from the sandbox job and signed-URL or proxy read in `GET /api/projects/:id/graph`.

### Code Quality & Testing

- [x] `uv run ruff check graphify/server/` clean (also covers `scripts/` and the new migrations).
- [x] `uv run pyright graphify/server/` clean.
- [x] App boots; all 29 HTTP routes + the WebSocket route registered.
- [x] **Automated test suite added, completed 2026-08-01** (`tests/server/`, 63 tests, all passing) — first FastAPI-server test coverage this project has had; previously zero.
  - **Pure logic, no DB/network** (42 tests): `test_config.py` (secret-reuse startup guard, `admin_auth_configured`/`railway_configured` booleans, PEM validation), `test_admin_sessions.py` (password hash/verify round trip, cookie tamper rejection, and — the important one — proving neither session type's cookie is accepted by the other's reader, in both directions), `test_usage.py` (the anthropic→claude pricing-key mapping, unknown-provider-returns-zero, Decimal-not-float), `test_sandbox_entrypoint.py` (token-injection URL building, LLM-backend detection, the new `GRAPH_REPORT.md` parser, file-tree building/truncation).
  - **Integration, against the real Neon DB** (21 tests, `test_launch_routes.py` + `test_admin_routes.py`): admin login/lockout/isolation, launch-route validation and the 409 duplicate-in-flight guard, the status/artifacts/usage callbacks (secret auth, terminal-state protection), and real WebSocket connections (via FastAPI's in-process `TestClient`) proving unauthenticated, forged-cookie, and wrong-owner connections all get rejected.
  - **Deliberate safety boundary, worth understanding before extending this suite:** this dev database has a real OpenAI key and real Railway credentials configured. Tests never call either — anything that would reach a paid API or trigger a real container deploy is monkeypatched (see `conftest.py`'s docstring), so running the suite never spends money or launches infrastructure. Every test row is prefixed `zz-pytest-` and cleaned up in a `finally` block, plus a session-wide sweep catches leftovers from a prior crashed run. Verified zero leftover rows after a full run.
  - **Not done:** the old Phase 3 admin tests (if any existed under a different path) asserting the superseded GitHub-role 403 contract weren't located/removed — worth a search before this is called fully clean. No SQLite/in-memory option exists (Postgres-specific column types), so this suite requires network + the real DB to run; that's a real constraint for CI, not just local dev.
- [x] **Migrations applied to Neon** (`c7f2a91be4d3`, `d4e8b2317ac6`); `alembic check` reports no drift.
- [x] **Live verification against the running server + real DB (stages 1–5, 2026-08-01):**
  - Admin seed → argon2id hash stored, no plaintext, re-run resets password idempotently.
  - Login: wrong password and unknown email return byte-identical 401s; lockout fires on attempt 6; cookie is HttpOnly.
  - Isolation: admin cookie 401s on every user route, and the admin token planted in the `graphify_session` cookie name is still rejected.
  - Admin data endpoints: 200 with cookie / 401 without; analytics returns `null` success-rate on empty data rather than dividing by zero; integrations reported as booleans, no token leakage.
  - Launch error paths: 401 / 400 / 503, with the no-LLM 503 firing *before* Railway is contacted.
  - Callback + WebSocket: streamed `CLONING 0→5% → INDEXING 40→85% → READY 100%`; bad/empty secret rejected; invalid status rejected; progress monotonic; post-terminal callbacks ignored; no-cookie and forged-cookie sockets close 4401.
  - Artifact upload: bad secret rejected, `graph.json` + `files.json` written per project, `graph_json_url` set.
- [x] **Real container verified end-to-end locally (no Railway involved):** built from `Dockerfile.sandbox`, cloned a live repo, extracted 17 nodes / 15 links / 6 communities, uploaded artifacts, drove the project to READY 100%. The failure path was verified too — a repo with no code correctly reported FAILED with a stored reason.
- [ ] TestClient regression suite (the above was manual/live, not automated). The Phase 3 admin tests still assert the old GitHub-session 403 contract and need rewriting.
- [x] **Stage 6 — real Railway deploy, completed 2026-08-01.** The originally-written `serviceInstanceDeploy` mutation was rejected outright by Railway's GraphQL validator (wrong shape — guessed from docs prose, not the real schema). Fixed by querying Railway's live schema directly (`__type` introspection) rather than guessing again: the real flow is two separate calls, not one — `variableCollectionUpsert` (sets this run's env vars, `skipDeploys: true`) then `serviceInstanceDeploy(serviceId, environmentId)` (triggers the deploy; returns a bare boolean, not a deployment id — a `deployments` query afterward finds the id for `Project.sandbox_id`, best-effort). Full real run verified end-to-end: launched via the actual `POST /api/projects` route → Railway deployed the real `ghcr.io/abdullah-wpcoderrs/graphify-sandbox:latest` image → container cloned `pypa/sampleproject`, extracted 17 nodes/15 links/6 communities, uploaded artifacts, reported READY — all in ~20 seconds, pulled straight from Railway's own log via `deploymentLogs`.
  - **Found and fixed:** the sandbox image was missing the `openai`/`anthropic` SDKs, so the AI community-naming step silently failed every time and fell back to placeholder names. `Dockerfile.sandbox` now installs the `[openai,anthropic,gemini]` extras. **Not yet re-verified with a fresh image build+push+redeploy.**
  - **Also fixed:** a running server does not pick up edited `.py` files without a restart (no `--reload` in this setup) — cost real debugging time chasing a "silent container" that was actually just talking to stale code. Worth remembering for any future backend edit made while a server is already running.

## Frontend Implementation (Next.js/React)

### Launch Screen

- [ ] Replace mock WebSocket event playback in the launch screen with a real WebSocket client (`/ws/projects/:id`), including reconnect-with-backoff and cleanup on unmount.
- [ ] Wire the "Launch Workspace" action to `POST /api/projects`, then route to `/projects/:id/launch`.
- [ ] Verify existing out-of-order/repeated/terminal-event handling and failure/retry states still hold against the real event shape (may need adjusting vs the mocked one).
- [ ] Add project cancellation mid-provisioning — needs a backend cancel endpoint too.

### Workspace Real-Data Wiring (deferred from Phase 3, architecture decision #3)

- [ ] Replace `app/lib/workspace-fixtures.ts` usage in `workspace-shell.tsx` with real data: `fetchProject`, `fetchProjectGraph`, `fetchProjectFiles` (already exist in `app/lib/api.ts` from Phase 3, currently unused by the workspace).
- [ ] Wire file explorer + Monaco to real file contents — needs a backend endpoint to serve individual file contents, not just the aggregate `files.json`.
- [ ] Wire the React Flow graph panel to the real `graph.json` shape returned by `GET /api/projects/:id/graph`. **Confirmed shape (from a real extraction run, 2026-08-01):** networkx node-link JSON with top-level keys `directed`, `multigraph`, `graph`, `nodes`, `links`, `hyperedges`, `built_at_commit`. Connections live under **`links`, not `edges`** — reading `edges` yields an empty array and renders every node with no connecting lines.
- [ ] `files.json` shape (generated by the sandbox entrypoint, not by graphify): `{files: [{path, size}], count, truncated}`. `truncated` is true when the repo exceeded 20,000 entries — the UI should say so rather than implying the tree is complete.
- [ ] Add workspace-level loading, disconnected, failed, and restored states — now meaningful once data is real instead of always-present fixtures.
- [ ] Delete `app/lib/workspace-fixtures.ts` once nothing references it.

### Navigation & Screen Split (decided 2026-07-31)

Phase 3 merged "recent projects" and "repository listing" into one Dashboard (architecture decision #1). That merge is now **reversed** — they become two screens with distinct jobs:

- [ ] **`/dashboard` — recent graphed projects only.** Strip the full repository listing out of `dashboard-screen.tsx`; show only projects that have actually been indexed, most-recent-first, with Resume/status. Keep the real-data fetching from Phase 3 (`GET /api/projects`), drop the merged repo cross-referencing.
- [ ] **`/repositories` — new screen, all of the user's repos, private and public.** This is where the search/filter/row UI and the `GET /api/repositories` + per-integration repo fetching from Phase 3's `dashboard-screen.tsx` move to. Launch action lives here.
- [ ] Add "Launch"/"Resume" actions on repository rows that call the new launch route.
- [ ] **`/projects` — new screen.** UI modeled on the Claude Cowork agent-mode IDE. **Blocked pending UI inspiration reference from the user** — do not design this screen speculatively; request the inspo, then build to it.
- [ ] **`/settings` — new screen.** Account preferences: profile, default branch behavior, theme, notifications, danger-zone account deletion.
- [ ] **Docs / Help — external link, not a route.** Points at the official Graphify documentation, opens in a new tab (`target="_blank"` + `rel="noopener noreferrer"`), rendered with a new-tab arrow icon in the sidebar to signal it leaves the app. **Confirm the exact docs URL with the user before wiring.**
- [ ] Update `NAV_ITEMS` in `sidebar.tsx`: Dashboard, Repositories, Projects, Settings, Docs/Help (external). **Remove "Admin Settings" entirely** — admin is now a separate environment with its own login, not a conditional nav item, so `session?.role === "ADMIN"` filtering and the `adminOnly` flag both go away.
- [ ] Add icons for each new nav item to the `ICONS` map; verify active-state highlighting via `usePathname()` still works for the new routes.
- [ ] Verify the new nav set at collapsed width and in the mobile drawer (375×812) — five items plus the external link is more than the three the current layout was verified against.

### Isolated Admin Frontend

- [ ] **New `app/(admin)/` route group** with its own `layout.tsx` — no `SessionProvider`, no `<Sidebar />`, no shared chrome with the authenticated app.
- [ ] `/admin/login` — email + password form posting to `POST /api/admin/login`. Generic failure copy ("Invalid email or password") that does not reveal whether the email exists.
- [ ] Admin layout guard: fetch `GET /api/admin/me`; on 401 redirect to `/admin/login`, never to `/`.
- [ ] **Move** `app/(authenticated)/admin/settings/` → the new `(admin)` group, along with `llm-credential-card.tsx` / `llm-credential-modal.tsx`. Verify the Phase 3 Test Connection → Save → Delete round trip still works under the new cookie.
- [ ] Admin-internal navigation for: LLM Credentials, Usage & Spend, Analytics, Users.
- [ ] **Usage & Spend screen** — spend by provider/user/project with a date-range filter, consuming `GET /api/admin/usage`.
- [ ] **Analytics screen** — signups, active users, projects launched, extraction success/failure, average indexing duration.
- [ ] **Users screen** — list, view connected integrations, suspend/reactivate, delete with an explicit confirmation step.
- [ ] Admin sign-out clears only `admin_session`; confirm it leaves any GitHub session untouched, and vice versa.
- [ ] Add admin API functions to `app/lib/api.ts` (or a separate `admin-api.ts` — decide, given the two environments now have genuinely separate contracts).

### Per-User Usage (main app)

- [ ] If the Usage nav is included: build the user-scoped usage screen against `GET /api/usage`. (Not selected in the nav decision above — build only if the user adds it later.)

### Code Quality

- [ ] `npm run lint` clean.
- [ ] `npx tsc --noEmit` clean.
- [ ] `npm run build` succeeds.

### Browser Verification

- [ ] End-to-end: connect a real repo, launch, watch live WebSocket progress (not mocked), land in workspace with real graph/files/editor content.
- [ ] Verify WebSocket teardown on navigating away mid-provisioning (no leaked connection, no state update on unmounted component).
- [ ] Verify failure path (kill/fail the sandbox job) surfaces the failure state and allows retry.

## Final Checklist (Phase 4)

- [ ] All backend tests pass.
- [ ] Frontend code quality checks pass (`lint`, `tsc --noEmit`, `build`).
- [ ] Browser verification pass (launch → progress → workspace, and failure/retry).
- [ ] `RAILWAY_API_TOKEN` set and live Railway provisioning verified at least once (not just TestClient-mocked).
- [ ] Admin isolation verified adversarially: a valid GitHub session cannot reach any `/api/admin/*` route, and an `admin_session` cannot reach any GitHub-authed route. Confirm the two cookies are independently signed.
- [ ] `public.admin` seeded via the `seed-admin` command with env-supplied credentials; verify login, logout, and that the stored value is a hash rather than plaintext.
- [ ] `TASK_CHECKLIST.md` "Known Issues" section updated to drop the items resolved here.

---

# Phase 5: Token Refresh Rotation

**Status**: Not started. Depends on Phase 4 being functional (a workspace that runs long enough for a token to expire mid-session is what makes this phase matter).

**Scope** (per `IMPLEMENTATION_PLAN.md` → "Follow-up phases": *"Phase 5: Token refresh rotation (GitHub/GitLab token expiry handling)"*).

Today, `routes/github.py` (`GET /api/repositories`) and `routes/integrations.py` (`GET /api/integrations/:provider/repos`) both return a plain 401 when a stored token has expired — there is no refresh attempt. This phase makes token expiry invisible to the user instead of forcing a full OAuth re-connect.

**Note:** Before starting, review how tokens are currently stored (`User.gitlab_*`/`gitbucket_*` fields + GitHub fields added in Phase 3 migration `9bb30a4ebf51`, encrypted via `crypto.py`) and confirm which providers actually issue a `refresh_token` alongside the `access_token` at OAuth-exchange time (GitHub Apps: yes, if configured for token expiration; GitLab: yes; GitBucket: depends on instance — verify against `GitBucketOAuthClient.exchange_code_for_token`'s actual response before assuming).

## Backend Implementation (Python/FastAPI)

### Schema

- [ ] Confirm/add columns to store `refresh_token` (encrypted, same pattern as access tokens) and `token_expires_at` per provider on `User`. Check `models.py` first — Phase 3's migration may already store expiry for some providers; don't duplicate.
- [ ] Alembic migration for any new columns, reviewed and applied.

### Refresh Logic

- [ ] Add a `refresh_<provider>_token(user)` helper per OAuth client in `git_clients.py` — calls the provider's token-refresh endpoint with the stored refresh token, returns new access/refresh tokens + expiry.
- [ ] Wrap the token-consuming call sites (`GET /api/repositories`, `GET /api/integrations/:provider/repos`, and Phase 4's sandbox provisioning token read) with: if `token_expires_at` is past/near, attempt refresh before the provider call; on refresh failure, fall back to the existing 401 behavior.
- [ ] Handle providers whose tokens don't expire / have no refresh flow — refresh logic must be a no-op for those, not an error.
- [ ] Persist rotated tokens immediately after a successful refresh (encrypted, same as initial OAuth exchange).
- [ ] Handle concurrent requests triggering simultaneous refresh for the same user/provider (race condition) — decide on a lock or accept last-write-wins if the window is negligible; document the choice.

### Testing

- [ ] Unit/TestClient coverage: expired token triggers refresh → success path returns data; expired token + failed refresh → 401 as before; non-expiring token skips refresh entirely.
- [ ] `uv run ruff check graphify/server/` clean.
- [ ] `uv run pyright graphify/server/` clean.

## Frontend Implementation (Next.js/React)

- [ ] No UI change expected for the happy path (refresh is transparent) — verify the existing "unauthorized" dashboard/integration states still trigger correctly for the *genuine* failure case (refresh token itself invalid/revoked), not just first-token expiry.
- [ ] If a provider's refresh token itself expires (full re-auth required), confirm the existing Integrations "Connect" flow correctly re-establishes the connection without requiring a disconnect first.

## Final Checklist (Phase 5)

- [ ] All backend tests pass.
- [ ] Frontend regression check: dashboard/integrations unauthorized states still correct.
- [ ] Manually verify at least one provider's real refresh flow against a token forced to near-expiry (not just mocked expiry logic).
- [ ] `TASK_CHECKLIST.md` "Known Issues" updated to drop "Token refresh" once resolved.

**Note on phase numbering:** `IMPLEMENTATION_PLAN.md` and `FRONTEND_IMPLEMENTATION_PLAN.md` disagree on what's in Phase 6+ (agent queries/diff/PR dispatch bundled vs PR workflow as its own later phase). `IMPLEMENTATION_PLAN.md`'s numbering is treated as canonical below — it's the actively maintained doc alongside this file. `FRONTEND_IMPLEMENTATION_PLAN.md`'s old Phase 9 (Agent and Output Log) and Phase 10 (Pull request workflow) both map onto the single Phase 6 below; their UI-only checkmarks are noted where relevant but do not mean the corresponding backend exists.

---

# Phase 6: Agent Queries, Diff Inspection, PR Dispatch

**Status**: Not started.

**Scope** (per `IMPLEMENTATION_PLAN.md` → "Follow-up phases": *"Phase 6: Agent queries, diff inspection, PR dispatch"*; also the `TASK_CHECKLIST.md` Known Issues entry *"Graph querying (Phase 6) — agent queries not yet wired to graph engine"*).

**Read this before scoping an estimate — this phase is materially different in kind from Phase 4/5.** Phase 4 wired a real Railway API and a real `graphify update` command that already existed. Phase 6 has no equivalent to wire: graphify's `query "<question>"` CLI command (`graphify/cli.py` → `graphify/serve.py::_query_graph_text`) only does BFS/DFS **retrieval** — it walks the graph and returns relevant node/edge context as text. It is not itself an agent, does not call an LLM, and does not propose code changes. **A real code-editing agent loop — something that takes a user's question, retrieves graph context, calls an LLM with that context plus the actual file contents, and produces a concrete file diff — does not exist anywhere in this codebase yet.** This phase has to design and build that loop, not just connect existing pieces. Budget accordingly, and treat the "Agent Architecture" section below as a design decision to make explicitly before writing any route.

**Also confirmed while scoping this phase (2026-08-01):** the workspace's agent panel (`app/components/workspace-shell.tsx`, inline — there is no separate `agent-panel.tsx` file) is entirely fixture-driven. Its "Prepare Pull Request" button does not open a PR flow at all — it just pastes a canned string into the prompt textarea (`setPrompt("Prepare a pull request summary...")`). `changedFiles` and `inspectDiff` likewise read from `app/lib/workspace-fixtures.ts`'s `AgentMessage` type. None of this is wired to anything real, and no PR-creation client method exists in `graphify/server/git_clients.py` for any provider (GitHub/GitLab/GitBucket) — that has to be added from scratch too.

**Note:** Before starting, read `graphify/serve.py::_query_graph_text` and `graphify/querylog.py` (existing retrieval + query-logging machinery to reuse rather than reinvent), `graphify/llm.py` (existing LLM call plumbing — the same registry Phase 4's `usage.py`/`Dockerfile.sandbox` already use), `app/components/workspace-shell.tsx` lines ~555–650 (the current fixture-fed agent panel) and `app/lib/workspace-fixtures.ts` (`AgentMessage`, `INITIAL_AGENT_MESSAGES`, `SUGGESTED_PROMPTS`).

## Agent Architecture — decide before implementing

- [ ] **Where does the agent run?** Two real options, each with different tradeoffs:
  - **(a) Inside a Railway sandbox**, similar to extraction — has real file access and can produce a real diff by editing the checkout directly, but needs the checkout kept alive between the initial extraction and an agent session (today's sandbox is ephemeral and exits after extraction), and needs a way to stream partial LLM output back (extending the WebSocket pattern from Phase 4).
  - **(b) In the main backend process**, working against `files.json`'s content plus on-demand fetches of individual file contents (needs a "fetch one file's content" endpoint that doesn't exist yet — `GET /api/projects/:id/files` currently returns only the aggregate tree, not per-file content) and constructing a diff without a live working directory (harder to validate the diff actually applies cleanly).
  - **Recommendation, not yet decided with the user:** (a) is more correct (real files, real diff validity) but couples agent sessions to Railway's uptime/cost model; (b) is cheaper and simpler but requires solving file-content serving first regardless (also needed for Monaco's file viewer per the Phase 4 Workspace Real-Data Wiring section above) and may produce diffs that don't cleanly apply. **Confirm which with the user before writing routes.**
- [ ] Define the message/session persistence model: does a conversation survive a page refresh? If yes, needs a DB table (`AgentSession`, `AgentMessage`) and migration; if no (ephemeral, in-memory per WebSocket connection), document that explicitly since it affects the "reconnect and see history" UX the launch WebSocket already has.
- [ ] Decide the LLM call shape: raw chat completion streamed token-by-token (like the UI's `isStreaming` fixture behavior implies), or a batched agentic loop (retrieve → call → maybe re-retrieve → produce diff) with only the final result streamed. This materially changes the WebSocket/SSE contract.
- [ ] Decide safety boundaries up front, mirroring Phase 4's "must never accidentally call a paid API in tests" lesson: what stops an agent session from looping and burning unbounded LLM spend? A per-session token/call budget is the minimum; decide where it's enforced and what happens when it's hit (hard stop with a message, vs silent truncation).

## Backend Implementation (Python/FastAPI)

### Graph-Aware Retrieval

- [ ] Expose `graphify`'s existing `_query_graph_text` retrieval (currently CLI-only) as an importable function the backend can call directly, or shell out to `graphify query` the same way `sandbox_entrypoint.py` shells out to `graphify update`/`graphify label` — decide which, consistent with how the rest of the backend already calls graphify (Phase 4 used subprocess from inside the sandbox, not a direct import from the main backend process; the main backend process has never directly imported graphify's query internals before).
- [ ] Confirm `graphify query` works against a `graph.json` fetched from `workspace-storage/` (local) as well as a remote URL — Phase 4's `GET /api/projects/:id/graph` already handles both sources; the agent's retrieval step needs the same flexibility.

### File Content Serving (blocking dependency, shared with Phase 4's Monaco wiring)

- [ ] `GET /api/projects/:id/files/{path:path}` — serves one file's raw content from the stored workspace output. Needed by both this phase (the agent needs real file contents to propose a diff) and Phase 4's still-open Monaco wiring item; build once, use in both places.
- [ ] Path traversal guard — `{path:path}` must be validated against the project's actual file list (from `files.json`) before touching disk, not trusted raw from the URL.
- [ ] Size cap and binary-file handling (reuse `graphify.security`'s existing fetch-size-cap patterns from `graphify/security.py` rather than writing a new one).

### Agent Session Endpoints

- [ ] `POST /api/projects/:id/agent/messages` (or `WS /ws/projects/:id/agent` if streaming per-token — depends on the Architecture decision above) — accepts a user prompt, runs retrieval + LLM call, returns/streams the response.
- [ ] Resolve the active LLM credential the same way `routes/launch.py::_active_llm_credential` already does (most-recently-updated configured `SystemCredential`) — do not duplicate that selection logic, import and reuse it.
- [ ] **Record usage via `usage.py::record_usage()`** for every agent LLM call, `operation="agent"`, attributed to `user_id`/`project_id` — this phase is the other major spend surface `usage_events` was built to track (Phase 4 only wired `verify` and `extraction`; `agent` was left as a documented future `operation` value in the model, see `models.py`'s `UsageEvent` docstring).
- [ ] Enforce the per-session budget decided above; return a clear "budget exceeded" response rather than an opaque failure.
- [ ] Error handling: LLM provider errors (rate limit, invalid key, timeout) must produce a safe user-facing message, mirroring `routes/admin.py::verify_credential`'s existing pattern of translating provider errors into generic copy.

### Diff Generation & Storage

- [ ] Decide the diff representation: unified diff text (simple, matches what Monaco's diff view and a PR API both consume directly) vs a structured per-file before/after pair (easier to validate/preview, more code to build). **Recommendation: unified diff text** — both Monaco's diff editor and every git provider's PR-creation API accept it directly, avoiding a translation layer.
- [ ] Persist the proposed diff somewhere retrievable after the agent response completes (a `Project`-scoped table, or embedded in the agent message row if session persistence was chosen above) — the "Prepare Pull Request" step needs to read it back, potentially in a later request than the one that generated it.
- [ ] `GET /api/projects/:id/agent/diff` (or embedded in the message response) — returns the current proposed diff for Monaco to render.

### PR Dispatch

- [ ] **New provider methods in `git_clients.py`** — none exist today for any of the three providers:
  - GitHub: `POST /repos/{owner}/{repo}/pulls` (needs a branch created first via `POST /repos/{owner}/{repo}/git/refs`, and the diff committed to it via the contents/tree API or a full git operation inside a sandbox — decide which given the Architecture choice above).
  - GitLab: `POST /projects/:id/merge_requests` (GitLab calls it a merge request, not a pull request — the UI copy and any shared "PR" naming need to account for this, or explicitly say "GitHub/GitBucket: pull request, GitLab: merge request" rather than assuming one term everywhere).
  - GitBucket: equivalent PR-creation endpoint — confirm it exists and matches GitHub's API shape closely enough to share code (GitBucket is GitHub-API-compatible by design, per the existing `GitBucketOAuthClient`'s pattern of mirroring `GitHubOAuthClient`).
- [ ] **Never push directly to the repo's default branch.** Create a feature branch (e.g. `graphify/agent-{project_id}-{short_id}`) and open the PR/MR against the default branch — decide the exact branch-naming scheme and document it.
- [ ] `POST /api/projects/:id/pull-request` — accepts title + description (user-editable, not silently auto-generated and dispatched), creates the branch, commits the diff, opens the PR/MR, returns the provider's PR number and URL.
- [ ] Decide what happens to the diff/branch on PR-creation failure (partial failure — branch created but PR open call failed — needs a documented recovery path, not a silent orphaned branch).
- [ ] Explicit confirmation required server-side too, not just client-side — this is a repo-mutating action reachable via a real dispatched API call; do not trust the frontend's confirm dialog alone (same principle as this session's safety rule about risky actions needing confirmation).

### Code Quality & Testing

- [ ] `uv run ruff check graphify/server/` clean.
- [ ] `uv run pyright graphify/server/` clean.
- [ ] **Automated tests, following the exact safety pattern established in Phase 4's `tests/server/conftest.py`:** any test touching the real LLM call path or the real PR-creation call must monkeypatch it — this dev environment has a real configured LLM key and, once Phase 6 ships, real git provider tokens capable of actually opening PRs against real repositories. A naive integration test here is worse than Phase 4's risk (Phase 4 could accidentally spend a few cents on Railway; this phase could accidentally open a real, public pull request against someone's real repository). Test the retrieval, diff-parsing, and branch-naming logic directly; monkeypatch the LLM call and the git provider's PR-creation call in every integration test.
- [ ] Verify `record_usage()` actually gets called for agent sessions the same way it was verified for `verify`/`extraction` in Phase 4 (a real, deliberately small/cheap agent call, checked against a real `usage_events` row, then cleaned up).

## Frontend Implementation (Next.js/React)

### Wire the Existing Agent Panel to Real Data

- [ ] Replace `INITIAL_AGENT_MESSAGES`/fixture-driven `messages` state in `workspace-shell.tsx` with real data from the new agent endpoint — this is the FRONTEND_IMPLEMENTATION_PLAN.md Phase 9 UI (message list, streaming indicator, composer, stop-generation button) already exists and looks correct; it needs its data source swapped, not rebuilding.
- [ ] Wire `isStreaming`/`stopStreaming` to the real streaming connection (WebSocket or SSE per the Architecture decision) instead of the fixture's simulated delay.
- [ ] Wire `changedFiles` + `inspectDiff` to the real diff endpoint; confirm Monaco's diff view (already built per FRONTEND_IMPLEMENTATION_PLAN.md Phase 7, currently fed fixture diffs) renders a real unified diff correctly.
- [ ] Handle the agent-error and provider-error states already flagged as unbuilt in `FRONTEND_IMPLEMENTATION_PLAN.md`'s Phase 9 checklist ("Handle reconnecting, canceled, provider-error, and agent-error states") — these become meaningful once the data is real.
- [ ] Build a real tool/activity timeline and output-log filtering/auto-scroll if the retrieval step surfaces intermediate state worth showing (also flagged unbuilt in the old Phase 9 list) — scope depends on the Architecture decision (a single LLM call has little to show; a multi-step retrieve-then-generate loop has real intermediate steps worth surfacing).

### Pull Request Review Flow (genuinely new — old Phase 10 was 100% unbuilt)

- [ ] Replace the "Prepare Pull Request" button's current fake behavior (pasting text into the prompt box) with a real review dialog/drawer.
- [ ] Build the changed-files review list (likely reusable from the existing `agent-change-card` markup in `workspace-shell.tsx`, which already lists `changedFiles` — extend rather than replace).
- [ ] Build the PR title/description form — user-editable, not auto-submitted; show base/head branch (the auto-generated feature branch name from the backend).
- [ ] Show validation errors and branch-conflict errors from the backend.
- [ ] Require explicit confirmation before dispatch; disable the button during submission to prevent duplicate PRs from a double-click.
- [ ] Show creation progress (branch → commit → PR open — three real steps, each of which can fail independently per the backend's partial-failure handling above).
- [ ] On success: show the created PR/MR number and a link to it on the provider (GitHub/GitLab/GitBucket).
- [ ] On failure: preserve the workspace and the proposed diff so the user doesn't lose their agent session's work — do not clear state on a failed PR attempt.

### Code Quality

- [ ] `npm run lint` clean.
- [ ] `npx tsc --noEmit` clean.
- [ ] `npm run build` succeeds.

### Browser Verification

- [ ] End-to-end against a real (throwaway/test) repository: ask the agent a real question, confirm the answer reflects real graph context (not a canned response); request a change, confirm a real diff renders in Monaco; prepare and dispatch a real PR, confirm it actually appears on the provider with the correct branch/title/description.
- [ ] Verify agent session cleanup on navigating away mid-response (no leaked connection, matching the WebSocket teardown check already required in Phase 4).
- [ ] Verify the per-session spend budget actually stops a runaway session, deliberately triggered.

## Final Checklist (Phase 6)

- [ ] Agent Architecture decisions (above) made explicitly with the user, not defaulted silently.
- [ ] All backend tests pass, none touching a real LLM or real git provider API.
- [ ] Frontend code quality checks pass (`lint`, `tsc --noEmit`, `build`).
- [ ] Browser verification pass, including one real end-to-end PR against a disposable test repository.
- [ ] `usage_events` confirmed recording real agent spend (`operation="agent"`), visible in the admin usage dashboard built in Phase 4.
- [ ] `TASK_CHECKLIST.md` Known Issues entry "Graph querying (Phase 6)" updated to reflect what shipped.

## Known Issues & Deferred Items (carried into Phase 7+)

- **Sandbox lifecycle & cleanup** (Phase 7 per `IMPLEMENTATION_PLAN.md`) — if Architecture option (a) is chosen (agent runs inside a kept-alive sandbox), this phase's scope and Phase 7's overlap significantly and may need to be sequenced together rather than strictly after.
- **PR dispatch automation** (`IMPLEMENTATION_PLAN.md` also separately lists "Phase 8: PR dispatch automation") — the exact boundary between this phase's manual/confirmed PR dispatch and a possible future *automatic* dispatch (no human review step) is undefined; treat Phase 6 as building the manual, confirmed flow only, and revisit whether Phase 8 is now redundant or means something narrower (e.g. scheduled/triggered re-runs) once this phase ships.
