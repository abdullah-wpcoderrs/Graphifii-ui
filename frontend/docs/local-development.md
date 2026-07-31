# Graphify UI Local Development

The frontend runs on port 3000 and connects directly to the Graphify backend on
port 8000.

## Configuration

`frontend/.env.local` contains:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Do not add GitHub secrets, database credentials, session secrets, private keys,
or AI-provider credentials to the frontend environment. Variables beginning
with `NEXT_PUBLIC_` are shipped to the browser.

The backend's local secrets and GitHub App values belong in `graphify/.env`.
Follow
[the GitHub App setup guide](../../graphify/docs/github-app-setup.md) to create
and populate them.

## Start the frontend

```sh
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Start the backend

After the planned FastAPI server module has been implemented:

```sh
cd graphify
uv run uvicorn graphify.server.app:app --reload --port 8000
```

The authentication endpoints do not exist yet. The current environment files
establish the contract they will use; they do not by themselves make GitHub
authentication functional.

## Browser-to-backend requests

Authenticated requests must include the backend session cookie:

```ts
await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/session`, {
  credentials: "include",
});
```

The backend will allow only the configured `FRONTEND_URL` as a credentialed
CORS origin. It must not use a wildcard origin with credentials.

## GitHub callbacks and webhooks

Add this GitHub App callback URL:

```text
http://localhost:8000/api/auth/github/callback
```

The callback works without a tunnel because GitHub redirects the user's local
browser.

GitHub webhooks originate from GitHub's servers and cannot reach localhost.
Use a public HTTPS tunnel to port 8000 and configure:

```text
https://your-tunnel-host/api/webhooks/github
```

Keep webhook signature verification enabled when using the tunnel.
