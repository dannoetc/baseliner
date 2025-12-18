[CmdletBinding()]
param(
    [string]$TaskName = "Baseliner Agent",
    [int]$WaitSeconds = 5,
    [int]$TailLines = 120
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Try-GetActionArgValue {
    param(
        [Parameter(Mandatory)][string]$Arguments,
        [Parameter(Mandatory)][string]$Key
    )
    # Matches: -Key "value"  OR  -Key value
    $re = [regex]::new("(?:^|\s)-$([regex]::Escape($Key))\s+(?:""([^""]+)""|(\S+))", "IgnoreCase")
    $m = $re.Match($Arguments)
    if (-not $m.Success) { return $null }
    if ($m.Groups[2].Success) { return $m.Groups[2].Value }
    if ($m.Groups[3].Success) { return $m.Groups[3].Value }
    return $null
}

function Tail-File([string]$Path, [int]$Lines) {
    if (Test-Path -LiteralPath $Path) {
        Write-Host "== tail: $Path =="
        Get-Content -LiteralPath $Path -Tail $Lines
    }
    else {
        Write-Warning "File not found: $Path"
    }
}

Start-ScheduledTask -TaskName $TaskName
Write-Host "[OK] Started: $TaskName"

Start-Sleep -Seconds $WaitSeconds

$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Host "LastRunTime    : $($info.LastRunTime)"
Write-Host "LastTaskResult : $($info.LastTaskResult)"
Write-Host "NextRunTime    : $($info.NextRunTime)"

$action = $task.Actions | Select-Object -First 1
Write-Host "Execute        : $($action.Execute)"
Write-Host "Arguments      : $($action.Arguments)"

$runnerPath = $null
$logPath = $null
if ($action.Arguments) {
    $runnerPath = Try-GetActionArgValue -Arguments $action.Arguments -Key "File"
    $logPath = Try-GetActionArgValue -Arguments $action.Arguments -Key "Log"
}

if ($runnerPath) {
    Write-Host "Runner         : $runnerPath"
    Tail-File -Path $runnerPath -Lines 80
}
else {
    Write-Warning "Could not parse runner path (-File ...) from task action arguments."
}

if ($logPath) {
    Tail-File -Path $logPath -Lines $TailLines
}
else {
    Write-Warning "Could not parse log path (-Log ...) from task action arguments."
}

# Task Scheduler operational events (often shows why exit code was 1)
try {
    $startTime = (Get-Date).AddMinutes(-10)
    $ev = Get-WinEvent -FilterHashtable @{
        LogName   = "Microsoft-Windows-TaskScheduler/Operational"
        StartTime = $startTime
    } -ErrorAction Stop | Where-Object {
        $_.Message -match [regex]::Escape($TaskName)
    } | Select-Object -First 15

    if ($ev) {
        Write-Host "== recent task scheduler events (last ~10 min) =="
        foreach ($e in $ev) {
            Write-Host ("[{0}] {1}" -f $e.TimeCreated.ToString("s"), ($e.Message -replace "\s+", " ").Trim())
        }
    }
}
catch {
    Write-Warning "Could not read TaskScheduler/Operational log (may be disabled): $($_.Exception.Message)"
}
