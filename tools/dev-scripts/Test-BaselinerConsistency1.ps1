<# 
.SYNOPSIS
  Baseliner correlation-id sanity test.

.DESCRIPTION
  Verifies:
   1) Server echoes X-Correlation-ID on responses (middleware wiring)
   2) Device report submission stores correlation_id on the created run
   3) Admin run detail returns correlation_id for that run

  Supports decrypting a device token stored with DPAPI using:
    ConvertFrom-SecureString | Set-Content token.txt
  or a raw DPAPI-protected Base64 blob.

.EXAMPLE
  # Token passed directly
  .\Test-BaselinerCorrelation.ps1 -Server http://localhost:8000 -AdminKey change-me-too -DeviceToken $env:BASELINER_DEVICE_TOKEN

.EXAMPLE
  # Token stored via DPAPI:
  #   $token | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString | Set-Content .\device_token.dpapi
  .\Test-BaselinerCorrelation.ps1 -Server http://localhost:8000 -AdminKey change-me-too -DeviceTokenPath .\device_token.dpapi
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Server = "http://localhost:8000",

    [Parameter(Mandatory = $false)]
    [string]$AdminKey = "change-me-too",

    # Provide either -DeviceToken OR -DeviceTokenPath (DPAPI encrypted)
    [Parameter(Mandatory = $false)]
    [string]$DeviceToken,

    [Parameter(Mandatory = $false)]
    [string]$DeviceTokenPath,

    # Optional: If your DPAPI blob was protected with LocalMachine scope instead of CurrentUser
    [ValidateSet("CurrentUser", "LocalMachine")]
    [string]$DpapiScope = "CurrentUser",

    # Optional: override correlation id prefix (script will append a guid)
    [string]$CorrelationPrefix = "ps",

    # If set, prints the raw HTTP response bodies too
    [switch]$ShowBodies
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-HeaderValue {
    param(
        [Parameter(Mandatory = $true)]$Headers,
        [Parameter(Mandatory = $true)][string]$Name
    )

    # Invoke-WebRequest returns different header types across PS versions.
    try {
        if ($null -eq $Headers) { return $null }

        if ($Headers -is [System.Collections.IDictionary]) {
            return $Headers[$Name]
        }

        # WebHeaderCollection / HttpResponseHeaders
        if ($Headers.PSObject.Methods.Name -contains "Get") {
            return $Headers.Get($Name)
        }

        if ($Headers.PSObject.Properties.Name -contains $Name) {
            return $Headers.$Name
        }

        return $null
    }
    catch {
        return $null
    }
}

function SecureStringToPlainText {
    param([Parameter(Mandatory = $true)][Security.SecureString]$Secure)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Read-DeviceTokenFromDpapiFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateSet("CurrentUser", "LocalMachine")]
        [string]$Scope = "CurrentUser"
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "DeviceTokenPath not found: $Path"
    }

    $raw = (Get-Content -LiteralPath $Path -Raw).Trim()
    if (-not $raw) { throw "DeviceTokenPath file is empty: $Path" }

    # Attempt 1: ConvertFrom-SecureString format
    try {
        $ss = ConvertTo-SecureString -String $raw
        $pt = SecureStringToPlainText -Secure $ss
        if ($pt -and $pt.Trim().Length -gt 0) { return $pt.Trim() }
    }
    catch {
        # fall through
    }

    # Attempt 2: Raw DPAPI Base64 blob (ProtectedData)
    try {
        $bytes = [Convert]::FromBase64String($raw)
        $dpScope = if ($Scope -eq "LocalMachine") {
            [System.Security.Cryptography.DataProtectionScope]::LocalMachine
        }
        else {
            [System.Security.Cryptography.DataProtectionScope]::CurrentUser
        }
        $plainBytes = [System.Security.Cryptography.ProtectedData]::Unprotect($bytes, $null, $dpScope)
        $pt2 = [Text.Encoding]::UTF8.GetString($plainBytes)
        if ($pt2 -and $pt2.Trim().Length -gt 0) { return $pt2.Trim() }
    }
    catch {
        # fall through
    }

    throw "Failed to decrypt device token at $Path. Expected ConvertFrom-SecureString output or DPAPI Base64 blob."
}

function Invoke-Baseliner {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "DELETE")]
        [string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $false)][hashtable]$Headers = @{},
        [Parameter(Mandatory = $false)]$BodyObject
    )

    $iwrParams = @{
        Method  = $Method
        Uri     = $Url
        Headers = $Headers
    }

    if ($null -ne $BodyObject) {
        $json = $BodyObject | ConvertTo-Json -Depth 20
        $iwrParams["Body"] = $json
        $iwrParams["ContentType"] = "application/json"
    }

    if ($PSVersionTable.PSVersion.Major -lt 6) {
        # Windows PowerShell compatibility
        $iwrParams["UseBasicParsing"] = $true
    }

    return Invoke-WebRequest @iwrParams
}

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if ($Actual -ne $Expected) {
        throw "$Message`nExpected: $Expected`nActual:   $Actual"
    }
}

# Resolve device token
if (-not $DeviceToken) {
    if ($DeviceTokenPath) {
        $DeviceToken = Read-DeviceTokenFromDpapiFile -Path $DeviceTokenPath -Scope $DpapiScope
    }
    elseif ($env:BASELINER_DEVICE_TOKEN) {
        $DeviceToken = $env:BASELINER_DEVICE_TOKEN
    }
}

if (-not $DeviceToken) {
    throw "No device token provided. Use -DeviceToken, -DeviceTokenPath, or set BASELINER_DEVICE_TOKEN."
}

$Server = $Server.TrimEnd("/")

$guid = ([Guid]::NewGuid().ToString("N"))
$cidHealth = "$CorrelationPrefix-health-$guid"
$cidReport = "$CorrelationPrefix-report-$guid"
$cidAdmin = "$CorrelationPrefix-admin-$guid"

Write-Host "== Baseliner Correlation-ID Test ==" -ForegroundColor Cyan
Write-Host "Server: $Server"
Write-Host "CID health: $cidHealth"
Write-Host "CID report: $cidReport"
Write-Host "CID admin : $cidAdmin"
Write-Host ""

# 1) Health check echoes correlation id
Write-Host "[1/3] GET /health (echo X-Correlation-ID)" -ForegroundColor Yellow
$respHealth = Invoke-Baseliner -Method GET -Url "$Server/health" -Headers @{ "X-Correlation-ID" = $cidHealth }
$echoHealth = Get-HeaderValue -Headers $respHealth.Headers -Name "X-Correlation-ID"
Assert-Equal -Actual $echoHealth -Expected $cidHealth -Message "Health endpoint did not echo X-Correlation-ID"
Write-Host "  OK: echoed X-Correlation-ID = $echoHealth"

if ($ShowBodies) {
    Write-Host "  Body: $($respHealth.Content)"
}

Write-Host ""

# 2) Submit a device report with known correlation id
Write-Host "[2/3] POST /api/v1/device/reports (persist correlation_id on run)" -ForegroundColor Yellow

$now = (Get-Date).ToUniversalTime()
$reportBody = @{
    started_at            = $now.ToString("o")
    ended_at              = $now.AddSeconds(2).ToString("o")
    status                = "success"
    agent_version         = "ps-correlation-test"
    effective_policy_hash = "ps-test"
    policy_snapshot       = @{
        policy_id             = "ps-test"
        policy_name           = "ps-test"
        schema_version        = "1"
        effective_policy_hash = "ps-test"
    }
    summary               = @{
        duration_ms = 2000
        note        = "powershell test report"
    }
    items                 = @()
    logs                  = @(
        @{
            ts      = $now.ToString("o")
            level   = "info"
            message = "ps correlation test report"
            data    = @{ cid = $cidReport }
        }
    )
}

$respReport = Invoke-Baseliner -Method POST -Url "$Server/api/v1/device/reports" -Headers @{
    "Authorization"    = "Bearer $DeviceToken"
    "X-Correlation-ID" = $cidReport
} -BodyObject $reportBody

$echoReport = Get-HeaderValue -Headers $respReport.Headers -Name "X-Correlation-ID"
Assert-Equal -Actual $echoReport -Expected $cidReport -Message "Report endpoint did not echo X-Correlation-ID"

$reportJson = $null
try { $reportJson = $respReport.Content | ConvertFrom-Json } catch {}
if ($null -eq $reportJson -or -not $reportJson.run_id) {
    throw "Report response did not contain run_id. Raw body:`n$($respReport.Content)"
}
$runId = [string]$reportJson.run_id

Write-Host "  OK: echoed X-Correlation-ID = $echoReport"
Write-Host "  OK: created run_id = $runId"

if ($ShowBodies) {
    Write-Host "  Body: $($respReport.Content)"
}

Write-Host ""

# 3) Admin run detail includes correlation_id == cidReport
Write-Host "[3/3] GET /api/v1/admin/runs/{run_id} (returns correlation_id)" -ForegroundColor Yellow
$respRun = Invoke-Baseliner -Method GET -Url "$Server/api/v1/admin/runs/$runId" -Headers @{
    "X-Admin-Key"      = $AdminKey
    "X-Correlation-ID" = $cidAdmin
}

$echoAdmin = Get-HeaderValue -Headers $respRun.Headers -Name "X-Correlation-ID"
Assert-Equal -Actual $echoAdmin -Expected $cidAdmin -Message "Admin endpoint did not echo X-Correlation-ID"

$runJson = $null
try { $runJson = $respRun.Content | ConvertFrom-Json } catch {}

if ($null -eq $runJson) {
    throw "Admin run detail response was not JSON. Raw body:`n$($respRun.Content)"
}

if (-not ($runJson.PSObject.Properties.Name -contains "correlation_id")) {
    throw "Admin run detail JSON does not contain correlation_id. Did you apply the server schema/endpoint updates?"
}

Assert-Equal -Actual ([string]$runJson.correlation_id) -Expected $cidReport -Message "Run correlation_id mismatch (DB persistence or response wiring issue)"
Write-Host "  OK: run correlation_id persisted and returned = $($runJson.correlation_id)"
Write-Host ""
Write-Host "PASS ✅  Correlation IDs are echoed and persisted end-to-end." -ForegroundColor Green
