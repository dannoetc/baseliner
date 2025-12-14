param(
    [string]$TaskName = "Baseliner Agent"
)

$ErrorActionPreference = "Stop"

Start-ScheduledTask -TaskName $TaskName
Write-Host "[OK] Started: $TaskName"
