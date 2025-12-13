# Baseliner

Baseliner is an open-source “desired state” baseline system for standardizing deployments and keeping third-party software up to date. The long-term goal is cross-platform support; the current focus is **Windows-first** with **WinGet**-backed package enforcement and a simple policy engine.

This repo currently contains a working **server MVP** (FastAPI + Postgres) that supports:
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
- `shared/examples/policies/` — example policy documents (JSON)

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

- Windows dev machine (tested)
- Python 3
