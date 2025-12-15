[CmdletBinding()]
param(
    [string]$Server = "http://localhost:8000",
    [string]$StateDir = "C:\ProgramData\Baseliner",
    [string]$Config = "C:\ProgramData\Baseliner\agent.toml",
    [string]$AdminKey = $env:BASELINER_ADMIN_KEY
)

$ErrorActionPreference = "Stop"

function Get-DeviceToken {
    $script = Join-Path $PSScriptRoot "get-baseliner-device-token.ps1"
    if (-not (Test-Path $script)) { throw "missing helper: $script" }
    return & $script
}

function Get-DeviceIdFromState {
    $statePath = Join-Path $StateDir "state.json"
    if (-not (Test-Path $statePath)) { return $null }
    try { return ((Get-Content $statePath -Raw | ConvertFrom-Json).device_id) } catch { return $null }
}

function Pause { Read-Host "enter to continue" | Out-Null }

while ($true) {
    Clear-Host
    Write-Host "baseliner quick tester" -ForegroundColor Cyan
    Write-Host "server : $Server"
    Write-Host "state  : $StateDir"
    Write-Host "config : $Config"
    Write-Host ""

    Write-Host "1) show local state.json"
    Write-Host "2) show device policy (decrypt local device token)"
    Write-Host "3) run agent run-once locally (current console)"
    Write-Host "4) list latest runs for this device (admin key required)"
    Write-Host "5) show latest run items + evidence (admin key required)"
    Write-Host "q) quit"
    $c = Read-Host ">"

    if ($c -eq "q") { break }

    if ($c -eq "1") {
        $p = Join-Path $StateDir "state.json"
        if (Test-Path $p) { Get-Content $p -Raw } else { "no state.json at $p" }
        Pause; continue
    }

    if ($c -eq "2") {
        $tok = Get-DeviceToken
        curl.exe -s "$Server/api/v1/device/policy" -H "Authorization: Bearer $tok" | ConvertFrom-Json | ConvertTo-Json -Depth 50
        Pause; continue
    }

    if ($c -eq "3") {
        $py = Join-Path $StateDir "venv\Scripts\python.exe"
        if (-not (Test-Path $py)) { throw "missing python venv: $py" }
        & $py -m baseliner_agent --config $Config --state-dir $StateDir run-once --force
        Pause; continue
    }

    if ($c -eq "4") {
        if (-not $AdminKey) { throw "set -AdminKey or $env:BASELINER_ADMIN_KEY" }
        $did = Get-DeviceIdFromState
        if (-not $did) { throw "could not read device_id from $StateDir\state.json" }
        $runs = curl.exe -s "$Server/api/v1/admin/runs?device_id=$did&limit=10" -H "X-Admin-Key: $AdminKey" | ConvertFrom-Json
        $runs.items | Select-Object id, started_at, status, agent_version | Format-Table -AutoSize
        Pause; continue
    }

    if ($c -eq "5") {
        if (-not $AdminKey) { throw "set -AdminKey or $env:BASELINER_ADMIN_KEY" }
        $did = Get-DeviceIdFromState
        if (-not $did) { throw "could not read device_id from $StateDir\state.json" }

        $runs = curl.exe -s "$Server/api/v1/admin/runs?device_id=$did&limit=1" -H "X-Admin-Key: $AdminKey" | ConvertFrom-Json
        $rid = $runs.items[0].id
        $run = curl.exe -s "$Server/api/v1/admin/runs/$rid" -H "X-Admin-Key: $AdminKey" | ConvertFrom-Json

        $run.items | Sort-Object ordinal | Format-Table ordinal, resource_type, resource_id, status_detect, status_remediate, status_validate, changed -AutoSize

        "`n---- evidence (winget.package detect) ----"
        ($run.items | Where-Object resource_type -eq "winget.package").evidence.detect | ConvertTo-Json -Depth 6

        Pause; continue
    }
}
