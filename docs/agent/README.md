# Agent

The Baseliner agent is a Windows-first MVP that:

- Enrolls to the Baseliner server using a one-time enroll token
- Fetches the device's effective policy, applies it, and posts a detailed run report (`run_kind=apply`)
- Optionally posts lightweight **heartbeat** runs between applies (`run_kind=heartbeat`)

## Install and update (Windows)

For MVP, installation uses a Scheduled Task (a Windows service can come later).

The packaging bundle contains:

- `baseliner-agent\...` (PyInstaller onedir output)
- `Install-BaselinerAgent.ps1`
- `Uninstall-BaselinerAgent.ps1`

### Build + bundle

From `agent\`:

```powershell
pwsh -File .\packaging\Build-Agent.ps1 -Bundle
```

Output:

- `agent\out\baseliner-agent-bundle.zip`

### Install from the bundle

Extract the bundle zip. If PowerShell warns that scripts came from the internet, unblock them:

```powershell
Get-ChildItem -Path . -Recurse -Filter *.ps1 | Unblock-File
```

Then run:

```powershell
pwsh -File .\Install-BaselinerAgent.ps1 `
  -ServerUrl "http://localhost:8000" `
  -EnrollToken "<one-time-token>" `
  -DeviceKey $env:COMPUTERNAME `
  -Tags "env=dev,site=denver" `
  -IntervalSeconds 900 `
  -HeartbeatIntervalSeconds 60 `
  -JitterSeconds 30
```

By default this installs:

- Binaries: `C:\\Program Files\\Baseliner\\`
- State/config/logs: `C:\\ProgramData\\Baseliner\\`
- Scheduled Task: `Baseliner Agent` (runs as SYSTEM by default)

### What the Scheduled Task runs

The installed Scheduled Task launches a **single long-lived** agent process at startup:

- `baseliner-agent run-loop`

The cadence is controlled by `C:\\ProgramData\\Baseliner\\agent.toml`:

- `poll_interval_seconds` (apply cadence)
- `heartbeat_interval_seconds` (set `0` to disable)
- `jitter_seconds` (also used as a one-time startup jitter)

To change the schedule:

1. Edit `C:\\ProgramData\\Baseliner\\agent.toml`
2. Restart the Scheduled Task (`Baseliner Agent`) or reboot

## Logs

There are two useful logs:

- Run-loop stdout/stderr (what the Scheduled Task captures):
  - `C:\\ProgramData\\Baseliner\\logs\\run-loop.log`
- Structured agent event log (local troubleshooting / support bundles):
  - `C:\\ProgramData\\Baseliner\\logs\\agent.log`

## State and configuration

Default locations:

- Config: `C:\\ProgramData\\Baseliner\\agent.toml`
- Encrypted device token: `C:\\ProgramData\\Baseliner\\device_token.dpapi`
- Health file: `C:\\ProgramData\\Baseliner\\health.json`

The agent supports overriding configuration via environment variables; see `docs\\reference\\configuration.md`.

## Running manually

From an elevated terminal (or a terminal with access to the state directory):

```powershell
$Exe = "C:\\Program Files\\Baseliner\\baseliner-agent.exe"
$State = "C:\\ProgramData\\Baseliner"
$Cfg = Join-Path $State "agent.toml"

# Apply once
& $Exe --config $Cfg --state-dir $State run-once --server "http://localhost:8000"

# Run continuously (defaults come from agent.toml)
& $Exe --config $Cfg --state-dir $State run-loop --server "http://localhost:8000"

# Local health
& $Exe --config $Cfg --state-dir $State health show
```

## Support bundle

To collect troubleshooting artifacts (recent logs/state/redacted config) into a zip:

```powershell
$Exe = "C:\\Program Files\\Baseliner\\baseliner-agent.exe"
$State = "C:\\ProgramData\\Baseliner"
$Cfg = Join-Path $State "agent.toml"

& $Exe --config $Cfg --state-dir $State support-bundle --since-hours 24
```

The command prints the created zip path.
