<#
.SYNOPSIS
  One-command dev/prod-ish up with Nginx + Let's Encrypt for Baseliner.

.DESCRIPTION
  Runs docker compose with the TLS override file and the required env vars.

  You MUST provide a real domain that resolves to this host and has ports 80/443 reachable.
  (Let's Encrypt HTTP-01 validation needs inbound port 80.)

.EXAMPLE
  .\tools\dev-scripts\Dev-UpTls.ps1 -Domain "api.example.com" -Email "admin@example.com"
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$Domain,

  [Parameter(Mandatory = $true)]
  [string]$Email,

  [Parameter(Mandatory = $false)]
  [string]$ComposeFile = "docker-compose.nginx-certbot.yml",

  [switch]$Detached
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..") | Select-Object -ExpandProperty Path

$env:BASELINER_DOMAIN = $Domain
$env:CERTBOT_EMAIL = $Email

Push-Location $repoRoot
try {
  $args = @('compose','-f','docker-compose.yml','-f',$ComposeFile,'up','--build')
  if ($Detached) { $args += '-d' }
  Write-Host "BASELINER_DOMAIN=$Domain" -ForegroundColor Cyan
  Write-Host "CERTBOT_EMAIL=$Email" -ForegroundColor Cyan
  Write-Host "Running: docker $($args -join ' ')" -ForegroundColor Cyan
  docker @args
}
finally {
  Pop-Location
}
