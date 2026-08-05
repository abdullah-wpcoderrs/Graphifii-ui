# Graph UI Deployment Setup

This document is derived from the current code in `frontend/` and `graphify/`. It describes how the deployed pieces talk to each other and which variables/configuration belong on each deployment target.

## 1. What talks to what

### Browser and frontend

1. The browser loads the Next.js app from Vercel.
2. The frontend reads exactly one public runtime variable:
   - `NEXT_PUBLIC_API_URL`
3. The frontend sends credentialed HTTP requests to the API at:
   - `/api/auth/github/*`
   - `/api/session`
   - `/api/projects*`
   - `/api/integrations*`
   - `/api/admin/*`
   - `/api/admin/credentials*`
   - `/api/admin/usage`
   - `/api/admin/analytics`
   - `/api/admin/users`
4. The frontend also derives a WebSocket base URL from `NEXT_PUBLIC_API_URL` and opens:
   - `/ws/projects/{projectId}` for extraction/provisioning progress
   - `/ws/projects/{projectId}/agent` for the workspace agent stream

### API service

1. The Railway API service is the only backend service the frontend talks to directly.
2. It handles:
   - GitHub login and callback
   - user session cookies
   - admin login and admin session cookies
   - project launch requests
   - project graph/file reads
   - integration OAuth flows
   - progress WebSockets
   - agent WebSockets
3. It also stores and reads all persistent state from Postgres.

### Worker service

1. The Railway worker does not talk to the frontend directly.
2. It watches queued extraction runs from Redis, with Postgres fallback.
3. It loads the immutable run data from Postgres.
4. It reads the active LLM credential from the database.
5. It launches the extractor service on Railway through the Railway GraphQL API.

### Extractor service

1. The Railway extractor does not talk to the frontend directly.
2. It is launched by the worker with run-scoped variables.
3. It clones the repository, runs graph extraction, uploads artifacts, and reports status back to the API.
4. Its communication back to the platform is:
   - `POST /api/internal/projects/{project_id}/runs/{run_id}/status`
   - `POST /api/internal/projects/{project_id}/runs/{run_id}/usage`
   - `POST /api/internal/projects/{project_id}/runs/{run_id}/artifacts`

### Migrate service

1. The migrate service does not talk to the frontend.
2. It is a one-shot Alembic job.
3. It uses the direct Neon/Postgres connection, not the pooled one.

## 2. The five deployment targets

You currently have five deployment targets to think about:

1. Vercel frontend
2. Railway API service
3. Railway worker service
4. Railway extractor service
5. Railway migrate job/service

## 3. Vercel frontend

### What this deployment does

- Serves the Next.js UI in `frontend/`
- Calls the Railway API over HTTPS
- Opens WebSockets to the Railway API

### Required configuration

| Setting | Value | Where to get it |
| --- | --- | --- |
| Root directory | `frontend` | This repo structure; the Next.js app lives in `frontend/` |
| Framework | Next.js | `frontend/package.json` |
| Public env var | `NEXT_PUBLIC_API_URL` | Set this in the Vercel project settings |

### Required variables

| Variable | Required | Where to get it | Purpose |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | Yes | The public Railway API domain for your deployed API service | Base URL for all frontend HTTP requests and derived WebSocket URLs |

### Important notes

- This is the only frontend env var used by the code right now.
- It must point to the public Railway API URL, for example `https://your-api.up.railway.app`.
- Because it is `NEXT_PUBLIC_*`, it is bundled into the browser. Do not put secrets here.

## 4. Railway API service

### What this deployment does

- Runs the FastAPI app
- Owns the public backend URL used by the frontend
- Sets session cookies and admin cookies
- Accepts extractor callbacks
- Serves project JSON/file endpoints
- Serves both frontend WebSocket endpoints

### Service role

| Variable | Value | Where to get it |
| --- | --- | --- |
| `SERVICE_ROLE` | `api` | Fixed value you set on the Railway API service |

### Required variables

| Variable | Required | Where to get it | Purpose |
| --- | --- | --- | --- |
| `SERVICE_ROLE` | Yes | Fixed value: set it to `api` on this service | Starts the API role in the shared platform image |
| `FRONTEND_URL` | Yes | Your deployed Vercel frontend URL | Allowed frontend origin for CORS and CSRF checks |
| `BACKEND_URL` | Yes | This API service's own public Railway URL | Public API origin used for OAuth callbacks and secure cookie behavior |
| `DATABASE_URL` | Yes | Your pooled Neon/Postgres connection string | Main pooled Postgres connection string |
| `SESSION_SECRET` | Yes | Generate a long random secret | Signs the user session cookie |
| `TOKEN_ENCRYPTION_KEY` | Yes | Generate a separate long random secret | Encrypts stored provider tokens and system credentials |
| `GITHUB_APP_ID` | Yes | GitHub App settings page | GitHub app integration |
| `GITHUB_CLIENT_ID` | Yes | GitHub App / OAuth app credentials | GitHub OAuth login |
| `GITHUB_CLIENT_SECRET` | Yes | GitHub App / OAuth app credentials | GitHub OAuth login |
| `GITHUB_PRIVATE_KEY` | Yes | Downloaded private key from the GitHub App | GitHub app private key |
| `GITHUB_WEBHOOK_SECRET` | Yes | GitHub App webhook settings | GitHub webhook verification |
| `RAILWAY_API_TOKEN` | Yes for project launches | Railway account/project token with deploy access | Lets the platform coordinate Railway extractor deploys |
| `RAILWAY_PROJECT_ID` | Yes for project launches | Railway project URL or Railway project settings | Railway project target for extractor deploys |
| `RAILWAY_SERVICE_ID` | Yes for project launches | The extractor service URL in Railway; use the extractor service ID, not the worker ID | Must point at the extractor service |
| `RAILWAY_ENVIRONMENT_ID` | Yes for project launches | Railway environment settings or URL | Railway environment target for extractor deploys |

### Usually required in production

| Variable | Usually set? | Where to get it | Purpose |
| --- | --- | --- | --- |
| `RUN_WORKER_ENABLED` | Yes, set to `false` | Fixed value you choose on the API service | Prevents the API service from also running the queue worker in production |
| `WORKSPACE_STORAGE_TYPE` | Yes | Chosen by your deployment design, usually `local` today | Controls artifact storage mode |
| `WORKSPACE_STORAGE_DIR` | Yes when using local storage | Chosen filesystem path on the API container, for example the mounted volume path | Local path where uploaded artifacts are written |
| `REDIS_URL` | Yes | Railway Redis service connection string | Fast queue delivery for extraction runs |
| `ADMIN_SESSION_SECRET` | Yes if admin login is enabled | Generate a separate long random secret | Signs the separate admin session cookie |

### Optional variables

| Variable | When needed | Where to get it | Purpose |
| --- | --- | --- | --- |
| `SANDBOX_CALLBACK_BASE_URL` | When callback base should differ from `BACKEND_URL` | Your public callback URL, usually a tunnel URL in local dev or a custom public callback base | Public callback base used by the extractor |
| `GITLAB_CLIENT_ID` | If GitLab integrations are enabled | GitLab OAuth application settings | GitLab OAuth |
| `GITLAB_CLIENT_SECRET` | If GitLab integrations are enabled | GitLab OAuth application settings | GitLab OAuth |
| `GITLAB_WEBHOOK_SECRET` | If GitLab webhooks are enabled | GitLab webhook configuration | GitLab webhook verification |
| `GITBUCKET_INSTANCE_URL` | If GitBucket integrations are enabled | Your GitBucket server base URL | GitBucket API/OAuth base URL |
| `GITBUCKET_CLIENT_ID` | If GitBucket integrations are enabled | GitBucket OAuth app settings | GitBucket OAuth |
| `GITBUCKET_CLIENT_SECRET` | If GitBucket integrations are enabled | GitBucket OAuth app settings | GitBucket OAuth |
| `GITBUCKET_WEBHOOK_SECRET` | If GitBucket webhooks are enabled | GitBucket webhook configuration | GitBucket webhook verification |
| `REDIS_RUN_QUEUE_STREAM` | Optional | Your own chosen override value | Redis stream name override |
| `REDIS_RUN_QUEUE_GROUP` | Optional | Your own chosen override value | Redis consumer group override |
| `REDIS_RUN_QUEUE_BLOCK_MS` | Optional | Your own chosen override value | Redis blocking read time |
| `REDIS_RUN_QUEUE_RECLAIM_SECONDS` | Optional | Your own chosen override value | Redis reclaim window |
| `REDIS_RUN_QUEUE_MAX_LENGTH` | Optional | Your own chosen override value | Redis stream max length |
| `RUN_WORKER_POLL_SECONDS` | Optional | Your own chosen override value | Poll interval fallback |
| `RUN_WORKER_LEASE_SECONDS` | Optional | Your own chosen override value | Lease window for active extractor job |
| `MAX_QUEUED_RUNS_PER_USER` | Optional | Your own chosen override value | Per-user queue cap |
| `MAX_QUEUED_RUNS_GLOBAL` | Optional | Your own chosen override value | Global queue cap |

### Things that should not live permanently on the API service

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `REPO_URL`
- `REPO_BRANCH`
- `REPO_TOKEN`
- `GRAPHIFY_CALLBACK_URL`
- `GRAPHIFY_CALLBACK_SECRET`

The code path today stores LLM provider credentials in the database and injects the selected provider key into the extractor at run time.

## 5. Railway worker service

### What this deployment does

- Runs the dedicated queue worker
- Claims queued extraction runs
- Loads repo token and selected LLM credential
- Calls Railway to deploy the extractor
- Cancels or reconciles extractor deployments when needed

### Service role

| Variable | Value | Where to get it |
| --- | --- | --- |
| `SERVICE_ROLE` | `worker` | Fixed value you set on the Railway worker service |

### Required variables

The worker imports the same backend settings model as the API, so it needs the same core configuration plus Railway access.

| Variable | Required | Where to get it | Purpose |
| --- | --- | --- | --- |
| `SERVICE_ROLE` | Yes | Fixed value: set it to `worker` on this service | Starts the worker role |
| `FRONTEND_URL` | Yes | Same deployed Vercel frontend URL used by the API service | Required by shared settings validation |
| `BACKEND_URL` | Yes | Same public API Railway URL used by the API service | Required by shared settings validation |
| `DATABASE_URL` | Yes | Same pooled Neon/Postgres connection string used by the API service | Reads queued runs and writes run state |
| `SESSION_SECRET` | Yes | Same secret used by the API service | Required by shared settings validation |
| `TOKEN_ENCRYPTION_KEY` | Yes | Same secret used by the API service | Decrypts stored provider tokens and system credentials |
| `GITHUB_APP_ID` | Yes | Same GitHub App setting used by the API service | Required by shared settings validation |
| `GITHUB_CLIENT_ID` | Yes | Same GitHub App/OAuth setting used by the API service | Required by shared settings validation |
| `GITHUB_CLIENT_SECRET` | Yes | Same GitHub App/OAuth setting used by the API service | Required by shared settings validation |
| `GITHUB_PRIVATE_KEY` | Yes | Same GitHub App private key used by the API service | Required by shared settings validation |
| `GITHUB_WEBHOOK_SECRET` | Yes | Same GitHub webhook secret used by the API service | Required by shared settings validation |
| `RAILWAY_API_TOKEN` | Yes | Same Railway token used by the API service | Launches/cancels extractor deployments |
| `RAILWAY_PROJECT_ID` | Yes | Same Railway project ID used by the API service | Railway project target |
| `RAILWAY_SERVICE_ID` | Yes | The extractor service ID in Railway | Must point at the extractor service |
| `RAILWAY_ENVIRONMENT_ID` | Yes | Same Railway environment ID used by the API service | Railway environment target |

### Usually required in production

| Variable | Usually set? | Where to get it | Purpose |
| --- | --- | --- | --- |
| `REDIS_URL` | Yes | Railway Redis service connection string | Fast queue consumption |

### Optional variables

| Variable | When needed | Where to get it | Purpose |
| --- | --- | --- | --- |
| `GITLAB_CLIENT_ID` | If GitLab is enabled | Same GitLab OAuth app setting used by the API service | Needed because the worker may refresh GitLab tokens |
| `GITLAB_CLIENT_SECRET` | If GitLab is enabled | Same GitLab OAuth app setting used by the API service | Needed because the worker may refresh GitLab tokens |
| `GITBUCKET_INSTANCE_URL` | If GitBucket is enabled | Same GitBucket server URL used by the API service | Needed for GitBucket-related repo/token flows |
| `GITBUCKET_CLIENT_ID` | If GitBucket is enabled | Same GitBucket OAuth app setting used by the API service | Shared settings for GitBucket |
| `GITBUCKET_CLIENT_SECRET` | If GitBucket is enabled | Same GitBucket OAuth app setting used by the API service | Shared settings for GitBucket |
| `REDIS_RUN_QUEUE_STREAM` | Optional | Your own chosen override value | Redis stream name override |
| `REDIS_RUN_QUEUE_GROUP` | Optional | Your own chosen override value | Redis consumer group override |
| `REDIS_RUN_QUEUE_BLOCK_MS` | Optional | Your own chosen override value | Redis blocking read time |
| `REDIS_RUN_QUEUE_RECLAIM_SECONDS` | Optional | Your own chosen override value | Redis reclaim window |
| `REDIS_RUN_QUEUE_MAX_LENGTH` | Optional | Your own chosen override value | Redis stream max length |
| `RUN_WORKER_POLL_SECONDS` | Optional | Your own chosen override value | Poll loop interval |
| `RUN_WORKER_LEASE_SECONDS` | Optional | Your own chosen override value | Lease window for active extractor job |

### Things that should not live permanently on the worker service

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `REPO_URL`
- `REPO_BRANCH`
- `REPO_TOKEN`
- `GRAPHIFY_CALLBACK_URL`
- `GRAPHIFY_CALLBACK_SECRET`

Those values are run-scoped. The worker computes or loads them and injects them into the extractor service for one specific run.

## 6. Railway extractor service

### What this deployment does

- Runs the sandbox entrypoint
- Clones the requested repository
- Runs `graphify update /workspace`
- Runs `graphify label /workspace` when an LLM key is available
- Uploads artifacts back to the API
- Reports progress and usage back to the API

### Service role

The extractor is launched with:

| Variable | Value | Where to get it |
| --- | --- | --- |
| `SERVICE_ROLE` | `extractor` | Fixed value injected by the worker for each run |

### Static deployment configuration

The extractor should be treated as a batch service, not a long-running app.

| Setting | Expected state | Where to get it / how to decide it |
| --- | --- | --- |
| Public URL | Not needed | Railway service settings; leave public networking off |
| Persistent volume | Not needed | Railway service settings; no volume required |
| Restart policy | Batch / do not auto-restart successful runs | Railway deploy/restart settings |
| Static env vars | Keep empty except where your platform requires defaults | Railway variables tab; do not permanently store run-scoped values here |

### Run-scoped variables injected by the worker

These are the variables the worker injects into the extractor deployment for each run:

| Variable | Required per run | Where to get it | Purpose |
| --- | --- | --- | --- |
| `SERVICE_ROLE` | Yes | Injected by the worker with fixed value `extractor` | Starts extractor mode |
| `REPO_URL` | Yes | From the queued extraction run in the database | Repository to clone |
| `PROJECT_ID` | Yes | From the project record tied to the run | Project identifier for callbacks |
| `RUN_ID` | Yes | From the queued extraction run in the database | Run identifier for callbacks and artifact paths |
| `REPO_BRANCH` | Usually | From the run's selected default branch | Branch to clone |
| `WORKSPACE_STORAGE_TYPE` | Yes | From the API/worker deployment setting | Matches the platform storage mode |
| `GRAPHIFY_CALLBACK_URL` | Yes | Built by the worker from `SANDBOX_CALLBACK_BASE_URL` or `BACKEND_URL`, plus project and run IDs | Status callback base to the API |
| `GRAPHIFY_CALLBACK_SECRET` | Yes | Generated fresh by the worker for that run | Shared secret for internal callbacks |
| `REPO_TOKEN` | Sometimes | The current user's decrypted provider token, when needed | Present when needed for private repositories |
| `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` | Sometimes | Injected from the active system credential stored in the database | Injected from the active system credential in the database |

### Important rule

Do not permanently set the run-scoped extractor variables on the extractor service itself. This service is designed to receive them from the worker per deploy.

## 7. Railway migrate job/service

### What this deployment does

- Runs `alembic upgrade head`
- Applies schema migrations against the direct Postgres connection

### Service role

| Variable | Value | Where to get it |
| --- | --- | --- |
| `SERVICE_ROLE` | `migrate` | Fixed value you set on the migrate job/service |

### Required variables

| Variable | Required | Where to get it | Purpose |
| --- | --- | --- | --- |
| `SERVICE_ROLE` | Yes | Fixed value: set it to `migrate` | Starts migrate mode |
| `DATABASE_URL_DIRECT` | Yes | Your direct Neon/Postgres connection string | Direct, non-pooled Postgres connection for Alembic |

### Important note

- The platform entrypoint promotes `DATABASE_URL_DIRECT` to `DATABASE_URL` for the child Alembic process.
- The migrate role does not need the full API/worker secret set.
- This should be a one-shot job, not a public service.

## 8. Variables that matter across multiple deployments

### `FRONTEND_URL`

- Must match the real frontend origin users visit.
- The API uses it for:
  - CORS allowlist
  - CSRF origin checking
  - frontend redirects after OAuth and error flows

### `BACKEND_URL`

- Must match the public API origin.
- The API uses it for:
  - GitHub OAuth callback URL
  - GitLab/GitBucket OAuth callback URLs
  - deciding whether cookies must be `Secure`

### `SANDBOX_CALLBACK_BASE_URL`

- Only set this when the extractor must call back through a different public base than `BACKEND_URL`.
- If unset, callback URLs fall back to `BACKEND_URL`.

### `RAILWAY_SERVICE_ID`

- This must be the extractor service ID, because that is the service the worker deploys for each run.

## 9. Recommended deployment checklist

### Step 1: Deploy Vercel

1. Point the Vercel project at `frontend/`.
2. Set `NEXT_PUBLIC_API_URL` to the public Railway API URL.
3. Deploy.

### Step 2: Configure the Railway API service

1. Set `SERVICE_ROLE=api`.
2. Set the shared core backend variables:
   - `FRONTEND_URL`
   - `BACKEND_URL`
   - `DATABASE_URL`
   - `SESSION_SECRET`
   - `TOKEN_ENCRYPTION_KEY`
   - `GITHUB_APP_ID`
   - `GITHUB_CLIENT_ID`
   - `GITHUB_CLIENT_SECRET`
   - `GITHUB_PRIVATE_KEY`
   - `GITHUB_WEBHOOK_SECRET`
3. Set Railway extractor-launch variables:
   - `RAILWAY_API_TOKEN`
   - `RAILWAY_PROJECT_ID`
   - `RAILWAY_SERVICE_ID`
   - `RAILWAY_ENVIRONMENT_ID`
4. Set `RUN_WORKER_ENABLED=false`.
5. Set storage config:
   - `WORKSPACE_STORAGE_TYPE`
   - `WORKSPACE_STORAGE_DIR` if using local storage
6. Set `REDIS_URL`.
7. Set `ADMIN_SESSION_SECRET` if the admin UI should work.
8. Add optional GitLab/GitBucket vars only if those integrations are enabled.

### Step 3: Configure the Railway worker service

1. Set `SERVICE_ROLE=worker`.
2. Copy the shared backend variables the worker needs:
   - `FRONTEND_URL`
   - `BACKEND_URL`
   - `DATABASE_URL`
   - `SESSION_SECRET`
   - `TOKEN_ENCRYPTION_KEY`
   - `GITHUB_APP_ID`
   - `GITHUB_CLIENT_ID`
   - `GITHUB_CLIENT_SECRET`
   - `GITHUB_PRIVATE_KEY`
   - `GITHUB_WEBHOOK_SECRET`
3. Set:
   - `RAILWAY_API_TOKEN`
   - `RAILWAY_PROJECT_ID`
   - `RAILWAY_SERVICE_ID`
   - `RAILWAY_ENVIRONMENT_ID`
4. Set `REDIS_URL`.
5. Add GitLab/GitBucket vars here too if those providers are enabled.

### Step 4: Configure the Railway extractor service

1. Use the same platform image.
2. Make sure the role can be started as `extractor`.
3. Do not permanently store run-scoped vars like `REPO_URL` or `GRAPHIFY_CALLBACK_URL`.
4. Keep it non-public.
5. Treat it as a one-run batch deployment.

### Step 5: Configure the Railway migrate job/service

1. Set `SERVICE_ROLE=migrate`.
2. Set `DATABASE_URL_DIRECT`.
3. Run it as a one-shot job when schema changes need to be applied.

## 10. Things that are not deployment env vars in the current design

These are not meant to be permanent deployment variables:

- The active LLM API key used for extraction
- Repo clone URLs for a specific run
- Repo clone tokens for a specific run
- Callback secrets for a specific run

Today, those values come from:

- the database
- the current run record
- the current user’s connected provider token
- the worker’s run-scoped Railway deploy injection

## 11. Practical summary

- The frontend talks only to the API.
- The frontend needs only `NEXT_PUBLIC_API_URL`.
- The API is the public control plane.
- The worker is private and launches extractor jobs.
- The extractor is private and reports back to the API.
- The migrate service is a one-shot schema job.
- `BACKEND_URL`, `FRONTEND_URL`, and `RAILWAY_SERVICE_ID` are the three values most likely to break the whole flow when they are wrong.
