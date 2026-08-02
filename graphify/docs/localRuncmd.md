Use three terminals. These commands use `graphify/.env`, not `.env.test`.

Terminal 1 — API, Redis, and local worker:

```bash
cd "/Users/mac/Documents/Graph UI"
docker compose up --build
```

Or run detached:

```bash
docker compose up -d --build
docker compose logs -f worker
```

Terminal 2 — Cloudflare tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

If `cloudflared` is not installed:

```bash
brew install cloudflared
```

Copy the generated URL, then update `graphify/.env`:

```env
BACKEND_URL=http://localhost:8000
SANDBOX_CALLBACK_BASE_URL=https://your-random-url.trycloudflare.com
```

Do not add a trailing `/` to the Cloudflare URL.

After changing `.env`, recreate the API and worker:

```bash
cd "/Users/mac/Documents/Graph UI"
docker compose up -d --force-recreate api worker
```

Verify both routes:

```bash
curl http://localhost:8000/health
curl https://your-random-url.trycloudflare.com/health
```

Both should return:

```json
{"status":"ok"}
```

Useful monitoring commands:

```bash
docker compose logs -f api worker redis
```

```bash
docker compose ps
```

Stop everything when finished:

```bash
docker compose down
```

Keep the Cloudflare terminal running while testing Railway extractions. Every time you restart `cloudflared`, it generates a new URL, so update `SANDBOX_CALLBACK_BASE_URL` and recreate `api` and `worker` again.