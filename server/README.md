# Baseliner Server

FastAPI-based API that handles device enrollment, policy management, effective policy compilation, and run reporting for the Baseliner ecosystem.

## Requirements
- Python 3.12
- Postgres 16 (local install or Docker)

## Docker compose

From repo root:
```bash
docker compose up --build
```

This starts Postgres + the API and runs migrations automatically.

## Local development

1. **Create a virtual environment and install dependencies**
   ```bash
   cd server
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment**
   Copy `server/.env.example` to `server/.env` and adjust:
   ```
   DATABASE_URL=postgresql+psycopg://baseliner:baseliner@localhost:5432/baseliner
   BASELINER_TOKEN_PEPPER=<random-string>
   BASELINER_ADMIN_KEY=<admin-api-key>
   ```

3. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

4. **Start the API**
   ```bash
   uvicorn baseliner_server.main:app --reload
   ```
   The service exposes `/health` plus the `api/v1` routes defined under `baseliner_server.api`.

## Project layout
- `src/baseliner_server/` — FastAPI app, routers, schemas, and services
- `alembic/` — migration environment and revision scripts
- `baseliner-debug/` — sample debug payloads used during development

## Running tests
```bash
pytest
```

## Request hardening (Issue #23)

The server includes basic, configurable protections:

### Request body size limits (413)

Controlled by:
- `MAX_REQUEST_BODY_BYTES_DEFAULT` (default: ~1MB)
- `MAX_REQUEST_BODY_BYTES_DEVICE_REPORTS` (default: ~10MB)

### Rate limiting for device report ingestion (429)

Controlled by:
- `RATE_LIMIT_ENABLED` (default: true)
- `RATE_LIMIT_REPORTS_PER_MINUTE` + `RATE_LIMIT_REPORTS_BURST` (device key)
- `RATE_LIMIT_REPORTS_IP_PER_MINUTE` + `RATE_LIMIT_REPORTS_IP_BURST` (fallback)

Notes:
- App-layer rate limiting is **in-memory** (per process). For production, consider adding an nginx/edge rate limit as well.
