<# 
.SYNOPSIS
  Dev helper for Baseliner (Issue #27).

.DESCRIPTION
  Wrapper around: python server/scripts/seed_dev.py

  Defaults to running the "seed" command, but can also drive lifecycle + audit helpers.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory = $false)]
  [string]$Server = $(if ($env:BASELINER_SERVER_URL) { $env:BASELINER_SERVER_URL } else { "http://localhost:8000" }),

  [Parameter(Mandatory = $false)]
  [string]$AdminKey = $(if ($env:BASELINER_ADMIN_KEY) { $env:BASELINER_ADMIN_KEY } else { "" }),

  [Parameter(Mandatory = $false)]
  [ValidateSet("seed","create-enroll-token","upsert-policy","assign-policy","restore-device","revoke-device-token","audit")]
  [string]$Command = "seed",

  # Common / seed args
  [Parameter(Mandatory = $false)]
  [string]$DeviceKey = "",

  [Parameter(Mandatory = $false)]
  [switch]$CreateToken,

  [Parameter(Mandatory = $false)]
  [int]$ExpiresHours = 24,

  [Parameter(Mandatory = $false)]
  [string]$ExpiresAt = "",

  [Parameter(Mandatory = $false)]
  [string]$Note = "dev token",

  [Parameter(Mandatory = $false)]
  [string]$PolicyFile = "policies/baseliner-windows-core.json",

  [Parameter(Mandatory = $false)]
  [string]$PolicyName = "baseliner-windows-core",

  [Parameter(Mandatory = $false)]
  [ValidateSet("enforce","audit")]
  [string]$Mode = "enforce",

  [Parameter(Mandatory = $false)]
  [int]$Priority = 9999,

  # Lifecycle args
  [Parameter(Mandatory = $false)]
  [string]$DeviceId = "",

  # Audit args
  [Parameter(Mandatory = $false)]
  [int]$Limit = 20,

  [Parameter(Mandatory = $false)]
  [string]$Cursor = "",

  [Parameter(Mandatory = $false)]
  [string]$Action = "",

  [Parameter(Mandatory = $false)]
  [string]$TargetType = "",

  [Parameter(Mandatory = $false)]
  [string]$TargetId = "",

  [Parameter(Mandatory = $false)]
  [string]$PythonPath = "python"
)

$ErrorActionPreference = "Stop"

if (-not $AdminKey) {
  throw "AdminKey is required. Pass -AdminKey or set env BASELINER_ADMIN_KEY."
}

# Ensure env is set for the underlying script
$env:BASELINER_ADMIN_KEY = $AdminKey
$env:BASELINER_SERVER_URL = $Server

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path
$scriptPath = Join-Path $repoRoot "server\scripts\seed_dev.py"

if (-not (Test-Path -LiteralPath $scriptPath)) {
  throw "seed_dev.py not found at: $scriptPath (are you running this from tools/dev-scripts/?)"
}

# IMPORTANT: argparse expects global args before the subcommand.
$argsList = @("--server", $Server, "--admin-key", $AdminKey, $Command)

switch ($Command) {
  "seed" {
    $argsList += @("--policy-file", $PolicyFile,
                   "--policy-name", $PolicyName,
                   "--mode", $Mode,
                   "--priority", "$Priority")
    if ($CreateToken) {
      $argsList += @("--create-token")
      if ($ExpiresAt) {
        $argsList += @("--expires-at", $ExpiresAt)
      } else {
        $argsList += @("--expires-hours", "$ExpiresHours")
      }
      if ($Note) {
        $argsList += @("--note", $Note)
      }
    }
    if ($DeviceKey) {
      $argsList += @("--device-key", $DeviceKey)
    }

    Write-Host "== Baseliner seed ==" -ForegroundColor Cyan
    Write-Host "Server     : $Server"
    Write-Host "PolicyFile : $PolicyFile"
    Write-Host "PolicyName : $PolicyName"
    Write-Host "DeviceKey  : $(if ($DeviceKey) { $DeviceKey } else { '(none)' })"
    Write-Host "CreateToken: $CreateToken"
  }

  "create-enroll-token" {
    if ($ExpiresAt) {
      $argsList += @("--expires-at", $ExpiresAt)
    } else {
      $argsList += @("--expires-hours", "$ExpiresHours")
    }
    if ($Note) {
      $argsList += @("--note", $Note)
    }
  }

  "upsert-policy" {
    $argsList += @("--file", $PolicyFile)
  }

  "assign-policy" {
    if (-not $DeviceKey) { throw "DeviceKey is required for assign-policy." }
    $argsList += @("--device-key", $DeviceKey,
                   "--policy-name", $PolicyName,
                   "--mode", $Mode,
                   "--priority", "$Priority")
  }

  "restore-device" {
    if (-not $DeviceId) { throw "DeviceId is required for restore-device." }
    $argsList += @("--device-id", $DeviceId)
  }

  "revoke-device-token" {
    if (-not $DeviceId) { throw "DeviceId is required for revoke-device-token." }
    $argsList += @("--device-id", $DeviceId)
  }

  "audit" {
    $argsList += @("--limit", "$Limit")
    if ($Cursor) { $argsList += @("--cursor", $Cursor) }
    if ($Action) { $argsList += @("--action", $Action) }
    if ($TargetType) { $argsList += @("--target-type", $TargetType) }
    if ($TargetId) { $argsList += @("--target-id", $TargetId) }
  }
}

Write-Host ""
& $PythonPath $scriptPath @argsList
