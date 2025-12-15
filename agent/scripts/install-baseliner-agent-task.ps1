# Requires: Run as Administrator
# Installs/updates a Scheduled Task that runs Baseliner agent at startup.
# Uses a PowerShell helper (C:\ProgramData\Baseliner\bin\baseliner-agent-task.ps1)
# Logs to C:\ProgramData\Baseliner\logs\agent.log

[CmdletBinding()]
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
    [string]$RunAs = "CURRENTUSER",

    [switch]$BootstrapVenv
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

# Paths
$agentDir = Join-Path $RepoRoot "agent"
$binDir = Join-Path $StateDir "bin"
$helperPath = Join-Path $binDir "baseliner-agent-task.ps1"
$venvDir = Join-Path $StateDir "venv"
$pyExe = Join-Path $venvDir "Scripts\python.exe"

# Ensure folders exist
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir   | Out-Null
New-Item -ItemType Directory -Force -Path $binDir   | Out-Null
if (-not (Test-Path -LiteralPath $LogFile)) {
    New-Item -ItemType File -Force -Path $LogFile | Out-Null
}

# Minimal default config if missing (server_url intentionally not forced)
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    $cfg = @"
# baseliner agent config (toml)
# server_url = "http://localhost:8000"
poll_interval_seconds = $IntervalSeconds
log_level = "info"

[tags]
env = "dev"
site = "denver"
"@
    Write-Utf8NoBom -Path $ConfigPath -Text $cfg
}

# Write/update helper into ProgramData so SYSTEM can access it
$helper = @'
# C:\ProgramData\Baseliner\bin\baseliner-agent-task.ps1
[CmdletBinding()]
param(
    [Parameter()] [string] $Python  = "C:\ProgramData\Baseliner\venv\Scripts\python.exe",
    [Parameter()] [string] $Config  = "C:\ProgramData\Baseliner\agent.toml",
    [Parameter()] [string] $State   = "C:\ProgramData\Baseliner",
    [Parameter()] [string] $Log     = "C:\ProgramData\Baseliner\logs\agent.log",
    [Parameter()] [ValidateSet("run-once","run-loop")] [string] $Command = "run-once",
    [Parameter()] [int] $IntervalSeconds = 900,
    [Parameter()] [int] $JitterSeconds   = 0,
    [Parameter()] [switch] $Force
)

$ErrorActionPreference = "Stop"

$logDir = Split-Path -Parent $Log
New-Item -ItemType Directory -Force $logDir | Out-Null

"==== baseliner task start: $((Get-Date).ToString('s')) ====" | Out-File $Log -Append -Encoding utf8
"whoami: $(whoami)" | Out-File $Log -Append -Encoding utf8
"python: $Python"  | Out-File $Log -Append -Encoding utf8
"config: $Config"  | Out-File $Log -Append -Encoding utf8
"state : $State"   | Out-File $Log -Append -Encoding utf8
"cmd   : $Command" | Out-File $Log -Append -Encoding utf8

if (-not (Test-Path -LiteralPath $Python)) {
    "ERROR: python not found at: $Python" | Out-File $Log -Append -Encoding utf8
    exit 2
}

# Make stdout/stderr sane in scheduled task context
$env:PYTHONUTF8 = "1"
try { chcp 65001 | Out-Null } catch { }

# Prefer to run from StateDir (keeps relative paths / cwd stable)
if (Test-Path -LiteralPath $State) {
    try { Set-Location -LiteralPath $State } catch { }
}

# IMPORTANT: global args go BEFORE the subcommand in argparse
$pyArgs = @(
    "-m", "baseliner_agent",
    "--config", $Config,
    "--state-dir", $State,
    $Command
)

if ($Command -eq "run-once") {
    if ($Force) { $pyArgs += "--force" }
}
elseif ($Command -eq "run-loop") {
    # only add if non-defaults were passed in
    if ($IntervalSeconds -gt 0) { $pyArgs += @("--interval", "$IntervalSeconds") }
    if ($JitterSeconds   -ge 0) { $pyArgs += @("--jitter",   "$JitterSeconds") }
}

& $Python @pyArgs *>> $Log
exit $LASTEXITCODE
'@

Write-Utf8NoBom -Path $helperPath -Text $helper

# Bootstrap venv into ProgramData (recommended for SYSTEM)
if ($BootstrapVenv) {
    if (-not (Test-Path -LiteralPath $agentDir)) {
        throw "agent directory not found: $agentDir"
    }

    if (-not (Test-Path -LiteralPath $pyExe)) {
        # Create venv
        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            & py -3.12 -m venv $venvDir
        }
        else {
            $python = Get-Command python -ErrorAction SilentlyContinue
            if (-not $python) { throw "could not find 'py' or 'python' to create venv" }
            & python -m venv $venvDir
        }
    }

    # Install/refresh editable package in the ProgramData venv
    & $pyExe -m pip install --upgrade pip | Out-Null
    & $pyExe -m pip install -e $agentDir
}

# Sanity check: python exists
if (-not (Test-Path -LiteralPath $pyExe)) {
    throw "python not found at $pyExe. re-run with -BootstrapVenv or create the venv at $venvDir"
}

# Build scheduled task action that calls the helper
$psExe = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"

# Quote carefully; scheduled tasks are picky
$arg = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$helperPath`"",
    "-Python", "`"$pyExe`"",
    "-Config", "`"$ConfigPath`"",
    "-State", "`"$StateDir`"",
    "-Log", "`"$LogFile`"",
    "-Command", "run-loop",
    "-IntervalSeconds", "$IntervalSeconds",
    "-JitterSeconds", "$JitterSeconds"
) -join " "

$action = New-ScheduledTaskAction -Execute $psExe -Argument $arg -WorkingDirectory $StateDir
$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)

if ($RunAs -eq "SYSTEM") {
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}
else {
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Highest
}

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal

# Replace existing task
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Optional: show resolved config (from ProgramData venv)
Write-Host "[INFO] resolved config (redacted):"
& $pyExe -m baseliner_agent --config "$ConfigPath" config show
if ($LASTEXITCODE -ne 0) { throw "baseliner_agent config show failed (exit $LASTEXITCODE)" }
Write-Host ""

Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null

Write-Host "[OK] installed scheduled task: $TaskName"
Write-Host "     runas : $RunAs"
Write-Host "     helper: $helperPath"
Write-Host "     python: $pyExe"
Write-Host "     config: $ConfigPath"
Write-Host "     state : $StateDir"
Write-Host "     logs  : $LogFile"
Write-Host ""
Write-Host "to start immediately:"
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
