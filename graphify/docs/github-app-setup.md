# Graphify GitHub App Setup

This guide configures the GitHub App used for Graphify authentication,
repository discovery, repository access, branch pushes, and pull request
creation.

Graphify uses this deployment boundary:

- The Next.js frontend is hosted by Vercel.
- The Python/FastAPI backend is hosted by Railway.
- GitHub credentials exist only in the Railway backend.
- Vercel receives only the public Graphify API URL.

## 1. Decide the application URLs

Use the final production URLs when they are available. Custom subdomains are
recommended:

```text
Frontend: https://app.example.com
Backend:  https://api.example.com
```

The corresponding GitHub endpoints will be:

```text
Callback URL: https://api.example.com/api/auth/github/callback
Webhook URL:  https://api.example.com/api/webhooks/github
```

For localhost development, also register:

```text
Homepage URL: http://localhost:3000
Callback URL: http://localhost:8000/api/auth/github/callback
```

GitHub supports multiple callback URLs. The OAuth `state` value must be
generated and verified by the backend for every authorization attempt.

## 2. Register the GitHub App

1. In GitHub, open **Settings**.
2. Open **Developer settings**.
3. Select **GitHub Apps**.
4. Select **New GitHub App**.
5. Enter a globally unique app name, such as `Graphify Cloud`.
6. Set **Homepage URL** to the Vercel frontend URL.
7. Add the Railway callback URL under **Callback URL**.
8. Add the localhost callback URL as an additional callback.
9. Enable **Request user authorization (OAuth) during installation**.
10. Leave **Device Flow** disabled.
11. Keep webhook delivery active.
12. Set **Webhook URL** to the Railway webhook endpoint.
13. Keep SSL verification enabled.

GitHub documents the registration fields and callback behavior in
[Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app).

## 3. Grant minimum permissions

Configure only these repository permissions for the initial Graphify product:

| Permission | Access | Why it is required |
| --- | --- | --- |
| Metadata | Read-only | Identify and list repositories available to an installation |
| Contents | Read and write | Clone/read code and push a Graphify-created branch |
| Pull requests | Read and write | Read PR state and open a pull request |

Do not enable Issues, Actions, Administration, Deployments, Secrets, or
organization-wide permissions unless a feature later requires them.

GitHub documents `Pull requests: write` for
[creating pull requests](https://docs.github.com/en/rest/pulls/pulls) and
`Contents: write` for
[changing repository contents](https://docs.github.com/en/rest/repos/contents).

Subscribe to these events:

- Installation
- Installation repositories
- Push
- Pull request

They keep Graphify synchronized when an installation changes, repository
access changes, code is pushed, or a Graphify PR changes state.

## 4. Copy the GitHub values into Railway

Open the GitHub App settings page.

### `GITHUB_APP_ID`

Copy **App ID**:

```env
GITHUB_APP_ID=123456
```

### `GITHUB_CLIENT_ID`

Copy **Client ID**:

```env
GITHUB_CLIENT_ID=Iv1.xxxxxxxxxxxxxxxx
```

### `GITHUB_CLIENT_SECRET`

Under **Client secrets**, select **Generate a new client secret**. Copy the
value immediately:

```env
GITHUB_CLIENT_SECRET=your-generated-client-secret
```

The client ID and secret are used by the backend to exchange GitHub's
temporary callback code for a user access token. See
[Generating a user access token](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app).

### `GITHUB_PRIVATE_KEY`

Under **Private keys**, select **Generate a private key**. GitHub downloads a
PEM file. Copy the entire value, including its boundary lines:

```text
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

Paste it into Railway as a multiline `GITHUB_PRIVATE_KEY` variable. Never add
the PEM file to Git and never expose it through a `NEXT_PUBLIC_*` variable.
The backend uses it to authenticate as the app and request short-lived
installation tokens. See
[GitHub App authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/about-authentication-with-a-github-app).

### `GITHUB_WEBHOOK_SECRET`

Generate a high-entropy random value:

```sh
openssl rand -hex 32
```

Enter the same value in:

1. GitHub App settings under **Webhook secret**.
2. Railway as `GITHUB_WEBHOOK_SECRET`.
3. `graphify/.env` when testing webhook delivery locally.

This secret must be different from `GITHUB_CLIENT_SECRET`,
`SESSION_SECRET`, and `TOKEN_ENCRYPTION_KEY`. GitHub recommends signing and
validating webhook deliveries with a secret in
[Using webhooks with GitHub Apps](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/using-webhooks-with-github-apps).

## 5. Add the non-GitHub Railway variables

Railway also needs:

```env
FRONTEND_URL=https://your-project.vercel.app
BACKEND_URL=https://your-backend.up.railway.app
DATABASE_URL=<provided-by-your-postgres-service>
SESSION_SECRET=<at-least-32-random-bytes>
TOKEN_ENCRYPTION_KEY=<separate-32-byte-base64-key>
```

Generate the two application secrets separately:

```sh
openssl rand -base64 32
openssl rand -base64 32
```

`SESSION_SECRET` signs application sessions. `TOKEN_ENCRYPTION_KEY` encrypts
stored GitHub user tokens; the values must not be reused.

The backend derives callback and webhook routes from `BACKEND_URL`, so separate
callback URL environment variables are unnecessary.

## 6. Add the Vercel variable

Vercel needs one initial variable:

```env
NEXT_PUBLIC_API_URL=https://your-backend.up.railway.app
```

This is intentionally public. No GitHub secret, database URL, encryption key,
or AI-provider key belongs in Vercel.

## 7. Localhost connection

The local services use:

```text
Next.js: http://localhost:3000
FastAPI: http://localhost:8000
```

The frontend reads `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

The backend reads `graphify/.env`:

```env
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
```

The browser flow is:

```text
http://localhost:3000
  -> http://localhost:8000/api/auth/github/login
  -> github.com
  -> http://localhost:8000/api/auth/github/callback
  -> http://localhost:3000/dashboard
```

The backend must:

1. Allow the exact CORS origin `http://localhost:3000`.
2. Allow credentials on CORS requests.
3. Set a host-only, HTTP-only session cookie.
4. Use `SameSite=Lax` locally and secure cookies in production.
5. Verify OAuth `state` before exchanging the callback code.

Frontend API requests that need the session must include credentials:

```ts
await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/session`, {
  credentials: "include",
});
```

Ports do not prevent the browser from sending a localhost cookie to the
localhost backend, but CORS still has to explicitly allow the frontend origin.

### Local webhook delivery

GitHub cannot send webhooks directly to `localhost`. Run an HTTPS tunnel that
forwards to port 8000, then temporarily set the GitHub App webhook URL to:

```text
https://your-tunnel-host/api/webhooks/github
```

The OAuth callback does not require a tunnel because the user's browser can
reach localhost. Only server-to-server webhook delivery requires the public
URL.

## 8. Local startup target

Once the FastAPI server module is implemented, the intended commands are:

```sh
cd graphify
uv run uvicorn graphify.server.app:app --reload --port 8000
```

In another terminal:

```sh
cd frontend
npm install
npm run dev
```

At the current project stage the Next.js development server can start, but the
documented authentication endpoints will not respond until the FastAPI backend
module is implemented.

## Environment-variable inventory

### Frontend

```env
NEXT_PUBLIC_API_URL=
```

### Backend

```env
FRONTEND_URL=
BACKEND_URL=
DATABASE_URL=
SESSION_SECRET=
TOKEN_ENCRYPTION_KEY=
GITHUB_APP_ID=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GITHUB_PRIVATE_KEY=
GITHUB_WEBHOOK_SECRET=
```

No Redis, object-storage, AI-provider, email, analytics, or observability
variables are introduced before the corresponding feature exists.
