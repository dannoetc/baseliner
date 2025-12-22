# Development setup

This is a placeholder for the full dev setup instructions.

## Repo layout

- `server/` — FastAPI API + migrations
- `agent/` — Python agent
- `shared/` — shared libs (if any)
- `deploy/` — nginx overlays, deployment assets

## Python version

Baseliner targets **Python 3.12 only**.

## TODO

- Document recommended virtualenv setup (server + agent)
- Document `docker compose` dev-up flow
- Document seed scripts (`server/scripts/seed_dev.py`, `Seed-Dev.ps1`)
- Add a short “smoke test” sequence for local dev
