# Baseliner

Baseliner is an open-source “desired state” baseline system for standardizing deployments and keeping third-party software up to date. The long-term goal is cross-platform support; the current focus is **Windows-first** with **WinGet**-backed package enforcement and a simple policy engine.

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
1. Start Postgres locally (or `docker-compose up -d db`).
2. From `server/`, create a virtual env and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Create `server/.env` with values for `database_url`, `baseliner_token_pepper`, and `baseliner_admin_key`.
4. Apply migrations: `alembic upgrade head`.
5. Run the API: `uvicorn baseliner_server.main:app --reload`.

### Agent (Windows dev box)
1. From `agent/`, create a virtual env and install dependencies:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. Enroll the device once: `python -m baseliner_agent enroll --server http://localhost:8000 --enroll-token <TOKEN> --device-key MY-DEVICE`.
3. Execute the policy once and report back: `python -m baseliner_agent run-once --server http://localhost:8000`.

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

- Windows dev machine (tested) for the agent
- Python 3.11+ for server + agent tooling
- Postgres 16 (via Docker or local install) for the server
