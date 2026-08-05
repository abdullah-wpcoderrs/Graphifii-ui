# Graph UI — Deployment & Ops Runbook

This is the top-level operations reference for running, deploying, and
maintaining Graphify: the `graphify` backend (API, queue worker, sandboxed
extractor) and the `frontend` Next.js UI. It's a quickstart for people who
already know the codebase and need the exact command to restart something —
for architecture and rollout rationale, see
[`graphify/docs/unified-railway-platform-plan.md`](graphify/docs/unified-railway-platform-plan.md);
for the full backend reference, see [`graphify/CLAUDE.md`](graphify/CLAUDE.md).

## Repository layout

```text
Graph UI/
├── frontend/    Next.js UI (deployed separately)
├── graphify/    Python backend: API, worker, sandboxed extractor
└── compose.yaml Local Docker Compose stack (api + worker + redis)
```

One Docker image (`graphify/Dockerfile.platform`) runs three Railway roles —
`SERVICE_ROLE=api|worker|extractor` — plus a one-shot `migrate` role. Neon
PostgreSQL is the only database provider; Redis is a managed Railway service
used only for queue delivery.

## Starting the backend locally (without Docker)

```bash
cd graphify
uv run uvicorn graphify.server.app:app --port 8000
```

**No `--reload`.** Editing a `.py` file under `graphify/server/` while the
server is running does not hot-reload it — kill and restart the process:

```bash
PID=$(lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $2}')
[ -n "$PID" ] && kill $PID
sleep 2
cd graphify && uv run uvicorn graphify.server.app:app --port 8000
```

Health check: `curl http://localhost:8000/health` → `{"status":"ok"}`.

## Local Docker Compose (API + worker + Redis)

```bash
# Start API, worker, and Redis (no database container — Neon is external)
docker compose up -d

# Run migrations against your Neon development branch
docker compose --profile migrate run --rm migrate

# Smoke-test the extractor role against a public repo
docker compose --profile extractor run --rm \
  -e REPO_URL=https://github.com/pypa/sampleproject.git \
  -e PROJECT_ID=<uuid> \
  -e RUN_ID=<uuid> \
  -e GRAPHIFY_CALLBACK_URL=http://api:8000/api/internal/projects/<uuid>/runs/<uuid>/status \
  -e GRAPHIFY_CALLBACK_SECRET=test-secret \
  extractor

# Stop (data persists in named volumes)
docker compose down

# Stop and erase Redis/artifact volumes
docker compose down --volumes
```

Before the first run, set `DATABASE_URL` (pooled) and `DATABASE_URL_DIRECT`
(direct) in `graphify/.env` to your Neon development branch — see
`graphify/.env.example`.

## The sandbox callback tunnel (local dev only)

Sandbox jobs run on Railway and need to reach your laptop's backend, so local
dev tunnels through Cloudflare:

```bash
cloudflared tunnel --url http://localhost:8000
```

Every restart prints a new random URL. Update `graphify/.env`:

```
SANDBOX_CALLBACK_BASE_URL=<the new tunnel URL, no trailing slash>
```

then restart the backend. Do **not** set `BACKEND_URL` to the tunnel URL —
`BACKEND_URL` drives OAuth redirect URIs and cookie `Secure` flags and must
stay `http://localhost:8000` locally; `SANDBOX_CALLBACK_BASE_URL` is only for
the container's callback. Verify both ends:

```bash
curl http://localhost:8000/health
curl "$(grep ^SANDBOX_CALLBACK_BASE_URL= graphify/.env | cut -d= -f2)/health"
```

## Database migrations

```bash
cd graphify
uv run alembic current       # revision the DB is actually on
uv run alembic heads         # revision the code expects
uv run alembic upgrade head  # apply pending migrations
uv run alembic check         # confirm no model/migration drift
```

## Admin account

```bash
cd graphify
uv run python scripts/seed_admin.py
```

Reads `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `graphify/.env`. Re-running with
the same email resets that admin's password (12+ characters, argon2-hashed).

## Building & deploying the platform image

### Push the image built by Docker Compose

`docker compose up --build` creates the local image
`graphify-platform:local`. Give that image an immutable GHCR tag, then push it:

```bash
cd "/Users/mac/Documents/Graph UI"

# Prompts for a GitHub PAT with write:packages permission.
docker login ghcr.io -u abdullah-wpcoderrs

GRAPHIFY_RELEASE_TAG="$(date -u +%Y%m%dT%H%M%SZ)"
GRAPHIFY_IMAGE_REF="ghcr.io/abdullah-wpcoderrs/graphify-platform:${GRAPHIFY_RELEASE_TAG}"

docker tag graphify-platform:local "$GRAPHIFY_IMAGE_REF"
docker push "$GRAPHIFY_IMAGE_REF"
docker buildx imagetools inspect "$GRAPHIFY_IMAGE_REF"
```

This pushes the exact local Compose image. Use this only when that image was
built for `linux/amd64`, the Railway runtime architecture.

### Recommended Railway release build

Build and push an explicit `linux/amd64` image directly from the platform
Dockerfile:

```bash
cd graphify
GRAPHIFY_RELEASE_TAG="$(date -u +%Y%m%dT%H%M%SZ)"
GRAPHIFY_IMAGE_REF="ghcr.io/abdullah-wpcoderrs/graphify-platform:${GRAPHIFY_RELEASE_TAG}"

docker buildx build --platform linux/amd64 -f Dockerfile.platform \
  -t "$GRAPHIFY_IMAGE_REF" --push .

docker buildx imagetools inspect "$GRAPHIFY_IMAGE_REF"
```

Pushing does **not** redeploy Railway automatically — update each service's
image source (by digest, not `:latest`) and redeploy explicitly. Requires
`docker login ghcr.io -u abdullah-wpcoderrs` with a PAT scoped
`write:packages`, and the GHCR package set to **Public** or Railway can't
pull it.

## Railway service configuration

Full walkthrough: [`graphify/docs/railway-setup.md`](graphify/docs/railway-setup.md).
Four Railway services point at the same image, each with its own
`SERVICE_ROLE` and its own Variables tab. Both API and worker call
`get_settings()` at startup, which builds the **same full `Settings` model**
— so the worker needs every field the API needs, not just `DATABASE_URL` and
`REDIS_URL`. Set every variable listed below on the service it's under, even
where the same variable repeats across services with the same value (e.g.
`SESSION_SECRET` must be identical on both API and worker, but it is a
separate variable entry on each service — Railway does not share Variables
across services unless you explicitly reference a Shared Variable).

### API service

Public domain enabled, one Railway volume at `/data/workspaces`, one replica
while `WORKSPACE_STORAGE_TYPE=local`.

```
SERVICE_ROLE=api
FRONTEND_URL=<your Vercel URL>
BACKEND_URL=<this API service's own public Railway URL>
DATABASE_URL=<pooled Neon URL>
REDIS_URL=${{Redis.REDIS_URL}}
SESSION_SECRET=<random secret>
TOKEN_ENCRYPTION_KEY=<random secret>
GITHUB_APP_ID=<from your GitHub App>
GITHUB_CLIENT_ID=<from your GitHub App>
GITHUB_CLIENT_SECRET=<from your GitHub App>
GITHUB_PRIVATE_KEY=<from your GitHub App — real newlines, not \n>
GITHUB_WEBHOOK_SECRET=<from your GitHub App>
RUN_WORKER_ENABLED=false
WORKSPACE_STORAGE_TYPE=local
WORKSPACE_STORAGE_DIR=/data/workspaces
```

### Worker service

No public domain, no volume. Must stay **Active** (a long-running process,
`while True:` in `run_worker.py`) — if its deployment status ever shows
"Completed", it has stopped consuming the queue entirely.

```
SERVICE_ROLE=worker
FRONTEND_URL=<same value as on the API service>
BACKEND_URL=<same value as on the API service>
DATABASE_URL=<same pooled Neon URL as on the API service>
REDIS_URL=${{Redis.REDIS_URL}}
SESSION_SECRET=<same value as on the API service>
TOKEN_ENCRYPTION_KEY=<same value as on the API service>
GITHUB_APP_ID=<same value as on the API service>
GITHUB_CLIENT_ID=<same value as on the API service>
GITHUB_CLIENT_SECRET=<same value as on the API service>
GITHUB_PRIVATE_KEY=<same value as on the API service — real newlines, not \n>
GITHUB_WEBHOOK_SECRET=<same value as on the API service>
RAILWAY_API_TOKEN=<from graphify/.env>
RAILWAY_PROJECT_ID=<from graphify/.env>
RAILWAY_SERVICE_ID=<the EXTRACTOR service's ID — not the worker's own>
RAILWAY_ENVIRONMENT_ID=<from graphify/.env>
```

Do **not** put `REPO_URL`, `REPO_BRANCH`, `REPO_TOKEN`,
`GRAPHIFY_CALLBACK_URL`, `GRAPHIFY_CALLBACK_SECRET`, or a provider API key
(e.g. `OPENAI_API_KEY`) on the worker — those are per-run values the worker
injects into the extractor's deployment automatically. If they're set
statically here, the worker runs one extraction directly on itself, exits
("Completed"), and never processes anything queued after that.

### Extractor service

Leave the Variables tab **completely empty** — the worker injects
`SERVICE_ROLE=extractor` and every run-scoped variable (`REPO_URL`,
`REPO_BRANCH`, `REPO_TOKEN`, `GRAPHIFY_CALLBACK_URL`,
`GRAPHIFY_CALLBACK_SECRET`, the provider API key, `WORKSPACE_STORAGE_TYPE`)
fresh on every deploy. Anything set statically here becomes a stale fallback
that can silently override a real run's values.

There is no fixed value to write down for any of these — each one is
computed per-run by `launch_project_on_railway()` in
`graphify/server/sandbox.py` and only exists for that run's lifetime:

| Variable | Where its value comes from |
| --- | --- |
| `REPO_URL` | The repo the user selected when starting the run — read off the `ExtractionRun` row |
| `REPO_BRANCH` | The branch the user selected (defaults to `main`) — same row |
| `REPO_TOKEN` | The logged-in user's own decrypted GitHub/GitLab OAuth token — only included for private repos, omitted entirely for public ones |
| `GRAPHIFY_CALLBACK_URL` | `<BACKEND_URL>/api/internal/projects/<project_id>/runs/<run_id>/status` — static base + this run's IDs |
| `GRAPHIFY_CALLBACK_SECRET` | A fresh random token (`secrets.token_urlsafe(48)`) generated new for this run; only its hash is stored, and the extractor echoes it back as the `X-Sandbox-Secret` header on every progress callback |
| `<PROVIDER>_API_KEY` | The admin-configured LLM credential, decrypted from the database |
| `WORKSPACE_STORAGE_TYPE` | Static worker config (`local` or `s3`), same on every run |

**Settings → Deploy → Restart Policy: `Never`.** This is a batch job that
exits when finished; the default restart policy treats a *successful* exit
as a crash and re-runs the extraction in a loop. No public domain.

### Migration job/service

One-shot, run manually (or as a one-off job) whenever the schema changes:

```
SERVICE_ROLE=migrate
DATABASE_URL_DIRECT=<direct, non-pooled Neon URL>
```

API and worker use the **pooled** Neon URL; only the migrate role gets the
**direct** URL. Neon is the only PostgreSQL provider — never provision a
Railway PostgreSQL service.

Debugging a deploy directly via Railway's GraphQL API (faster than the
dashboard log viewer) is documented in `graphify/CLAUDE.md`.

## Running the test suite

```bash
cd graphify
uv run pytest tests/server/ -v
```

Hits the real Neon dev database (deliberately — see
`tests/server/conftest.py`); never calls a paid provider or triggers a real
Railway deploy. Every test row is prefixed `zz-pytest-` and cleaned up.

For the full extractor suite (~3900+ tests, rarely needed for a server-only
change), or a fast import/config sanity check:

```bash
uv run pytest tests/ -v                    # full suite
uv run pytest tests/ --collect-only -q     # fast collection check
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

See [`frontend/README.md`](frontend/README.md) and
[`frontend/ui-registry.md`](frontend/ui-registry.md) for UI conventions. The
frontend is deployed separately from the backend and is outside the Railway
platform-image consolidation.

### Deploying to Vercel

This is a monorepo — the repo root has no `package.json`. **Set the Vercel
project's Root Directory to `frontend`** (Settings → General → Root
Directory), or the build finds no Next.js app and every route 404s.

Required environment variable on the Vercel project:

```
NEXT_PUBLIC_API_URL=https://graphify-api-production.up.railway.app
```

This must match the API service's actual Railway public domain
(`BACKEND_URL` in the [Railway service configuration](#railway-service-configuration)
section above) — the frontend calls this URL directly from the browser.


## ENV ADDED TO THE RAILWAY GRAPHIFY_WORKER-SERVICE
RAILWAY_API_TOKEN=<from graphify/.env>
RAILWAY_PROJECT_ID=<from graphify/.env>
RAILWAY_SERVICE_ID=<the graphify-extractor-staging service's ID, NOT the worker's own>
RAILWAY_ENVIRONMENT_ID=<from graphify/.env>
One thing to get right: RAILWAY_SERVICE_ID must be the extractor service's ID (the one named graphify-extractor-staging), since that's the service the worker launches deployments into — not the worker's own service ID. You can get it from that service's URL in Railway: https://railway.app/project/<PROJECT_ID>/service/<SERVICE_ID>.

Also worth adding REDIS_URL=${{Redis.REDIS_URL}} if it's not already there (it's not in your 12) — without it the worker falls back to the slower Postgres-polling path, which still works but isn't the intended fast path.