# Baseliner

Baseliner is an open-source “desired state” baseline system for standardizing deployments and keeping third-party software up to date. The long-term goal is cross-platform support; the current focus is **Windows-first** with **WinGet**-backed package enforcement and a simple policy engine. The agent now runs in a limited “report-only” mode on non-Windows hosts to help iterate on the server/device contract during development.

This repo currently contains a working **server MVP** (FastAPI + Postgres) and a Windows-focused **agent scaffold**. Together they support:
- device enrollment + device auth tokens
- policy upsert + assignment to devices
- effective policy compilation + `effectivePolicyHash`
- run reporting (items + logs)
- admin endpoints to inspect devices/runs

---

## Repo layout (current)

> Paths shown relative to repo root.

- `server/` — FastAPI API + Alembic migrations + server package
  - `server/src/baseliner_server/` — Python package (src-layout)
  - `server/alembic/` — Alembic env + migrations
  - `server/.env` — local dev config (not committed)
- `agent/` — Windows-focused Baseliner agent scaffold
  - `agent/src/baseliner_agent/` — Agent package + CLI
  - `agent/scripts/` — Helper scripts for local testing
- `shared/examples/policies/` — example policy documents (JSON)

---

## Quick start

### Server (local dev)
You can run entirely on SQLite for a quick API smoke test or switch to Postgres for the full migration path.

1. From `server/`, create a virtual env and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Copy `server/.env` as a starting point and set `baseliner_token_pepper` / `baseliner_admin_key`.
   - SQLite quickstart: keep `database_url=sqlite:///./baseliner.db` and `auto_create_schema=true` to let the app create tables on startup.
   - Postgres: point `database_url` at your DSN, set `auto_create_schema=false`, and run `alembic upgrade head` to apply migrations.
3. Run the API: `uvicorn baseliner_server.main:app --reload`.
   - Admin helpers: `GET /api/v1/admin/devices/{device_id}/assignments` lists current policy assignments; `DELETE /api/v1/admin/devices/{device_id}/assignments` clears them for fast policy reset loops.

### Agent (Windows-first, cross-platform dev)
1. From `agent/`, create a virtual env and install dependencies:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. Enroll the device once: `python -m baseliner_agent enroll --server http://localhost:8000 --enroll-token <TOKEN> --device-key MY-DEVICE`.
3. Execute the policy once and report back: `python -m baseliner_agent run-once --server http://localhost:8000`.
   - On Windows the agent enforces `winget.package` resources; on macOS/Linux it runs in a report-only mode and stores the device token in plaintext for developer convenience. Override the state folder with `--state-dir` or `BASELINER_STATE_DIR` when testing on non-Windows hosts.

---

## Architecture (MVP)

**Auth model**
- **Admin**: `X-Admin-Key: <ADMIN_KEY>` header (dev/MVP)
- **Device**: `Authorization: Bearer <DEVICE_TOKEN>` header

**Core flow**
1. Admin creates a one-time **enrollment token**
2. Device enrolls with that token and receives a **device token**
3. Device fetches compiled effective policy (`effectivePolicyHash` included)
4. Device runs resources and posts a **run report** (items + logs)
5. Admin inspects devices/runs/run detail via admin endpoints

---

## Requirements

- Windows dev machine recommended for full agent enforcement; macOS/Linux supported for report-only dev/testing
- Python 3.11+ for server + agent tooling
- SQLite for quick server smoke tests or Postgres 16 for migrations/production-style dev
