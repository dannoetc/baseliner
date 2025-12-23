# Agent Packaging (PyInstaller)

This folder contains a pragmatic MVP packaging flow for the **Baseliner Windows agent**.

Goals:
- Produce a self-contained agent binary (`baseliner-agent.exe`) via PyInstaller.
- Provide install/uninstall PowerShell scripts suitable for:
  - RMM execution
  - Intune Win32 app install/uninstall command lines
- Run the agent via a **Scheduled Task** for MVP (a Windows service can come later).

## Build (PyInstaller)

From `agent\`:

```powershell
pwsh -File .\packaging\Build-Agent.ps1
```

Outputs (onedir build):
- `agent\dist\baseliner-agent\baseliner-agent.exe` (and supporting files)

### Build + Bundle

```powershell
pwsh -File .\packaging\Build-Agent.ps1 -Bundle
```

Outputs:
- `agent\out\baseliner-agent-bundle.zip`

Bundle contents:
- `baseliner-agent\...` (PyInstaller onedir output)
- `Install-BaselinerAgent.ps1`
- `Uninstall-BaselinerAgent.ps1`
- `README.md`

## Install (RMM / manual)

Unblock scripts if they came from a zip download (Mark-of-the-Web prompt):

```powershell
Get-ChildItem -Path . -Recurse -Filter *.ps1 | Unblock-File
```

Run install from the extracted bundle directory:

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

Installs:
- Binaries: `C:\\Program Files\\Baseliner\\`
- State/config/logs: `C:\\ProgramData\\Baseliner\\`
- Scheduled task: `Baseliner Agent` (SYSTEM by default)

### What the Scheduled Task runs

The installed Scheduled Task launches a **single long-lived** agent process at startup using:

- `baseliner-agent run-loop`

The cadence is controlled by `C:\\ProgramData\\Baseliner\\agent.toml`:

- `poll_interval_seconds`
- `heartbeat_interval_seconds` (set `0` to disable)
- `jitter_seconds` (also used as a one-time startup jitter)

To change cadence:

1. Edit `agent.toml`
2. Restart the Scheduled Task (`Baseliner Agent`) or reboot

### Logs

There are two useful logs:

- Run-loop stdout/stderr captured by the Scheduled Task:
  - `C:\\ProgramData\\Baseliner\\logs\\run-loop.log`
- Structured agent event log (used by support bundles):
  - `C:\\ProgramData\\Baseliner\\logs\\agent.log`

## Intune Win32 App

Use the same scripts.

Install command (example):

```text
powershell.exe -ExecutionPolicy Bypass -File Install-BaselinerAgent.ps1 -ServerUrl https://server.example -EnrollToken <token> -DeviceKey %COMPUTERNAME% -Tags "env=prod,site=nyc"
```

Uninstall command:

```text
powershell.exe -ExecutionPolicy Bypass -File Uninstall-BaselinerAgent.ps1
```

Detection rule suggestion:
- File exists: `C:\\Program Files\\Baseliner\\baseliner-agent.exe`

## Notes / Gotchas

### Editing `agent.toml`

The installer **upserts** schedule keys into `agent.toml` if they are missing.
This is safe to run on top of an existing install without blowing away unrelated keys.

### Running PyInstaller as admin

PyInstaller prints a warning if you build as Administrator. Prefer running `Build-Agent.ps1` from a non-admin terminal.
