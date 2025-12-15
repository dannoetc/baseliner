# Requires: Run as Administrator
# Installs/updates a Scheduled Task that runs Baseliner agent at startup/logon.
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
Set-StrictMode -Version Latest

function Test-IsAdministrator {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    throw "This script must be run as Administrator."
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Get-CurrentUserId {
    # Returns DOMAIN\\User when available (preferred for Scheduled Task principal)
    try {
        return [Security.Principal.WindowsIdentity]::GetCurrent().Name
    }
    catch {
        if ($env:USERDOMAIN) { return "$env:USERDOMAIN\$env:USERNAME" }
        return "$env:USERNAME"
    }
}

function Resolve-PythonForTask {
    param([Parameter(Mandatory)][string]$PyExePath)
    # Scheduled tasks love absolute paths. Return full resolved path.
    try {
        return (Resolve-Path -LiteralPath $PyExePath -ErrorAction Stop).Path
    }
    catch {
        throw "python not found at $PyExePath. Re-run with -BootstrapVenv or create the venv at $(Split-Path -Parent $PyExePath)"
    }
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
# NOTE: patched to:
#  - create per-run log files from the new Python agent health line (still appends to agent.log)
#  - add a small sleep/jitter in run-loop to avoid thundering herd
#  - robust error handling + always emit a final status line
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
Set-StrictMode -Version Latest

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null }
}

function Now-Iso {
    (Get-Date).ToString("s")
}

function Sleep-WithJitter([int]$BaseSeconds, [int]$JitterSeconds) {
    $b = [Math]::Max(1, [int]$BaseSeconds)
    $j = [Math]::Max(0, [int]$JitterSeconds)
    if ($j -le 0) { return $b }
    return ($b + (Get-Random -Minimum 0 -Maximum ($j + 1)))
}

$logDir = Split-Path -Parent $Log
Ensure-Dir $logDir

# Optional separate rolling "runs" directory (keeps long agent.log from being the only artifact)
$runsDir = Join-Path $logDir "runs"
Ensure-Dir $runsDir

$runId = [guid]::NewGuid().ToString()
$runLog = Join-Path $runsDir ("task-run-{0}.log" -f $runId)

"==== baseliner task start: $((Now-Iso)) ====" | Out-File $Log -Append -Encoding utf8
"run_id: $runId" | Out-File $Log -Append -Encoding utf8
"whoami: $(whoami)" | Out-File $Log -Append -Encoding utf8
"python: $Python"  | Out-File $Log -Append -Encoding utf8
"config: $Config"  | Out-File $Log -Append -Encoding utf8
"state : $State"   | Out-File $Log -Append -Encoding utf8
"cmd   : $Command" | Out-File $Log -Append -Encoding utf8
"interval_seconds: $IntervalSeconds" | Out-File $Log -Append -Encoding utf8
"jitter_seconds  : $JitterSeconds"   | Out-File $Log -Append -Encoding utf8
"" | Out-File $Log -Append -Encoding utf8

# Mirror header to per-run file
Get-Content -LiteralPath $Log -Tail 10 | Out-File $runLog -Append -Encoding utf8

if (-not (Test-Path -LiteralPath $Python)) {
    "ERROR: python not found at: $Python" | Out-File $Log -Append -Encoding utf8
    "ERROR: python not found at: $Python" | Out-File $runLog -Append -Encoding utf8
    exit 2
}

# Make stdout/stderr sane in scheduled task context
$env:PYTHONUTF8 = "1"
try { chcp 65001 | Out-Null } catch { }

# Prefer to run from StateDir (keeps relative paths / cwd stable)
if (Test-Path -LiteralPath $State) {
    try { Set-Location -LiteralPath $State } catch { }
}

function Invoke-AgentOnce {
    param([switch]$ForceFlag)

    # IMPORTANT: global args go BEFORE the subcommand in argparse
    $pyArgs = @(
        "-m", "baseliner_agent",
        "--config", $Config,
        "--state-dir", $State,
        "run-once"
    )
    if ($ForceFlag) { $pyArgs += "--force" }

    $start = Get-Date
    try {
        # Capture output so we can tee it to both logs.
        $out = & $Python @pyArgs 2>&1
        $code = $LASTEXITCODE
    }
    catch {
        $out = $_.Exception.ToString()
        $code = 1
    }
    $dur = (New-TimeSpan -Start $start -End (Get-Date)).TotalSeconds

    # Write output to both logs
    if ($out) {
        $out | Out-File $Log    -Append -Encoding utf8
        $out | Out-File $runLog -Append -Encoding utf8
    }

    # Always append a short footer marker
    ("[TASK] run_once_exit_code={0} dur_s={1:N2} ts={2}" -f $code, $dur, (Now-Iso)) | Out-File $Log -Append -Encoding utf8
    ("[TASK] run_once_exit_code={0} dur_s={1:N2} ts={2}" -f $code, $dur, (Now-Iso)) | Out-File $runLog -Append -Encoding utf8

    return $code
}

# Dispatch
if ($Command -eq "run-once") {
    $exit = Invoke-AgentOnce -ForceFlag:$Force
    exit $exit
}

if ($Command -eq "run-loop") {
    while ($true) {
        $exit = Invoke-AgentOnce -ForceFlag:$Force
        $sleep = Sleep-WithJitter -BaseSeconds $IntervalSeconds -JitterSeconds $JitterSeconds
        ("[TASK] sleeping_s={0} last_exit={1} ts={2}" -f $sleep, $exit, (Now-Iso)) | Out-File $Log -Append -Encoding utf8
        ("[TASK] sleeping_s={0} last_exit={1} ts={2}" -f $sleep, $exit, (Now-Iso)) | Out-File $runLog -Append -Encoding utf8
        Start-Sleep -Seconds $sleep
    }
}

"ERROR: unknown Command=$Command" | Out-File $Log -Append -Encoding utf8
"ERROR: unknown Command=$Command" | Out-File $runLog -Append -Encoding utf8
exit 3
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

# Sanity check: python exists (and resolve to absolute path for task)
$pyExeResolved = Resolve-PythonForTask -PyExePath $pyExe

# Build scheduled task action that calls the helper
$psExe = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"

# Quote carefully; scheduled tasks are picky
$arg = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$helperPath`"",
    "-Python", "`"$pyExeResolved`"",
    "-Config", "`"$ConfigPath`"",
    "-State", "`"$StateDir`"",
    "-Log", "`"$LogFile`"",
    "-Command", "run-loop",
    "-IntervalSeconds", "$IntervalSeconds",
    "-JitterSeconds", "$JitterSeconds"
) -join " "

$action = New-ScheduledTaskAction -Execute $psExe -Argument $arg -WorkingDirectory $StateDir

if ($RunAs -eq "SYSTEM") {
    # AtStartup is ideal for the agent as SYSTEM.
    $trigger = New-ScheduledTaskTrigger -AtStartup
}
else {
    # For CURRENTUSER, AtLogOn is more reliable than AtStartup.
    $userId = Get-CurrentUserId
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -MultipleInstances IgnoreNew

# Optional: add a small startup delay when possible (helps on boot before network is ready)
try {
    if ($RunAs -eq "SYSTEM") {
        # Not all PowerShell versions expose -Delay for startup triggers.
        $null = $trigger.Delay
        $trigger.Delay = "PT30S"
    }
}
catch {
    # ignore
}

if ($RunAs -eq "SYSTEM") {
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}
else {
    # S4U allows the task to run without storing a password.
    # Some environments can be finicky; fall back to Interactive if needed.
    if (-not $userId) { $userId = Get-CurrentUserId }
    try {
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType S4U -RunLevel Highest
    }
    catch {
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Highest
    }
}

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal

# Replace existing task
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch { }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Optional: show resolved config (from ProgramData venv)
Write-Host "[INFO] resolved config (redacted):"
& $pyExeResolved -m baseliner_agent --config "$ConfigPath" config show
if ($LASTEXITCODE -ne 0) { throw "baseliner_agent config show failed (exit $LASTEXITCODE)" }
Write-Host ""

Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null

Write-Host "[OK] installed scheduled task: $TaskName"
Write-Host "     runas : $RunAs"
if ($RunAs -eq "SYSTEM") {
    Write-Host "     trigger: AtStartup"
    Write-Host "     user   : SYSTEM"
}
else {
    if (-not $userId) { $userId = Get-CurrentUserId }
    Write-Host "     trigger: AtLogOn"
    Write-Host "     user   : $userId"
}
Write-Host "     helper: $helperPath"
Write-Host "     python: $pyExeResolved"
Write-Host "     config: $ConfigPath"
Write-Host "     state : $StateDir"
Write-Host "     logs  : $LogFile"
Write-Host "     runs  : $(Join-Path $LogDir 'runs')"
Write-Host ""
Write-Host "to start immediately:"
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
