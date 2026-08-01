# Graphify Backend — Operational Reference

This file is for whoever (human or Claude) needs to restart the server,
rebuild the sandbox image, or run the test suite without re-deriving how any
of it works. It reflects the Phase 4 backend build (isolated admin auth,
Railway sandbox provisioning, AI usage tracking), completed 2026-08-01.

## Starting / restarting the backend server

```bash
cd graphify
uv run uvicorn graphify.server.app:app --port 8000
```

**Critical gotcha, cost real debugging time once already:** this is started
**without `--reload`**. If you edit any `.py` file under `graphify/server/`
while the server is already running, the running process keeps executing
the OLD code — Python does not hot-reload on its own. You must kill the
process and restart it after every backend code change, or you will be
testing stale code and get confusing results (this happened mid-session: a
Railway fix was made, but the still-running old server kept using the
broken version for ten minutes before anyone noticed).

To check if the server picked up a specific file's latest edit:

```bash
PID=$(lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $2}')
ps -p $PID -o lstart=              # when the server process started
stat -f "%Sm" graphify/server/sandbox.py   # when the file was last edited
```

If the file's mtime is after the process start time, restart the server.

To restart cleanly:

```bash
PID=$(lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $2}')
[ -n "$PID" ] && kill $PID
sleep 2
cd graphify && uv run uvicorn graphify.server.app:app --port 8000
```

Health check: `curl http://localhost:8000/health` should return `{"status":"ok"}`.

## The sandbox callback tunnel (local dev only)

Sandbox jobs run in Railway's cloud and need to reach this backend to report
progress. Your laptop's `localhost` is not reachable from there, so local
dev uses a tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

This prints a public HTTPS URL (`https://<random-words>.trycloudflare.com`).
**Every restart of this command produces a NEW random URL.** After starting
it, update `graphify/.env`:

```
SANDBOX_CALLBACK_BASE_URL=<the new tunnel URL, no trailing slash>
```

Then restart the backend server (env vars are read at process start).

**Do NOT set `BACKEND_URL` to the tunnel URL instead** — they serve
different purposes and must stay different in local dev:
- `BACKEND_URL` drives GitHub/GitLab OAuth redirect URIs (registered with
  those providers) and whether cookies get the `Secure` flag. It must stay
  `http://localhost:8000` locally, or OAuth breaks and the browser stops
  sending session cookies to plain-http localhost.
- `SANDBOX_CALLBACK_BASE_URL` is only used to build the URL a Railway
  container calls home to. It's the tunnel.

In production, both collapse to the same real public origin and
`SANDBOX_CALLBACK_BASE_URL` is left unset (falls back to `BACKEND_URL`).

Verify the tunnel actually works end-to-end before trusting it:

```bash
curl http://localhost:8000/health                                    # direct
curl "$(grep ^SANDBOX_CALLBACK_BASE_URL= .env | cut -d= -f2)/health"  # via tunnel
```

Both should return `{"status":"ok"}`.

## Seeding / resetting the admin account

Admins are a separate login system from GitHub users (see "Architecture
decisions" below). To create or reset the admin account:

```bash
cd graphify
uv run python scripts/seed_admin.py
```

Reads `ADMIN_EMAIL` and `ADMIN_PASSWORD` from `graphify/.env` (or real env
vars, which take precedence). Re-running with the same email resets that
admin's password — this doubles as the password-reset path. Password must
be 12+ characters. Only the argon2 hash is ever stored.

## Running database migrations

```bash
cd graphify
uv run alembic current       # what revision the DB is actually on
uv run alembic heads         # what revision the code expects
uv run alembic upgrade head  # apply pending migrations
uv run alembic check         # confirm no drift between models.py and migrations
```

Current head as of this session: `d4e8b2317ac6` (adds `usage_events` +
`projects` progress columns + `users.is_active`), on top of `c7f2a91be4d3`
(adds the `admin` table).

## Building and deploying the sandbox image

The sandbox is a **separate Docker image** from the main backend — it's the
ephemeral container Railway runs per project to clone a repo and extract its
graph. Built from `graphify/Dockerfile.sandbox`, not `graphify/Dockerfile`
(that one builds the unrelated MCP server).

### Rebuild after any change to `scripts/sandbox_entrypoint.py` or `Dockerfile.sandbox`

```bash
cd graphify
docker build -f Dockerfile.sandbox -t graphify-sandbox:latest .
```

Requires Docker Desktop running. On Apple Silicon, cross-build explicitly
since Railway runs linux/amd64:

```bash
docker build --platform linux/amd64 -f Dockerfile.sandbox -t graphify-sandbox:latest .
```

### Push to the registry

```bash
docker tag graphify-sandbox:latest ghcr.io/abdullah-wpcoderrs/graphify-sandbox:latest
docker push ghcr.io/abdullah-wpcoderrs/graphify-sandbox:latest
```

Requires being logged in once: `docker login ghcr.io -u abdullah-wpcoderrs`
(needs a GitHub personal access token with `write:packages`).

**The GHCR package must stay Public**, or Railway's deploy will fail to
pull it. Check under the GitHub profile's Packages tab (not under
Settings, and not under the repo) → `graphify-sandbox` → Package settings →
Visibility.

Verify the push landed and is pullable:

```bash
docker manifest inspect ghcr.io/abdullah-wpcoderrs/graphify-sandbox:latest
```

Railway is pointed at the `:latest` tag, so it picks up a new push
automatically on the next launch — nothing to click on Railway's side after
a push.

### Testing the container locally before touching Railway

The container only needs plain HTTP to talk to a backend — test the whole
pipeline on your laptop first, with no Railway involved:

```bash
docker run --rm \
  -e REPO_URL="https://github.com/pypa/sampleproject.git" \
  -e PROJECT_ID="<a real project uuid — create one first, see below>" \
  -e GRAPHIFY_CALLBACK_URL="http://host.docker.internal:8000/api/internal/projects/<uuid>/status" \
  -e GRAPHIFY_CALLBACK_SECRET="<SANDBOX_CALLBACK_SECRET from .env>" \
  -e OPENAI_API_KEY="<optional — omit to skip community labeling>" \
  graphify-sandbox:latest
```

`host.docker.internal` is how a container reaches the host machine on Docker
Desktop. Watch the backend's terminal for incoming callback requests, and
check `workspace-storage/<project-id>/` for the uploaded `graph.json` /
`files.json` afterward.

## Railway service configuration

Full walkthrough: [`docs/railway-setup.md`](docs/railway-setup.md). The
non-obvious settings, once the service exists and points at the GHCR image:

- **Settings → Source → Image**: `ghcr.io/abdullah-wpcoderrs/graphify-sandbox:latest`
- **Settings → Deploy → Restart Policy: `Never`.** Without this, Railway
  treats the container's normal successful exit as a crash and re-runs the
  job forever.
- **Settings → Deploy → Serverless: off.** Serverless/scale-to-zero is for
  web services waiting on incoming HTTP traffic; this container never
  receives any and would just sit in limbo.
- **Leave the Variables tab empty.** The backend injects every env var
  fresh on each deploy (`graphify/server/sandbox.py`); anything set here
  becomes a stale fallback that can silently override what's intended.
- **No public domain.** This container only makes outbound calls.

Required `.env` values for the Railway connection (all in
`graphify/.env`, see `.env.example` for how to obtain each):
`RAILWAY_API_TOKEN`, `RAILWAY_PROJECT_ID`, `RAILWAY_SERVICE_ID`,
`RAILWAY_ENVIRONMENT_ID`, `SANDBOX_CALLBACK_SECRET`.

### Debugging a Railway deploy directly via its API

Faster and more reliable than the dashboard's log viewer, which has a
noticeable delay before showing recent output:

```bash
TOKEN=$(grep ^RAILWAY_API_TOKEN= .env | cut -d= -f2)
PID=$(grep ^RAILWAY_PROJECT_ID= .env | cut -d= -f2)
SID=$(grep ^RAILWAY_SERVICE_ID= .env | cut -d= -f2)
EID=$(grep ^RAILWAY_ENVIRONMENT_ID= .env | cut -d= -f2)

# Find the latest deployment
curl -s https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"query\":\"query { deployments(first: 1, input: {projectId: \\\"$PID\\\", serviceId: \\\"$SID\\\", environmentId: \\\"$EID\\\"}) { edges { node { id status } } } }\"}"

# Pull its raw log (replace DEPLOYMENT_ID)
curl -s https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"query { deploymentLogs(deploymentId: \"DEPLOYMENT_ID\", limit: 100) { message timestamp } }"}'
```

Railway's GraphQL schema can describe itself on request — if a mutation's
exact shape is ever unclear again, don't guess from docs prose:

```bash
curl -s https://backboard.railway.app/graphql/v2 -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"query { __type(name: \"Mutation\") { fields { name args { name type { name } } } } }"}'
```

## Running the test suite

```bash
cd graphify
uv run pytest tests/server/ -v
```

**Reads real credentials from `graphify/.env` and hits the real Neon
database.** This is deliberate (the models use Postgres-specific column
types that don't translate to SQLite, so there's no in-memory fallback) —
see `tests/server/conftest.py`'s module docstring for the full rationale.

**Safety property that must be preserved if this suite is extended:** this
dev database has a real OpenAI key and real Railway credentials configured.
The test suite must NEVER call either for real — anything that would reach
a paid provider API or trigger an actual Railway deploy is monkeypatched
(see `test_admin_routes.py`'s credential-verify tests and
`test_launch_routes.py`'s no-LLM-configured test for the pattern). Every row
a test creates is prefixed `zz-pytest-` and deleted in a `finally` block,
plus `conftest.py` runs a session-wide sweep to catch anything a crashed
run left behind.

Running the full project test suite (`tests/`, ~3926 tests including every
language extractor) takes long enough that it's rarely worth doing for a
server-only change — `tests/server/` is the relevant subset. A collection
check (fast, catches import/config breakage without running everything) is
a reasonable middle ground:

```bash
uv run pytest tests/ --collect-only -q
```

## Architecture decisions (read before changing auth or the sandbox flow)

- **Admins are a separate principal from `User`, not a role flag.** Own
  table (`admin`), own login (`POST /api/admin/login`), own cookie
  (`graphify_admin_session`, distinct secret `ADMIN_SESSION_SECRET`,
  distinct signing salt). A GitHub session grants zero admin access and
  vice versa — verified in both directions. `User.role == ADMIN` still
  exists on the model but is now purely informational.
- **WebSocket progress polls the database**, not an in-memory event bus —
  correct across reconnects and multiple backend instances, at the cost of
  one query per second per watching client.
- **Sandbox progress is push (container → backend callback), not the
  backend polling Railway.** Simpler, and doesn't require understanding
  Railway's job-status shape from the backend side.
- **`Project.progress_percent` / `status_message` / `error_message` /
  `started_at` / `finished_at`** persist provisioning state so a
  reconnecting WebSocket client sees truth immediately.
- **Sandbox AI-labeling spend is read from `GRAPH_REPORT.md`**, not
  recomputed — graphify already tracks it via `label_communities()`'s
  `usage_out` parameter and writes `Token cost: N input · M output` into
  that file; the sandbox entrypoint parses that line rather than
  duplicating the accounting.
- **Confirmed graph.json shape** (networkx node-link format): connections
  are under the key `links`, **not** `edges`. `files.json` (a
  sandbox-entrypoint artifact, not something graphify itself emits):
  `{files: [{path, size}], count, truncated}`.
