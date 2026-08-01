# Railway deployment setup for Graphify

You do not need Railway PostgreSQL if you are already using Neon. In this setup, Railway should host the API, Redis, queue worker, and extractor, while Neon remains the external PostgreSQL database.

## Architecture

```text
Vercel frontend
      ↓
Railway API
   ↙       ↘
Neon      Railway Redis
Postgres     ↓
            Queue worker
                 ↓
          Railway extractor
```

This is a clean split between frontend hosting, application runtime, data persistence, and background job execution.

---

## Why Neon may not be working

The most common issue is the PostgreSQL connection string format.

Neon typically provides a URL in this form:

```bash
postgresql://user:password@host/database?sslmode=require
```

Graphify’s async SQLAlchemy configuration expects:

```bash
postgresql+psycopg://user:password@host/database?sslmode=require
```

The fix is simple: change only the prefix from `postgresql://` to `postgresql+psycopg://`.

Other common causes include:

- the `DATABASE_URL` was added to Vercel instead of Railway
- `alembic upgrade head` was never run
- the API and worker are pointing to different Neon branches or databases
- `sslmode=require` is missing
- tests are being run without `GRAPHIFY_TEST_DATABASE_URL`, which is intentional for production safety

For the live API and worker, use Neon’s pooled connection string that includes `-pooler`. For migrations, use the direct, non-pooled connection string instead.

---

## 1. Prepare Neon

From Neon’s Connect dialog, copy both of the following:

- pooled connection — for the API and worker
- direct connection — for migrations

Convert the scheme accordingly:

```bash
# Railway API and worker
DATABASE_URL=postgresql+psycopg://user:password@ep-name-pooler.region.aws.neon.tech/neondb?sslmode=require&channel_binding=require
```

Run migrations with the direct URL:

```bash
DATABASE_URL="postgresql+psycopg://user:password@ep-name.region.aws.neon.tech/neondb?sslmode=require&channel_binding=require" \
uv run alembic upgrade head
```

This is important because Alembic loads the validated application configuration and requires the required environment variables to be present.

For integration tests, create a separate disposable Neon branch and use a dedicated variable such as:

```bash
GRAPHIFY_TEST_DATABASE_URL=postgresql+psycopg://...test-branch...
```

Never point this at production.

---

## 2. Create the Railway Redis service

In the Railway project:

1. Select New → Database → Redis
2. Keep the service private and do not expose a public domain
3. Add this environment reference to both the API and worker:

```bash
REDIS_URL=${{Redis.REDIS_URL}}
```

Also add the queue-related settings:

```bash
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

---

## 3. Create the Railway API service

Connect the GitHub repository and select the project root directory.

Important: the root Dockerfile in this repo starts the MCP server, not the API server. Because of that, you have two options:

- use Railway’s Railpack builder and install `.[server]`
- create a dedicated `Dockerfile.api`

With Railpack, configure:

```bash
Build command: pip install ".[server]"
Start command: graphify-server
```

Set these variables:

```bash
RUN_WORKER_ENABLED=false

FRONTEND_URL=https://your-vercel-domain.vercel.app
BACKEND_URL=https://your-api-domain.up.railway.app
SANDBOX_CALLBACK_BASE_URL=https://your-api-domain.up.railway.app

DATABASE_URL=<pooled Neon URL>
REDIS_URL=${{Redis.REDIS_URL}}
```

Also copy the session, encryption, GitHub App, Railway, and queue variables from the project’s environment template, such as [.env.example](../.env.example).

Only the API service should have a public Railway domain.

---

## 4. Create the Railway queue worker

Connect the same repository to a separate Railway service.

Set:

```bash
RAILWAY_DOCKERFILE_PATH=Dockerfile.worker
```

If the project root is the repository root rather than the `graphify` directory, use:

```bash
RAILWAY_DOCKERFILE_PATH=graphify/Dockerfile.worker
```

The worker image already starts:

```bash
graphify-run-worker
```

Do not expose the worker to a public domain.

Copy these values from the API configuration:

- pooled Neon `DATABASE_URL`
- Redis settings
- `TOKEN_ENCRYPTION_KEY`
- Railway token and IDs
- backend and callback URLs
- Git provider configuration
- queue and lease settings

Start with one worker replica.

---

## 5. Configure the extractor service

The extractor uses the container image:

```bash
ghcr.io/abdullah-wpcoderrs/graphify-sandbox:latest
```

Recommended service configuration:

- restart policy: Never
- no public domain
- no static service variables
- disable automatic image redeploys

The worker injects repository, LLM, and callback variables for each job run and clears them afterward.

---

## 6. Configure Vercel

Set the API URL in Vercel:

```bash
NEXT_PUBLIC_API_URL=https://your-api-domain.up.railway.app
```

Then redeploy the frontend.

Set the matching frontend URL in Railway as well:

```bash
FRONTEND_URL=https://your-vercel-domain.vercel.app
```

---

## 7. Persistent artifacts

Artifacts currently use local storage. To support this in Railway, attach a volume to the API and set:

```bash
WORKSPACE_STORAGE_TYPE=local
WORKSPACE_STORAGE_DIR=/data/workspace-storage
```

Until storage is migrated to an S3-compatible object store, keep only one API replica. Multiple API replicas cannot safely share separate local filesystems.

---

## 8. Deployment order

Deploy in this order:

1. apply Neon migrations
2. create Redis
3. configure the extractor
4. deploy the worker
5. deploy the API
6. update and redeploy Vercel
7. launch a small public repository
8. launch a second repository and confirm it waits
9. test cancellation

---

## Notes and references

For full queue setup and recovery details, see [redis-run-queue.md](redis-run-queue.md).

Railway supports GitHub deployment and custom Dockerfile paths through `RAILWAY_DOCKERFILE_PATH`.

This architecture is consistent with Railway’s Dockerfile and deployment documentation.
