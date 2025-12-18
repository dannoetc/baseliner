# Agent Packaging (PyInstaller)

This folder contains a pragmatic MVP packaging flow for the **Baseliner Windows agent**.

Goals:
- Produce a self-contained agent binary (`baseliner-agent.exe`) via PyInstaller.
- Provide install/uninstall PowerShell scripts suitable for:
  - RMM execution
  - Intune Win32 app install/uninstall command lines
- Run the agent via a **Scheduled Task** for MVP (service can come later).

## Build (PyInstaller)

From `agent/`:

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
  -IntervalSeconds 900
```

Installs:
- Binaries: `C:\Program Files\Baseliner\`
- State/config/logs: `C:\ProgramData\Baseliner\`
- Scheduled task: `Baseliner Agent` (SYSTEM by default)

Logs:
- `C:\ProgramData\Baseliner\logs\agent.log`

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
- File exists: `C:\Program Files\Baseliner\baseliner-agent.exe`

## Notes / Gotchas

### Scheduled Task repetition compatibility

Some Windows builds do not support setting `trigger.RepetitionInterval` / `trigger.RepetitionDuration` properties directly.

The installer uses a **version-tolerant** approach:
- Prefer `New-ScheduledTaskTrigger -RepetitionInterval/-RepetitionDuration`
- Fall back to attaching a `MSFT_TaskRepetitionPattern` object (`trigger.Repetition`)

Also, repetition is most reliable when `IntervalSeconds` is divisible by 60.
If not divisible, the installer rounds up to the next minute.
