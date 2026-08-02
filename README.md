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

```bash
cd graphify
GRAPHIFY_IMAGE_REF="ghcr.io/abdullah-wpcoderrs/graphify-platform:<tag>"

docker buildx build --platform linux/amd64 -f Dockerfile.platform \
  -t "$GRAPHIFY_IMAGE_REF" --load .

docker push "$GRAPHIFY_IMAGE_REF"
docker buildx imagetools inspect "$GRAPHIFY_IMAGE_REF"
```

Pushing does **not** redeploy Railway automatically — update each service's
image source (by digest, not `:latest`) and redeploy explicitly. Requires
`docker login ghcr.io -u abdullah-wpcoderrs` with a PAT scoped
`write:packages`, and the GHCR package set to **Public** or Railway can't
pull it.

## Railway service configuration

Full walkthrough: [`graphify/docs/railway-setup.md`](graphify/docs/railway-setup.md).
The non-obvious settings once a service points at the image:

- **API**: `SERVICE_ROLE=api`, public domain enabled, one Railway volume at
  `/data/workspaces`, one replica while `WORKSPACE_STORAGE_TYPE=local`.
- **Worker**: `SERVICE_ROLE=worker`, no public domain, no volume.
- **Extractor**: leave the Variables tab empty — the worker injects
  `SERVICE_ROLE=extractor` and run-scoped variables per run.
  **Settings → Deploy → Restart Policy: `Never`**, or Railway treats a
  successful exit as a crash and reruns the job forever. No public domain.
- **Migrate**: one-shot, `SERVICE_ROLE=migrate` + `DATABASE_URL_DIRECT`.
- API and worker share the pooled Neon URL; only the migrate role gets the
  direct URL. Neon is the only PostgreSQL provider — never provision a
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
