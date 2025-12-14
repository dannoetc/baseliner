# Requires: Run as Administrator
# Uninstalls the Baseliner Agent scheduled task.

param(
    [string]$TaskName = "Baseliner Agent"
)

$ErrorActionPreference = "Stop"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "[OK] Task not found: $TaskName"
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] Uninstalled Scheduled Task: $TaskName"
