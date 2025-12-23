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

    # Apply cadence (agent.toml: poll_interval_seconds)
    [int]$IntervalSeconds = 900,

    # Heartbeat cadence (agent.toml: heartbeat_interval_seconds). 0 disables heartbeat.
    [int]$HeartbeatIntervalSeconds = 60,

    # Jitter applied to scheduling (agent.toml: jitter_seconds). Also used as one-time startup jitter.
    [int]$JitterSeconds = 60,

    # If set, re-enroll even if a device token exists.
    [switch]$ReEnroll = $false,

    # Start the Scheduled Task immediately after install.
    [switch]$StartNow = $false,

    # If set, do not attempt to enroll (useful if you are just updating files).
    [switch]$SkipEnroll = $false
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Ensure-Dir {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Stop-ExistingTaskIfAny {
    param([Parameter(Mandatory)][string]$TaskName)
    try {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
        if ($info.State -eq "Running") {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
            Start-Sleep -Seconds 2
        }
    } catch {
        # Task doesn't exist
    }
}

function Remove-ExistingTaskIfAny {
    param([Parameter(Mandatory)][string]$TaskName)
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop | Out-Null
    } catch {
        # ignore
    }
}

function Resolve-AgentExe {
    param([Parameter(Mandatory)][string]$PackagingDir)

    # Prefer current working dir (bundle extraction folder)
    $cwdExe = Join-Path (Get-Location) "baseliner-agent.exe"
    if (Test-Path -LiteralPath $cwdExe) { return (Resolve-Path -LiteralPath $cwdExe).Path }

    # Next, alongside this script (if run from bundle folder)
    $scriptExe = Join-Path $PackagingDir "baseliner-agent.exe"
    if (Test-Path -LiteralPath $scriptExe) { return (Resolve-Path -LiteralPath $scriptExe).Path }

    # Finally, dev tree dist locations
    $distDir = Join-Path $PackagingDir "..\dist"
    $exe1 = Join-Path $distDir "baseliner-agent\baseliner-agent.exe"
    $exe2 = Join-Path $distDir "baseliner-agent.exe"
    if (Test-Path -LiteralPath $exe1) { return (Resolve-Path -LiteralPath $exe1).Path }
    if (Test-Path -LiteralPath $exe2) { return (Resolve-Path -LiteralPath $exe2).Path }

    throw "Could not find baseliner-agent.exe. Expected it next to this installer (bundle), or in agent\dist."
}

function Escape-TomlString {
    param([Parameter(Mandatory)][string]$Value)
    # minimal TOML string escaping
    return $Value.Replace('\', '\\').Replace('"', '\"')
}

function Toml-StringLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return '"' + (Escape-TomlString $Value) + '"'
}

function Set-TomlKey {
    <#
      Upsert a TOML key either at top-level or within [agent] if that section exists.
      - If key exists in target, replace its value.
      - If key does not exist, insert it at end of target section.
    #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][string]$ValueLiteral
    )

    $text = ""
    if (Test-Path -LiteralPath $Path) {
        $text = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue
        if ($null -eq $text) { $text = "" }
    }

    # Normalize newlines to \n for processing
    $text = $text -replace "`r`n", "`n"
    $lines = $text -split "`n", 0, "SimpleMatch"

    $agentHeader = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*\[agent\]\s*$') { $agentHeader = $i; break }
    }

    $targetStart = 0
    $targetEnd = $lines.Count

    if ($agentHeader -ge 0) {
        $targetStart = $agentHeader + 1
        $targetEnd = $lines.Count
        for ($j = $targetStart; $j -lt $lines.Count; $j++) {
            if ($lines[$j] -match '^\s*\[.*\]\s*$') { $targetEnd = $j; break }
        }
    }

    $keyRegex = '^\s*' + [regex]::Escape($Key) + '\s*='
    $replaced = $false
    for ($i = $targetStart; $i -lt $targetEnd; $i++) {
        if ($lines[$i] -match $keyRegex) {
            $lines[$i] = "$Key = $ValueLiteral"
            $replaced = $true
            break
        }
    }

    if (-not $replaced) {
        # Insert before targetEnd
        $newLines = New-Object System.Collections.Generic.List[string]
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($i -eq $targetEnd) {
                $newLines.Add("$Key = $ValueLiteral")
            }
            $newLines.Add($lines[$i])
        }
        if ($targetEnd -ge $lines.Count) {
            $newLines.Add("$Key = $ValueLiteral")
        }
        $lines = $newLines.ToArray()
    }

    $final = ($lines -join "`r`n").TrimEnd() + "`r`n"
    Write-Utf8NoBom -Path $Path -Content $final
}

if (-not (Test-IsAdministrator)) {
    throw "This installer must be run from an elevated (Administrator) PowerShell."
}

if ($IntervalSeconds -lt 30) { throw "IntervalSeconds must be >= 30 (got $IntervalSeconds)" }
if ($HeartbeatIntervalSeconds -lt 0) { throw "HeartbeatIntervalSeconds must be >= 0 (got $HeartbeatIntervalSeconds)" }
if ($JitterSeconds -lt 0) { throw "JitterSeconds must be >= 0 (got $JitterSeconds)" }

$PackagingDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$programFiles = $env:ProgramFiles
if (-not $programFiles) { $programFiles = "C:\Program Files" }
$installDir = Join-Path $programFiles "Baseliner"
$exePath = Join-Path $installDir "baseliner-agent.exe"
$runnerPath = Join-Path $installDir "baseliner-agent-run.ps1"

$programData = $env:ProgramData
if (-not $programData) { $programData = "C:\ProgramData" }
$stateDir = Join-Path $programData "Baseliner"
$configPath = Join-Path $stateDir "agent.toml"
$logsDir = Join-Path $stateDir "logs"
$runLoopLog = Join-Path $logsDir "run-loop.log"
$taskName = "Baseliner Agent"

Write-Host "[INFO] InstallDir:   $installDir"
Write-Host "[INFO] StateDir:     $stateDir"
Write-Host "[INFO] Config:       $configPath"
Write-Host "[INFO] Run-loop log: $runLoopLog"
Write-Host "[INFO] TaskName:     $taskName"

Ensure-Dir -Path $installDir
Ensure-Dir -Path $stateDir
Ensure-Dir -Path $logsDir

# Copy agent exe
$payloadExe = Resolve-AgentExe -PackagingDir $PackagingDir
Copy-Item -LiteralPath $payloadExe -Destination $exePath -Force
Write-Host "[OK] Copied agent: $exePath"

# Ensure/Upsert agent.toml scheduling knobs
if (-not (Test-Path -LiteralPath $configPath)) {
    $base = @"
# Baseliner agent configuration
# Edit this file and restart the Scheduled Task to apply changes.

server_url = $(Toml-StringLiteral -Value $ServerUrl)
poll_interval_seconds = $IntervalSeconds
heartbeat_interval_seconds = $HeartbeatIntervalSeconds
jitter_seconds = $JitterSeconds
log_level = "info"
"@
    Write-Utf8NoBom -Path $configPath -Content $base
    Write-Host "[OK] Created agent.toml"
} else {
    Write-Host "[INFO] Updating agent.toml (upsert keys)"
}

Set-TomlKey -Path $configPath -Key "server_url" -ValueLiteral (Toml-StringLiteral -Value $ServerUrl)
Set-TomlKey -Path $configPath -Key "poll_interval_seconds" -ValueLiteral "$IntervalSeconds"
Set-TomlKey -Path $configPath -Key "heartbeat_interval_seconds" -ValueLiteral "$HeartbeatIntervalSeconds"
Set-TomlKey -Path $configPath -Key "jitter_seconds" -ValueLiteral "$JitterSeconds"

# Runner script: runs run-loop and appends output to dedicated log (with simple rotation)
$runner = @'
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Exe,
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][string]$State,
    [Parameter(Mandatory)][string]$LogPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Rotate-LogIfNeeded([string]$Path, [int64]$MaxBytes = 10485760, [int]$Keep = 5) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        $len = (Get-Item -LiteralPath $Path).Length
        if ($len -lt $MaxBytes) { return }

        $ts = Get-Date -Format "yyyyMMdd-HHmmss"
        $dir = Split-Path -Parent $Path
        $base = [System.IO.Path]::GetFileNameWithoutExtension($Path)
        $rot = Join-Path $dir ("$base-$ts.log")
        Rename-Item -LiteralPath $Path -NewName $rot -Force

        $pattern = "$base-*.log"
        $files = Get-ChildItem -LiteralPath $dir -Filter $pattern -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
        if ($files.Count -gt $Keep) {
            $files | Select-Object -Skip $Keep | ForEach-Object {
                Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
            }
        }
    } catch { }
}

Ensure-Dir (Split-Path -Parent $LogPath)
Ensure-Dir $State
Rotate-LogIfNeeded $LogPath

try { chcp 65001 | Out-Null } catch {}
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

"$(Get-Date -Format o) [runner] starting: $Exe --config $Config --state-dir $State run-loop" | Out-File -FilePath $LogPath -Append -Encoding utf8

try {
    & $Exe --config $Config --state-dir $State run-loop 2>&1 | Tee-Object -FilePath $LogPath -Append | Out-Null
    $code = $LASTEXITCODE
} catch {
    "$(Get-Date -Format o) [runner] exception: $($_.Exception.Message)" | Out-File -FilePath $LogPath -Append -Encoding utf8
    $code = 1
}

"$(Get-Date -Format o) [runner] exit_code=$code" | Out-File -FilePath $LogPath -Append -Encoding utf8
exit $code
'@

Write-Utf8NoBom -Path $runnerPath -Content $runner
Write-Host "[OK] Wrote runner: $runnerPath"

# Enroll if needed
$tokenPath = Join-Path $stateDir "device_token.dpapi"
$hasToken = Test-Path -LiteralPath $tokenPath

if (-not $SkipEnroll) {
    if ($ReEnroll -or (-not $hasToken)) {
        if (-not $EnrollToken) {
            throw "EnrollToken is required for initial enrollment (or ReEnroll)."
        }
        Write-Host "[INFO] Enrolling device..."
        & $exePath --config $configPath --state-dir $stateDir enroll --server $ServerUrl --enroll-token $EnrollToken --device-key $DeviceKey --tags $Tags
        if ($LASTEXITCODE -ne 0) { throw "Enroll failed: exit_code=$LASTEXITCODE" }
        Write-Host "[OK] Enrolled."
    } else {
        Write-Host "[INFO] Device token exists; skipping enroll (use -ReEnroll to force)."
    }
} else {
    Write-Host "[INFO] SkipEnroll set; not enrolling."
}

# Scheduled Task: run-loop at startup (long-lived)
Write-Host "[INFO] Installing Scheduled Task: $taskName"
Stop-ExistingTaskIfAny -TaskName $taskName
Remove-ExistingTaskIfAny -TaskName $taskName

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    "-NoProfile -ExecutionPolicy Bypass -File `"$runnerPath`" " +
    "-Exe `"$exePath`" " +
    "-Config `"$configPath`" " +
    "-State `"$stateDir`" " +
    "-LogPath `"$runLoopLog`""
)

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 0)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Write-Host "[OK] Installed Scheduled Task: $taskName"

if ($StartNow) {
    Write-Host "[INFO] Starting Scheduled Task..."
    Start-ScheduledTask -TaskName $taskName
    Write-Host "[OK] Started."
}

Write-Host ""
Write-Host "[OK] Install complete."
Write-Host "    Config:       $configPath"
Write-Host "    State:        $stateDir"
Write-Host "    Run-loop log: $runLoopLog"
