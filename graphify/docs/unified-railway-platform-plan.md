# Unified Graphify Railway Platform — implementation plan

This document is the build checklist for consolidating Graphify's API, queue
worker, and extraction sandbox into **one reusable Docker image** while keeping
each process isolated on Railway.

It is written as an implementation plan, not as a claim that the consolidation
is already finished. Check an item only after its verification step passes.

> **Status — 2026-08-02.** Phases 1–3 are implemented. The API, worker, Redis,
> migration role, persistence, and health checks are verified locally, and the
> Phase 2 extractor exit gate has now passed on Railway with a genuine queued
> public-repository run. Phases 4–5 remain split: every code-side/local item is
> done, while production variables, volumes, provider policies, and service
> topology still require dashboard confirmation. Phase 6 now has a tested
> immutable GHCR release candidate, but Railway has not yet been confirmed on
> that new digest. Search this file for `NEEDS DASHBOARD` to find remaining
> human steps.
>
> Items are annotated inline as the work happened:
> `— done:` how it was verified, `— NEEDS DASHBOARD:` waiting on you,
> `— n/a:` why it did not apply.
>
> **Seven real bugs or coverage gaps surfaced during implementation and live
> verification.** Five are the original containerization findings. The live
> hybrid test then exposed an unguarded first WebSocket write and incomplete
> SQL extraction coverage in the unified image. They are recorded under "Bugs
> found while implementing" near the end of this file.

### Verified release and live-run record — 2026-08-02

- Local Compose was rebuilt with `redis`, `api`, and `worker`; all three became
  healthy/running and the Neon-backed `/health` endpoint returned HTTP 200.
- Forced API recreation preserved `/data/workspaces`. An immediate `curl`
  during restart can receive `connection reset by peer`; use Compose `--wait`
  or poll `/health` until the new process has completed startup.
- Railway ran the unified image as `SERVICE_ROLE=extractor` for
  `https://github.com/abdullah-wpcoderrs/byte-earn` and reached terminal
  success: 1,309 nodes, 2,762 edges, 89 communities; usage, progress, artifact,
  and final callbacks returned HTTP 200; the artifact upload returned
  `{"ok":true,...}`; Railway logged `[sandbox] done`.
- The warning about five zero-node JSON metadata files was non-fatal. The
  warning that 49 SQL files were skipped was actionable, so the platform image
  now installs `graphifyy[server,openai,anthropic,gemini,sql]`.
- The frontend's initial WebSocket snapshot send is now inside the normal
  `WebSocketDisconnect` guard, preventing an ASGI traceback when hydration
  replaces the first socket.
- Release candidate
  `ghcr.io/abdullah-wpcoderrs/graphify-platform:railway-sql-ws-20260802T070343Z`
  was built for `linux/amd64`, tested locally, pushed to GHCR, and remotely
  verified at OCI digest
  `sha256:f63820e15d8f8807e4c16e8dc36489aecad5f9f710f4e13345d3fcd4d36d0972`.
  Updating Railway services to this digest and re-running extraction remains a
  dashboard step; publishing the image did not deploy it automatically.

## The beginner version

A Docker **image** is a packaged application. A Railway **service** is a running
copy of that image.

We will build one image and start it three different ways:

```text
One graphify-platform image
    |
    +-- SERVICE_ROLE=api       -> public backend API
    +-- SERVICE_ROLE=worker    -> private Redis queue worker
    +-- SERVICE_ROLE=extractor -> private sandboxed extraction job
```

## Terminology and migration intent

This plan reconfigures existing deployment components; it does not invent a
second extraction system.

- **Current sandbox image** means the existing image built from
  `Dockerfile.sandbox` and executed through `scripts/sandbox_entrypoint.py`.
- **Sandbox**, **sandboxed extractor**, and **extractor** refer to the same
  isolated repository-processing workload.
- **Extractor role** means that existing sandbox workload running from the new
  shared `graphify-platform` image with `SERVICE_ROLE=extractor`.
- **Unified image** means one packaged application image capable of starting as
  API, worker, or sandboxed extractor. It does not mean those processes share a
  container or filesystem at runtime.

The intended change is:

```text
Before
  Dockerfile.worker  -> dedicated worker image
  Dockerfile.sandbox -> dedicated sandbox/extractor image

After
  Dockerfile.platform -> SERVICE_ROLE=worker
                      -> SERVICE_ROLE=extractor (the existing sandbox behavior)
```

The sandbox security boundary must remain intact: each extraction still runs as
an isolated Railway deployment with ephemeral `/workspace`, run-scoped
variables, callback authentication, cancellation, and cleanup. Only its image
packaging and startup dispatch change. `Dockerfile.sandbox` remains available
during the rollback window and is retired only after behavioral and security
parity is proven.

The existing Neon project remains Graphify's only PostgreSQL provider and the
authoritative source of truth. Redis remains a managed Railway service used for
fast queue delivery. Neither belongs in the application image: Neon owns the
durable relational data, while Railway owns application compute and the Redis
queue runtime.

A volume also does not live inside an image. The image contains code; Railway
attaches persistent volumes when a service starts.

## Goal

After this plan is complete, production will have:

| Runtime service | Source | Public? | Persistent storage |
| --- | --- | ---: | --- |
| Graphify API | `graphify-platform:<digest>` with `SERVICE_ROLE=api` | Yes | Artifact volume initially |
| Graphify worker | Same image with `SERVICE_ROLE=worker` | No | None |
| Graphify sandboxed extractor | Same image with `SERVICE_ROLE=extractor` | No | Ephemeral `/workspace` only |
| Neon PostgreSQL | Existing Neon project | No | Neon managed |
| Redis | Railway managed database | No | Railway managed |

This creates four Railway runtime services—API, worker, extractor, and Redis—
plus the existing external Neon data platform. There is only one custom
application image, one application version, and one shared configuration model.

The frontend is outside this plan and remains separately deployed.

## Architecture

```text
Browser
   |
   v
Graphify API ------------------------------+
   |                                       |
   | creates immutable run                 | receives callbacks/artifacts
   v                                       |
Neon PostgreSQL                            |
   ^                                       |
   | claims exact run                      |
   |                                       |
Graphify worker <---- Redis Stream         |
   |                                       |
   | starts exact Railway deployment       |
   v                                       |
Graphify sandboxed extractor --------------+
```

### Where external Neon fits

Neon is **not** copied into `graphify-platform`, started by `compose.yaml`, or
attached as a Railway volume. It remains isolated in the existing Neon account,
project, and database branch. The containers are database clients; Neon is the
remote PostgreSQL server.

Local Docker Compose works like this:

```text
Developer machine
  |
  +-- Compose network
  |     +-- API container ----+
  |     +-- Worker container -+---- outbound TLS ----> Neon development branch
  |     +-- Redis container <-- API and worker via Docker service name `redis`
  |
  +-- local `.env` supplies the Neon development URLs at container startup
```

Production Railway works like this:

```text
Railway environment
  |
  +-- API service --------+
  +-- Worker service -----+---- outbound TLS ----> Neon production branch
  +-- Sandboxed extractor       no Neon credentials or database connection
  +-- Redis service <---------- Railway private-network traffic from API/worker

External Neon project
  +-- accepts authenticated TLS connections from API and worker
  +-- stores all authoritative application and run state
```

The API and worker initiate outbound connections using `DATABASE_URL`; Neon
does not initiate connections into Railway or Docker. Locally, Compose injects
the pooled Neon development URL from the gitignored `.env`. On Railway, Shared
Variables inject the pooled production URL into only the API and worker. The
migration role receives the direct Neon URL separately. Redis communication
stays inside the Compose network locally and Railway's private network in
production.

This preserves isolation:

- Neon has its own provider boundary, credentials, branches, storage, backups,
  and monitoring.
- The Docker image contains database client libraries but no database data or
  Neon secret.
- API and worker are the only long-running services authorized to reach Neon.
- Extractor compromise cannot directly read or write the database because the
  extractor receives no database URL.
- Development, staging, and production use different Neon branches and
  credentials so one environment cannot accidentally write to another.

## Service and data roles

| Component | Role |
| --- | --- |
| Neon PostgreSQL | Durable source of truth for users, projects, immutable runs, state transitions, leases, queue recovery, and exact Railway deployment IDs |
| Railway Redis | Fast delivery signal for queued `run_id` values; it is not authoritative and may be rebuilt from Neon state |
| Railway API | Authenticates requests, commits run state to Neon, publishes Redis notifications, receives callbacks, and serves artifacts |
| Railway worker | Consumes Redis messages, verifies and locks runs in Neon, enforces singleton execution, and launches/cancels exact extractor deployments |
| Railway sandboxed extractor | Existing sandbox workload, reconfigured as `SERVICE_ROLE=extractor`; performs one isolated extraction and reports results to the API without Neon credentials |
| Railway volume | Stores generated workspace artifacts for the single API replica until object storage replaces it |

## Important rules

- [ ] Never copy `.env` or secrets into the Docker image.
- [ ] Redis messages contain only `run_id`.
- [ ] Neon PostgreSQL remains the only source of truth and the singleton safety
  fence.
- [ ] API, worker, and extractor use the same immutable image tag or digest.
- [ ] Each Railway service receives only the runtime variables it needs.
- [ ] Do not provision a second PostgreSQL database on Railway.
- [ ] Neon and Railway Redis remain independent managed services.
- [ ] API and worker use the same Neon production branch.
- [ ] Extractor receives no Neon connection string.
- [ ] The extractor service has no public domain and no persistent volume.
- [ ] The worker service has no public domain and no persistent volume.
- [ ] Keep extraction concurrency at one while Railway variables are shared.

---

# Implementation checklist

## Phase 0 — Confirm the design before changing deployment

- [x] Confirm the frontend stays outside the unified backend image.
  — done: `compose.yaml` and `Dockerfile.platform` cover backend roles only.
- [x] Confirm the first release uses one API replica with an attached artifact
  volume. — done: encoded in `compose.yaml` (only `api` mounts
  `workspace-artifacts`) and asserted by `test_compose_environment.py`.
- [x] Confirm horizontal API scaling is postponed until artifacts move to S3 or
  another shared object store. — done: recorded in Phase 5 below.
- [x] Record the current API, worker, and extractor image tags for rollback.
  — done, present locally and on GHCR:
  `ghcr.io/abdullah-wpcoderrs/graphify-sandbox:latest` (digest `169d474917f7`)
  and `ghcr.io/abdullah-wpcoderrs/graphify-run-worker:latest` (`f3f67b3f65ec`).
  There was no API image before this work — the API had never been
  containerized, which is how bug #1 below stayed hidden.
- [x] Record the current `Dockerfile.sandbox`, sandbox entrypoint, environment
  contract, filesystem paths, callback flow, cancellation flow, and security
  controls as the extractor-parity baseline. — done: `Dockerfile.sandbox` is
  unchanged on disk, and the parity properties are now executable assertions
  rather than prose, in `test_deployment_security.py` ("Extractor parity").
- [ ] Export or record the current Railway variables without committing secret
  values. — NEEDS DASHBOARD.
- [x] Confirm the existing Neon project, production branch, database, and role
  that Graphify will use. — done for the **development** branch: connected
  from inside the API container to `neondb` on
  `ep-tiny-wind-avx47g80-pooler.c-11.us-east-1.aws.neon.tech`, PostgreSQL
  17.10. The production branch is NEEDS DASHBOARD.
- [x] Record the current Neon pooled and direct connection strings in the secret
  manager without committing either value. — done for local development:
  `graphify/.env` now holds the pooled URL as `DATABASE_URL` and the direct URL
  as `DATABASE_URL_DIRECT` (see bug #4 — they were previously both assigned to
  `DATABASE_URL`). `.env` remains gitignored and excluded from the image.
- [ ] Confirm Neon restore history/retention meets the recovery requirement.
  — NEEDS DASHBOARD (Neon console).
- [ ] Confirm Railway Redis persistence/backups meet the recovery requirement.
  — NEEDS DASHBOARD.

### Phase 0 exit gate

- [ ] The owner has approved Neon as the only production PostgreSQL provider and
  has approved the application rollback point. — NEEDS YOUR SIGN-OFF. The
  rollback point is commit `75e8f8b` plus the two GHCR digests recorded above.

## Phase 1 — Build one role-based platform image

- [x] Create `Dockerfile.platform` as a multi-stage build.
- [x] Copy only package/build inputs explicitly; never use `COPY .`.
  — done and enforced: `test_platform_image_copies_no_secrets_tests_or_local_artifacts`
  compares every `COPY` source against an allowlist, so a new build input has
  to be justified rather than merely avoid a blocklist.
- [x] Install the combined runtime requirements:
  `graphifyy[server,openai,anthropic,gemini,sql]`. The SQL extra keeps `.sql`
  files in extractor graphs instead of silently reducing repository coverage.
- [x] Install `git` and CA certificates for the extractor role. — done, and
  exercised for real: the smoke extraction cloned a public repo over TLS.
- [x] Copy `scripts/sandbox_entrypoint.py` into the runtime image.
- [x] Copy `alembic.ini` and `alembic/` into the runtime image so migrations can
  run from the same artifact. — done, and verified equal: the image's
  `alembic/versions/` is byte-identical in filenames to the repo's (7 files),
  and `alembic heads` inside the container matches `alembic heads` on the host.
- [x] Run the image as an unprivileged user after any required volume setup.
  — done, and this needed more care than a `USER` line. Railway mounts volumes
  root-owned, so a container that is *already* unprivileged cannot take
  ownership of its own mount point. PID 1 therefore starts as root, chowns the
  API's artifact directory, and then drops to uid 10001 irreversibly before
  `exec`. The drop is verified at runtime, not assumed: it re-attempts
  `setuid(0)` and refuses to start if that succeeds. The dispatcher also
  rewrites `HOME`, `USER`, and `LOGNAME` to the uid 10001 account before exec;
  without that, psycopg tries to read `/root/.postgresql` after the uid drop
  and cannot connect (bug #5 below).
- [x] Add `PYTHONUNBUFFERED=1` for live Railway logs.
- [x] Do not include `.env`, tests, graph outputs, repository history, local
  workspaces, or credential files. — done: canary run inside the built image
  found none of them; `/app` contains exactly `alembic/`, `alembic.ini`,
  `platform_entrypoint.py`, `sandbox_entrypoint.py`.

### Phase 1 image roles

- [x] Create `scripts/platform_entrypoint.py`.
- [x] Read `SERVICE_ROLE` from the runtime environment. — done, tolerant of
  case and surrounding whitespace.
- [x] Use process replacement (`os.execvp`) so Railway signals reach the real
  API, worker, or extractor process. — done, using `os.execvpe` (the `e`
  variant, so the migration role's rewritten environment is passed explicitly
  rather than mutated globally).
- [x] Implement `SERVICE_ROLE=api` -> `graphify-server`.
- [x] Implement `SERVICE_ROLE=worker` -> `graphify-run-worker`.
- [x] Implement `SERVICE_ROLE=extractor` ->
  `python /app/sandbox_entrypoint.py`.
- [x] Implement `SERVICE_ROLE=migrate` -> `alembic upgrade head`.
- [x] Require `DATABASE_URL_DIRECT` for the migration role and expose it to
  Alembic as `DATABASE_URL` only inside that migration process. — done, and
  proved by observation: a migrate run whose *only* database input was
  `DATABASE_URL_DIRECT` tried to resolve exactly that host.
- [x] Reject missing or unknown roles with a clear message and non-zero exit.
  — done: unset, unknown, and `migrate`-without-a-direct-URL all exit 2 in the
  real container, naming the valid roles.
- [x] Ensure no role prints secrets or the complete environment. — done: the
  only startup line is `[platform] starting role=<role> command=<argv[0]>`,
  covered by a test that plants a secret in the environment and asserts it
  never appears in output.

### Phase 1 tests

- [x] Extend the Docker security test to cover `Dockerfile.platform`.
- [x] Test every valid `SERVICE_ROLE` command mapping.
- [x] Test unknown and missing roles fail closed.
- [x] Build the image locally. — done for `linux/amd64` (Railway's
  architecture), 896 MB. Cross-building on Apple Silicon made a transient PyPI
  read timeout likely enough to fail a build outright, so the image now sets
  `PIP_DEFAULT_TIMEOUT`/`PIP_RETRIES`.
- [x] Inspect its history and prove no broad context-copy layer exists.
  — done: the runtime stage's only `COPY` instructions are the four explicit
  ones plus `--from=builder /wheels`.
- [x] Run an image canary proving `.env`, backup files, keys, and credentials are
  absent. — done: globbed `/app/.env*`, `env.backup-*`, `*.pem`, `*.key`,
  `*credentials*.json`, `/app/tests`, `/app/.git`, `workspace-storage`,
  `graphify-out`. Zero findings.
- [x] Run import checks for `redis`, `sqlalchemy`, `psycopg`, provider SDKs,
  `tree_sitter_sql`, and `graphify.server.run_worker`. — done. The original
  checks caught bug #1 (the API router package was missing from the wheel); the
  release-candidate check then proved SQL support in the built Linux image.
- [x] Confirm the container runs as the intended non-root UID. — done: after
  dispatch, `euid=10001 egid=10001 groups=[]` for both the extractor and API
  roles, including when the API role first chowns a root-owned volume.

### Phase 1 exit gate

- [x] One local image successfully starts the API, worker, extractor smoke mode,
  and migration role. — **passed.** All four reach their real process from one
  image: the API served `/health` under Compose, the worker reached
  `run_worker.py`, the extractor cloned and extracted a real repository, and
  the migration role ran `alembic current` against Neon's direct endpoint.

## Phase 2 — Make the extractor role work from the shared image

This phase migrates the existing `Dockerfile.sandbox` workload into
`SERVICE_ROLE=extractor`; it must preserve sandbox behavior and isolation rather
than redesigning extraction.

- [x] Update `graphify/server/sandbox.py` to inject
  `SERVICE_ROLE=extractor` for every Railway extraction deployment.
- [x] Preserve the immutable `RUN_ID`, repository inputs, callback URL, and
  per-run callback credential. — done: the launch payload is otherwise
  untouched; `SERVICE_ROLE` is the single added key.
- [x] Preserve the existing sandbox entrypoint behavior, unprivileged runtime
  user, ephemeral `/workspace`, artifact upload, and terminal cleanup.
  — done: `scripts/sandbox_entrypoint.py` is unmodified. It is the same file,
  copied to the same path, run by the same interpreter, as the same uid.
- [x] Compare the unified extractor filesystem, environment, and network access
  against the existing `Dockerfile.sandbox` image. — done, as four executable
  parity assertions (runtime uid, image-owned ephemeral `/workspace` with no
  `VOLUME`, identical entrypoint copy, all three provider SDKs).
- [x] Continue replacing/clearing the extractor service variables safely.
  — done, unchanged: `replace: True` + `skipDeploys: True`, with
  `clear_sandbox_variables_on_railway()` still wiping to an empty map.
- [x] Confirm the worker persists the exact deployment ID before acknowledging
  Redis. — confirmed unchanged in `run_worker.py`; covered by the existing
  `test_run_service.py` / `test_redis_queue.py` suites, which still pass.
- [x] Confirm cancellation targets that exact deployment ID. — confirmed:
  `cancel_deployment_on_railway()` takes the exact id and falls back from
  `deploymentCancel` to `deploymentStop`; existing test still passes.
- [x] Confirm terminal cleanup removes run-scoped variables before releasing the
  Neon PostgreSQL active slot. — confirmed unchanged in `run_worker.py`.
- [x] Add a regression test proving the extractor receives the role variable.
  — done: `test_launch_selects_the_extractor_role_of_the_unified_image`.
- [x] Add a regression test proving API/worker-only variables are not injected
  into the extractor. — done, and written as an **exhaustive set comparison**
  rather than a list of forbidden names, so any newly added launch variable
  fails the test until someone consciously adds it to the allowlist.
- [x] Run the same sandbox security tests against both `Dockerfile.sandbox` and
  the unified image's extractor role during the migration window. — done for
  the build-configuration properties (see parity tests above).

### Phase 2 exit gate

- [x] A staging extraction reaches `READY` using `SERVICE_ROLE=extractor` from
  the unified image. — **passed on Railway.** A genuine queued run for
  `abdullah-wpcoderrs/byte-earn` started with
  `[platform] starting role=extractor`, cloned `main`, built 1,309 nodes, 2,762
  edges, and 89 communities, uploaded artifacts successfully, and ended with
  `[sandbox] done`. All callback classes returned HTTP 200 and the frontend
  reached Graph ready. This closes the behavioral gate for the unified
  extractor. A repeat on the newer SQL/WebSocket digest is still required
  before that exact digest is promoted.

## Phase 3 — Add a local Docker Compose environment

- [x] Create `compose.yaml` at the repository root.
- [x] Add an `api` service using `Dockerfile.platform` and `SERVICE_ROLE=api`.
- [x] Add a `worker` service using the same image and `SERVICE_ROLE=worker`.
  — done. Only `api` carries the `build:` key; every other role references the
  resulting tag, so `up --build` performs exactly one build and every role is
  provably the same bits.
- [x] Add an official Redis service; do not add a PostgreSQL container.
  — done, and `test_no_postgres_container_is_ever_defined` keeps it that way.
- [x] Connect API and worker to a dedicated Neon development branch.
- [x] Pass `DATABASE_URL` into only the API and worker containers from the
  gitignored local `.env`; do not add Neon as a Compose service. — done. The
  rendered config shows the extractor with exactly 2 variables
  (`SERVICE_ROLE`, `WORKSPACE_STORAGE_TYPE`) against 29–30 for API and worker.
- [x] Confirm both containers can resolve the Neon hostname and establish a TLS
  connection over outbound internet access. — done from inside the running API
  container: connected to `neondb`, PostgreSQL 17.10, and read
  `alembic_version`. (`pg_stat_ssl` reports `false` because the pooled
  endpoint terminates TLS at PgBouncer and that view describes the
  pooler-to-Postgres hop, not the client's; `sslmode=require` governs ours.)
- [x] Confirm the extractor Compose profile receives no database URL. — done,
  by rendering the config and by `test_the_extractor_receives_no_backend_credentials`.
- [x] Add a Redis health check and a Neon connectivity readiness check. — done.
  `/health` now acquires a real SQLAlchemy connection and executes `SELECT 1`;
  it returns HTTP 503 if the Neon round trip fails. The container healthcheck
  calls that endpoint with `urllib` rather than `curl`, which the slim base
  image does not have and should not gain.
- [x] Add restart policies suitable for local development. — done, and split by
  kind: long-running services use `unless-stopped`, batch roles (`migrate`,
  `extractor`) use `no`, so a successful exit is not treated as a crash. That
  is the same trap `CLAUDE.md` documents for Railway.
- [x] Add `redis-data` and `workspace-artifacts` named volumes.
- [x] Mount `workspace-artifacts` only into the API service.
- [x] Keep the worker stateless. — done: no `ports`, no `volumes`, asserted.
- [x] Put the extractor under an optional Compose profile or run it only as a
  one-off smoke job. — done: `extractor` and `migrate` are both profile-gated,
  so a plain `up` starts only `redis`, `api`, `worker`.
- [x] Add startup connection retries; do not rely only on Compose `depends_on`.
  — done in the API lifespan: it makes up to 12 real SQL round trips at
  five-second intervals before failing startup. An idle Neon branch can wake
  during that window; exhaustion exits the process, after which
  `restart: unless-stopped` starts a fresh bounded attempt. The dedicated
  worker already catches database failures and retries its authoritative
  PostgreSQL scan loop.

### Local environment files

- [x] Keep `.env` gitignored and use it only for local development. — verified:
  `.env`, `.env.*`, and `env.backup-*` are all in `.dockerignore`, and the
  image canary confirms none reached a layer.
- [x] Update `.env.example` with every required variable and safe placeholder.
  — done: added `SERVICE_ROLE`, `DATABASE_URL_DIRECT`, `WORKSPACE_STORAGE_DIR`,
  `API_PORT`, the pooled-vs-direct explanation, the Compose command reference,
  and an explicit "none of this file goes to Railway" section.
- [x] Put only a Neon development-branch connection string in local `.env`;
  never use the production branch for routine local development. — confirmed:
  the configured branch is the development one.
- [x] Do not put real secrets into `compose.yaml`. — done and asserted by
  `test_compose_file_contains_no_secret_values`. Secrets arrive by file
  reference only, so `compose.yaml` is safe to commit.
- [x] Document `docker compose --env-file .env up --build`. — done, but the
  documented command is deliberately **`docker compose up --build`**, without
  `--env-file`. See bug #3: `--env-file` runs every value through Compose's
  `${...}` interpolation, and the real `.env` contains Railway reference
  syntax that the interpolator rejects outright, so nothing starts. The file
  is attached per service with `env_file: … format: raw` instead.
- [x] Document how to stop services without deleting volumes. — `docker compose
  down`, documented at the top of `compose.yaml` and in `.env.example`.
- [x] Document the separate destructive command for intentionally removing the
  local Redis and artifact volumes. — `docker compose down --volumes`, flagged
  as destructive in both places.

### Phase 3 exit gate

- [x] A new developer can clone the repository, add Neon development-branch
  credentials to `.env`, run one Compose command, migrate that branch, and
  launch a smoke extraction. — **passed**, walked end to end on this machine:
  `docker compose up -d` brought Redis to healthy and the API to healthy;
  `docker compose --profile migrate run --rm migrate` reached Neon over the
  direct endpoint and reported `f83a49b127d1 (head)` — already current, so
  nothing was applied; and the extractor profile ran a full extraction.
  Three latent bugs (#1, #2, #4) had to be fixed before this gate could pass.

  The worker was deliberately omitted from the first smoke pass because it can
  launch live Railway infrastructure. It was subsequently started intentionally
  with the configured disposable environment and successfully dispatched the
  genuine `byte-earn` Railway extraction described in the Phase 2 exit gate.

## Phase 4 — Centralize Railway variables safely

Do not import a secret-filled `.env` into the Docker image. Use Railway Shared
Variables and service references.

> **Everything in this phase is Railway dashboard work.** It changes the live
> production project, so none of it was applied from here — that is your call
> to make, not an implementation detail. What follows is the exact set of
> values to enter. The application side that this phase depends on is done:
> the image reads `SERVICE_ROLE`, `DATABASE_URL`, `DATABASE_URL_DIRECT`, and
> `REDIS_URL` from the runtime environment and holds no baked-in secret.

### Shared variables

- [ ] Create environment-level Railway Shared Variables for common application
  configuration. — NEEDS DASHBOARD.
- [ ] Seal sensitive values where Railway operational workflows allow it.
  — NEEDS DASHBOARD.
- [ ] Share each variable only with the services that require it. — NEEDS
  DASHBOARD. The one that matters most: the extractor service must receive
  none of them.
- [ ] Use `${{ shared.VARIABLE_NAME }}` references rather than duplicating
  values manually. — NEEDS DASHBOARD.
- [ ] Store the existing Neon pooled URL as the sealed shared variable
  `NEON_DATABASE_URL_POOLED`. — NEEDS DASHBOARD. The pooled URL is the one
  whose host contains `-pooler`.
- [ ] Store the existing Neon direct URL as the sealed shared variable
  `NEON_DATABASE_URL_DIRECT`. — NEEDS DASHBOARD. Same host **without**
  `-pooler`.
- [ ] Set `DATABASE_URL=${{shared.NEON_DATABASE_URL_POOLED}}` on API and worker.
  — NEEDS DASHBOARD.
- [ ] Set `DATABASE_URL_DIRECT=${{shared.NEON_DATABASE_URL_DIRECT}}` only on the
  migration job/service. — NEEDS DASHBOARD. The migrate role fails closed if
  this is missing, so a misconfiguration here cannot silently migrate through
  the pooler.
- [ ] Use `${{Redis.REDIS_URL}}` for `REDIS_URL`. — NEEDS DASHBOARD.
- [x] Do not create or reference a Railway PostgreSQL service. — done: no
  Postgres appears anywhere in `compose.yaml` or the image, and a test
  enforces it. Nothing to add on Railway.
- [x] Use TLS-enabled Neon connection strings and keep credentials sealed.
  — the URL form is settled (`sslmode=require`, already in use); sealing is
  NEEDS DASHBOARD.
- [ ] Confirm Railway API and worker services have outbound connectivity to the
  Neon endpoint. — NEEDS DASHBOARD, but low risk: the same connection succeeds
  from a container locally, and Railway allows outbound egress by default.
- [ ] If Neon IP allow rules are enabled, configure an approved stable Railway
  egress path before enforcing the allowlist. — NEEDS DASHBOARD. Check this
  *before* switching production over; an allowlist that omits Railway's egress
  fails every connection at once.

> **Note on scheme robustness.** Neon's console emits `postgresql://`, which
> SQLAlchemy maps to psycopg2 — a driver this project does not install. As of
> bug #2 the application rewrites that scheme to `postgresql+psycopg://`
> automatically, so pasting either form into Railway now works. You no longer
> have to remember to edit the prefix by hand.

### Common API and worker variables

- [ ] `FRONTEND_URL`
- [ ] `BACKEND_URL`
- [ ] `DATABASE_URL=${{shared.NEON_DATABASE_URL_POOLED}}`
- [ ] `REDIS_URL=${{Redis.REDIS_URL}}`
- [ ] `SESSION_SECRET`
- [ ] `TOKEN_ENCRYPTION_KEY`
- [ ] Required GitHub application/client/webhook configuration
- [ ] Enabled GitLab/GitBucket OAuth configuration
- [ ] `RAILWAY_API_TOKEN`
- [ ] `RAILWAY_PROJECT_ID`
- [ ] `RAILWAY_SERVICE_ID`
- [ ] `RAILWAY_ENVIRONMENT_ID`
- [ ] `SANDBOX_CALLBACK_BASE_URL` when different from `BACKEND_URL`
- [ ] Redis stream/group/block/reclaim/max-length settings
- [ ] Worker poll and lease settings
- [ ] Per-user and global queue limits

### Service-specific variables

API service — all four NEEDS DASHBOARD, and all four are already the values
Compose uses locally, so they are known-good rather than guesses:

- [ ] `SERVICE_ROLE=api`
- [ ] `RUN_WORKER_ENABLED=false`
- [ ] `WORKSPACE_STORAGE_TYPE=local`
- [ ] `WORKSPACE_STORAGE_DIR=/data/workspaces`

Worker service:

- [ ] `SERVICE_ROLE=worker` — NEEDS DASHBOARD.
- [ ] Do not assign a public domain. — NEEDS DASHBOARD.
- [ ] Do not attach an artifact volume. — NEEDS DASHBOARD.

Extractor service:

- [x] The worker injects `SERVICE_ROLE=extractor` per run. — **done in code**,
  `graphify/server/sandbox.py`. This is the only Phase 4 item that was a code
  change, and it needs no dashboard action.
- [x] Do not provide `DATABASE_URL`, `DATABASE_URL_DIRECT`, or Neon credentials.
  — done and enforced: the launch payload is an exhaustive 10-key set, sent
  with `replace: True`, asserted by
  `test_launch_never_hands_the_extractor_database_or_platform_secrets`. Any
  variable not in that set does not exist in the container.
- [ ] Leave static service variables empty unless Railway itself requires one.
  — NEEDS DASHBOARD. `CLAUDE.md` already warns that anything set here becomes
  a stale fallback that can silently override the per-run injection.
- [ ] Configure restart policy so a successful batch exit is not restarted.
  — NEEDS DASHBOARD: **Settings → Deploy → Restart Policy: `Never`.** Without
  it Railway treats the container's normal exit as a crash and re-runs the
  extraction forever.
- [ ] Do not assign a public domain. — NEEDS DASHBOARD.

### Phase 4 exit gate

- [ ] No secret exists in the image or repository, and all three roles start
  from Railway-provided runtime variables. — **first half passed, second half
  NEEDS DASHBOARD.** The image was canaried clean and every role was shown to
  start purely from injected environment variables (locally, from Compose).
  What remains is entering those variables on Railway.

## Phase 5 — Configure storage and volumes

### Neon PostgreSQL and Railway Redis

- [ ] Use the existing Neon production branch as the only production database.
  — NEEDS DASHBOARD (nothing in code can pick the wrong provider; there is
  only one).
- [x] Use a separate Neon branch for staging and a separate branch for local
  development or automated tests. — done for local: development uses its own
  branch, and `tests/server/conftest.py` refuses to fall back to the
  application `DATABASE_URL`, requiring an explicit
  `GRAPHIFY_TEST_DATABASE_URL`. Staging branch is NEEDS DASHBOARD.
- [x] Use the pooled Neon URL for long-running API and worker application
  traffic. — done: `DATABASE_URL` in `.env` is now the `-pooler` endpoint. It
  previously was not (bug #4).
- [x] Use the direct Neon URL for Alembic migrations and administrative tools.
  — done: `DATABASE_URL_DIRECT`, consumed only by the migrate role, which
  fails closed without it. Verified against Neon.
- [ ] Confirm API and worker connection-pool limits fit the Neon compute size.
  — NEEDS DASHBOARD. Note `db.py` uses SQLAlchemy's default pool size with
  `pool_pre_ping=True`; worth an explicit cap before production load.
- [ ] Configure Neon restore retention, monitoring, and capacity alerts.
  — NEEDS DASHBOARD (Neon console).
- [ ] Use Railway managed Redis storage. — NEEDS DASHBOARD.
- [x] Do not mount Neon or Redis data directories into the Graphify application
  image. — done: the application image declares no `VOLUME` at all, and the
  only mount it receives is the API's artifact directory.
- [ ] Configure Redis persistence, alerts, and capacity monitoring in Railway.
  — NEEDS DASHBOARD. Local Compose already runs Redis with `--appendonly yes`
  so local behaviour matches a persistent managed Redis.

### API artifacts

- [ ] Attach one Railway volume to the API service at `/data/workspaces`.
  — NEEDS DASHBOARD. The path is already the image's default and the Compose
  mount point, so the value is settled.
- [x] Ensure the API runtime user can read/write the mounted directory.
  — done and verified in a running container: `/data/workspaces` is
  `graphify:graphify` mode 755, and a write performed *as* the runtime user
  succeeded.
- [x] Add a safe volume-initialization strategy before dropping privileges.
  — done, and this was the subtle part of Phase 1. Railway attaches volumes
  root-owned, so PID 1 starts as root, chowns the mount, and then drops to uid
  10001 permanently before `exec`. Confirmed in the running API container:
  PID 1 is `graphify-server` running as uid 10001, with the dispatcher gone.
  The production entrypoint explicitly disables uvicorn reload, so it does not
  insert a development reloader supervisor and Railway's SIGTERM reaches the
  server directly. A read-only or externally managed mount logs a clear
  warning instead of crash-looping.
- [x] Confirm artifacts survive an API redeployment. — done: wrote a file,
  ran `docker compose up --force-recreate api`, and read it back intact.
- [x] Keep one API replica while using a local attached volume. — done locally
  (single replica); Railway replica count is NEEDS DASHBOARD.
- [ ] Create a later migration plan to S3-compatible object storage before
  enabling multiple API replicas. — deferred by design, and the constraint is
  recorded here: **do not raise the API replica count above 1 while
  `WORKSPACE_STORAGE_TYPE=local`.** A second replica gets a different volume
  and will serve 404s for artifacts written by the first.

### Worker and extractor

- [x] Worker uses no persistent filesystem. — done: no `volumes` key, asserted
  by `test_only_the_api_is_stateful_and_published`.
- [x] Extractor uses ephemeral `/workspace` only. — done: created and owned in
  the image, never a mount, no `VOLUME` declared; parity-tested against
  `Dockerfile.sandbox`.
- [x] Extractor uploads artifacts before exiting. — unchanged behaviour in
  `scripts/sandbox_entrypoint.py`, which was not modified.

### Phase 5 exit gate

- [x] Neon state, the Redis queue, and API artifacts each survive the expected
  restart test — **passed locally; the Railway equivalent NEEDS DASHBOARD.**
  Neon is external and unaffected by container restarts (verified by
  reconnecting and reading `alembic_version` after recreates); Redis runs
  `--appendonly yes` against the named `redis-data` volume; and the API
  artifact survived a forced container recreate.

## Phase 6 — Configure Railway services from the same image

- [x] Build one immutable image tag, preferably a commit SHA. — built for
  `linux/amd64` as
  `railway-sql-ws-20260802T070343Z`; the timestamped tag is unique because the
  release was produced from an intentionally uncommitted worktree.
- [x] Push it to GHCR or another Railway-accessible registry. — pushed to
  `ghcr.io/abdullah-wpcoderrs/graphify-platform`.
- [x] Record the resulting image digest. — OCI index digest
  `sha256:f63820e15d8f8807e4c16e8dc36489aecad5f9f710f4e13345d3fcd4d36d0972`;
  `linux/amd64` image manifest
  `sha256:504c7b3157ebe34e98a720782b74118a3283eb18ac219444c1e4fbcdadff2f3f`.
- [ ] Point API, worker, and extractor services to the same digest.
- [ ] Set the role variable for API and worker.
- [x] Configure the extractor role injection in worker code. — done and
  verified both by regression tests and the successful Railway launch log.
- [ ] Give only the API a public domain.
- [ ] Keep worker and extractor on Railway private infrastructure.
- [ ] Verify API and worker can connect to Neon from Railway using the pooled
  production URL.
- [ ] Verify the extractor environment contains no Neon hostname, username,
  password, or connection URL.
- [ ] Start with one API replica and one worker replica.
- [ ] Disable automatic extractor redeploys from image-tag changes.
- [ ] Configure Railway spend alerts, hard limits, and replica limits.

### Phase 6 exit gate

- [ ] Railway shows the API, worker, and extractor using the same image digest
  with different isolated roles.

## Phase 7 — Migration and release order

- [ ] Build and scan the unified image.
- [x] Push the immutable image tag/digest. — release candidate
  `railway-sql-ws-20260802T070343Z`, digest `sha256:f63820e15d8f8807e4c16e8dc36489aecad5f9f710f4e13345d3fcd4d36d0972`.
- [ ] Run `SERVICE_ROLE=migrate` with the direct URL against the Neon staging
  branch.
- [ ] Deploy the worker role to staging.
- [ ] Deploy the API role to staging.
- [ ] Update the extractor service to the same digest.
- [x] Run one public-repository extraction. — `abdullah-wpcoderrs/byte-earn`
  reached Graph ready through the local API/worker and Railway extractor. This
  proves the flow, but must be repeated after Railway is changed to the release
  candidate digest before the Phase 7 exit gate can close.
- [ ] Run one private-repository extraction.
- [ ] Test cancel during cloning.
- [ ] Test cancel during indexing.
- [ ] Test Redis unavailable at enqueue time.
- [ ] Test worker restart with a pending Redis message.
- [ ] Test API restart with persisted artifacts.
- [ ] Confirm no stale callback can update a replacement run.
- [ ] Promote the exact staging digest to production.

### Phase 7 exit gate

- [ ] All staging release tests pass against the exact production image digest.

## Phase 8 — Remove temporary deployment paths

Do this only after the unified production deployment is stable.

- [ ] Mark `Dockerfile.worker` deprecated.
- [ ] Mark `Dockerfile.sandbox` deprecated.
- [ ] Keep both available for at least one rollback window.
- [ ] Update build scripts and CI to build `Dockerfile.platform` only.
- [x] Update `docs/railway-setup.md` to use the unified image. — updated with
  the build, runtime smoke, immutable GHCR push, digest verification, and
  Railway image-update sequence.
- [ ] Update `docs/redis-run-queue.md` to use the unified image and roles.
- [ ] Remove obsolete registry images only after confirming they are not used by
  any Railway environment.
- [ ] Record the final deployment architecture and image digest.

---

# Exact file-change map

## Files to create

| File | Purpose |
| --- | --- |
| `Dockerfile.platform` | One hardened multi-role application image |
| `scripts/platform_entrypoint.py` | Selects API, worker, existing sandboxed-extractor behavior, or migration role |
| `compose.yaml` | Local API + worker + Redis orchestration connected to a Neon development branch |
| `tests/server/test_platform_entrypoint.py` | Role dispatch and fail-closed tests |
| `docs/unified-railway-platform-plan.md` | This implementation and rollout checklist |

## Files to modify

| File | Required change |
| --- | --- |
| `.dockerignore` | Confirm platform build excludes secrets, artifacts, volumes, docs, and tests |
| `.env.example` | Add `SERVICE_ROLE`, pooled/direct Neon URL placeholders, Compose settings, volume path, and centralized variable guidance |
| `pyproject.toml` | Confirm all platform role dependencies and entrypoints are packaged |
| `uv.lock` | Lock any dependency changes |
| `graphify/server/sandbox.py` | Inject `SERVICE_ROLE=extractor` into every run deployment |
| `graphify/server/config.py` | Add role/storage settings and separate direct migration URL support if needed |
| `graphify/server/app.py` | Keep embedded worker disabled in production API role |
| `graphify/server/run_worker.py` | Preserve exact-run dispatch and unified-image extractor launch behavior |
| `scripts/sandbox_entrypoint.py` | Preserve the existing sandbox behavior while it is launched through the platform extractor role |
| `tests/server/test_deployment_security.py` | Add platform image and secret-canary checks |
| `tests/server/test_sandbox_api.py` | Verify role and run-specific Railway variables |
| `docs/railway-setup.md` | Replace separate sandbox-image instructions with unified-image setup |
| `docs/redis-run-queue.md` | Replace separate worker-image instructions with role-based deployment |

## Files to retain temporarily for rollback

| File | Rollback purpose |
| --- | --- |
| `Dockerfile.worker` | Restore the dedicated worker image if platform rollout fails |
| `Dockerfile.sandbox` | Existing sandbox/extractor image retained as the behavioral baseline and rollback image |
| `Dockerfile` | Existing MCP image; it is outside the Railway application-role consolidation |

---

# How the completed system works

## Successful user launch

1. A user clicks **Launch Workspace**.
2. The API validates authentication, repository input, credentials, and quotas.
3. Neon PostgreSQL commits an immutable `QUEUED` run.
4. The API writes only the `run_id` to Redis.
5. The worker consumes the message and locks that exact run.
6. Neon PostgreSQL grants the global active slot only if no extractor is already
   active.
7. The worker deploys the same platform image with
   `SERVICE_ROLE=extractor` and run-scoped variables.
8. The extractor clones the repository, builds artifacts, and calls the API.
9. The API writes artifacts to its attached volume and updates Neon PostgreSQL.
10. The UI receives `READY` and opens the workspace.

## Cancellation

1. The user clicks cancel.
2. The API revokes the run callback hash.
3. The exact Railway deployment ID is canceled or stopped.
4. Run-scoped Railway variables are cleared.
5. Only then does Neon PostgreSQL release the global active slot.
6. Redis can deliver the next queued run.

## Redis outage

1. The API still commits the run to Neon PostgreSQL.
2. Redis notification failure is logged without losing the run.
3. The worker's Neon PostgreSQL fallback scan discovers the queued run.
4. Normal execution continues when the worker safely claims it.

## Worker crash

1. Redis leaves the message pending.
2. Neon PostgreSQL retains the run state and lease.
3. Another worker reclaims the idle message.
4. The database determines whether it is safe to acknowledge, retry, or remain
   fail-closed.

---

# Bugs found while implementing

Five implementation defects surfaced during Phases 1–3, followed by two
coverage/runtime findings during the live hybrid test. Most share one shape:
**the application had never run from a wheel inside a container and through a
real browser-to-Railway flow**, so differences between a checkout, a built
image, and a live client connection had gone untested.

### 1. The API's router package was never packaged

`pyproject.toml` lists `[tool.setuptools] packages` explicitly, and
`graphify.server.routes` was missing. Importing from a checkout worked because
the directory is right there; the installed wheel simply did not contain the
routers, so the API died at startup with `ModuleNotFoundError: No module named
'graphify.server.routes'`.

This affected the *existing* worker image too — it was only ever invisible
because `graphify-run-worker` does not import `app.py`.

Fixed by adding the package. Guarded by
`test_every_subpackage_is_declared_for_packaging`, which walks `__init__.py`
files on disk and fails if any is undeclared, so the next subpackage cannot
repeat this.

### 2. Neon's connection URL selects a driver that is not installed

Neon's console emits `postgresql://…`. SQLAlchemy maps that bare scheme to
**psycopg2**, which this project neither depends on nor installs — it uses
psycopg3. A checkout can survive if psycopg2 happens to be present in the
virtualenv; the image cannot, and fails deep inside engine creation with
`ModuleNotFoundError: No module named 'psycopg2'`.

Fixed by normalizing the scheme to `postgresql+psycopg://` in one shared
helper (`normalize_database_url`) used by both `Settings` and `alembic/env.py`
— the migration role reads `DATABASE_URL` from the environment without ever
constructing `Settings`, so fixing only one left the other broken.

### 3. `.env` means two different things to two different parsers

The same file yields different values depending on who reads it:

| | python-dotenv (checkout) | Docker `env_file` (container) |
| --- | --- | --- |
| `KEY="value"` | quotes stripped | quotes **kept**, literally |
| `KEY="a\nb"` | `\n` becomes a newline | stays a backslash and an `n` |
| `${{...}}` | passed through | **rejected**, unless `format: raw` |

All three bit. The quoted `DATABASE_URL` reached SQLAlchemy with its quotes
attached; `GITHUB_PRIVATE_KEY` arrived with literal `\n` and failed PEM
validation with a message pointing at the wrong cause; and Railway reference
syntax in `.env` made Compose refuse to start anything at all.

Fixed on both sides: `compose.yaml` uses `env_file: … format: raw`, and
`config.py` strips matching surrounding quotes from every string setting and
un-escapes the PEM. One `.env` now behaves identically under uvicorn, Compose,
and Railway.

### 4. `.env` had three duplicated keys, and the wrong copies were winning

`DATABASE_URL`, `REDIS_URL`, and `RUN_WORKER_ENABLED` were each defined twice.
Last assignment wins, so:

- `DATABASE_URL` resolved to the **direct** (non-pooled) endpoint, quoted and
  driverless — the opposite of the intended pooled connection, and exactly
  what long-running services must not use.
- `REDIS_URL` resolved to the literal string `${{Redis.REDIS_URL}}`, which is
  Railway syntax and meaningless locally.

Fixed in place (a timestamped `env.backup-*` was written first): the direct URL
was promoted to the `DATABASE_URL_DIRECT` variable the migrate role actually
reads, `DATABASE_URL` now resolves to the pooled endpoint, and the shadowed
duplicates were commented out with an explanation. No secret value changed.

### 5. Dropping uid did not change `HOME=/root`

The first platform dispatcher correctly called `setgid`/`setuid`, but process
environment variables do not change with the kernel identity. Because the
container initially starts as root, the API inherited `HOME=/root` after it
became uid 10001. Psycopg/libpq checks `$HOME/.postgresql/postgresql.crt`; each
IPv4 Neon connection therefore failed with `Permission denied` even though the
same probe worked in a container started directly as uid 10001.

This was introduced in the initial unified dispatcher implementation and found
by the live container verification in this review. Fixed by setting `HOME`,
`USER`, and `LOGNAME` from the `graphify` passwd entry in the exact environment
passed to `exec`. Guarded by `test_runtime_identity_environment_matches_the_dropped_user`
and by the live Neon-backed `/health` container test.

### 6. The first WebSocket snapshot was outside the disconnect guard

The progress route accepted a WebSocket and immediately sent the current
project snapshot before entering its existing `WebSocketDisconnect` handler.
During frontend hydration, the browser can replace that first socket after the
handshake but before the first frame is written. The normal client disconnect
therefore escaped as an ASGI application traceback with code 1006, even though
the replacement socket continued normally.

Fixed by moving the initial snapshot, terminal close, and polling setup inside
the existing disconnect guard. Guarded by
`test_websocket_disconnect_during_initial_snapshot_is_normal`; the published
release candidate was also inspected to confirm it contains this exact guard.

### 7. The unified extractor omitted the optional SQL grammar

The first successful `byte-earn` extraction produced a valid graph but warned
that 49 `.sql` files contributed nothing because `tree_sitter_sql` was not
installed. The warning was printed on stderr and labelled as an error by
Railway's log viewer, but it was non-terminal: labeling, artifact upload, and
the final callback all completed. It nevertheless represented real coverage
loss for SQL-heavy repositories.

Fixed by adding the `sql` extra to both the builder and runtime dependency sets
in `Dockerfile.platform`. The `linux/amd64` release candidate imported
`tree_sitter_sql` successfully and extracted a SQL smoke schema into 3 nodes
and 3 edges. The Phase 1 deployment-security test now enforces the complete
extras string so a later edit cannot silently drop SQL support.

---

# Acceptance criteria

The consolidation is complete only when all of these are true:

- [ ] One image digest runs API, worker, and extractor roles.
- [ ] The extractor role preserves the existing sandbox's isolation, entrypoint,
  callback, cancellation, cleanup, and ephemeral-workspace behavior.
- [ ] An unknown role cannot accidentally start the API or worker.
- [ ] No secret or `.env` file exists in image filesystems or saved layers.
- [ ] API is the only public backend service.
- [ ] Worker and extractor are private and stateless.
- [ ] Neon is the only PostgreSQL provider and uses managed persistent storage.
- [ ] API and worker use the pooled Neon connection; migrations use the direct
  Neon connection.
- [ ] Production, staging, and local development use separate Neon branches.
- [ ] Railway Redis uses managed persistent storage.
- [ ] API artifacts survive redeployment.
- [ ] Redis duplicates never create duplicate Railway deployments.
- [ ] Redis failure does not lose committed runs.
- [ ] Worker failure does not release the active slot unsafely.
- [ ] Exact deployment cancellation works.
- [ ] Stale callbacks are rejected.
- [ ] Staging and production use the same tested image digest.
- [ ] A documented rollback restores the previous worker and sandbox images.

---

# Rollback plan

If the unified image fails in production:

1. Stop new project launches.
2. Keep Neon and Redis running; do not delete database branches, queues, or
   volumes.
3. Restore the previous API deployment.
4. Point the worker back to the last known `Dockerfile.worker` image.
5. Point the extractor back to the last known `Dockerfile.sandbox` image.
6. Reconcile any active run by exact deployment ID.
7. Resume launches only after one successful smoke extraction.

Never roll the database backward until application rollback compatibility has
been checked. Prefer backward-compatible migrations so old and new services can
coexist during the deployment window.
