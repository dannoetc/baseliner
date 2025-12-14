# Requires: Run as Administrator
# Installs a Scheduled Task that runs Baseliner agent at startup (run-loop).
# Logs stdout/stderr to C:\ProgramData\Baseliner\logs\agent.log

param(
    [string]$TaskName = "Baseliner Agent",
    [string]$RepoRoot = "C:\Users\Administrator\Documents\GitHub\baseliner",
    [string]$ConfigPath = "C:\ProgramData\Baseliner\agent.toml",
    [string]$StateDir = "C:\ProgramData\Baseliner",
    [string]$LogDir = "C:\ProgramData\Baseliner\logs",
    [string]$LogFile = "C:\ProgramData\Baseliner\logs\agent.log",
    [int]$IntervalSeconds = 900,
    [int]$JitterSeconds = 0,
    [ValidateSet("SYSTEM", "CURRENTUSER")]
    [string]$RunAs = "CURRENTUSER"
)

$ErrorActionPreference = "Stop"

$agentDir = Join-Path $RepoRoot "agent"
$venvPython = Join-Path $agentDir ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Python venv not found at: $venvPython. Create/activate the agent venv in $agentDir first."
}

# Ensure folders exist
$pd = Split-Path -Parent $ConfigPath
New-Item -ItemType Directory -Force -Path $pd | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType File -Force -Path $LogFile | Out-Null

# Minimal default config if missing (server_url is intentionally not forced)
if (-not (Test-Path $ConfigPath)) {
    @"
# Baseliner Agent config (TOML)
# Place at: $ConfigPath
#
# server_url = "http://localhost:8000"
poll_interval_seconds = $IntervalSeconds
log_level = "info"

[tags]
env = "dev"
"@ | Set-Content -Path $ConfigPath -Encoding UTF8
}

# Task action:
# We invoke python.exe directly and run the module.
# Use cmd.exe wrapper so we can redirect output easily (append).
# NOTE: We pass --config and --state-dir explicitly so task is deterministic.
$cmd = @(
    "/c",
    "`"$venvPython`" -m baseliner_agent --config `"$ConfigPath`" --state-dir `"$StateDir`" run-loop --interval $IntervalSeconds --jitter $JitterSeconds >> `"$LogFile`" 2>&1"
) -join " "

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmd -WorkingDirectory $agentDir

# Trigger at startup
$trigger = New-ScheduledTaskTrigger -AtStartup

# Settings: restart on failure
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)  # basically "no limit"

# Principal
if ($RunAs -eq "SYSTEM") {
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}
else {
    # CURRENTUSER
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Highest
}

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Write-Host "[INFO] Resolved config (redacted):"
& $venvPython -m baseliner_agent --config "$ConfigPath" config show
if ($LASTEXITCODE -ne 0) { throw "baseliner_agent config show failed (exit $LASTEXITCODE)" }
Write-Host ""

Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null

Write-Host "[OK] Installed Scheduled Task: $TaskName"
Write-Host "     RunAs: $RunAs"
Write-Host "     Config: $ConfigPath"
Write-Host "     State:  $StateDir"
Write-Host "     Logs:   $LogFile"
Write-Host ""
Write-Host "To start immediately:"
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
