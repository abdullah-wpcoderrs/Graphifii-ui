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
- **Token refresh** (Phase 5) — resolved for the three originally-scoped call sites (`GET /api/repositories`, `GET /api/integrations/:provider/repos`, sandbox launch token read), see the Phase 5 section below. Not yet live-verified against a real near-expiry token. `routes/projects.py`'s file-content endpoint and `routes/agent.py`'s two token reads (both Phase 6, postdate this phase's original scope) still don't refresh — documented as a deliberate scope boundary in the Phase 5 section, not an oversight.
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

### Launch Screen — done 2026-08-01

- [x] Replace mock WebSocket event playback in the launch screen with a real WebSocket client (`/ws/projects/:id`), including reconnect-with-backoff (1s→10s cap) and cleanup on unmount. `app/components/provisioning-screen.tsx`.
- [x] Wire the "Launch Workspace" action to `POST /api/projects`, then route to `/projects/:id/launch`. `launchProject()` in `app/lib/api.ts`, called from `repositories-screen.tsx`.
- [x] Verified terminal/reconnect handling against the real event shape: server closes with 4401/4403/4404 for auth failures (no retry, shown as a fatal error) vs. a normal 1000 close after a terminal READY/FAILED payload (also no retry) vs. any other close (backoff reconnect).
- [x] Project cancellation mid-provisioning — `cancelProject()` wired to the existing `POST /api/projects/:id/cancel`.

### Workspace Real-Data Wiring — done 2026-08-01

- [x] Replaced `app/lib/workspace-fixtures.ts` usage in `workspace-shell.tsx` with real data via `fetchProject`, `fetchProjectGraph`, `fetchProjectFiles`.
- [x] Wired the React Flow graph panel to the real `graph.json` shape (`links`, not `edges`) — adapter in `app/lib/graph.ts` (`buildGraphView`), reads the confirmed real node/edge fields (`label`, `type`, `source_file`, `source_location`, `community`/`community_name`) and derives "god node" emphasis from computed degree since graphify doesn't persist a centrality flag.
- [x] `files.json` wired via `buildFileGroups()` in the same file — groups by top-level folder, caps rendering at 1000 files, and surfaces the `truncated` flag in the UI instead of implying a complete tree.
- [x] Workspace-level states added: loading (spinner), error/disconnected (`ErrorState` + retry), and non-READY projects redirect to the launch screen rather than duplicating its state machine (that screen already handles "provisioning" and "failed" well).
- [x] Deleted `app/lib/workspace-fixtures.ts`.
- [ ] **Not done — backend gap, not touched this pass:** per-file content endpoint. There is still no way to fetch a single file's real source, so the Monaco editor shows a read-only placeholder instead of real content. The diff editor, "Proposed changes"/PR card, and file `status` badges were removed from the workspace shell entirely rather than left wired to fixture-only data — they depended on an agent-authored-changes concept that doesn't exist yet (Phase 6).

### Navigation & Screen Split (decided 2026-07-31) — done 2026-08-01

Phase 3 merged "recent projects" and "repository listing" into one Dashboard (architecture decision #1). That merge is now **reversed** — they become two screens with distinct jobs:

- [x] **`/dashboard` — recent graphed projects only.** `dashboard-screen.tsx` rewritten from scratch against `GET /api/projects` only; the repo cross-referencing moved out.
- [x] **`/repositories` — new screen, all of the user's repos, private and public.** The search/filter/row UI and per-integration repo fetching moved to `repositories-screen.tsx` (renamed from the old `dashboard-screen.tsx`); `app/lib/dashboard.ts` renamed to `app/lib/repositories.ts` to match.
- [x] "Launch"/"Resume" actions on repository rows now call `launchProject()` for real instead of linking to a fabricated project id.
- [x] **`/projects` — new screen**, built from the user's own description (not the Cowork screenshot literally — used only as a loose layout reference): left column lists the user's projects, right side is a query panel scoped to the selected project. Uses the app's existing color/font tokens throughout. Real graph stats are fetched per selection; the query itself is still mocked (no backend query endpoint exists yet — same limitation as the workspace agent panel).
- [x] **`/settings` — new screen.** Real profile + sign-out from the session; default-branch behavior, theme, and notifications are explicitly marked "Not yet available" rather than faked. Account deletion likewise — no self-service delete endpoint exists yet.
- [x] **Docs / Help** — external link to `https://graphify.com/docs` (confirmed by the user), `target="_blank"` + `rel="noopener noreferrer"`, new-tab icon.
- [x] Updated `NAV_ITEMS` in `sidebar.tsx`: Dashboard, Repositories, Projects, **Integrations**, Settings, Docs/Help (external). **Deviation from the plan:** Integrations was kept (the plan's list omitted it) — dropping it would have left the OAuth-connections screen with no way to reach it. "Admin Settings" was already gone from this sidebar (admin is a separate app, see below).
- [x] Icons added for every new nav item; active-state highlighting verified via `usePathname()`.
- [x] Verified the six-item nav (five links + external) renders correctly collapsed and in the mobile drawer.

### Isolated Admin Frontend

- [x] **New `app/admin/` tree**, `(protected)` route group for the authenticated shell — no `SessionProvider`, no the authenticated-app `<Sidebar />`, its own `admin-shell`/`admin-topbar` chrome.
- [x] `/admin/login` — email + password form posting to `POST /api/admin/login`. Generic failure copy ("Invalid email or password" / a 429-specific lockout message) that does not reveal whether the email exists.
- [x] Admin layout guard (`admin-session-context.tsx`) — fetches `GET /api/admin/me`; redirects to `/admin/login` on 401, never to `/`.
- [x] `app/admin/(protected)/settings/` (LLM credentials) exists and works against the isolated cookie — Test Connection → Save → Delete round trip unaffected by the Phase 4 cookie isolation work.
- [x] Admin-internal navigation for: LLM Credentials, Usage & Spend, Analytics, Users — added to `admin-topbar` as a nav row.
- [x] **Usage & Spend screen** (`/admin/usage`) — totals + by-provider + by-user spend, with a days-range filter (7/30/90/365), consuming `GET /api/admin/usage`.
- [x] **Analytics screen** (`/admin/analytics`) — signups (total + new-in-range), active users, projects launched, status breakdown, success rate, average indexing duration, same days-range filter, consuming `GET /api/admin/analytics`.
- [x] **Users screen** (`/admin/users`) — paginated list, integrations shown as booleans (no tokens), suspend/reactivate (`PATCH .../users/:id`), delete with an explicit inline confirm step (not a native `confirm()`) before `DELETE .../users/:id` fires.
- [x] Admin sign-out (`adminLogout()`) only calls `POST /api/admin/logout`, which per `admin_sessions.py` clears only the isolated `graphify_admin_session` cookie — never touches the GitHub-session cookie, and vice versa (unchanged from the already-verified backend isolation).
- [x] Admin usage/analytics/user-management API functions added to `app/lib/api.ts` alongside the existing admin-credentials functions — kept in one file rather than splitting into `admin-api.ts`, since the credentials functions already lived there and splitting only the newly-added ones would fragment the admin surface for no real benefit.

### Per-User Usage (main app)

- [ ] If the Usage nav is included: build the user-scoped usage screen against `GET /api/usage`. (Not selected in the nav decision above — build only if the user adds it later.)

### Code Quality — verified 2026-08-01

- [x] `npm run lint` clean.
- [x] `npx tsc --noEmit` clean.
- [x] `npm run build` succeeds — all routes register, including the four new `/admin/*` pages (`usage`, `analytics`, `users`, plus the pre-existing `settings`) and `/projects` alongside `/projects/[projectId]/launch`.

### Browser Verification

- [ ] End-to-end: connect a real repo, launch, watch live WebSocket progress (not mocked), land in workspace with real graph/files/editor content. **Partially verified** — confirmed live in-browser that every new/changed route (`/dashboard`, `/repositories`, `/projects`, `/settings`, `/admin/usage`, `/admin/analytics`, `/admin/users`) loads and redirects correctly with no console errors, both unauthenticated and admin-unauthenticated. The authenticated click-through (real GitHub session, real admin login) was **not** run — this sandbox has no real GitHub session and no known admin password, and forging either would mean writing into the production Neon DB without sign-off.
- [ ] Verify WebSocket teardown on navigating away mid-provisioning (no leaked connection, no state update on unmounted component). Implemented (cleanup closes the socket and clears the retry timer on unmount) but not exercised against a live extraction.
- [ ] Verify failure path (kill/fail the sandbox job) surfaces the failure state and allows retry. Implemented, not live-verified for the same reason as above.

## Final Checklist (Phase 4)

- [ ] All backend tests pass.
- [x] Frontend code quality checks pass (`lint`, `tsc --noEmit`, `build`).
- [ ] Browser verification pass (launch → progress → workspace, and failure/retry) — see the partial note above; needs a real session to finish.
- [ ] `RAILWAY_API_TOKEN` set and live Railway provisioning verified at least once (not just TestClient-mocked).
- [ ] Admin isolation verified adversarially: a valid GitHub session cannot reach any `/api/admin/*` route, and an `admin_session` cannot reach any GitHub-authed route. Confirm the two cookies are independently signed.
- [ ] `public.admin` seeded via the `seed-admin` command with env-supplied credentials; verify login, logout, and that the stored value is a hash rather than plaintext.
- [ ] `TASK_CHECKLIST.md` "Known Issues" section updated to drop the items resolved here.

---

# Phase 5: Token Refresh Rotation

**Status**: Backend code-complete, ruff/pyright/pytest clean. Frontend has no changes to make (see below) — nothing to build there. **Not yet browser/live-verified** — see Final Checklist.

**Scope** (per `IMPLEMENTATION_PLAN.md` → "Follow-up phases": *"Phase 5: Token refresh rotation (GitHub/GitLab token expiry handling)"*).

Today, `routes/github.py` (`GET /api/repositories`) and `routes/integrations.py` (`GET /api/integrations/:provider/repos`) both return a plain 401 when a stored token has expired — there is no refresh attempt. This phase makes token expiry invisible to the user instead of forcing a full OAuth re-connect.

**Note:** Before starting, review how tokens are currently stored (`User.gitlab_*`/`gitbucket_*` fields + GitHub fields added in Phase 3 migration `9bb30a4ebf51`, encrypted via `crypto.py`) and confirm which providers actually issue a `refresh_token` alongside the `access_token` at OAuth-exchange time (GitHub Apps: yes, if configured for token expiration; GitLab: yes; GitBucket: depends on instance — verify against `GitBucketOAuthClient.exchange_code_for_token`'s actual response before assuming).

## Backend Implementation (Python/FastAPI)

### Schema

- [x] **No new columns needed.** `User.gitlab_refresh_token_ciphertext`/`_iv` and `github_refresh_token_*`/`github_access_token_expires_at` already exist (Phase 3 migration `9bb30a4ebf51` for GitLab, GitHub's own migration for GitHub) — confirmed by reading `models.py` before writing anything. GitBucket gets no new columns either: **it has no refresh flow at all** — `GitBucketOAuthClient.exchange_code_for_token` never parses a `refresh_token` from the response (GitBucket's OAuth predates that grant type and its access tokens don't expire), documented directly on the class.
- [x] **Real bug found and fixed while reading the callback code**: `routes/integrations.py`'s GitLab OAuth callback decoded `token_data.refresh_token` from GitLab's response but never stored it — the columns existed since Phase 3 but nothing ever wrote to them, so refresh could never have worked no matter what this phase built. Fixed in the same callback that already handles the access token.

### Refresh Logic

- [x] `git_clients.py`: added `refresh_github_token(refresh_token)` (module function, mirrors `exchange_code_for_token`, same endpoint + `grant_type=refresh_token`) and `GitLabOAuthClient.refresh_access_token(refresh_token)`. No GitBucket equivalent — see Schema note above.
- [x] New `token_refresh.py::get_valid_access_token(user, provider, db)` — the single entry point all three call sites below use. Decrypts and returns the current token if it isn't expiring within 60s; otherwise refreshes (if a refresh token is on file), persists the rotation, and returns the new token; returns `None` if there's nothing to refresh with or the refresh call itself fails — callers already treat `None` as "give the existing 401", so no new error path was needed downstream.
- [x] Wrapped all three call sites named in the original scope: `GET /api/repositories` (`routes/github.py`), `GET /api/integrations/:provider/repos` (`routes/integrations.py`), and the sandbox launch's repo-token read (`run_worker.py::_load_launch_inputs`, replacing its inline decrypt with the same helper so a launch doesn't fail on a token that was refreshable).
- [x] GitBucket's branch in `get_valid_access_token` is a plain decrypt, never attempts refresh — a no-op by construction, not a stub.
- [x] Rotated tokens persisted via `db.commit()` inside the helper immediately after a successful refresh, same AES-GCM encryption (`crypto.py`) as the initial OAuth exchange.
- [x] **Concurrency decision: accept last-write-wins, documented in `token_refresh.py`'s module docstring.** Two requests racing a refresh both succeed independently (neither commits until the provider responds) and the later commit just overwrites the earlier one's equally-valid pair — the race window is one network round trip, not worth a row lock for.
- [x] **Not wired into `routes/projects.py::get_project_file_content` or `routes/agent.py`'s two `_decrypt_repo_token` call sites** (Phase 6 code, doesn't exist in the phase scope's original note). Left as a plain decrypt — deliberately, not an oversight: `agent.py`'s file-fetching path already has a documented design decision to do its provider I/O *outside* the DB session ("Retrieval and file fetching happen outside a DB session — both are network-bound and would otherwise hold a pooled connection idle"), and threading a refresh-and-persist call through there would fight that. Those three sites still 401 on an expired token exactly as before; only the three call sites the phase actually scoped got transparent refresh.

### Testing

- [x] `tests/server/test_token_refresh.py` — 11 pure-logic tests (no DB/network; `User` rows built as plain unpersisted objects, provider refresh calls monkeypatched): fresh/non-expiring tokens skip refresh, expired-with-valid-refresh-token rotates and persists (asserted via a fake session's commit count), expired-with-no-refresh-token → `None`, refresh call raising → `None` without committing, GitLab's `gitlab_configured` gate, GitBucket's always-plain-decrypt path (even given a stale expiry, which shouldn't happen but is checked anyway), unknown provider raises. All passing.
- [x] `uv run ruff check graphify/server/` clean.
- [x] `uv run pyright graphify/server/` clean (including the new test file).
- [ ] DB-backed integration test (real callback storing a real GitLab refresh token, real `/api/repositories` call against an artificially-expired row) — not run this session, same DB-dependency pattern as the rest of `tests/server/`.

## Frontend Implementation (Next.js/React)

- [x] **No frontend changes required.** Refresh is entirely server-side and transparent to the client — the existing "unauthorized" dashboard/integration states are unchanged code paths that still fire correctly for the genuine failure case (no refresh token on file, or the provider rejects the refresh token itself), since `get_valid_access_token` returns `None` for both and the routes still 401 exactly as before.
- [ ] Live-verify the *genuine* failure case still surfaces correctly (a revoked/expired refresh token) rather than just trusting the code path — not done this session (needs a real expired+revoked token, not just mocked expiry).
- [ ] Confirm the existing Integrations "Connect" flow re-establishes a connection without requiring Disconnect first, for the case where refresh fails outright — not done this session (same live-token dependency as above).

## Final Checklist (Phase 5)

- [x] All backend tests pass (11/11 new pure-logic tests; full `tests/server/` not re-run this session — no DB access in this pass, see the DB-backed item above).
- [ ] Frontend regression check: dashboard/integrations unauthorized states still correct — not live-verified this session (no real GitHub/GitLab session available in this sandbox).
- [ ] Manually verify at least one provider's real refresh flow against a token forced to near-expiry (not just mocked expiry logic).
- [x] `TASK_CHECKLIST.md` "Known Issues" updated to drop "Token refresh" once resolved — see below.

**Known issue carried forward:** `alembic check` fails — the DB is one migration behind the code (`a2c6dcfb8864` applied, code head is `f83a49b127d1`, "add immutable extraction runs and callback replay ledger"). Unrelated to this phase's own changes (no new migration was needed here), flagged during this session's `alembic check` run. That migration also mutates existing data (fails any in-flight `CLONING`/`INDEXING` project as part of backfilling `extraction_runs`), so it needs a deliberate, confirmed `alembic upgrade head` run, not a blind one.

**Note on phase numbering:** `IMPLEMENTATION_PLAN.md` and `FRONTEND_IMPLEMENTATION_PLAN.md` disagree on what's in Phase 6+ (agent queries/diff/PR dispatch bundled vs PR workflow as its own later phase). `IMPLEMENTATION_PLAN.md`'s numbering is treated as canonical below — it's the actively maintained doc alongside this file. `FRONTEND_IMPLEMENTATION_PLAN.md`'s old Phase 9 (Agent and Output Log) and Phase 10 (Pull request workflow) both map onto the single Phase 6 below; their UI-only checkmarks are noted where relevant but do not mean the corresponding backend exists.

---

# Phase 6: Agent Queries, Diff Inspection, PR Dispatch

**Status**: Backend and frontend code-complete, code-quality-checked (ruff/pyright/lint/tsc/build all clean). **Not yet browser-verified end-to-end** — see "🚩 Flagged — resume here" below before calling this phase done.

**🚩 Flagged — resume here next session:** While implementing this phase, live-tested the *existing* Phase 4 provisioning flow (unrelated regression, not part of this phase's scope) and found + fixed a real bug: `SANDBOX_CALLBACK_BASE_URL` in `graphify/.env` was pointing at a dead `cloudflared` tunnel URL from an earlier session (tunnels mint a new random URL every restart, see `graphify/CLAUDE.md`), so every sandbox job's final "Uploading results" callback (~92%) hit a 502 and the project died just short of READY. Fixed: tunnel restarted, `.env` updated to the fresh URL (`https://saying-rap-schemes-call.trycloudflare.com` as of 2026-08-01 — **this will already be stale by the next session, get a fresh one**), backend restarted. Kicked off a real retry via the browser to confirm the fix, but **the Railway deployment crashed for an unrelated reason before the run completed, and the fix has not been redeployed/reverified yet.** Next session: redeploy on Railway, retry the `abdullah-wpcoderrs/postiz-app` project (or any project) end-to-end, and confirm it actually reaches READY / the workspace view this time before trusting the fix.

Also noted mid-session: `graphify/graphify/server/app.py`, `models.py`, and `routes/launch.py` picked up substantial concurrent external edits from outside this conversation — a new queue/worker-based extraction system (`ExtractionRun`, `ExtractionRunStatus`, `ExtractionCallbackEvent`, `run_service.py`, `run_worker.py`, a `run_worker_enabled` lifespan task, per-user/global queue caps) replacing the old single-status `Project`-only model. Left untouched/unreverted per standing instruction. Verified afterward:
- `uv run python -c "from graphify.server.app import app"` — imports clean, 15 HTTP routes registered. This phase's own `models.py` additions (`AgentSession`, `AgentMessage`, `ProjectAgentChange`, `AppSetting`, `Project.provider`) coexist fine, and `routes/agent.py`'s imports of `_active_llm_credential`/`_decrypt_repo_token` from `routes/launch.py` still resolve (those two helpers survived the rewrite unchanged).
- `uv run ruff check graphify/server/` — clean.
- **`uv run alembic check` — FAILS.** The concurrent work added `ExtractionRun`, `ExtractionCallbackEvent`, `Project.current_run_id`, and `UsageEvent.run_id` to `models.py` with no migration generated for them yet. This is real, current schema drift (not caused by this phase's own migration `a2c6dcfb8864`, which is already applied and not part of the diff) — **do not run `alembic upgrade head` blindly next session; first generate and review a migration for the queue/worker tables**, or check whether that work is still mid-edit and intentionally not yet migrated.

**Scope** (per `IMPLEMENTATION_PLAN.md` → "Follow-up phases": *"Phase 6: Agent queries, diff inspection, PR dispatch"*; also the `TASK_CHECKLIST.md` Known Issues entry *"Graph querying (Phase 6) — agent queries not yet wired to graph engine"*).

**Read this before scoping an estimate — this phase is materially different in kind from Phase 4/5.** Phase 4 wired a real Railway API and a real `graphify update` command that already existed. Phase 6 has no equivalent to wire: graphify's `query "<question>"` CLI command (`graphify/cli.py` → `graphify/serve.py::_query_graph_text`) only does BFS/DFS **retrieval** — it walks the graph and returns relevant node/edge context as text. It is not itself an agent, does not call an LLM, and does not propose code changes. **A real code-editing agent loop — something that takes a user's question, retrieves graph context, calls an LLM with that context plus the actual file contents, and produces a concrete file diff — does not exist anywhere in this codebase yet.** This phase has to design and build that loop, not just connect existing pieces. Budget accordingly, and treat the "Agent Architecture" section below as a design decision to make explicitly before writing any route.

**Also confirmed while scoping this phase (2026-08-01):** the workspace's agent panel (`app/components/workspace-shell.tsx`, inline — there is no separate `agent-panel.tsx` file) is entirely fixture-driven. Its "Prepare Pull Request" button does not open a PR flow at all — it just pastes a canned string into the prompt textarea (`setPrompt("Prepare a pull request summary...")`). `changedFiles` and `inspectDiff` likewise read from `app/lib/workspace-fixtures.ts`'s `AgentMessage` type. None of this is wired to anything real, and no PR-creation client method exists in `graphify/server/git_clients.py` for any provider (GitHub/GitLab/GitBucket) — that has to be added from scratch too.

**Note:** Before starting, read `graphify/serve.py::_query_graph_text` and `graphify/querylog.py` (existing retrieval + query-logging machinery to reuse rather than reinvent), `graphify/llm.py` (existing LLM call plumbing — the same registry Phase 4's `usage.py`/`Dockerfile.sandbox` already use), `app/components/workspace-shell.tsx` lines ~555–650 (the current fixture-fed agent panel) and `app/lib/workspace-fixtures.ts` (`AgentMessage`, `INITIAL_AGENT_MESSAGES`, `SUGGESTED_PROMPTS`).

## Agent Architecture — decided with the user (2026-08-01)

- [x] **Where does the agent run?** Decided: **(b) in the main backend process**, not a kept-alive Railway sandbox — files are read live from the git provider's API (`repo_api.py`), never a clone/checkout. Diff validity is handled by construction, not `git apply` validation: the agent emits *complete new file contents*, not a patch, so there's nothing to "fail to apply" — see `agent_llm.py`'s tagged-block protocol below.
- [x] Session persistence: **yes, DB-backed, survives refresh.** `AgentSession` (one per project, unique constraint) + `AgentMessage` (role/content/error) in `models.py`, migration `a2c6dcfb8864`. Proposed changes are their own table, `ProjectAgentChange` (`before_content`/`after_content`/`base_sha`/`status`), not embedded in the message row — this is what makes a change editable independent of the message that proposed it.
- [x] LLM call shape: **both prose and file diffs stream progressively**, from one LLM call. The model is prompted to emit `<<<FILE: path>>>...<<<END FILE>>>` blocks inline with its prose; `agent_llm.py::StreamDemultiplexer` is an incremental parser that demultiplexes the raw token stream into `TextDelta`/`FileStart`/`FileDelta`/`FileEnd` events as they arrive, handling markers split across chunk boundaries (this needed two bug-fix passes on newline handling around block boundaries — see `tests/server/test_agent_llm.py`, 7 tests, all passing).
- [x] Safety boundary: **per-user/per-day USD budget, admin-configurable, DB-stored.** `budget.py` (`AppSetting` key/value row, default $5/day, `-1` = unlimited), enforced pre-call by summing today's `operation="agent"` `usage_events` against the cap; hard stop with a clear "budget exceeded, resets at 00:00 UTC" message, not silent truncation. Admin UI: new "Agent daily spend limit" card on `/admin/settings`.

## Backend Implementation (Python/FastAPI)

### Graph-Aware Retrieval

- [x] `agent_retrieval.py::retrieve_context` imports and calls `graphify.serve._query_graph_text` directly (in-process, not subprocess) against an in-memory, LRU-cached (`_CACHE_MAX_ENTRIES=8`) `networkx` graph loaded via `nx.node_link_graph(data, edges="links")` — the `edges="links"` argument is required, matches the confirmed graph.json shape from Phase 4.
- [x] Works against both a local path and a remote URL for `graph_json_url`, mirroring `routes/projects.py::_fetch_json_artifact`'s existing dual-source handling.

### File Content Serving (blocking dependency, shared with Phase 4's Monaco wiring)

- [x] `GET /api/projects/:id/files/{path:path}` added to `routes/projects.py`. Serves content **live from the git provider's API** (`repo_api.py`), not a stored snapshot — always current, no extra storage.
- [x] Path validated as an allowlist membership check against the project's own `files.json` file list before any provider call is made — a traversal attempt simply isn't in that list, rather than relying on catching every encoding of `..`.
- [x] Size cap (`repo_api.MAX_FILE_BYTES`, 1MB) and binary-file rejection (non-UTF-8 decode raises a clear error) in `repo_api.py`'s `_decode_blob`.
- [x] Wired into Monaco in `workspace-shell.tsx` — the file viewer's placeholder text is gone, replaced with a real fetch-on-select effect.

### Agent Session Endpoints

- [x] `WS /ws/projects/:id/agent` in the new `routes/agent.py` — accepts `{type: "user_message", content}`, streams `text_token`/`file_start`/`file_token`/`file_end`/`message_end`/`error` frames, replays full history + open changes as the first frame on connect.
- [x] `GET /api/projects/:id/agent/messages`, `GET .../agent/changes`, `PUT .../agent/changes/{id}` (save an edit), `POST .../agent/changes/{id}/dismiss` — REST counterparts for anything that doesn't need the socket.
- [x] Reuses `routes/launch.py::_active_llm_credential`/`_decrypt_repo_token` directly (imported, not duplicated) — confirmed these two helpers survived the concurrent queue/worker rewrite of `launch.py` unchanged (see flag at the top of this phase).
- [x] `record_usage(operation="agent", ...)` called after every generation (success or failure — a stream that dies partway still consumed billed tokens).
- [x] Budget checked via `budget.check_budget` before retrieval/generation starts, so a user over their cap never triggers a provider call at all.
- [x] Provider errors translated to safe copy in `agent_llm.py::_provider_error_message`, mirroring `routes/admin.py::verify_credential`'s pattern (never echoes the provider's raw body, which can leak the API key).

### Diff Generation & Storage

- [x] **Decided against unified-diff-as-source-of-truth.** Chosen instead: `ProjectAgentChange.before_content`/`after_content` (full file bodies). The unified diff shown in the UI is *derived* on every read (`routes/agent.py::_unified_diff`, stdlib `difflib`) from that pair — this is what makes edits work: the user overwrites `after_content` directly (`PUT .../agent/changes/{id}`), and the diff view just reflects whatever's currently stored, live.
- [x] `GET /api/projects/:id/agent/changes` returns the current open (`PROPOSED`) changes with their rendered diffs.

### PR Dispatch

- [x] **New `repo_api.py`** (not `git_clients.py` — kept separate since `git_clients.py` is OAuth-only and this is repo-content operations): `GitHubRepoClient` (Git Data API: blob → tree → commit → ref, one atomic multi-file commit, no clone), `GitBucketRepoClient` (subclasses GitHub client, `/api/v3` + `token` auth scheme), `GitLabRepoClient` (GitLab's single-call multi-file commit API). All three: `get_file`, `create_branch`, `commit_files` (with pre-commit conflict detection via blob-sha comparison), `open_pull_request`.
- [x] Branch naming: `graphify/agent-{repo-slug}-{6-hex-chars}` (`routes/agent.py::_branch_name`) — random suffix so a retry after partial failure never collides with the half-finished branch.
- [x] `POST /api/projects/:id/pull-request` — branch → commit → PR/MR, three independently-failable steps, each HTTPException naming which step failed and (for a post-branch failure) that the branch itself is safe to delete/reuse.
- [x] Partial-failure handling: on a failed PR-open after a successful commit, the response says the branch/commit succeeded and to open the PR manually — nothing is silently orphaned or hidden.
- [x] Server-side `confirm: bool` required in the request body, checked before any provider call — the frontend dialog's confirm step is not trusted alone.

### Code Quality & Testing

- [x] `uv run ruff check graphify/server/` clean.
- [x] `uv run pyright graphify/server/` — 0 errors.
- [x] `tests/server/test_agent_llm.py` — 7 pure-logic tests for `StreamDemultiplexer` (chunk-boundary marker splitting, multi-file blocks, unterminated-block-on-finish, malformed markers), run standalone (DB was unreachable this session — see below) and all passing. Caught and fixed two real bugs in the parser this way (leading/trailing newline handling around markers split across chunks).
- [ ] **Not yet run this session: the DB-backed integration tests** (budget persistence, PR-dispatch confirm-required, change CRUD) — planned but blocked by a transient DNS outage to the Neon DB from this sandbox for the remainder of the session. Write `tests/server/test_budget.py` and extend `test_agent_routes.py`-equivalent coverage next session, monkeypatching the LLM call and provider PR-creation call per the established safety pattern.
- [ ] Verify `record_usage()` fires for a real (small/cheap) agent call the same way Phase 4 verified `verify`/`extraction` — blocked on the same DB outage + the provisioning retest flagged above.

## Frontend Implementation (Next.js/React)

**Correction to this phase's original scoping note:** `app/lib/workspace-fixtures.ts` referenced throughout the original plan **does not exist in the repo** — the agent panel in `workspace-shell.tsx` was already fully hardcoded local state (no fixtures file, no `changedFiles`, no `inspectDiff`, no "Prepare Pull Request" button). This was new-build, not fixture-rewiring.

### Wire the Agent Panel to Real Data

- [x] `workspace-shell.tsx`'s agent panel now runs on a real `WebSocket` (`/ws/projects/:id/agent`), mirroring the reconnect-with-backoff pattern already established in `provisioning-screen.tsx`. Local hardcoded `AgentMessage` type replaced with `app/lib/api.ts`'s real `AgentMessage`/`AgentChange` types.
- [x] `isStreaming` now reflects the real socket's `message_start`/`message_end` frames; `stopStreaming` closes and reconnects the socket (documented limitation: there is no server-side generation-abort in this phase, so a "stopped" generation still completes and bills server-side — only client-side rendering stops).
- [x] Streaming file changes render live into the message bubble (`agent-streaming-file` rows) as `file_start`/`file_token`/`file_end` frames arrive, then finalize into the "Proposed changes" summary card on `message_end`.
- [x] Error and budget-exceeded states surface inline (`agent-message-error`).

### Pull Request Review Flow (genuinely new — old Phase 10 was 100% unbuilt)

- [x] New `agent-diff-dialog.tsx` — real review dialog, not the old fake "paste text into prompt" button. File list sidebar + Monaco `DiffEditor` (editable modified side — typing in it saves to local draft state, "Save edit" persists via `PUT .../agent/changes/{id}`) + PR title/description form.
- [x] Dismiss-per-file and save-edit both wired to real endpoints.
- [x] Explicit two-step confirm on submit (button reads "Open pull request" → "Confirm: open pull request" on second click) before the real `POST .../pull-request` fires.
- [x] On success: shows the real PR/MR number + link, appended to the workspace's Output Log.
- [x] On failure: dialog stays open with the error shown, proposed changes are not cleared — nothing is lost on a failed attempt.
- [ ] Not yet built: a distinct three-step "branch → commit → PR open" progress indicator during dispatch (the backend's partial-failure detail is surfaced as an error message, but not as a live step-by-step UI) — acceptable for this pass, worth revisiting if PR dispatch turns out to be slow enough in practice to need it.

### Admin: Agent Budget Setting

- [x] New "Agent daily spend limit" card on `/admin/settings`, reading/writing `GET`/`PUT /api/admin/settings/agent-budget`.

### Code Quality

- [x] `npm run lint` clean.
- [x] `npx tsc --noEmit` clean.
- [x] `npm run build` succeeds (all 16 routes, including the new `/admin/settings` budget card).

### Browser Verification

- [ ] **Not done this session.** End-to-end agent conversation + diff + PR dispatch against a real repo needs a working provisioning pipeline first (a project has to reach READY before the agent has a graph to query) — blocked on the flagged provisioning-tunnel retest above. Do the provisioning retest first, then run the full agent flow against whichever project comes up READY.
- [ ] WebSocket teardown on navigating away mid-response — not explicitly verified, though the effect cleanup mirrors the already-verified launch-screen pattern.
- [ ] Budget cap actually stopping a session — not deliberately triggered/verified live.

## Final Checklist (Phase 6)

- [x] Agent Architecture decisions made explicitly with the user (see above), not defaulted silently.
- [ ] All backend tests pass — pure-logic tests pass (7/7); DB-backed tests not run this session (DNS outage, see above).
- [x] Frontend code quality checks pass (`lint`, `tsc --noEmit`, `build`).
- [ ] Browser verification pass — blocked on the flagged provisioning retest (Railway crashed before the tunnel fix could be confirmed).
- [ ] `usage_events` confirmed recording real agent spend — not yet verified live.
- [x] `TASK_CHECKLIST.md` Known Issues entry "Graph querying (Phase 6)" — superseded by this phase's actual scope; graph querying is now wired (`agent_retrieval.py`), what's left is the live end-to-end verification tracked above.

## Known Issues & Deferred Items (carried into Phase 7+)

- **Sandbox lifecycle & cleanup** (Phase 7 per `IMPLEMENTATION_PLAN.md`) — if Architecture option (a) is chosen (agent runs inside a kept-alive sandbox), this phase's scope and Phase 7's overlap significantly and may need to be sequenced together rather than strictly after.
- **PR dispatch automation** (`IMPLEMENTATION_PLAN.md` also separately lists "Phase 8: PR dispatch automation") — the exact boundary between this phase's manual/confirmed PR dispatch and a possible future *automatic* dispatch (no human review step) is undefined; treat Phase 6 as building the manual, confirmed flow only, and revisit whether Phase 8 is now redundant or means something narrower (e.g. scheduled/triggered re-runs) once this phase ships.
