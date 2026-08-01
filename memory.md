# Memory — Graphify Phase 4 Backend: COMPLETE (Admin Auth, Railway Sandbox, Usage Tracking, Tests)

Last updated: 2026-08-01

## Status in one line

The entire Phase 4 **backend** is built, live-tested against the real
Neon DB, and proven end-to-end against the real Railway API — including a
full real launch (repo → Railway container → extraction → graph uploaded →
READY). AI spend tracking and a 63-test automated suite were added after
that. **Nothing left on the backend side except optional follow-ups** (see
below). The Phase 4 **frontend** has not been started at all.

See `graphify/CLAUDE.md` for the operational how-to (restart the server,
rebuild/push the sandbox image, run migrations, run tests, debug Railway
directly) — this file is the narrative history; that one is the reference
card.

## What was built

**Isolated admin authentication** (separate from GitHub-user auth entirely):
- `graphify/graphify/server/models.py` — `Admin` model (own table), `UsageEvent`
  model, `is_active` on `User`, provisioning-progress columns on `Project`.
- `graphify/graphify/server/admin_sessions.py` — argon2 hashing, `get_current_admin`
  dependency, `graphify_admin_session` cookie. Isolated from user sessions via
  3 independent things: separate secret, separate itsdangerous salt, separate
  cookie name.
- `graphify/graphify/server/routes/admin_auth.py` — login (5-attempt lockout,
  uniform error message, timing-equalized), logout, me.
- `graphify/graphify/server/routes/admin.py` — re-gated onto `get_current_admin`.
  `Role.ADMIN` on `User` is now informational only.
- `graphify/graphify/server/routes/admin_data.py` — usage/analytics/users endpoints.
- `graphify/scripts/seed_admin.py` — reads `ADMIN_EMAIL`/`ADMIN_PASSWORD` from
  real env vars or `graphify/.env` directly. Idempotent (re-run = password reset).

**Project launch + WebSocket streaming:**
- `graphify/graphify/server/routes/launch.py` — launch, cancel, status callback,
  artifacts upload, usage report, WebSocket progress stream (polls the DB row,
  1s interval — correct across reconnects/multi-replica, unlike an in-memory bus).
- `graphify/graphify/server/config.py` — all the new settings, incl.
  `sandbox_callback_base_url` (deliberately separate from `backend_url`).
- `graphify/graphify/server/sandbox.py` — the real, working Railway GraphQL client.

**Sandbox container:**
- `graphify/Dockerfile.sandbox` + `graphify/scripts/sandbox_entrypoint.py` —
  clones, runs `graphify update` (+ `graphify label` if a key is present),
  builds `files.json`, uploads both artifacts, reports progress throughout.

**AI usage/cost tracking** (added after Railway was proven working):
- `graphify/graphify/server/usage.py` — `record_usage()` + `estimate_cost()`
  (maps the UI's `"anthropic"` to llm.py's `"claude"` pricing key).
- Wired into **two** real call sites:
  1. Admin credential verify (`routes/admin.py`) — parses the real `usage`
     field from the OpenAI/Anthropic API response.
  2. Sandbox community labeling — graphify already writes
     `Token cost: N input · M output` into `GRAPH_REPORT.md`
     (`label_communities()`'s `usage_out` param); the entrypoint parses that
     line (`parse_token_cost()`) and POSTs it to a new endpoint,
     `POST /api/internal/projects/{id}/usage`.

**Automated tests** (first FastAPI-server coverage this project has had):
- `graphify/tests/server/` — 63 tests, all passing. 42 pure-logic (no DB/network:
  config validation, cookie isolation, cost math, sandbox entrypoint parsing/
  URL-building). 21 integration, against the **real Neon DB**
  (`test_launch_routes.py`, `test_admin_routes.py`): login/lockout/isolation,
  launch validation + 409 duplicate guard, callbacks, real WebSocket connections.
- **Safety property, load-bearing if this suite is ever extended:** the dev DB
  has a real OpenAI key and real Railway credentials configured. Tests never
  call either for real — anything that would spend money or deploy a
  container is monkeypatched. Verified zero leftover test rows after a run.

**Migrations:** `c7f2a91be4d3` (admin table), `d4e8b2317ac6` (usage_events +
progress columns + users.is_active). **Applied to the real Neon DB.**
`alembic check` confirms no drift.

**Docs added:** `graphify/docs/railway-setup.md` (full account/service setup,
GHCR push walkthrough, container-testing steps), `graphify/CLAUDE.md`
(operational reference — commands to restart/rebuild/test/debug), both
`.env.example` files updated with every new var and why it exists.

## Decisions made

- **Admins are a separate principal, not a `User` with a role flag.** No
  GitHub identity, own login, own cookie — a compromised or self-registered
  GitHub account must never become an admin.
- **`sandbox_callback_base_url` is separate from `backend_url`.** In local
  dev they must differ (OAuth + cookie `Secure` flag vs. what a Railway
  container can actually reach). Same origin in production; sandbox var left
  unset there.
- **WebSocket progress polls the DB, not an in-memory event bus** — correct
  across reconnects and multiple backend instances.
- **Progress transport is push** (sandbox → backend callback), not backend
  polling Railway's API.
- **User/admin suspension is enforced on every request**, not just at login.
- **Sandbox AI spend is read from `GRAPH_REPORT.md`**, not recomputed —
  graphify already tracks it; the entrypoint just surfaces the number.
- **Confirmed graph.json shape** (from a real extraction run): networkx
  node-link format. Connections are under **`links`, not `edges`** — matters
  for whoever wires the React Flow graph panel.
- **`files.json` shape** (sandbox-entrypoint artifact, not from graphify
  itself): `{files: [{path, size}], count, truncated}`.
- **Integration tests use the real Neon DB, no SQLite fallback** — the
  models use Postgres-specific column types. Tests are made safe via
  monkeypatching anything that would reach a paid API or Railway, not by
  avoiding the real DB.

## Problems solved (roughly chronological)

- **`python-multipart` was missing** — FastAPI raises at import time when a
  route declares `UploadFile` without it; the app wouldn't have started.
- **Reused-secret footgun** — startup validator now refuses to boot if
  `ADMIN_SESSION_SECRET` collides with either other secret.
- **`seed_admin.py` only read `os.environ`** but docs said to use `.env` —
  fixed with a custom `.env` reader.
- **`graphify extract` doesn't exist** — real command is `graphify update`.
- **graphify doesn't emit `files.json`** — built in the sandbox entrypoint instead.
- **The ephemeral container had nowhere to persist output** — added the
  artifacts-upload endpoint.
- **A running server does not pick up edited `.py` files** (no `--reload`) —
  cost real time chasing a "silently broken" container that was actually
  just talking to stale backend code. Now documented prominently in
  `graphify/CLAUDE.md`'s first section.
- **The first `serviceInstanceDeploy` GraphQL mutation was flatly rejected**
  by Railway's schema validator — it was guessed from documentation prose,
  not the real schema. Fixed by querying Railway's live schema directly
  (`__type` introspection) instead of guessing again: the real flow is two
  separate calls (`variableCollectionUpsert` with `skipDeploys: true`, then
  `serviceInstanceDeploy(serviceId, environmentId)` — which returns a bare
  boolean, not a deployment id; a `deployments` query afterward finds the id
  for tracking, best-effort).
- **Railway's dashboard log viewer has a real display delay** — an early
  test deploy looked "silent" (only "Starting Container", nothing else) and
  was wrongly suspected to mean the container wasn't running at all. Pulling
  the log straight from Railway's GraphQL API (`deploymentLogs`) proved it
  was actually a display-timing issue, not a real problem — the same
  container later completed successfully.
- **The sandbox image was missing the `openai`/`anthropic` SDKs** — AI
  community-naming silently failed every run and fell back to placeholder
  names ("Community 1", etc.), discovered by pulling a real deployment's log
  after the first genuinely successful Railway run. Fixed by installing the
  `[openai,anthropic,gemini]` extras in `Dockerfile.sandbox`; image rebuilt
  and re-pushed.
- **Settings() in unit tests silently read the real `graphify/.env`** for
  any field not explicitly passed, making three config tests pass/fail based
  on what happened to be in the developer's real `.env` rather than the code
  under test. Fixed with `_env_file=None` in a shared `_settings()` test helper.

## Current state — verified live, end-to-end

- Admin login, lockout, cookie isolation (both directions).
- All admin data endpoints, launch error paths (401/400/409/503).
- Full callback + WebSocket pipeline (real and simulated).
- **A complete real Railway launch**, triggered through the actual
  `POST /api/projects` route: Railway deployed the real GHCR image, the
  container cloned `pypa/sampleproject`, ran extraction (17 nodes / 15
  links / 6 communities), attempted AI labeling (failed gracefully at the
  time — missing SDK, since fixed), uploaded both artifacts, and reported
  READY — entire round trip in ~20 seconds. Confirmed via the real database
  row (`graph_json_url`, `sandbox_id`, `started_at`/`finished_at`) and via
  Railway's own raw log.
- Real AI usage recording, both integration points (admin verify, sandbox
  labeling), confirmed with real token counts and real cost calculation.
- 63/63 automated tests passing, real DB, zero leftover rows, zero real
  external calls.
- Sandbox image rebuilt with the SDK fix and re-pushed to GHCR
  (`ghcr.io/abdullah-wpcoderrs/graphify-sandbox:latest`), confirmed public
  and pullable.

## What's left (optional follow-ups, not blockers)

- The rebuilt image (with the AI SDK fix) hasn't had its own fresh
  end-to-end Railway run yet — the *previous* image was proven working;
  this one should behave identically but hasn't been explicitly re-verified.
- Sandbox teardown / cleanup after a job finishes is not implemented
  (Phase 7 scope per the original plan).
- Token refresh rotation for expired GitHub/GitLab tokens (Phase 5 scope).
- A search for any old Phase-3-era admin tests asserting the superseded
  GitHub-role 403 contract, to confirm none linger elsewhere in the repo.

## Next session starts with

**The entire Phase 4 frontend is unstarted.** Per
`frontend/docs/TASK_CHECKLIST.md`:
1. Split `/dashboard` (recent projects only) from a new `/repositories` page.
2. Build the isolated admin frontend — its own login screen (separate from
   the GitHub-authed app) plus usage/analytics/users screens, all now backed
   by real, tested endpoints.
3. New `/projects` page — **blocked on a UI reference from the user**
   (they mentioned wanting something modeled on the Claude Cowork
   agent-mode IDE; get that reference before designing this screen).
4. New `/settings` page, and the Docs/Help external link — **need the real
   Graphify docs URL from the user** before wiring the link.
5. Replace `workspace-fixtures.ts` with real data — the backend contract is
   now fully proven live (real `graph.json`/`files.json` shapes confirmed,
   see Decisions above).
6. Real WebSocket client on the launch screen, replacing the mock event
   playback — the backend's `/ws/projects/{id}` is proven working.

## Open questions

- Should GHCR stay public long-term, or move to a private package + Railway
  pull credentials once this goes to production?
- Is per-backend (not per-model) cost pricing (see `usage.py`'s docstring)
  accurate enough long-term, or does it need per-model rates eventually?
