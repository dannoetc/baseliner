[CmdletBinding()]
param(
    [string]$Server = "http://localhost:8000",
    [string]$AdminKey = "change-me-too",

    [Parameter(Mandatory)]
    [string]$DeviceId,

    [Parameter(Mandatory)]
    [string]$PolicyA,
    [Parameter(Mandatory)]
    [string]$PolicyB,

    [int]$Priority = 100,
    [string]$Mode = "enforce",
    [int]$PollSeconds = 1,
    [int]$MaxPolls = 15
)

$ErrorActionPreference = "Stop"

function Invoke-BaselinerAdminJson {
    param(
        [Parameter(Mandatory)][ValidateSet("GET", "POST", "DELETE")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body = $null
    )

    $uri = ($Server.TrimEnd("/") + $Path)
    $headers = @{
        "X-Admin-Key" = $AdminKey
        "Accept"      = "application/json"
    }

    if ($Body -ne $null) {
        $json = $Body | ConvertTo-Json -Depth 20
        return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -ContentType "application/json" -Body $json
    }

    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers
}

function Show-DebugSummary {
    param($dbg)

    Write-Host ""
    Write-Host "=== assignments (ordered) ===" -ForegroundColor Yellow
    if (-not $dbg.assignments) { Write-Host "(none)" }
    else {
        $dbg.assignments |
        Select-Object priority, created_at, policy_name, mode, assignment_id |
        Format-Table -AutoSize
    }

    $compile = $dbg.effective_policy.compile
    Write-Host ""
    Write-Host "=== compile ===" -ForegroundColor Yellow
    Write-Host ("hash:      {0}" -f $dbg.effective_policy.effective_policy_hash)
    Write-Host ("resources: {0}" -f (($compile.resources | Measure-Object).Count))
    Write-Host ("conflicts: {0}" -f (($compile.conflicts | Measure-Object).Count))

    if ($compile.conflicts -and $compile.conflicts.Count -gt 0) {
        Write-Host ""
        Write-Host "Top conflicts:" -ForegroundColor Yellow
        $compile.conflicts |
        Select-Object -First 10 key,
        @{n = "winner_policy"; e = { $_.winner.policy_name } },
        @{n = "loser_policy"; e = { $_.loser.policy_name } },
        reason |
        Format-Table -AutoSize
    }

    if ($compile.resources -and $compile.resources.Count -gt 0) {
        $r0 = $compile.resources[0]
        Write-Host ""
        Write-Host "First effective resource source:" -ForegroundColor Yellow
        Write-Host ("key:    {0}" -f $r0.key)
        Write-Host ("source: {0} (assignment {1}, priority {2})" -f $r0.source.policy_name, $r0.source.assignment_id, $r0.source.priority)
    }
}

Write-Host "== clearing assignments for device $DeviceId ==" -ForegroundColor Cyan
Invoke-BaselinerAdminJson -Method "DELETE" -Path "/api/v1/admin/devices/$DeviceId/assignments" | Out-Null

Write-Host "== creating assignment A (same priority) ==" -ForegroundColor Cyan
Invoke-BaselinerAdminJson -Method "POST" -Path "/api/v1/admin/assign-policy" -Body @{
    device_id   = $DeviceId
    policy_name = $PolicyA
    priority    = $Priority
    mode        = $Mode
} | Out-Null

Start-Sleep -Milliseconds 250

Write-Host "== creating assignment B (same priority) ==" -ForegroundColor Cyan
Invoke-BaselinerAdminJson -Method "POST" -Path "/api/v1/admin/assign-policy" -Body @{
    device_id   = $DeviceId
    policy_name = $PolicyB
    priority    = $Priority
    mode        = $Mode
} | Out-Null

Write-Host "== polling debug endpoint ==" -ForegroundColor Cyan
for ($i = 1; $i -le $MaxPolls; $i++) {
    $dbg = Invoke-BaselinerAdminJson -Method "GET" -Path "/api/v1/admin/devices/$DeviceId/debug"
    $hash = $dbg.effective_policy.effective_policy_hash

    if ($hash) {
        Write-Host ("poll {0}/{1}: hash {2}" -f $i, $MaxPolls, $hash) -ForegroundColor Green
        Show-DebugSummary $dbg
        break
    }

    Write-Host ("poll {0}/{1}: no hash yet" -f $i, $MaxPolls) -ForegroundColor DarkGray
    Start-Sleep -Seconds $PollSeconds
}
