# Configuration reference

Baseliner is configured primarily via environment variables. In dev, we typically use a `.env` file
(or `docker compose` environment) and in prod we inject env vars via the host/secret manager.

## Server (FastAPI)

These values are loaded by the server settings object (`server/src/baseliner_server/core/config.py`).

### Required

- `DATABASE_URL`  
  SQLAlchemy DB URL. Example (docker compose):  
  `postgresql+psycopg://baseliner:baseliner@db:5432/baseliner`

- `BASELINER_ADMIN_KEY`  
  Admin API key. Sent as the `X-Admin-Key` header for all `/api/v1/admin/*` routes.

- `BASELINER_TOKEN_PEPPER`  
  Secret “pepper” used when hashing tokens (enroll tokens + device tokens). **Treat like a password**.

### Tooling convenience

- `BASELINER_SERVER_URL`  
  Used by helper scripts like `server/scripts/seed_dev.py` and PowerShell wrappers.
  Defaults to `http://localhost:8000` if not set.

### Example `.env`

```bash
DATABASE_URL=postgresql+psycopg://baseliner:baseliner@db:5432/baseliner
BASELINER_ADMIN_KEY=change-me-too
BASELINER_TOKEN_PEPPER=change-me-too
```

## TLS reverse proxy overlay (nginx + certbot)

When using `docker-compose.nginx-certbot.yml`:

### Required

- `BASELINER_DOMAIN`  
  Public DNS name (e.g. `api.example.com`).

- `CERTBOT_EMAIL`  
  Email for Let’s Encrypt registration / expiry notices.

See `docs/operations/nginx-certbot.md` for full deployment and verification steps.

## Request hardening (rate limits, size limits)

Baseliner supports optional controls to protect report ingestion from accidental or malicious overload.

Because these knobs can vary by deployment, use these as the “where to look” pointers:

- **Nginx layer**: `docs/operations/nginx-certbot.md` (optional `limit_req` / `limit_conn` configuration)
- **App layer**: middleware under `server/src/baseliner_server/middleware/` (request size + rate limiting)

If you enable both, nginx typically handles bulk load-shaping, while app-layer limits provide a second line of defense
and better per-device semantics.
