[CmdletBinding()]
param(
    [string]$Server = "http://localhost:8000",
    [string]$AdminKey = "change-me-too",
    [string]$DeviceId = "7a912a9e-acda-4100-b755-2a77fe523e33",
    [string]$PolicyName = "test-ps-timeout",
    [int]$TimeoutSeconds = 10,
    [int]$PollSeconds = 2,
    [int]$PollMax = 45
)

$ErrorActionPreference = "Stop"

$Headers = @{
    "X-Admin-Key" = $AdminKey
    "Accept"      = "application/json"
}

function Get-Json($Path) {
    Invoke-RestMethod -Method GET -Uri "$Server$Path" -Headers $Headers
}

function Post-Json($Path, $BodyObj) {
    Invoke-RestMethod -Method POST -Uri "$Server$Path" -Headers $Headers -ContentType "application/json" -Body ($BodyObj | ConvertTo-Json -Depth 30)
}

Write-Host "== baseline: capture last run id =="
$baseline = Get-Json "/api/v1/admin/devices/$DeviceId/debug"
$baselineRunId = $baseline.last_run.id
Write-Host "baseline run: $baselineRunId"

Write-Host "== clear assignments =="
Invoke-RestMethod -Method DELETE -Uri "$Server/api/v1/admin/devices/$DeviceId/assignments" -Headers $Headers | Out-Null

Write-Host "== upsert timeout policy ($PolicyName) =="
# Detect always fails quickly; remediate sleeps longer than timeout_seconds; validate fails.
$Policy = @{
    name           = $PolicyName
    description    = "script.powershell timeout validation (remediate sleeps past timeout)"
    schema_version = "1.0"
    is_active      = $true
    document       = @{
        resources = @(
            @{
                type            = "script.powershell"
                id              = "ps-timeout"
                name            = "powershell timeout test"
                timeout_seconds = $TimeoutSeconds

                detect          = 'Write-Output "detect: failing"; exit 1'
                remediate       = "Write-Output `"remediate: sleeping...`"; Start-Sleep -Seconds $($TimeoutSeconds + 20); Write-Output `"remediate: done`"; exit 0"
            }
        )
    }
}

Post-Json "/api/v1/admin/policies" $Policy | Out-Null

Write-Host "== assign policy to device (priority=100 mode=enforce) =="
Post-Json "/api/v1/admin/assign-policy" @{
    device_id   = $DeviceId
    policy_name = $PolicyName
    priority    = 100
    mode        = "enforce"
} | Out-Null

Write-Host "== start scheduled task 'Baseliner Agent' =="
Start-ScheduledTask -TaskName "Baseliner Agent"

Write-Host "== let task run for 30 seconds =="
Start-Sleep -Seconds 30

Write-Host "== stop scheduled task 'Baseliner Agent' (best-effort) =="
try { Stop-ScheduledTask -TaskName "Baseliner Agent" } catch { }

Write-Host "== poll debug endpoint for a NEW run =="
$newRunId = $null
for ($i = 1; $i -le $PollMax; $i++) {
    $dbg = Get-Json "/api/v1/admin/devices/$DeviceId/debug"
    $rid = $dbg.last_run.id
    if ($rid -and $rid -ne $baselineRunId) {
        $newRunId = $rid
        Write-Host "poll $i/$PollMax new run $newRunId"
        break
    }
    Write-Host "poll $i/$PollMax still $rid"
    Start-Sleep -Seconds $PollSeconds
}

if (-not $newRunId) {
    throw "Did not observe a new run within polling window."
}

Write-Host "== fetch run detail =="
$run = Get-Json "/api/v1/admin/runs/$newRunId"

$item = $run.items | Select-Object -First 1

Write-Host ""
Write-Host "=== RESULT ==="
Write-Host "run_id: $($run.id)"
Write-Host "run_status: $($run.status)"
Write-Host "item.status_detect: $($item.status_detect)"
Write-Host "item.status_remediate: $($item.status_remediate)"
Write-Host "item.status_validate: $($item.status_validate)"
Write-Host "item.error.type: $($item.error.type)"
Write-Host "item.error.message: $($item.error.message)"

Write-Host ""
Write-Host "Evidence (remediate exit code, expect 124):"
Write-Host "detect.exit_code:    $($item.evidence.detect.exit_code)"
Write-Host "remediate.exit_code: $($item.evidence.remediate.exit_code)"
Write-Host "validate.exit_code:  $($item.evidence.validate.exit_code)"
