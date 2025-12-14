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

## Commands

### Enroll (one-time)
```powershell
python -m baseliner_agent enroll --server http://localhost:8000 --enroll-token <TOKEN> --device-key TEST-DEVICE-001
```

### Run once
```powershell
python -m baseliner_agent run-once --server http://localhost:8000
```

## State files
Default path: `%ProgramData%\Baseliner\`
- `state.json` (device_id, device_key, last_policy_hash, etc.)
- `device_token.dpapi` (DPAPI-encrypted device bearer token)
- `queue\*.json` (queued reports if the server is unreachable)

## Notes
- DPAPI encryption uses the *current Windows user context*. For a service later,
  run the agent consistently under the same account (e.g., LocalSystem) or switch to machine DPAPI.
