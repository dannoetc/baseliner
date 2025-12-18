[CmdletBinding()]
param(
    [string]$Server = "http://localhost:8000",
    [string]$AdminKey = "change-me-too",

    # Device UUID in Baseliner server DB (for polling debug endpoint)
    [Parameter(Mandatory)]
    [string]$DeviceId,

    # Path to extracted bundle directory that contains:
    # - Install-BaselinerAgent.ps1
    # - Uninstall-BaselinerAgent.ps1
    # - baseliner-agent\baseliner-agent.exe  (onedir)
    [Parameter(Mandatory)]
    [string]$BundleDir,

    # Optional: if omitted and the device is not enrolled, script will request a new enroll token via admin API
    [string]$EnrollToken = "",

    [string]$TaskName = "Baseliner Agent",
    [int]$IntervalSeconds = 900,
    [int]$JitterSeconds = 0,
    [string]$Tags = "env=dev",

    # How long to let the scheduled task run before stopping (best-effort)
    [int]$RunForSeconds = 30,

    # Poll settings for waiting on a new run to appear in debug endpoint
    [int]$PollSeconds = 90,
    [int]$PollIntervalSeconds = 2,

    # If set, will force uninstall to purge ProgramData and will force re-enroll (needs token or admin API)
    [switch]$PurgeData,

    # If set, uninstall again after verifying a new run
    [switch]$CleanupAtEnd
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Headers = @{
    "X-Admin-Key" = $AdminKey
    "Accept"      = "application/json"
}

function Invoke-Api {
    param(
        [Parameter(Mandatory)][ValidateSet("GET", "POST", "DELETE")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body = $null
    )

    $uri = "$Server$Path"

    if ($Method -eq "GET" -or $Method -eq "DELETE") {
        return Invoke-RestMethod -Method $Method -Uri $uri -Headers $Headers
    }

    $json = $null
    if ($null -ne $Body) {
        $json = ($Body | ConvertTo-Json -Depth 20)
    }

    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $Headers -ContentType "application/json" -Body $json
}

function Get-DeviceDebug {
    return Invoke-Api -Method GET -Path "/api/v1/admin/devices/$DeviceId/debug"
}

function Get-LastRunId {
    try {
        $d = Get-DeviceDebug
        if ($d.last_run -and $d.last_run.id) { return [string]$d.last_run.id }
        return $null
    }
    catch {
        Write-Warning "Failed to fetch debug bundle: $($_.Exception.Message)"
        return $null
    }
}

function New-EnrollToken {
    # Keep it simple: omit expires_at (server can default to null/never)
    $body = @{
        expires_at = $null
        note       = "installer-lifecycle-test"
    }

    $resp = Invoke-Api -Method POST -Path "/api/v1/admin/enroll-tokens" -Body $body
    if (-not $resp.enroll_token) { throw "Enroll token creation returned no enroll_token" }
    return [string]$resp.enroll_token
}

function Stop-TaskBestEffort([string]$Name) {
    try { Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue | Out-Null } catch { }
}

function Start-TaskBestEffort([string]$Name) {
    try { Start-ScheduledTask -TaskName $Name -ErrorAction Stop | Out-Null } catch {
        throw "Failed to start scheduled task '$Name': $($_.Exception.Message)"
    }
}

function Ensure-FileExists([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing $Label $Path"
    }
}

function Run-PwshFile {
    param(
        [Parameter(Mandatory)][string]$File,
        [string[]]$Args = @()
    )

    $pwsh = (Get-Command powershell.exe -ErrorAction Stop).Path
    $argLine = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $File) + $Args

    Write-Host ">> powershell.exe $($argLine -join ' ')"
    & $pwsh @argLine
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        throw "Script failed: $File (exit $code)"
    }
}

function Show-TaskAction([string]$Name) {
    $t = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    $a = $t.Actions | Select-Object -First 1

    Write-Host "== scheduled task action =="
    Write-Host ("Execute : {0}" -f $a.Execute)
    Write-Host ("Args    : {0}" -f $a.Arguments)
    Write-Host ("WorkDir : {0}" -f $a.WorkingDirectory)
}

function Assert-TaskHasArgs([string]$Name, [string[]]$MustContain) {
    $t = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    $a = $t.Actions | Select-Object -First 1
    $args = [string]($a.Arguments ?? "")

    foreach ($s in $MustContain) {
        if ($args -notmatch [regex]::Escape($s)) {
            throw "Scheduled task '$Name' missing required argument fragment: $s`nArgs: $args"
        }
    }
}

function Dump-LocalLogs {
    # Canonical install locations (NOT repo-relative)
    $logPath = Join-Path $env:ProgramData "Baseliner\logs\agent.log"
    $runnerDir = Join-Path $env:ProgramData "Baseliner\logs\runner"

    if (Test-Path -LiteralPath $logPath) {
        Write-Host "=== agent.log tail ==="
        Get-Content -LiteralPath $logPath -Tail 200
    }
    else {
        Write-Host "(no agent.log found at $logPath)"
    }

    if (Test-Path -LiteralPath $runnerDir) {
        Write-Host "=== runner logs (latest 3) ==="
        Get-ChildItem -LiteralPath $runnerDir -Filter "agent-*.out.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 3 |
        ForEach-Object {
            Write-Host ("--- {0} ---" -f $_.FullName)
            Get-Content -LiteralPath $_.FullName -Tail 200
        }
    }
    else {
        Write-Host "(no runner dir found at $runnerDir)"
    }
}

# ---- paths
$BundleDir = (Resolve-Path -LiteralPath $BundleDir).Path
$InstallScript = Join-Path $BundleDir "Install-BaselinerAgent.ps1"
$UninstallScript = Join-Path $BundleDir "Uninstall-BaselinerAgent.ps1"

Ensure-FileExists $InstallScript "Install script"
Ensure-FileExists $UninstallScript "Uninstall script"

Write-Host "== installer lifecycle test =="
Write-Host "server    : $Server"
Write-Host "device_id  : $DeviceId"
Write-Host "bundle_dir : $BundleDir"
Write-Host "task       : $TaskName"
Write-Host "run_for_s  : $RunForSeconds"
Write-Host "poll_s     : $PollSeconds"

# Avoid Mark-of-the-Web prompt on scripts
try {
    Get-ChildItem -Path $BundleDir -Recurse -Filter *.ps1 | Unblock-File -ErrorAction SilentlyContinue
}
catch { }

# 1) baseline run id
Write-Host "== baseline: capture last run id =="
$baselineRunId = Get-LastRunId
Write-Host ("baseline_run_id: {0}" -f ($baselineRunId ?? "<none>"))

# 2) uninstall existing (best-effort)
Write-Host "== uninstall existing agent (best-effort) =="
Stop-TaskBestEffort $TaskName
$uArgs = @()
if ($PurgeData) { $uArgs += "-PurgeData" }
try {
    Run-PwshFile -File $UninstallScript -Args $uArgs
}
catch {
    Write-Warning "Uninstall failed (continuing): $($_.Exception.Message)"
}

# 3) ensure we have an enroll token if needed
# If purge_data was used, token is gone and installer will require an enroll token.
if (-not $EnrollToken.Trim()) {
    # If not purging data, device might already be enrolled from prior run; installer will skip if token exists.
    # If purging data, we must enroll -> get token from server admin API.
    if ($PurgeData) {
        Write-Host "== creating enroll token (required because -PurgeData was used) =="
        $EnrollToken = New-EnrollToken
        Write-Host "[OK] enroll token created"
    }
}

# 4) install (do not auto-start task; we control start/stop)
Write-Host "== install agent from bundle =="
$iArgs = @(
    "-ServerUrl", $Server,
    "-DeviceKey", $env:COMPUTERNAME,
    "-Tags", $Tags,
    "-IntervalSeconds", "$IntervalSeconds",
    "-JitterSeconds", "$JitterSeconds",
    "-TaskName", $TaskName,
    "-RunAs", "SYSTEM",
    "-NoStart"
)

if ($EnrollToken.Trim()) {
    $iArgs += @("-EnrollToken", $EnrollToken)
}

Run-PwshFile -File $InstallScript -Args $iArgs

# 4b) verify task action matches wrapper expectations (fail-fast)
Show-TaskAction -Name $TaskName
Assert-TaskHasArgs -Name $TaskName -MustContain @(
    "baseliner-agent-run.ps1",
    "-Exe",
    "-Config",
    "-State",
    "-Server",
    "-LogDir"
)

# 5) start task, let it run, then stop best-effort
Write-Host "== start scheduled task '$TaskName' =="
Start-TaskBestEffort $TaskName

Write-Host "== let task run for $RunForSeconds seconds =="
Start-Sleep -Seconds $RunForSeconds

Write-Host "== stop scheduled task '$TaskName' (best-effort) =="
Stop-TaskBestEffort $TaskName

# 6) poll debug endpoint until new run appears
Write-Host "== poll debug endpoint for a NEW run =="
$deadline = (Get-Date).AddSeconds($PollSeconds)
$newRunId = $null

while ((Get-Date) -lt $deadline) {
    $rid = Get-LastRunId
    if ($rid -and ($rid -ne $baselineRunId)) {
        $newRunId = $rid
        break
    }

    Start-Sleep -Seconds $PollIntervalSeconds
}

if (-not $newRunId) {
    Write-Warning "No new run observed within timeout. Dumping latest debug bundle and local logs..."
    try {
        $dbg = Get-DeviceDebug
        $dbg | ConvertTo-Json -Depth 20 | Out-File -Encoding utf8 ".\device_debug_latest.json"
        Write-Host "Saved debug payload to: .\device_debug_latest.json"
    }
    catch { }

    Dump-LocalLogs

    throw "Timed out waiting for a new run to appear for device $DeviceId"
}

Write-Host "[OK] new run observed: $newRunId"

# 7) show log tails + run detail link
Write-Host "== local logs tail =="
Dump-LocalLogs

Write-Host "== run detail =="
Write-Host "$Server/api/v1/admin/runs/$newRunId"

if ($CleanupAtEnd) {
    Write-Host "== cleanup_at_end: uninstalling =="
    Stop-TaskBestEffort $TaskName
    $u2 = @()
    if ($PurgeData) { $u2 += "-PurgeData" }
    Run-PwshFile -File $UninstallScript -Args $u2
    Write-Host "[OK] cleanup complete"
}

Write-Host "[OK] installer lifecycle test complete"
