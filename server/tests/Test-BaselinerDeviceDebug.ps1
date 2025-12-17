[CmdletBinding()]
param(
  [string]$Server = "http://localhost:8000",
  [string]$AdminKey = "change-me-too",
  [Parameter(Mandatory)]
  [string]$DeviceId,                         # device UUID
  [string]$OutFile = ".\device_debug.json",
  [switch]$OpenOutFile
)

$ErrorActionPreference = "Stop"

function Invoke-BaselinerAdminJson {
  param(
    [Parameter(Mandatory)][string]$Method,
    [Parameter(Mandatory)][string]$Path
  )

  $uri = ($Server.TrimEnd("/") + $Path)

  $headers = @{
    "X-Admin-Key"  = $AdminKey
    "Accept"       = "application/json"
  }

  Write-Host "-> $Method $uri" -ForegroundColor Cyan
  return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers
}

# 1) call debug bundle
$debug = Invoke-BaselinerAdminJson -Method "GET" -Path "/api/v1/admin/devices/$DeviceId/debug"

# 2) save full json
$debug | ConvertTo-Json -Depth 50 | Out-File -Encoding utf8 $OutFile
Write-Host "Saved full payload to: $OutFile" -ForegroundColor Green
if ($OpenOutFile) { Invoke-Item $OutFile }

# 3) friendly summary
Write-Host ""
Write-Host "=== DEVICE ===" -ForegroundColor Yellow
Write-Host ("id:        {0}" -f $debug.device.id)
Write-Host ("device_key:{0}" -f $debug.device.device_key)
if ($debug.device.tags) { Write-Host ("tags:      {0}" -f ($debug.device.tags -join ", ")) }

Write-Host ""
Write-Host "=== ASSIGNMENTS (ordered) ===" -ForegroundColor Yellow
if (-not $debug.assignments -or $debug.assignments.Count -eq 0) {
  Write-Host "(none)"
} else {
  $debug.assignments |
    Select-Object `
      @{n="priority";e={$_.priority}},
      @{n="created_at";e={$_.created_at}},
      @{n="policy";e={$_.policy_name}},
      @{n="mode";e={$_.mode}},
      @{n="assignment_id";e={$_.assignment_id}} |
    Format-Table -AutoSize
}

Write-Host ""
Write-Host "=== EFFECTIVE POLICY ===" -ForegroundColor Yellow
Write-Host ("hash: {0}" -f $debug.effective_policy.effective_policy_hash)

$compile = $debug.effective_policy.compile
if ($compile -and $compile.resources) {
  Write-Host ("resources: {0}" -f $compile.resources.Count)
  Write-Host ("conflicts: {0}" -f (($compile.conflicts | Measure-Object).Count))
} else {
  Write-Host "compile metadata missing (check server build / endpoint response)"
}

Write-Host ""
Write-Host "=== LAST RUN ===" -ForegroundColor Yellow
if (-not $debug.last_run) {
  Write-Host "(no runs yet)"
} else {
  Write-Host ("run_id:     {0}" -f $debug.last_run.id)
  Write-Host ("started_at: {0}" -f $debug.last_run.started_at)
  Write-Host ("status:     {0}" -f $debug.last_run.status)
  if ($debug.last_run.detail_path) {
    Write-Host ("details:    {0}{1}" -f $Server.TrimEnd("/"), $debug.last_run.detail_path)
  }

  if ($debug.last_run_items) {
    Write-Host ""
    Write-Host "Last run items (first 25):" -ForegroundColor Yellow
    $debug.last_run_items |
      Select-Object -First 25 `
        @{n="type";e={$_.resource_type}},
        @{n="id";e={$_.resource_id}},
        @{n="state";e={$_.state}},
        @{n="result";e={$_.result}} |
      Format-Table -AutoSize
  }
}

# 4) extra: show top 10 conflicts (if any)
if ($compile -and $compile.conflicts -and $compile.conflicts.Count -gt 0) {
  Write-Host ""
  Write-Host "=== SAMPLE CONFLICTS (top 10) ===" -ForegroundColor Yellow
  $compile.conflicts |
    Select-Object -First 10 `
      @{n="key";e={$_.key}},
      @{n="winner_policy";e={$_.winner.policy_name}},
      @{n="loser_policy";e={$_.loser.policy_name}},
      @{n="reason";e={$_.reason}} |
    Format-Table -AutoSize
}
