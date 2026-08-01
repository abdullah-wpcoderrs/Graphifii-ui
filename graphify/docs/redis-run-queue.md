# Redis extraction queue — setup and system flow

Graphify uses Redis Streams to deliver extraction runs quickly to a dedicated
worker. Redis carries only an immutable `run_id`; PostgreSQL stores the real
run state, quotas, callback hash, lease, deployment ID, and global active slot.

This separation is intentional:

- Redis provides blocking delivery, acknowledgements, and abandoned-message
  reclaiming.
- PostgreSQL provides correctness, idempotency, and recovery when Redis is
  unavailable.
- Railway runs the extraction container.

The current Railway extractor is one shared mutable service, so extraction
concurrency remains **one**. Adding API or worker replicas improves availability
but must not increase sandbox concurrency until each run has isolated Railway
compute and variables.

## Required production services

One Railway environment should contain:

| Service | Purpose | Image/start command |
| --- | --- | --- |
| API | Authentication, launch requests, callbacks, artifacts, WebSockets | Backend source/image with `graphify-server` |
| PostgreSQL | Authoritative users, projects, runs, leases, usage, callback replay ledger | Railway PostgreSQL or compatible external Postgres |
| Redis | Run-ID delivery and pending-message recovery | Railway Redis |
| Worker | Claims runs and controls the singleton extractor | `Dockerfile.worker` / `graphify-run-worker` |
| Extractor | Clones one repository, builds artifacts, then exits | `Dockerfile.sandbox` |

The worker and extractor are different images. The worker is long-running and
never clones repositories itself. The extractor is ephemeral and never reads
Redis or the main database.

## Architecture

```text
Browser
   |
   v
API service ---- transaction ----> PostgreSQL
   |                                  |
   | XADD run_id                      | authoritative QUEUED run
   v                                  |
Redis Stream                          |
   | XREADGROUP                       |
   v                                  v
Worker service ---- row lock/claim -> extraction_runs.active_slot = 1
   |
   | exact deployment ID
   v
Railway extractor ---- run-scoped callbacks/artifacts ----> API
```

## Step 1 — Add Redis

In the Railway project containing the API:

1. Select **New → Database → Redis**.
2. Keep Redis, the API, worker, and PostgreSQL in the same Railway environment.
3. Use Railway's private connection URL; Redis does not need a public endpoint.
4. In both the API and worker services, set:

```env
REDIS_URL=${{Redis.REDIS_URL}}
```

If the generated Redis service has a different name, replace `Redis` in the
reference with that service name.

## Step 2 — Configure shared queue settings

Set the same values on the API and worker services:

```env
REDIS_RUN_QUEUE_STREAM=graphify:extraction-runs
REDIS_RUN_QUEUE_GROUP=graphify-dispatchers
REDIS_RUN_QUEUE_BLOCK_MS=2000
REDIS_RUN_QUEUE_RECLAIM_SECONDS=60
REDIS_RUN_QUEUE_MAX_LENGTH=10000

RUN_WORKER_POLL_SECONDS=2
RUN_WORKER_LEASE_SECONDS=14400
MAX_QUEUED_RUNS_PER_USER=3
MAX_QUEUED_RUNS_GLOBAL=100
```

What these control:

| Variable | Meaning |
| --- | --- |
| `REDIS_RUN_QUEUE_STREAM` | Redis Stream that contains run notifications |
| `REDIS_RUN_QUEUE_GROUP` | Consumer group shared by all dispatchers |
| `REDIS_RUN_QUEUE_BLOCK_MS` | Maximum blocking wait before the worker performs a PostgreSQL recovery scan |
| `REDIS_RUN_QUEUE_RECLAIM_SECONDS` | How long an unacknowledged message is idle before another worker may reclaim it |
| `REDIS_RUN_QUEUE_MAX_LENGTH` | Approximate stream history cap; PostgreSQL retains durable history |
| `RUN_WORKER_POLL_SECONDS` | Retry delay after Redis/worker errors and polling interval without Redis |
| `RUN_WORKER_LEASE_SECONDS` | Fail-closed ownership lease for an active Railway deployment |
| `MAX_QUEUED_RUNS_*` | Admission limits enforced from PostgreSQL, not Redis counters |

## Step 3 — Configure API services

Every production API replica should use:

```env
RUN_WORKER_ENABLED=false
```

Start command:

```bash
graphify-server
```

The API still connects to Redis to enqueue `run_id` messages. Disabling the
embedded worker prevents API restarts and horizontal scaling from also changing
the worker topology.

For local development, it is fine to leave `RUN_WORKER_ENABLED=true`; the API
then runs one embedded dispatcher and no separate worker process is required.

## Step 4 — Build and publish the worker image

From `graphify/`, build the dedicated image:

```bash
docker build -f Dockerfile.worker -t graphify-run-worker:latest .
```

On Apple Silicon, build the Railway target architecture explicitly:

```bash
docker build --platform linux/amd64 \
  -f Dockerfile.worker \
  -t graphify-run-worker:latest .
```

Verify the installed entrypoint and critical dependencies:

```bash
docker run --rm --entrypoint python graphify-run-worker:latest -c \
  "import redis, sqlalchemy, psycopg, graphify.server.run_worker; print('worker image ok')"
```

Publish it to GHCR or another Railway-accessible registry:

```bash
docker tag graphify-run-worker:latest \
  ghcr.io/abdullah-wpcoderrs/graphify-run-worker:latest
docker push ghcr.io/abdullah-wpcoderrs/graphify-run-worker:latest
```

If using GHCR, make the package public or configure Railway with private
registry credentials. The detailed authentication steps are in
[Railway sandbox setup](railway-setup.md#step-c--push-to-a-registry-ghcr).

## Step 5 — Create the dedicated worker service

Create another Railway service from the worker image.

1. Name it `graphify-run-worker`.
2. Under **Settings → Source → Image**, use
   `ghcr.io/abdullah-wpcoderrs/graphify-run-worker:latest`.
3. Give it the environment variables listed in the matrix below.
4. The image already has this entrypoint, so no start-command override is
   required:

```bash
graphify-run-worker
```

5. Do not assign it a public domain.
6. Start with one replica. A second replica is safe for failover, but cannot
   increase throughput while the extractor remains a singleton service.

`RUN_WORKER_ENABLED` only controls the worker embedded in `graphify-server`;
the dedicated `graphify-run-worker` command always runs the dispatcher.

### API and worker environment matrix

The current backend and worker use the same validated Settings model. Configure
these through Railway variables or reference variables; do not bake them into
either image.

| Variable group | API | Worker | Extractor service |
| --- | ---: | ---: | ---: |
| `DATABASE_URL` | Required | Required | Never set |
| `REDIS_URL` and `REDIS_RUN_QUEUE_*` | Required | Required | Never set |
| `FRONTEND_URL`, `BACKEND_URL` | Required | Required | Never set |
| `SESSION_SECRET` | Required | Required by shared settings validation | Never set |
| `TOKEN_ENCRYPTION_KEY` | Required | Required to decrypt launch credentials | Never set |
| GitHub app/client/webhook variables | Required | Required by shared settings and token refresh | Never set |
| Optional GitLab/GitBucket OAuth variables | When enabled | When enabled for token refresh | Never set |
| `RAILWAY_API_TOKEN` and three Railway IDs | Required for launch routes | Required to launch/cancel jobs | Never set |
| `SANDBOX_CALLBACK_BASE_URL` | Required only when different from `BACKEND_URL` | Same public callback base | Injected per run |
| `RUN_WORKER_ENABLED` | `false` in production | Ignored by dedicated command | Never set |
| Queue limits and lease settings | Required/same values | Required/same values | Never set |

Keep the extractor service's static variables empty. The worker injects only
the run-scoped values listed in [Railway sandbox setup](railway-setup.md#what-the-backend-sends-the-job),
then clears them before releasing the global active slot.

## Step 6 — Apply the database migration

Before deploying the API and worker code, apply the immutable-run migration:

```bash
alembic upgrade head
```

Deploy the worker and then the API. Both versions must understand the same run
schema before users create new projects.

## Step 7 — Verify the complete deployment

1. Launch one small public repository from the UI.
2. Confirm the project immediately shows `Queued for provisioning`.
3. Confirm the worker logs show a Redis Streams dispatcher and the exact run ID.
4. Confirm the run advances through `STARTING`, `CLONING`, `INDEXING`, and
   `READY`.
5. Launch a second repository while the first is active. It must remain queued
   until the first deployment reaches a verified terminal state.
6. Cancel a test run and confirm the worker/API logs show cancellation of the
   exact deployment ID and release of the active slot only after cleanup.

Optional Redis diagnostics:

```bash
redis-cli -u "$REDIS_URL" XINFO GROUPS graphify:extraction-runs
redis-cli -u "$REDIS_URL" XPENDING graphify:extraction-runs graphify-dispatchers
```

Queue messages contain only run IDs. Never add repository tokens, callback
credentials, LLM keys, or complete repository URLs to Redis payloads.

## User flow — what someone experiences

1. The user selects a repository and chooses **Launch Workspace**.
2. The API authenticates the user and validates the repository/provider.
3. PostgreSQL atomically checks the per-user, per-project, and global limits.
4. The API creates a new immutable `ExtractionRun` in `QUEUED` state.
5. The UI receives the project and run IDs and begins watching progress.
6. Redis notifies the worker without making the browser wait for provisioning.
7. The worker safely claims the run and the UI moves to cloning/indexing.
8. The sandbox uploads artifacts and reports `READY` or `FAILED`.
9. The UI opens the completed workspace or displays the bounded failure message.
10. If the user cancels, the exact Railway deployment is stopped and callbacks
    from that run are revoked.

## System flow — successful extraction

1. `POST /api/projects` starts a PostgreSQL transaction.
2. The API takes the launch advisory lock, checks quotas, creates the run, and
   commits it before touching Redis.
3. The API performs `XADD` with only `run_id`.
4. A worker receives the message using `XREADGROUP`.
5. The worker locks that exact run with `FOR UPDATE SKIP LOCKED`.
6. PostgreSQL's unique `active_slot=1` constraint prevents every other worker
   from owning the singleton Railway service.
7. The worker generates a random per-run callback secret and stores only its
   hash.
8. The worker loads immutable repository inputs and current encrypted
   credentials from PostgreSQL.
9. It replaces the shared Railway variables and invokes
   `serviceInstanceDeployV2`.
10. The exact returned deployment ID is committed to the run.
11. Only after that commit does the worker `XACK` the Redis message.
12. Run-scoped callbacks extend the lease and update monotonic progress.
13. On `READY`, `FAILED`, or cancellation, Railway variables are cleared before
   PostgreSQL releases the global active slot.

## Recovery flows

### Redis is unavailable during launch

The PostgreSQL transaction still commits and the API returns normally. The
worker's periodic database scan finds the `QUEUED` row later. Redis is an
acceleration and delivery layer, not a condition for preserving the request.

### A worker dies before claiming

The Redis message remains pending. After
`REDIS_RUN_QUEUE_RECLAIM_SECONDS`, another consumer uses `XAUTOCLAIM` and tries
the same run ID.

### A worker dies after claiming but before launching Railway

The PostgreSQL lease eventually expires. Since no deployment was triggered,
an operator can safely reconcile or fail the run. The worker never starts a
second run while ownership is uncertain.

### Railway may have started but no deployment ID was committed

The run and Redis message remain unacknowledged and the global active slot stays
locked. This deliberately requires manual reconciliation: automatically retrying
could launch a second deployment with overwritten variables.

### Redis delivers a duplicate

The worker checks PostgreSQL. Terminal runs or runs with a safely persisted
deployment ID are acknowledged without launching again. Queue delivery is
therefore at-least-once, while external deployment remains idempotent/fail-closed.

## Scaling safely

- Scale API replicas independently; all of them may enqueue to the same stream.
- Keep one worker replica for normal operation and optionally one for failover.
- Do not increase extraction concurrency while all runs mutate one Railway
  service's variables.
- To process runs in parallel, first replace the singleton extractor with an
  isolated service/job and immutable variables per run. Then increase worker
  replicas and introduce an explicit concurrency limit.
- Keep PostgreSQL constraints even after scaling. Redis locks alone are not the
  correctness boundary.
