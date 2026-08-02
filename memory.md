# Memory — Graphify secure queue and unified Railway platform

Last updated: 2026-08-02 08:32 WAT

## What was built

- The earlier Phase 4 backend remains complete: isolated admin authentication,
  project launch/callback/WebSocket flow, Railway sandbox execution, usage
  tracking, Neon migrations, and the backend test suite were previously proven
  end to end.
- Security checklist Phase 0 and Phase 1 code work in `graphify/issues.md` is
  implemented: hardened image inputs, immutable `ExtractionRun` records,
  database-backed singleton dispatch, per-run callback credentials, exact
  deployment correlation/cancellation, idempotent callback events, quotas,
  leases, and stale-callback rejection. Operational/staging proof items remain.
- Redis Streams queue support is implemented and documented in
  `graphify/docs/redis-run-queue.md`. Redis carries only `run_id`; Neon remains
  authoritative and the database fallback scan preserves runs when Redis is
  unavailable.
- A dedicated worker image exists at `graphify/Dockerfile.worker`. The local
  `graphify-run-worker:latest` image was rebuilt successfully and smoke-tested
  as non-root with Redis, SQLAlchemy, psycopg, and worker imports.
- The unified-platform implementation through the local and extractor staging
  gates is complete and tracked in
  `graphify/docs/unified-railway-platform-plan.md`. Created or modified work
  includes `graphify/Dockerfile.platform`,
  `graphify/scripts/platform_entrypoint.py`, the repository-root
  `compose.yaml`, Neon direct-migration configuration, sandbox role injection,
  `.env.example`, dependency metadata, and platform/Compose/security tests.
- The unified checklist records evidence beside completed tasks. Phases 1–3
  are complete, including a genuine Railway extractor run that closed the
  Phase 2 exit gate. Phase 5 restart/persistence behavior is verified locally.
  Phase 6 now has a tested immutable GHCR release candidate. Railway production
  variables, same-digest service selection, volumes, private topology, and the
  remaining Phase 7 release tests are still pending.
- `Dockerfile.platform` now installs the optional `sql` extra. The published
  Linux image imports `tree_sitter_sql` and a runtime smoke schema produced 3
  nodes and 3 edges.
- `project_progress_ws` now treats a disconnect during the initial snapshot as
  a normal browser disconnect. The focused regression test passed and the
  published image was inspected to confirm that it contains the guard.

## Decisions made

- The existing Neon project is the only PostgreSQL provider and source of
  truth. Do not provision Railway PostgreSQL. API and worker use a pooled Neon
  URL; migrations use a separate direct Neon URL. Production, staging, and
  development should use separate Neon branches.
- Railway owns application compute and managed Redis. The intended Railway
  application roles are API, worker, and sandboxed extractor, all built from
  one immutable platform image but executed as isolated services/deployments.
- “Sandbox,” “sandboxed extractor,” and “extractor” are the same existing
  workload. `Dockerfile.sandbox` plus `scripts/sandbox_entrypoint.py` is the
  current baseline; the unified image rehosts that behavior as
  `SERVICE_ROLE=extractor`. It is not a new extraction system.
- The sandbox security boundary must remain: isolated Railway deployment,
  ephemeral `/workspace`, run-scoped variables, per-run callback auth,
  cancellation, cleanup, non-root execution, and no Neon credentials.
- `Dockerfile.worker` and `Dockerfile.sandbox` stay available through a rollback
  window. Do not retire them until staging and production parity is proven.
- Redis is delivery acceleration, not correctness. Neon state, constraints,
  leases, and exact deployment IDs remain authoritative.
- Keep one API replica while artifacts live on an attached filesystem volume.
  Move artifacts to shared object storage before horizontal API scaling.
- Secrets and connection strings must be injected at runtime and must never be
  copied into images, Compose files, documentation, tests, or this memory.
- Use a new immutable GHCR tag for every build. Pushing an image does not update
  Railway automatically; change each service's source reference and redeploy.
  Preserve the previous digest for rollback.
- Database migration updates Neon schema only; it never assigns Railway roles.
  API and worker receive static `SERVICE_ROLE=api|worker` variables, a one-shot
  migration job receives `SERVICE_ROLE=migrate` plus `DATABASE_URL_DIRECT`, and
  the worker injects `SERVICE_ROLE=extractor` automatically per extraction run.
- `SANDBOX_CALLBACK_BASE_URL` is the callback base when it is set. A Cloudflare
  quick tunnel hostname is disposable; after changing it in `.env`, recreate
  API and worker containers because running containers keep their old
  environment snapshot.

## Problems solved

- The architecture documentation now explicitly shows how external Neon stays
  isolated outside Docker Compose/Railway and how API/worker initiate outbound
  TLS connections to it.
- The documentation now removes the ambiguity between the old sandbox image
  and the new extractor role, including parity requirements and rollback intent.
- The scattered Railway deployment model is being consolidated around one
  role-based image and one centralized runtime-variable model without placing
  multiple long-running processes in one container.
- The stale callback hostname was traced to the value actually present in
  `graphify/.env` and in the already-created worker container. `.env` was
  corrected to the active `citation-contribution-rom-pull.trycloudflare.com`
  tunnel and Compose services were recreated. Railway then resolved the
  callback and all progress, usage, artifact, and terminal reports returned
  HTTP 200.
- The frontend appeared stuck because the extractor could not report to the
  stale callback host. Once callback resolution was fixed, the genuine run
  reached Graph ready. A separate WebSocket code-1006 traceback was also fixed;
  it was a browser hydration disconnect, not a Neon or extraction failure.
- Railway's five zero-node JSON messages were confirmed non-fatal metadata
  warnings. The separate 49-file SQL warning represented real graph coverage
  loss and is fixed in the new platform image through the `sql` extra.

## Successful verification runs

- Local Compose migration reached the disposable Neon branch and reported
  Alembic head `f83a49b127d1`.
- Redis, API, and worker were rebuilt/recreated together. Redis and API became
  healthy, the worker started, and the Neon-backed `GET /health` returned HTTP
  200.
- API persistence survived `docker compose up -d --force-recreate api`; the
  named `/data/workspaces` volume remained intact. An immediate curl during
  process replacement can reset before readiness, so the reliable procedure
  uses Compose `--wait` or a health polling loop.
- Railway successfully extracted
  `https://github.com/abdullah-wpcoderrs/byte-earn` from branch `main`:
  project `eb25089e-e5d3-4c9c-9023-8734540a55bf`, run
  `50aa6189-df55-419b-8622-f8e41a1d3359`, 1,309 nodes, 2,762 edges, 89
  communities. Artifacts uploaded with `ok:true`, Railway logged
  `[sandbox] done`, and the local frontend reached Graph ready.
- The initial Railway verification above used the earlier unified
  `railway-test-1` tag. It proved the hybrid API/worker/extractor flow but did
  not include SQL parsing.
- New release candidate pushed to GHCR:
  `ghcr.io/abdullah-wpcoderrs/graphify-platform:railway-sql-ws-20260802T070343Z`.
  OCI index digest:
  `sha256:f63820e15d8f8807e4c16e8dc36489aecad5f9f710f4e13345d3fcd4d36d0972`.
  Linux/amd64 manifest:
  `sha256:504c7b3157ebe34e98a720782b74118a3283eb18ac219444c1e4fbcdadff2f3f`.
- New image runtime checks: `tree_sitter_sql=ok`; SQL smoke extraction produced
  3 nodes/3 edges; WebSocket initial-disconnect guard present.
- Focused verification after the fixes: 17 launch-route tests passed against
  the disposable Neon test database; deployment/security plus WebSocket checks
  passed (9 tests); Ruff, production-route Pyright, and `git diff --check`
  passed. Host-only SQL tests skipped where the optional grammar was absent,
  which is why the built-image SQL smoke was required.

## Commands used for the verified local and GHCR run

From the workspace root:

```bash
cd "/Users/mac/Documents/Graph UI"

docker compose --profile migrate run --rm migrate
docker compose up -d --build --force-recreate --wait --wait-timeout 120 redis api worker
docker compose ps
curl -i http://localhost:8000/health
docker compose logs --tail=120 api worker redis

docker compose up -d --force-recreate --wait api
curl -i http://localhost:8000/health
```

Focused repository checks from `graphify/`:

```bash
cd "/Users/mac/Documents/Graph UI/graphify"

.venv/bin/pytest -q tests/server/test_launch_routes.py
.venv/bin/pytest -q tests/server/test_deployment_security.py \
  tests/server/test_launch_routes.py \
  -k 'platform_image or websocket_disconnect_during_initial_snapshot'
.venv/bin/ruff check tests/server/test_deployment_security.py \
  graphify/server/routes/launch.py tests/server/test_launch_routes.py
git diff --check
.venv/bin/graphify update .
```

Exact release build, smoke, push, and remote verification sequence:

```bash
cd "/Users/mac/Documents/Graph UI/graphify"

GRAPHIFY_IMAGE_REF="ghcr.io/abdullah-wpcoderrs/graphify-platform:railway-sql-ws-20260802T070343Z"

docker buildx build \
  --platform linux/amd64 \
  -f Dockerfile.platform \
  -t "$GRAPHIFY_IMAGE_REF" \
  --load \
  .

docker run --rm --platform linux/amd64 --entrypoint python \
  "$GRAPHIFY_IMAGE_REF" \
  -c 'import tempfile; from pathlib import Path; import tree_sitter_sql; from graphify.extract import extract; d=tempfile.TemporaryDirectory(); p=Path(d.name)/"schema.sql"; p.write_text("CREATE TABLE users (id INT PRIMARY KEY);\n"); result=extract([p], cache_root=Path(d.name), parallel=False); print("SQL nodes=%d edges=%d" % (len(result["nodes"]), len(result["edges"]))); assert result["nodes"]'

docker run --rm --platform linux/amd64 --entrypoint python \
  "$GRAPHIFY_IMAGE_REF" \
  -c 'import inspect; from graphify.server.routes.launch import project_progress_ws; source=inspect.getsource(project_progress_ws); assert "Keep this inside the disconnect guard too" in source; print("websocket_initial_disconnect_guard=ok")'

docker push "$GRAPHIFY_IMAGE_REF"
docker buildx imagetools inspect "$GRAPHIFY_IMAGE_REF"
```

The Railway extraction was launched through the local Graphify UI/API and
worker, not through a manual Railway CLI command. The worker created the exact
Railway deployment and injected the run-scoped variables.

## Current state

- The working tree is intentionally uncommitted. Preserve all existing changes.
  Current platform-related files include modified `.env.example`,
  `alembic/env.py`, `graphify/server/config.py`, `graphify/server/sandbox.py`,
  `pyproject.toml`, and related tests, plus untracked `compose.yaml`,
  `Dockerfile.platform`, `scripts/platform_entrypoint.py`, platform/Compose
  tests, and `docs/unified-railway-platform-plan.md`.
- Treat checked tasks and their evidence annotations in
  `graphify/docs/unified-railway-platform-plan.md` as completed work. Do not
  restart Phase 1–3 from scratch.
- Local unified image/Compose work is implemented and locally validated.
- The Phase 2 Railway extraction gate is complete on the earlier unified image.
- The SQL/WebSocket release candidate is published but is **not yet confirmed
  as selected or deployed in Railway**. Do not describe the new digest as
  deployed until the dashboard source is updated and a fresh extraction proves
  the missing-SQL warning is gone.
- Railway Shared Variables, Neon/Redis production wiring, same-digest API and
  worker deployment, API volume, staging release tests, and production rollout
  are not yet fully configured or verified.
- The dedicated worker image is ready locally but was not recorded as pushed to
  a registry during this session.
- A frontend "rerun extraction" feature exists
  (`frontend/app/components/rerun-project-button.tsx`), wired into both
  `dashboard-screen.tsx` and `repositories-screen.tsx`, and already documented
  in `frontend/ui-registry.md`. It was built outside this file's tracking but
  is real, integrated, and passing local review — not a stray/unused file.
- This sandbox's Bash tool cannot reach `railway.app`/`backboard.railway.app`
  (DNS resolves via `nslookup` but `curl` fails to connect even with the
  sandbox override) even though other hosts like `api.github.com` work — a
  network allowlist blocks Railway specifically. Driving Phase 4/6 Railway
  config via its GraphQL API from this environment is not currently possible;
  the owner must apply those steps manually in the Railway dashboard (exact
  variable names/values were handed over in-session, sourced from
  `graphify/.env`).
- All of `tests/server/` passes locally (156 passed, 26 skipped — the skips
  are SQL-grammar tests that only run inside the built Linux image).

## Next session starts with

1. Read `graphify/docs/unified-railway-platform-plan.md` and preserve every
   checked item; begin at the first unchecked exit gate or dashboard task.
2. Run the focused platform, Compose, deployment-security, sandbox, worker, and
   Redis test suites to reconfirm the dirty worktree before deployment.
3. Update the Railway extractor source to
   `railway-sql-ws-20260802T070343Z` (prefer the recorded digest), redeploy, and
   repeat the `byte-earn` extraction. Confirm there is no
   `tree_sitter_sql not installed` warning.
4. When deploying API and worker on Railway, point both at the same digest and
   set `SERVICE_ROLE=api` / `SERVICE_ROLE=worker`. The extractor role remains
   automatically injected per run; the migration job uses
   `SERVICE_ROLE=migrate` plus `DATABASE_URL_DIRECT`.
5. Configure Phase 4 Railway Shared Variables without exposing values:
   pooled Neon URL for API/worker, direct Neon URL for migrations, private Redis
   URL, role variables, and existing Railway identifiers/credentials.
6. Continue through storage, same-digest deployment, staging release, and only
   then deprecate the dedicated worker/sandbox images.

## Open questions

- Which Phase 0 operational tasks have already been done outside the repository
  (secret rotation record, image scan, Neon restore policy, Redis persistence)?
- Have Railway Shared Variables, stable egress/IP rules, Redis persistence, and
  the API artifact volume already been configured manually?
- Has Railway been updated from the earlier `railway-test-1` extractor image to
  the SQL/WebSocket release candidate digest recorded above?
- Should the first production rollout keep the existing dedicated sandbox image
  as the extractor while API/worker move first, or promote all three roles to
  the unified digest together after staging parity?
