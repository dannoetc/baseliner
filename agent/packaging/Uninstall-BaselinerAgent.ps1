[CmdletBinding()]
param(
    [string]$TaskName = "Baseliner Agent",

    # Remove ProgramData state/config/logs too.
    [switch]$PurgeData
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-IsAdministrator {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    throw "Uninstall must be run as Administrator."
}

$programFiles = [Environment]::GetFolderPath("ProgramFiles")
$programData = [Environment]::GetFolderPath("CommonApplicationData")

$InstallDir = Join-Path $programFiles "Baseliner"
$DataDir = Join-Path $programData  "Baseliner"

Write-Host "== Baseliner Agent uninstall =="
Write-Host "task : $TaskName"
Write-Host "purge: $($PurgeData.IsPresent)"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "== removing scheduled task =="
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch { }
    try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false } catch { }
}

if (Test-Path -LiteralPath $InstallDir) {
    Write-Host "== removing binaries =="
    try { Remove-Item -Recurse -Force -LiteralPath $InstallDir } catch { }
}

if ($PurgeData -and (Test-Path -LiteralPath $DataDir)) {
    Write-Host "== removing data =="
    try { Remove-Item -Recurse -Force -LiteralPath $DataDir } catch { }
}

Write-Host "[OK] done"
