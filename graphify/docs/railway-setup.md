# Railway setup — unified platform and extraction provisioning

The Graphify backend launches an **ephemeral Railway job** for each project:
it clones the repository, runs `graphify extract /workspace`, writes
`graph.json` + `files.json`, and reports progress back to the backend. This
guide creates the Railway project and produces the four environment values
the backend needs.

**Result of this guide** — four values for `graphify/.env`:

```
RAILWAY_API_TOKEN=
RAILWAY_PROJECT_ID=
RAILWAY_SERVICE_ID=
RAILWAY_ENVIRONMENT_ID=
```

Until all of them are set, `POST /api/projects` returns **503** with a clear
"not configured" message rather than failing confusingly — you can develop
everything else before doing this.

---

## Step 1 — Create the Railway account and project

1. Sign up at <https://railway.app> (GitHub sign-in is easiest, and you already
   have a GitHub App configured for this project).
2. Railway's free trial is limited; sandbox jobs need real build minutes, so
   expect to add a payment method on the **Hobby** plan for anything beyond a
   couple of test runs.
3. From the dashboard choose **New Project → Empty Project**.
4. Name it something unambiguous, e.g. `graphify-sandbox`.

## Step 2 — Get `RAILWAY_PROJECT_ID`

Open the project. The browser URL is:

```
https://railway.app/project/<PROJECT_ID>
```

Copy the UUID after `/project/`. That is `RAILWAY_PROJECT_ID`.

## Step 3 — Create the sandbox service

The service is the container template each extraction run deploys.

1. Inside the project: **New → Empty Service** (not "Deploy from GitHub" — the
   backend injects the repo to clone at deploy time as `REPO_URL`, so the
   service itself must not be pinned to one repository).
2. Name it `graphify-extractor`.
3. Open the service → **Settings → Source**, choose **Docker Image**, and point
   it at the immutable `graphify-platform` tag or digest built below. Do not
   use the legacy `graphify-sandbox:latest` image for new deployments.
4. Do not override the start command. `Dockerfile.platform` dispatches through
   `scripts/platform_entrypoint.py`; the worker injects
   `SERVICE_ROLE=extractor` into each run deployment automatically.

### Step 3a — Get `RAILWAY_SERVICE_ID`

With the service open, the URL becomes:

```
https://railway.app/project/<PROJECT_ID>/service/<SERVICE_ID>
```

Copy the UUID after `/service/`.

### Step 3b — Get `RAILWAY_ENVIRONMENT_ID`

Railway projects have environments (`production` by default). The id appears
in the URL as `?environmentId=<UUID>` when you switch environments, or via the
GraphQL API in Step 5. Copy that UUID.

## Step 4 — Create `RAILWAY_API_TOKEN`

1. Go to **Account Settings → Tokens** (<https://railway.app/account/tokens>).
2. **Create Token**. Scope it to the `graphify-sandbox` project — a
   project-scoped token that leaks cannot touch your other Railway projects.
3. Copy it immediately; Railway shows it once.

Treat this like a password: it can deploy and delete infrastructure. It
belongs in `.env` (gitignored) and in your host's secret store — never in a
commit.

## Step 5 — Verify the IDs before wiring them in

Confirm all three IDs are real and mutually consistent, so a typo surfaces
here rather than as an opaque Railway error during a launch:

```bash
curl -s https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"query { me { projects { edges { node { id name environments { edges { node { id name } } } services { edges { node { id name } } } } } } } }"}' | python3 -m json.tool
```

The response lists each project with its `id`, its environments, and its
services. Match them against what you copied from the URLs.

## Step 6 — Fill in `.env` and restart

```
RAILWAY_API_TOKEN=<step 4>
RAILWAY_PROJECT_ID=<step 2>
RAILWAY_SERVICE_ID=<step 3a>
RAILWAY_ENVIRONMENT_ID=<step 3b>
```

Restart the backend. `POST /api/projects` now creates an immutable queued run.
The database-backed dispatcher generates a random callback credential for
that run, stores only its SHA-256 hash, and passes the plaintext credential
directly to the one Railway deployment that needs it.

For production, add Redis and run the dispatcher as a separate worker service.
Follow [Redis extraction queue setup](redis-run-queue.md) after completing this
guide. PostgreSQL remains the source of truth in both configurations.

---

## Building and publishing the unified platform image

### Step A — Build locally

Start Docker Desktop first, then from `graphify/`. Railway runs
**linux/amd64**, so build that platform explicitly on Apple Silicon. Use a new
tag for every release; never overwrite a tag that has already been deployed.

```bash
cd "/Users/mac/Documents/Graph UI/graphify"

GRAPHIFY_RELEASE_TAG="railway-$(date -u +%Y%m%dT%H%M%SZ)"
GRAPHIFY_IMAGE_REF="ghcr.io/abdullah-wpcoderrs/graphify-platform:${GRAPHIFY_RELEASE_TAG}"

docker buildx build \
  --platform linux/amd64 \
  -f Dockerfile.platform \
  -t "$GRAPHIFY_IMAGE_REF" \
  --load \
  .
```

`--load` keeps the exact build in the local Docker image store so it can be
tested before it is published. For a clean committed release, a commit SHA can
replace the timestamp. For an intentionally uncommitted test build, retain the
timestamp so the tag still identifies one unique snapshot.

The verified 2026-08-02 release candidate is:

```text
ghcr.io/abdullah-wpcoderrs/graphify-platform:railway-sql-ws-20260802T070343Z
OCI digest: sha256:f63820e15d8f8807e4c16e8dc36489aecad5f9f710f4e13345d3fcd4d36d0972
```

### Step B — Test the container locally (do this before Railway)

First prove that the optional SQL grammar is installed and can contribute
nodes. This catches the exact issue that previously omitted 49 `.sql` files
from the `byte-earn` graph:

```bash
docker run --rm \
  --platform linux/amd64 \
  --entrypoint python \
  "$GRAPHIFY_IMAGE_REF" \
  -c 'import tempfile; from pathlib import Path; import tree_sitter_sql; from graphify.extract import extract; d=tempfile.TemporaryDirectory(); p=Path(d.name)/"schema.sql"; p.write_text("CREATE TABLE users (id INT PRIMARY KEY);\n"); result=extract([p], cache_root=Path(d.name), parallel=False); print("SQL nodes=%d edges=%d" % (len(result["nodes"]), len(result["edges"]))); assert result["nodes"]'
```

Then exercise the extractor role. The container talks to the backend over
plain HTTP. The supported end-to-end test starts the backend and uses
`POST /api/projects`, which creates the required project/run rows and per-run
credential. For a container-only smoke test, callbacks can be omitted and the
extractor logs progress locally:

```bash
docker run --rm \
  --platform linux/amd64 \
  -e SERVICE_ROLE=extractor \
  -e REPO_URL="https://github.com/octocat/Hello-World.git" \
  -e PROJECT_ID="smoke-project" \
  -e RUN_ID="smoke-run" \
  -e OPENAI_API_KEY="<optional — skips community labeling if absent>" \
  "$GRAPHIFY_IMAGE_REF"
```

`host.docker.internal` is how a container reaches the host on Docker Desktop
(on Linux, add `--add-host=host.docker.internal:host-gateway`). Watch the
backend log: you should see `CLONING → INDEXING → READY` callbacks arrive and
an artifact upload land in `workspace-storage/<project-id>/`.

If this works, the container is correct and anything that fails afterwards is
Railway configuration.

### Step C — Push to a registry (GHCR)

A registry is online storage for Docker images. Railway cannot see your local
Docker daemon, so the image has to live somewhere Railway can download it
from. We use GHCR (GitHub Container Registry) because the project already has
a GitHub account.

#### C1 — Create an access token

GitHub needs proof it is really you before letting you upload.

1. github.com → **Settings** → **Developer settings** → **Personal access
   tokens** → **Tokens (classic)** → **Generate new token (classic)**.
2. Tick the **`write:packages`** scope. (That automatically includes
   `read:packages`, which is what lets an image be pulled back down.)
3. Generate, then copy the token immediately — GitHub displays it exactly
   once and you cannot retrieve it later.

Treat it like a password: it can publish packages under your account. Do not
commit it.

#### C2 — Log in to the registry

Use the GitHub token as the password. Your GitHub account password will be
rejected by GHCR. Avoid putting the token directly in shell history:

```bash
read -s GRAPHIFY_GHCR_TOKEN
printf '%s' "$GRAPHIFY_GHCR_TOKEN" | \
  docker login ghcr.io -u abdullah-wpcoderrs --password-stdin
unset GRAPHIFY_GHCR_TOKEN
```

`--password-stdin` pipes the token in rather than typing it as an argument,
which keeps it out of your shell history and out of the process list where
other programs on the machine could read it.

Expect: `Login Succeeded`.

#### C3 — Push the tested immutable tag

The build command already used the full GHCR image name, so no separate
`docker tag` command is required:

```bash
docker push "$GRAPHIFY_IMAGE_REF"
```

The first push can take several minutes. Later pushes reuse unchanged layers.
Do not reuse an old tag: Railway and Docker caches make mutable tags difficult
to audit and roll back safely.

#### C4 — Make the package public (easy to miss)

**New GHCR packages are private by default, and Railway cannot download a
private image.** The symptom is confusing: the Railway deploy simply never
starts, usually with no clear error explaining why.

1. Your GitHub profile → **Packages** → **graphify-platform**.
2. **Package settings** → **Change visibility** → **Public**.

Public here exposes only the built image, not your source repository. If the
image must stay private instead, give Railway a pull credential under
Service → Settings → Source → private registry credentials.

#### C5 — Verify the push worked

```bash
docker buildx imagetools inspect "$GRAPHIFY_IMAGE_REF"
```

Record the reported OCI digest beside the tag. Run this after making the
package public or configuring Railway with private-registry pull credentials.
If it fails with `unauthorized` or `denied`, Railway will fail the same way.

#### Publishing an update after code changes

An image is a snapshot. Editing source locally does not change either GHCR or
Railway. Generate a **new** tag and repeat build, smoke, push, and inspect:

```bash
GRAPHIFY_RELEASE_TAG="railway-$(date -u +%Y%m%dT%H%M%SZ)"
GRAPHIFY_IMAGE_REF="ghcr.io/abdullah-wpcoderrs/graphify-platform:${GRAPHIFY_RELEASE_TAG}"

docker buildx build \
  --platform linux/amd64 \
  -f Dockerfile.platform \
  -t "$GRAPHIFY_IMAGE_REF" \
  --load \
  .

docker run --rm --platform linux/amd64 --entrypoint python \
  "$GRAPHIFY_IMAGE_REF" \
  -c 'import tree_sitter_sql; import graphify.server.routes.launch; print("platform imports ok")'

docker push "$GRAPHIFY_IMAGE_REF"
docker buildx imagetools inspect "$GRAPHIFY_IMAGE_REF"
```

Pushing does **not** deploy the image. Update the Railway source reference and
create a deployment explicitly. Keep the previous tag/digest recorded for
rollback.

### Step D — Point the Railway service at the image

In the `graphify-extractor` service:

1. **Settings → Source → Image** — set the new immutable
   `ghcr.io/abdullah-wpcoderrs/graphify-platform:<tag>` reference. For strict
   pinning, use `ghcr.io/abdullah-wpcoderrs/graphify-platform@sha256:<digest>`
   when the Railway source field accepts digest references.
   If you originally created it from a repo, switch the source to an image.
2. **Settings → Deploy → Restart Policy: Never.** This is a batch job that
   exits when finished; the default restart policy would treat a *successful*
   exit as a crash and re-run the extraction in a loop.
3. Leave **Variables** empty. The backend injects everything per deploy (see
   the table below) — anything set here is a static fallback, and stale values
   silently override what you expect.
4. Do **not** assign a public domain. Nothing connects to this container; it
   makes outbound calls only.

### Step E — Set roles for long-running services and migrations

Database migrations do not configure Railway service roles. Alembic changes
database schema only. Role selection is intentionally explicit and fail-closed:

| Railway service/job | How `SERVICE_ROLE` is supplied |
| --- | --- |
| API | Set `SERVICE_ROLE=api` in that service's **Variables** tab |
| Worker | Set `SERVICE_ROLE=worker` in that service's **Variables** tab |
| Extractor | Do not set it statically; the worker injects `SERVICE_ROLE=extractor` for every run |
| Migration | Set `SERVICE_ROLE=migrate` and `DATABASE_URL_DIRECT` on the one-shot migration service/job |

After changing the image reference, redeploy every service that should run the
new bits. Updating only the extractor does not deploy the WebSocket fix to the
API; updating only the API does not add SQL parsing to extraction.

Confirm the role in each service log:

```text
[platform] starting role=api
[platform] starting role=worker
[platform] starting role=extractor
[platform] starting role=migrate
```

### Step F — Set the login-critical variables on the API service

On Railway, on the API service, set these 4 things:

| Set this | To this | Why |
| --- | --- | --- |
| `BACKEND_URL` | Your API's real web address, starting with `https://` (e.g. `https://graphify-api.up.railway.app`) — **not** the internal Railway hostname | This is what tells the login cookie "you're allowed to travel between sites." Get it wrong and login silently fails. |
| `FRONTEND_URL` | Your frontend's exact web address, starting with `https://` (e.g. `https://graphify.vercel.app`) | This is the "guest list" — only requests from this exact address are allowed in. |
| `ADMIN_SESSION_SECRET` | A random secret you generate once | Without it, admin login is switched off entirely. |
| `SESSION_SECRET` | A different random secret (already probably set — just make sure it's not the same as the one above) | Keeps admin logins and regular user logins from being mixed up. |

**How to generate the random secrets** — run this twice (once for each secret) in any terminal:

```bash
openssl rand -base64 48
```

Paste one result into `ADMIN_SESSION_SECRET`, the other into `SESSION_SECRET`. They must be different from each other.

**Where to enter these on Railway** — API service → **Settings** → **Variables** tab → add each one as a key/value pair.

**After setting them:**

1. Redeploy the API service (Railway usually does this automatically when you save a variable).
2. Create the admin account against the real production database by running, on your own computer:
   ```bash
   DATABASE_URL='<production URL>' ADMIN_EMAIL='you@example.com' ADMIN_PASSWORD='<12+ chars>' uv run python scripts/seed_admin.py
   ```
3. Try logging in on the real site.

Vercel preview deployments each get their own web address, so they will not match `FRONTEND_URL` and cannot log in against production. That's expected — point previews at a separate backend environment if they need to authenticate.

---

## What the backend sends the job

`launch_project_on_railway()` injects these env vars per deploy. None of
these are fixed values — every row below is computed fresh for that one run
and only lives for its duration:

| Variable | Purpose | Where its value comes from |
| --- | --- | --- |
| `SERVICE_ROLE` | Always `extractor`; injected by the worker for this run | Hardcoded literal in `sandbox.py` |
| `REPO_URL` | Repository to clone | The repo the user picked when starting the run — the `ExtractionRun.repo_url` DB column |
| `PROJECT_ID` | Included in the progress callback URL | This run's project ID |
| `RUN_ID` | Immutable extraction attempt identity | This run's own ID |
| `REPO_BRANCH` | Branch to clone | The branch the user picked (defaults to `main`) — `ExtractionRun.default_branch` |
| `REPO_TOKEN` | User's decrypted git token — only set for private repos | The launching user's own OAuth token, decrypted just for this run; omitted entirely for public repos |
| `<PROVIDER>_API_KEY` | Admin-configured LLM key, e.g. `OPENAI_API_KEY` | The active `SystemCredential` row, decrypted per run |
| `GRAPHIFY_CALLBACK_URL` | Where to POST progress | `<callback_base_url>/api/internal/projects/<project_id>/runs/<run_id>/status` — static base URL + this run's IDs |
| `GRAPHIFY_CALLBACK_SECRET` | Random per-run credential, sent back as `X-Sandbox-Secret` | Freshly generated (`secrets.token_urlsafe(48)`) for this run alone; only its hash is persisted, so it can't be looked up or reused after the run ends |
| `WORKSPACE_STORAGE_TYPE` | `local` or `s3` | Static worker config, same value every run |

The job is expected to POST progress as it goes:

```bash
curl -X POST "$GRAPHIFY_CALLBACK_URL" \
  -H "X-Sandbox-Secret: $GRAPHIFY_CALLBACK_SECRET" \
  -H "X-Sandbox-Event-Id: $(python -c 'import uuid; print(uuid.uuid4())')" \
  -H "Content-Type: application/json" \
  -d '{"status":"INDEXING","progress_percent":40,"message":"Parsing sources"}'
```

and finish with a terminal status:

```bash
-d '{"status":"READY","progress_percent":100,"graph_json_url":"<url>"}'
# or
-d '{"status":"FAILED","error":"clone failed: repository not found"}'
```

Valid `status` values are `CLONING`, `INDEXING`, `READY`, `FAILED`. Callbacks
arriving after a project is already terminal are ignored, so a job that keeps
running after the user cancels cannot resurrect it.

---

## Caveats worth knowing before you rely on this

- **The callback base URL must be reachable from Railway.** When
  `SANDBOX_CALLBACK_BASE_URL` is set, it takes precedence over `BACKEND_URL`.
  For a local API with a real Railway extractor, expose port 8000 through a
  tunnel and set `SANDBOX_CALLBACK_BASE_URL` to the currently running public
  hostname. Recreate the API and worker after changing `.env`; Compose
  containers retain the environment snapshot from the time they were created.
- **The shared Railway service is serialized.** Redis Streams delivers work,
  while the dispatcher uses the database's unique active slot and
  `FOR UPDATE SKIP LOCKED`; queued runs do not replace variables until the
  prior run is terminal.
- **Secrets reach the job as environment variables.** The LLM key and the
  user's git token are visible to anything running inside that container.
  That is inherent to this design; it is safe only as long as the container
  runs Graphify's own image and nothing user-supplied.
- **Cancellation is run-scoped.** The backend revokes the callback credential
  and uses Railway's exact deployment id with `deploymentCancel`, falling back
  to `deploymentStop` after the container is running.
- **Cost scales with launches.** Every "Launch Workspace" is a container
  build+run. Watch the Railway usage dashboard once real users can trigger it.
