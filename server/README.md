# Baseliner Server

FastAPI-based API that handles device enrollment, policy management, effective policy compilation, and run reporting for the Baseliner ecosystem.

## Requirements
- Python 3.11+
- Postgres 16 (local install or Docker)

## Local development

1. **Create a virtual environment and install dependencies**
   ```bash
   cd server
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment**
   Create `server/.env` with:
   ```
   database_url=postgresql+psycopg://baseliner:baseliner@localhost:5432/baseliner
   baseliner_token_pepper=<random-string>
   baseliner_admin_key=<admin-api-key>
   auto_create_schema=false
   ```
   For quick smoke tests without Postgres, point `database_url` at SQLite and set
   `auto_create_schema=true` so the app will create tables from metadata on
   startup (Alembic migrations are Postgres-only).

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
