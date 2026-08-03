# Memory — Graphify production rollout: Railway/Vercel deploy + auth fixes

Last updated: 2026-08-02 20:30 WAT

## What was built

- Merged the unified Railway platform image (`Dockerfile.platform`,
  `compose.yaml`, role dispatcher) into `main` via [PR #6](https://github.com/abdullah-wpcoderrs/Graphifii/pull/6),
  including a rerun-extraction frontend action
  (`frontend/app/components/rerun-project-button.tsx`).
- Added a root `README.md` as a deployment/ops runbook ([PR #5](https://github.com/abdullah-wpcoderrs/Graphifii/pull/5),
  later expanded in [PR #8](https://github.com/abdullah-wpcoderrs/Graphifii/pull/8) and
  [PR #10](https://github.com/abdullah-wpcoderrs/Graphifii/pull/10)). The
  "Railway service configuration" section now lists every required env var
  **explicitly per service** (API/worker/extractor/migrate), not summarized —
  the worker needs the same full `Settings()` field set as the API
  (`get_settings()` validates all of it at startup), not just
  `DATABASE_URL`/`REDIS_URL`.
- Fixed a production login loop: session/admin cookies were `SameSite=Lax`,
  which silently drops the cookie on cross-site `fetch()` calls between the
  Vercel frontend and Railway API (different sites in production). Fixed in
  [PR #9](https://github.com/abdullah-wpcoderrs/Graphifii/pull/9):
  - `graphify/server/sessions.py`: added `session_cookie_samesite()` —
    returns `"none"` only when `is_secure_cookie()` is true, falls back to
    `"lax"` for local HTTP dev (where `SameSite=None` without `Secure` would
    be silently rejected by browsers).
  - `graphify/server/csrf.py` (new): `CSRFOriginMiddleware` — `SameSite=None`
    reopened a CSRF hole (cookie-only auth, no CSRF token), so this rejects
    unsafe-method requests carrying the session/admin cookie whose
    Origin/Referer doesn't match `frontend_url`.
  - Updated the `app_client` test fixture (`tests/server/conftest.py`) to
    send a default `Origin` header matching `frontend_url`, or every
    DB-backed mutation test would fail under the new middleware.
  - Added `tests/server/test_csrf.py` (8 tests) and `tests/server/test_sessions.py`
    (2 tests) — DB-free unit coverage, since the DB-backed route tests are
    skipped in this environment without `GRAPHIFY_TEST_DATABASE_URL`.

## Decisions made

- Keep argon2-cffi as the only admin password hashing algorithm — did not
  switch to pgcrypto/bcrypt when asked to write raw SQL for admin creation,
  because Postgres has no argon2 function and switching hash algorithms
  would require rewriting `verify_password()`/`hash_password()` in
  `admin_sessions.py`, fragmenting the auth system. Instead: hash locally via
  the app's own `hash_password()` (so it's guaranteed compatible with the
  login route's verification), then SQL only ever receives the resulting
  hash — plaintext passwords never touch a SQL statement or Neon's query log.
- Admin credentials were already fully DB-backed before this session
  (`admin` table, argon2 hash, isolated from `User`) — `ADMIN_EMAIL`/
  `ADMIN_PASSWORD` env vars are used only by the one-time
  `scripts/seed_admin.py` seed/reset script, never read by the live login
  route. No code change was needed; only documented the raw-SQL alternative
  to that script.
- Railway image releases are pinned to specific GHCR digests, not built live
  from GitHub on every push — merging a PR to `main` does **not** redeploy
  Railway by itself. A new image must be built (`docker buildx build
  --platform linux/amd64 -f Dockerfile.platform ... --push`) and each
  service's image source updated explicitly. Cross-platform builds from
  Apple Silicon are slow and should be run in the user's own terminal, not
  through the sandboxed agent session (its network path is bandwidth-limited
  and blocks `railway.app`/`backboard.railway.app` outright).
- PR workflow this session: branch off `main` → commit → push → `gh pr
  create` → merge via `gh pr merge --merge --delete-branch` once CI/Qodo
  checks are either clean or irrelevant (e.g. a docs-only PR doesn't need to
  wait on a Vercel preview-deploy check).

## Problems solved

- **Root cause of the login redirect loop**: `SameSite=Lax` cookies ride
  along on the OAuth callback's top-level redirect (so login "succeeds" and
  briefly reaches `/dashboard`) but are silently withheld from the
  dashboard's subsequent cross-site `fetch()` session check, bouncing the
  user back to `/`. Fixed by `SameSite=None` (guarded by `Secure`) plus the
  new CSRF Origin-check middleware to compensate for the protection `Lax`
  had been incidentally providing.
- **Root cause of extractions never leaving "queued"**: the Railway service
  named `graphify-worker` had the **extractor's** per-run variables statically
  set (`SERVICE_ROLE=extractor`, `REPO_URL`... no wait, actually
  `GRAPHIFY_CALLBACK_URL`, `OPENAI_API_KEY`, `REPO_BRANCH`, `REPO_TOKEN`,
  `SERVICE_ROLE`), so it ran one extraction directly on itself instead of
  dispatching to the extractor service, then exited ("Completed" status) —
  a real worker process (`run_worker.py`'s `while True:` loop) never exits on
  its own. After correcting `SERVICE_ROLE=worker` and the full required
  variable set, the worker came up `Active` and began claiming queued runs,
  but then failed with `RailwayNotConfiguredError` — it was still missing
  `RAILWAY_API_TOKEN`/`RAILWAY_PROJECT_ID`/`RAILWAY_SERVICE_ID`/
  `RAILWAY_ENVIRONMENT_ID` (the worker needs these on **itself**, separately
  from the API, since it's the worker process that calls Railway's API to
  launch the extractor deployment).
- Vercel frontend served a platform-level `404: NOT_FOUND` on every route —
  root cause: the repo is a monorepo with no `package.json` at the root, and
  Vercel's Root Directory wasn't set to `frontend`, so it detected no
  Next.js app and deployed empty output.
- `POST /api/projects` returning `Railway sandbox provisioning is not
  configured` — root cause: whichever service made that call was missing one
  or more of the four `RAILWAY_*` variables.

## Current state

- `main` has all fixes merged: unified platform image, README env var docs,
  SameSite/CSRF cookie fixes. GHCR image `railway-csrf-samesite-fix-*` build
  was interrupted (sandbox network too slow — 28.7 kB/s on a 16.7MB numpy
  wheel) and needs to be rebuilt/pushed from the user's own machine, then
  Railway's API/worker/extractor services need their image source updated to
  the new digest.
- `graphify-worker` on Railway is now `Active` and correctly claiming queued
  runs (confirmed via deploy logs), but was last seen still missing the four
  `RAILWAY_*` variables needed to actually launch extractor deployments — a
  run (`628033ce-badc-4e2a-982e-c5d3bf72d9b5`) is stuck because the worker
  also failed to clean up Railway variables after the launch failure
  ("queue remains fail-closed" — the singleton-safety design working as
  intended, but it needs manual reconciliation once the worker is fixed).
- `graphify-API` and `graphify-extractor-staging` are both correctly
  configured per the README's explicit per-service variable lists.
- Vercel Root Directory fix (`frontend`) and `NEXT_PUBLIC_API_URL` were
  identified as needed; not confirmed fixed by the user as of this save.
- Admin login: fully functional in code; user was given a two-step
  local-hash + SQL-upsert path to create the first admin row directly in
  Neon without running `scripts/seed_admin.py`. Not confirmed run yet.

## Next session starts with

1. Confirm the user finished rebuilding/pushing the new GHCR image from
   their own machine, and updated Railway API/worker/extractor to the new
   digest — then confirm `SameSite=None` login no longer loops.
2. Confirm `graphify-worker` has all four `RAILWAY_*` variables set and is
   successfully launching extractor deployments end-to-end (watch for
   `[platform] starting role=extractor` in a *new* deployment, not the
   stuck one).
3. Check whether the stuck run `628033ce-badc-4e2a-982e-c5d3bf72d9b5` needs
   manual reconciliation in Neon (`ExtractionRun` table) — it may be holding
   the singleton active slot open.
4. Confirm Vercel's Root Directory is set to `frontend` and
   `NEXT_PUBLIC_API_URL` is set, and that a fresh deploy (not just a saved
   variable) has happened since — `NEXT_PUBLIC_*` vars are baked in at Next.js
   build time, not read at runtime.
5. Confirm the admin row was created via the local-hash + SQL-upsert path
   and that `POST /api/admin/login` works in production.

## Open questions

- Has the new GHCR image (post `SameSite`/CSRF fix) actually been built,
  pushed, and pointed to by all three long-running Railway services yet?
- Is `RAILWAY_SERVICE_ID` on the worker correctly set to the **extractor**
  service's ID (not the worker's own) — this is an easy copy-paste mistake?
- Does the stuck run need a manual `UPDATE` in Neon, or will the worker's own
  reconciliation logic clear it automatically on next successful cycle?
