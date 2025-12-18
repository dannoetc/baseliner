# Agent Packaging (PyInstaller)

This folder contains a pragmatic MVP packaging flow for the **Baseliner Windows agent**.

Goals:
- Produce a self-contained agent binary (`baseliner-agent.exe`) via PyInstaller.
- Provide install/uninstall PowerShell scripts suitable for:
  - RMM execution
  - Intune Win32 app install/uninstall command lines

## Build

From `agent/`:

```powershell
pwsh -File .\packaging\Build-Agent.ps1
```

Outputs:
- `agent\dist\baseliner-agent\baseliner-agent.exe` (and supporting files; onedir build)

## Create an install bundle

```powershell
pwsh -File .\packaging\Build-Agent.ps1 -Bundle
```

Outputs:
- `agent\out\baseliner-agent-bundle.zip`

The bundle contains:
- `baseliner-agent\...` (PyInstaller onedir output)
- `Install-BaselinerAgent.ps1`
- `Uninstall-BaselinerAgent.ps1`

## Install (RMM / manual)

From inside the extracted bundle directory:

```powershell
pwsh -File .\Install-BaselinerAgent.ps1 `
  -ServerUrl "http://localhost:8000" `
  -EnrollToken "<one-time-token>" `
  -DeviceKey $env:COMPUTERNAME `
  -Tags "env=dev,site=denver" `
  -IntervalSeconds 900
```

## Intune Win32 app

Use the same scripts:
- **Install command:** `powershell.exe -ExecutionPolicy Bypass -File Install-BaselinerAgent.ps1 -ServerUrl ... -EnrollToken ... -DeviceKey ... -Tags ...`
- **Uninstall command:** `powershell.exe -ExecutionPolicy Bypass -File Uninstall-BaselinerAgent.ps1`

Detection rule suggestion (file exists):
- `C:\Program Files\Baseliner\baseliner-agent.exe`
