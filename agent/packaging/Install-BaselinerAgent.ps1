[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ServerUrl,

    # One-time enroll token. Required if the device is not enrolled yet, or if -ReEnroll is set.
    [string]$EnrollToken = "",

    # Default to hostname.
    [string]$DeviceKey = $env:COMPUTERNAME,

    # Comma-separated tags, e.g. "env=dev,site=denver"
    [string]$Tags = "",

    [int]$IntervalSeconds = 900,
    [int]$JitterSeconds = 0,

    [string]$TaskName = "Baseliner Agent",

    [ValidateSet("SYSTEM", "CURRENTUSER")]
    [string]$RunAs = "SYSTEM",

    [switch]$ReEnroll,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-IsAdministrator {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-RepeatingTrigger {
    param(
        [Parameter(Mandatory)][datetime]$StartAt,
        [Parameter(Mandatory)][int]$IntervalSeconds
    )

    # Scheduled Tasks repetition is best-supported in minutes. Keep MVP simple.
    if ($IntervalSeconds -lt 60) { throw "IntervalSeconds must be >= 60 for Scheduled Task repetition compatibility." }
    if (($IntervalSeconds % 60) -ne 0) {
        $rounded = [int][Math]::Ceiling($IntervalSeconds / 60.0) * 60
        Write-Warning "IntervalSeconds ($IntervalSeconds) is not divisible by 60; rounding up to $rounded seconds."
        $IntervalSeconds = $rounded
    }

    $interval = New-TimeSpan -Seconds $IntervalSeconds
    $duration = New-TimeSpan -Days 3650

    # Best path: pass repetition at construction time (works on newer builds)
    try {
        return New-ScheduledTaskTrigger -Once -At $StartAt -RepetitionInterval $interval -RepetitionDuration $duration
    }
    catch {
        # Fallback: build and attach MSFT_TaskRepetitionPattern
        $t = New-ScheduledTaskTrigger -Once -At $StartAt

        $ns = "Root/Microsoft/Windows/TaskScheduler"
        $rep = New-CimInstance -Namespace $ns -ClassName MSFT_TaskRepetitionPattern -ClientOnly -Property @{
            Interval          = ("PT{0}S" -f [int]$interval.TotalSeconds)
            Duration          = ("P{0}D" -f 3650)
            StopAtDurationEnd = $false
        }

        # Some builds expose .Repetition (CIM instance) instead of RepetitionInterval/Duration properties.
        $t.Repetition = $rep
        return $t
    }
}


function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Stop-ExistingTaskIfAny([string]$Name) {
    $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($existing) {
        try { Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue } catch { }
    }
}

function Remove-ExistingTaskIfAny([string]$Name) {
    $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($existing) {
        try { Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue } catch { }
        try { Unregister-ScheduledTask -TaskName $Name -Confirm:$false } catch { }
    }
}

function Resolve-AgentPayload {
    param([string]$Root)

    $candidates = @(
        @{ Kind = "onedir"; Dir = (Join-Path $Root "baseliner-agent"); Exe = (Join-Path $Root "baseliner-agent\baseliner-agent.exe") },
        @{ Kind = "onefile"; Dir = $Root; Exe = (Join-Path $Root "baseliner-agent.exe") },
        @{ Kind = "onedir"; Dir = (Join-Path $Root "dist\baseliner-agent"); Exe = (Join-Path $Root "dist\baseliner-agent\baseliner-agent.exe") },
        @{ Kind = "onedir"; Dir = (Join-Path $Root "..\dist\baseliner-agent"); Exe = (Join-Path $Root "..\dist\baseliner-agent\baseliner-agent.exe") }
    )

    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c.Exe) {
            return $c
        }
    }

    throw @"
Could not find baseliner-agent payload.
Expected one of:
  - $Root\baseliner-agent\baseliner-agent.exe
  - $Root\baseliner-agent.exe
  - $Root\dist\baseliner-agent\baseliner-agent.exe
  - $Root\..\dist\baseliner-agent\baseliner-agent.exe

If you're using the bundle output, make sure the folder "baseliner-agent" exists next to this script.
"@
}

if (-not (Test-IsAdministrator)) {
    throw "Install must be run as Administrator (required to register the Scheduled Task)."
}

if ($IntervalSeconds -lt 30) {
    throw "IntervalSeconds must be >= 30"
}

$programFiles = [Environment]::GetFolderPath("ProgramFiles")
$programData = [Environment]::GetFolderPath("CommonApplicationData")

$InstallDir = Join-Path $programFiles "Baseliner"
$DataDir = Join-Path $programData  "Baseliner"
$BinDir = Join-Path $DataDir "bin"
$LogDir = Join-Path $DataDir "logs"

$ConfigPath = Join-Path $DataDir "agent.toml"
$TokenPath = Join-Path $DataDir "device_token.dpapi"

Write-Host "== Baseliner Agent install =="
Write-Host "server : $ServerUrl"
Write-Host "device : $DeviceKey"
Write-Host "task   : $TaskName"
Write-Host "runas  : $RunAs"
Write-Host "interval_seconds: $IntervalSeconds"
Write-Host "jitter_seconds  : $JitterSeconds"

Stop-ExistingTaskIfAny -Name $TaskName

Ensure-Dir $InstallDir
Ensure-Dir $DataDir
Ensure-Dir $BinDir
Ensure-Dir $LogDir

# Locate payload
$payload = Resolve-AgentPayload -Root $PSScriptRoot
$SourceDir = $payload.Dir
$SourceExe = $payload.Exe
$PayloadKind = $payload.Kind

Write-Host "== payload =="
Write-Host "kind  : $PayloadKind"
Write-Host "dir   : $SourceDir"
Write-Host "exe   : $SourceExe"

# Deploy binaries
Write-Host "== deploying binaries =="

try {
    if (Test-Path -LiteralPath $InstallDir) {
        Get-ChildItem -LiteralPath $InstallDir -Force -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
}
catch { }

if ($PayloadKind -eq "onedir") {
    # IMPORTANT: use -Path here (NOT -LiteralPath) because we intentionally use a wildcard.
    Copy-Item -Recurse -Force -Path (Join-Path $SourceDir "*") -Destination $InstallDir
}
else {
    Copy-Item -Force -LiteralPath $SourceExe -Destination (Join-Path $InstallDir "baseliner-agent.exe")
}

$ExePath = Join-Path $InstallDir "baseliner-agent.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Deploy succeeded but exe missing: $ExePath"
}

# Write minimal config
Write-Host "== writing config =="

$cfg = @"
server_url = "$ServerUrl"
poll_interval_seconds = $IntervalSeconds
log_level = "info"
"@

Write-Utf8NoBom -Path $ConfigPath -Text $cfg

# Enroll if needed
if ($ReEnroll) {
    Write-Host "== reenroll requested =="
    if (Test-Path -LiteralPath $TokenPath) {
        Remove-Item -Force -LiteralPath $TokenPath -ErrorAction SilentlyContinue
    }
}

$isEnrolled = Test-Path -LiteralPath $TokenPath
if (-not $isEnrolled) {
    if (-not $EnrollToken.Trim()) {
        throw "Device is not enrolled yet. Provide -EnrollToken (or remove -ReEnroll)."
    }

    Write-Host "== enrolling device =="
    & $ExePath --config $ConfigPath --state-dir $DataDir enroll --server $ServerUrl --enroll-token $EnrollToken --device-key $DeviceKey --tags $Tags
    if ($LASTEXITCODE -ne 0) { throw "Enroll failed (exit $LASTEXITCODE)" }
}
else {
    Write-Host "== already enrolled (token present) =="
}

# Wrapper called by the Scheduled Task (captures stdout/stderr)
$WrapperPath = Join-Path $BinDir "baseliner-agent-run.ps1"
$LogFile = Join-Path $LogDir "agent.log"

$wrapper = @'
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][string]$State,
    [Parameter(Mandatory)][string]$Server,
    [Parameter()][string]$Tags = "",
    [Parameter()][string]$Log = "",
    [Parameter()][int]$JitterSeconds = 0
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Now-Iso { (Get-Date).ToString("s") }
function Ensure-Dir([string]$Path) { if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null } }

if ($Log) {
    Ensure-Dir (Split-Path -Parent $Log)
    "==== baseliner task tick: $((Now-Iso)) ====" | Out-File $Log -Append -Encoding utf8
    "exe=$Exe" | Out-File $Log -Append -Encoding utf8
    "server=$Server" | Out-File $Log -Append -Encoding utf8
}

if ($JitterSeconds -gt 0) {
    $j = Get-Random -Minimum 0 -Maximum ($JitterSeconds + 1)
    if ($Log) { "[TASK] jitter_sleep_s=$j" | Out-File $Log -Append -Encoding utf8 }
    Start-Sleep -Seconds $j
}

try { chcp 65001 | Out-Null } catch { }
$env:PYTHONUTF8 = "1"

if (Test-Path -LiteralPath $State) {
    try { Set-Location -LiteralPath $State } catch { }
}

$args = @(
    "--config", $Config,
    "--state-dir", $State,
    "run-once",
    "--server", $Server
)

if ($Tags) {
    $args += @("--tags", $Tags)
}

$out = & $Exe @args 2>&1
$code = $LASTEXITCODE

if ($Log) {
    if ($out) { $out | Out-File $Log -Append -Encoding utf8 }
    ("[TASK] exit_code={0} ts={1}" -f $code, (Now-Iso)) | Out-File $Log -Append -Encoding utf8
}

exit $code
'@

Write-Utf8NoBom -Path $WrapperPath -Text $wrapper

# Register Scheduled Task
Write-Host "== registering scheduled task =="

Remove-ExistingTaskIfAny -Name $TaskName

$psExe = (Get-Command powershell.exe -ErrorAction Stop).Path
$argList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$WrapperPath`"",
    "-Exe", "`"$ExePath`"",
    "-Config", "`"$ConfigPath`"",
    "-State", "`"$DataDir`"",
    "-Server", "`"$ServerUrl`"",
    "-Tags", "`"$Tags`"",
    "-Log", "`"$LogFile`"",
    "-JitterSeconds", "$JitterSeconds"
) -join " "

$action = New-ScheduledTaskAction -Execute $psExe -Argument $argList -WorkingDirectory $DataDir

# Triggers:
#  - AtStartup (one run when machine boots)
#  - Repeating trigger every IntervalSeconds (start 1 minute from now)

$startup = New-ScheduledTaskTrigger -AtStartup
$repeat = New-RepeatingTrigger -StartAt (Get-Date).AddMinutes(1) -IntervalSeconds $IntervalSeconds


if ($RunAs -eq "SYSTEM") {
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}
else {
    $userId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    try {
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType S4U -RunLevel Highest
    }
    catch {
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Highest
    }
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

$task = New-ScheduledTask -Action $action -Trigger @($startup, $repeat) -Settings $settings -Principal $principal
Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null

Write-Host "[OK] Installed scheduled task: $TaskName"
Write-Host "exe   : $ExePath"
Write-Host "config: $ConfigPath"
Write-Host "state : $DataDir"
Write-Host "logs  : $LogFile"

if (-not $NoStart) {
    Write-Host "== starting task =="
    Start-ScheduledTask -TaskName $TaskName
}

Write-Host "[OK] done"
