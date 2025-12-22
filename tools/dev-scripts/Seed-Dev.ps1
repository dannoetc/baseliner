<#
.SYNOPSIS
  Dev seeding helper for Baseliner (Issue #27).

.DESCRIPTION
  Wrapper around: python server/scripts/seed_dev.py

  Creates an enroll token (optional), upserts the sample policy, and (optionally) assigns it to a device by device_key.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory = $false)]
  [string]$Server = $(if ($env:BASELINER_SERVER_URL) { $env:BASELINER_SERVER_URL } else { "http://localhost:8000" }),

  [Parameter(Mandatory = $false)]
  [string]$AdminKey = $(if ($env:BASELINER_ADMIN_KEY) { $env:BASELINER_ADMIN_KEY } else { "" }),

  [Parameter(Mandatory = $false)]
  [string]$DeviceKey = "",

  [Parameter(Mandatory = $false)]
  [switch]$CreateToken,

  [Parameter(Mandatory = $false)]
  [int]$ExpiresHours = 24,

  [Parameter(Mandatory = $false)]
  [string]$PolicyFile = "policies/baseliner-windows-core.json",

  [Parameter(Mandatory = $false)]
  [string]$PolicyName = "baseliner-windows-core",

  [Parameter(Mandatory = $false)]
  [ValidateSet("enforce","audit")]
  [string]$Mode = "enforce",

  [Parameter(Mandatory = $false)]
  [int]$Priority = 9999,

  [Parameter(Mandatory = $false)]
  [string]$PythonPath = "python"
)

Set-StrictMode -Version Latest
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
$argsList = @("--server", $Server, "--admin-key", $AdminKey, "seed",
              "--policy-file", $PolicyFile,
              "--policy-name", $PolicyName,
              "--mode", $Mode,
              "--priority", "$Priority")

if ($CreateToken) {
  $argsList += @("--create-token", "--expires-hours", "$ExpiresHours")
}
if ($DeviceKey) {
  $argsList += @("--device-key", $DeviceKey)
}

Write-Host "== Baseliner dev seed ==" -ForegroundColor Cyan
Write-Host "Server     : $Server"
Write-Host "PolicyFile : $PolicyFile"
Write-Host "PolicyName : $PolicyName"
Write-Host "DeviceKey  : $(if ($DeviceKey) { $DeviceKey } else { '(none)' })"
Write-Host "CreateToken: $CreateToken"
Write-Host ""

& $PythonPath $scriptPath @argsList
