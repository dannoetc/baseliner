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
  Used by helper scripts like `server/scripts/seed_dev.py` and some PowerShell wrappers.
  Defaults to `http://localhost:8000` if not set.

### Example `.env`

```bash
DATABASE_URL=postgresql+psycopg://baseliner:baseliner@db:5432/baseliner
BASELINER_ADMIN_KEY=change-me-too
BASELINER_TOKEN_PEPPER=change-me-too
```

## Agent (Windows)

The agent reads configuration from (lowest precedence to highest):

1. Built-in defaults
2. Config file (TOML) at `C:\ProgramData\Baseliner\agent.toml`
3. Environment variables
4. CLI flags

### Agent config file keys (`agent.toml`)

These are parsed by `agent/src/baseliner_agent/config.py`.

- `server_url` (string)
- `enroll_token` (string, optional; usually only used for initial enrollment)

**Run-loop scheduling**

- `poll_interval_seconds` (int; apply cadence)
- `heartbeat_interval_seconds` (int; set `0` to disable)
- `jitter_seconds` (int; random 0..jitter sleep used at startup and between cycles)

Other:

- `log_level` (string; currently informational)
- `tags` (table/dict of key/value pairs)
- `state_dir` (string; defaults to `C:\ProgramData\Baseliner`)
- `winget_path` (string; optional override for `winget.exe` when running as SYSTEM)

Example:

```toml
server_url = "https://api.example.com"
poll_interval_seconds = 900
heartbeat_interval_seconds = 60
jitter_seconds = 30
log_level = "info"

[tags]
env = "prod"
site = "nyc"
```

### Agent environment variables

These override config file values when set:

- `BASELINER_SERVER_URL`
- `BASELINER_ENROLL_TOKEN`
- `BASELINER_POLL_INTERVAL_SECONDS`
- `BASELINER_HEARTBEAT_INTERVAL_SECONDS`
- `BASELINER_JITTER_SECONDS`
- `BASELINER_LOG_LEVEL`
- `BASELINER_STATE_DIR`
- `BASELINER_TAGS` (comma-separated `k=v` pairs)
- `BASELINER_WINGET_PATH`

The agent also supports:

- `BASELINER_CONFIG` to point at a non-default config file path.

### Scheduling knobs

When installed via `agent/packaging/Install-BaselinerAgent.ps1`, the Scheduled Task runs a **single long-lived**:

- `baseliner-agent run-loop`

The cadence is controlled by `agent.toml`:

- `poll_interval_seconds`
- `heartbeat_interval_seconds`
- `jitter_seconds`

To change the cadence:

1. Edit `C:\ProgramData\Baseliner\agent.toml`
2. Restart the Scheduled Task (`Baseliner Agent`) or reboot

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
