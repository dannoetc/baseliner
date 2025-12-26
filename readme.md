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
  - `server/.env` — local dev config (not committed; copy from `.env.example`)
- `agent/` — Windows-focused Baseliner agent scaffold
  - `agent/src/baseliner_agent/` — Agent package + CLI
  - `agent/scripts/` — Helper scripts for local testing
- `ui/` — Web admin UI (React SPA)
- `policies/` — example policy documents (JSON)

---

## Quick start (Docker, recommended)

From repo root:
```bash
docker compose up --build
```

This starts **db** (Postgres) + **api** (FastAPI), runs Alembic migrations on startup, and exposes:
- API: `http://localhost:8000`
- UI: `http://localhost:8080`
- DB: `localhost:5432`


The UI uses the same admin auth header as the CLI: `X-Admin-Key`.
In dev, log in with the `BASELINER_ADMIN_KEY` value from `docker-compose.yml` (default `change-me-too`).

Windows convenience wrapper:
```powershell
.\tools\dev-scripts\Dev-Up.ps1
```

---

## TLS / production-ish setup (edge nginx + Let's Encrypt)

If you want the **UI** and **API** on different hostnames (recommended), set:

- `BASELINER_UI_DOMAIN` — where the web UI is served (e.g. `baselinerops.com` or `ui.baselinerops.com`)
- `BASELINER_DOMAIN` — where the API is served (e.g. `api.baselinerops.com`)

Then run:

```bash
BASELINER_UI_DOMAIN=ui.example.com BASELINER_DOMAIN=api.example.com CERTBOT_EMAIL=you@example.com \
  docker compose -f docker-compose.yml -f docker-compose.nginx-certbot.yml up -d --build
```

Notes:
- The cert is requested with `BASELINER_UI_DOMAIN` as the **primary** name and `BASELINER_DOMAIN` as a **SAN**.
- The UI can still reach the API via the UI hostname at `/api` (same-origin) unless you override `UI_API_BASE_URL`.


---

## Docs

Project documentation lives under `docs/`. Start here:

- `docs/README.md`


---

## Server (local dev, without Docker API)

1. Start Postgres only:
   ```bash
   docker compose up -d db
   ```
2. From `server/`, create a virtual env and install dependencies:
   ```bash
   cd server
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `server/.env.example` to `server/.env` and adjust values.
4. Apply migrations:
   ```bash
   alembic upgrade head
   ```
5. Run the API:
   ```bash
   uvicorn baseliner_server.main:app --reload
   ```

---

## Agent (Windows dev box)

1. From `agent/`, create a virtual env and install dependencies:
   ```powershell
   cd agent
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. Enroll the device once:
   ```powershell
   python -m baseliner_agent enroll --server http://localhost:8000 --enroll-token <TOKEN> --device-key MY-DEVICE
   ```
3. Execute the policy once and report back:
   ```powershell
   python -m baseliner_agent run-once --server http://localhost:8000
   ```

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
- Python **3.12 only** for server + agent tooling
- Postgres 16 (via Docker or local install) for the server

---

## Dev hygiene (lint/format/typecheck)

Install pre-commit hooks:
```bash
pip install pre-commit
pre-commit install
```

Run checks manually:
```bash
ruff format .
ruff check .
mypy server/src agent/src
pytest -q
```

## Documentation

Start with `docs/README.md`.
