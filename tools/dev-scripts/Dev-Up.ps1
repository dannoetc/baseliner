<#
.SYNOPSIS
  One-command dev up for Baseliner (Docker compose).

.DESCRIPTION
  Runs `docker compose up --build` from repo root.

  Tip: Windows may prompt about scripts downloaded from the internet.
  If needed, run: Unblock-File .\tools\dev-scripts\Dev-Up.ps1
#>

[CmdletBinding()]
param(
  [switch]$Detached
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path
Push-Location $repoRoot
try {
  $args = @('compose','up','--build')
  if ($Detached) { $args += '-d' }
  Write-Host "Running: docker $($args -join ' ')" -ForegroundColor Cyan
  docker @args
}
finally {
  Pop-Location
}
