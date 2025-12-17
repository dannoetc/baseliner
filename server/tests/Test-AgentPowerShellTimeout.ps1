[CmdletBinding()]
param(
    [string]$Server = "http://localhost:8000",
    [string]$AdminKey = "change-me-too",

    [Parameter(Mandatory)]
    [string]$DeviceId,

    [string]$PolicyName = "test-ps-timeout",
    [int]$Priority = 100,
    [string]$Mode = "enforce",

    [int]$RemediateTimeoutSeconds = 10,

    # NEW: use scheduled task instead of calling the agent directly
    [string]$TaskName = "Baseliner Agent",
    [int]$TaskRunSeconds = 30,

    [int]$PollSeconds = 1,
    [int]$MaxPolls = 45
)

$ErrorActionPreference = "Stop"

$Headers = @{
    "X-Admin-Key" = $AdminKey
    "Accept"      = "application/json"
}

function Get-Debug {
    Invoke-RestMethod -Method GET -Uri "$Server/api/v1/admin/devices/$DeviceId/debug" -Headers $Headers
}

function Upsert-Policy($policyObj) {
    Invoke-RestMethod -Method POST `
        -Uri "$Server/api/v1/admin/policies" `
        -Headers $Headers `
        -ContentType "application/json" `
        -Body ($policyObj | ConvertTo-Json -Depth 20) | Out-Null
}

function Assign-Policy([string]$name) {
    Invoke-RestMethod -Method POST `
        -Uri "$Server/api/v1/admin/assign-policy" `
        -Headers $Headers `
        -ContentType "application/json" `
        -Body (@{
            device_id   = $DeviceId
            policy_name = $name
            priority    = $Priority
            mode        = $Mode
        } | ConvertTo-Json) | Out-Null
}

function Start-AgentTask {
    param([string]$Name)
    try {
        Start-ScheduledTask -TaskName $Name | Out-Null
        return
    }
    catch {
        # fallback
        schtasks /Run /TN $Name | Out-Null
    }
}

function Stop-AgentTask {
    param([string]$Name)
    try {
        Stop-ScheduledTask -TaskName $Name | Out-Null
        return
    }
    catch {
        # fallback
        schtasks /End /TN $Name | Out-Null
    }
}

Write-Host "== baseline: capture last run id ==" -ForegroundColor Cyan
$before = Get-Debug
$beforeRunId = $before.last_run.id

Write-Host "== clear assignments ==" -ForegroundColor Cyan
Invoke-RestMethod -Method DELETE -Uri "$Server/api/v1/admin/devices/$DeviceId/assignments" -Headers $Headers | Out-Null

Write-Host "== upsert timeout policy ($PolicyName) ==" -ForegroundColor Cyan
$Policy = @{
    name           = $PolicyName
    description    = "agent timeout test (script.powershell remediate sleep)"
    schema_version = "1.0"
    is_active      = $true
    document       = @{
        resources = @(
            @{
                type            = "script.powershell"
                id              = "pshang"
                name            = "powershell remediation timeout test"
                detect          = "exit 1"
                remediate       = "Start-Sleep -Seconds 9999; exit 0"
                timeout_seconds = $RemediateTimeoutSeconds
            }
        )
    }
}
Upsert-Policy $Policy

Write-Host "== assign policy to device (priority=$Priority mode=$Mode) ==" -ForegroundColor Cyan
Assign-Policy $PolicyName

Write-Host "== start scheduled task '$TaskName' ==" -ForegroundColor Cyan
Start-AgentTask -Name $TaskName

Write-Host "== let task run for $TaskRunSeconds seconds ==" -ForegroundColor Cyan
Start-Sleep -Seconds $TaskRunSeconds

Write-Host "== stop scheduled task '$TaskName' (best-effort) ==" -ForegroundColor Cyan
Stop-AgentTask -Name $TaskName

Write-Host "== poll debug endpoint for a NEW run ==" -ForegroundColor Cyan
$runId = $null
for ($i = 1; $i -le $MaxPolls; $i++) {
    $dbg = Get-Debug
    $rid = $dbg.last_run.id

    if ($rid -and $rid -ne $beforeRunId) {
        $runId = $rid
        Write-Host ("poll {0}/{1}: new run {2}" -f $i, $MaxPolls, $runId) -ForegroundColor Green
        break
    }

    Write-Host ("poll {0}/{1}: no new run yet" -f $i, $MaxPolls) -ForegroundColor DarkGray
    Start-Sleep -Seconds $PollSeconds
}

if (-not $runId) {
    throw "Timed out waiting for a new run. Check agent task history + server logs."
}

Write-Host "== fetch run detail ==" -ForegroundColor Cyan
$run = Invoke-RestMethod -Method GET -Uri "$Server/api/v1/admin/runs/$runId" -Headers $Headers

$item = $run.items | Where-Object { $_.resource_type -eq "script.powershell" -and $_.resource_id -eq "pshang" } | Select-Object -First 1
if (-not $item) {
    throw "Run $runId did not include expected run item script.powershell/pshang"
}

Write-Host ""
Write-Host "=== RESULT ===" -ForegroundColor Yellow
Write-Host ("run_id: {0}" -f $runId)
Write-Host ("run_status: {0}" -f $run.status)
Write-Host ("item.status_detect: {0}" -f $item.status_detect)
Write-Host ("item.status_remediate: {0}" -f $item.status_remediate)
Write-Host ("item.status_validate: {0}" -f $item.status_validate)

$errType = $item.error.type
$errMsg = $item.error.message
Write-Host ("item.error.type: {0}" -f $errType)
Write-Host ("item.error.message: {0}" -f $errMsg)

if ($errType -ne "timeout") {
    Write-Host "[WARN] Expected item.error.type = timeout" -ForegroundColor Yellow
}
else {
    Write-Host "[OK] Timeout surfaced and run still posted." -ForegroundColor Green
}

Write-Host ""
Write-Host "Evidence (remediate exit code, expect 124):" -ForegroundColor Yellow
Write-Host ("detect.exit_code:    {0}" -f $item.evidence.detect.exit_code)
Write-Host ("remediate.exit_code: {0}" -f $item.evidence.remediate.exit_code)
Write-Host ("validate.exit_code:  {0}" -f $item.evidence.validate.exit_code)
