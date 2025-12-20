# Baseliner Server

FastAPI-based API that handles device enrollment, policy management, effective policy compilation, and run reporting for the Baseliner ecosystem.

## Requirements
- Python 3.11+
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
