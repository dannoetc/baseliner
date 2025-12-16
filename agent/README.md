# Baseliner Agent (Windows MVP)

This is the first Windows-focused Baseliner agent scaffold. It supports:
- one-time enrollment (`enroll`) to obtain a device token
- fetch effective policy (`run-once`) and compare `effective_policy_hash`
- execute `winget.package` resources (detect + install/upgrade)
- submit a run report (items + logs) to the Baseliner server
- simple local state + an offline report queue

## Requirements
- Windows 10/11 or Windows Server with `winget` installed
- Python 3.12+

## Setup (dev)
From `repo_root/agent`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configuration

Configuration is resolved in this order: defaults → `agent.toml` → environment variables → CLI overrides. The default config path is `%ProgramData%\Baseliner\agent.toml` and supports either top-level keys or an `[agent]` table.

Environment variable overrides:
- `BASELINER_SERVER_URL`
- `BASELINER_ENROLL_TOKEN`
- `BASELINER_POLL_INTERVAL_SECONDS`
- `BASELINER_LOG_LEVEL`
- `BASELINER_STATE_DIR`
- `BASELINER_TAGS`
- `BASELINER_WINGET_PATH`

Tags can be supplied via `BASELINER_TAGS` using comma-separated values such as `role=workstation,team=it`.

## Commands

### Enroll (one-time)
```powershell
python -m baseliner_agent enroll --server http://localhost:8000 --enroll-token <TOKEN> --device-key TEST-DEVICE-001
```

### Run once
```powershell
python -m baseliner_agent run-once --server http://localhost:8000
```

### Policy lifecycle + reporting smoketest
Run this on your Windows dev box to exercise the admin/device contract end-to-end (policy upsert → assign → agent run → run detail diagnostics → winget assertions). It walks through the PuTTY/7-Zip/Firefox phases described in the PRD and pauses after each policy so you can trigger a single agent execution.

```powershell
cd scripts
./policy-lifecycle-smoketest.ps1 -Server http://localhost:8000 -AdminKey <ADMIN_KEY> -DeviceKey <YOUR_DEVICE_KEY>
```

## State files
Default path: `%ProgramData%\Baseliner\`
- `state.json` (device_id, device_key, last_policy_hash, etc.)
- `device_token.dpapi` (DPAPI-encrypted device bearer token)
- `queue\*.json` (queued reports if the server is unreachable)

## Notes
- DPAPI encryption uses the *current Windows user context*. For a service later,
  run the agent consistently under the same account (e.g., LocalSystem) or switch to machine DPAPI.
