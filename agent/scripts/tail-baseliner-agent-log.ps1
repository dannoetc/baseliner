param(
    [string]$LogFile = "C:\ProgramData\Baseliner\logs\agent.log",
    [int]$Tail = 80
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $LogFile)) {
    Write-Host "[WARN] Log file not found yet: $LogFile"
    Write-Host "       Waiting for it to appear..."
    while (-not (Test-Path $LogFile)) { Start-Sleep -Seconds 1 }
}

Write-Host "[OK] Tailing: $LogFile"
Get-Content -Path $LogFile -Tail $Tail -Wait
