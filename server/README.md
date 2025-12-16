# Baseliner Server

FastAPI-based API that handles device enrollment, policy management, effective policy compilation, and run reporting for the Baseliner ecosystem.

## Requirements
- Python 3.11+
- SQLite (dev quickstart) **or** Postgres 16 (local install or Docker)

## Local development

1. **Create a virtual environment and install dependencies**
   ```bash
   cd server
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment**
   Copy `server/.env` as a starting point. Common setups:
   - **SQLite smoke test (no external DB)** — keep `database_url=sqlite:///./baseliner.db` and set `auto_create_schema=true` so the API will create tables on startup.
   - **Postgres** — set `database_url` to your DSN, set `auto_create_schema=false`, and use Alembic for migrations.

3. **Run database migrations (Postgres-only)**
   ```bash
   alembic upgrade head
   ```

4. **Start the API**
   ```bash
   uvicorn baseliner_server.main:app --reload
   ```
   The service exposes `/health` plus the `api/v1` routes defined under `baseliner_server.api`.
   - Admin helpers for policy debugging: `GET /api/v1/admin/devices/{device_id}/assignments` to list current assignments and `DELETE /api/v1/admin/devices/{device_id}/assignments` to clear them when iterating on policy changes.

## Project layout
- `src/baseliner_server/` — FastAPI app, routers, schemas, and services
- `alembic/` — migration environment and revision scripts
- `baseliner-debug/` — sample debug payloads used during development

## Running tests
```bash
pytest
```
