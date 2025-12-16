# ====== CONFIG ======
$BaseUrl = "http://localhost:8000"
$AdminKey = "change-me-too"

# Optional: if you already have a device token, set it here and skip Step 1-2.
# $DeviceToken = "<DEVICE_TOKEN>"

# ====== Step 1: Create an enroll token (admin) ======
Write-Host "`n== Step 1: Create enroll token =="
$tokJson = curl.exe -s -X POST "$BaseUrl/api/v1/admin/enroll-tokens" `
    -H "X-Admin-Key: $AdminKey" `
    -H "Content-Type: application/json" `
    -d "{}"

$tokJson
$EnrollToken = ($tokJson | ConvertFrom-Json).enroll_token

# ====== Step 2: Enroll device (get device_token) ======
if (-not $DeviceToken) {
    Write-Host "`n== Step 2: Enroll device =="
    $enrollBody = @{
        enroll_token  = $EnrollToken
        device_key    = "TEST-DEVICE-001"
        hostname      = $env:COMPUTERNAME
        os            = "windows"
        os_version    = (Get-CimInstance Win32_OperatingSystem).Version
        arch          = $env:PROCESSOR_ARCHITECTURE
        agent_version = "0.1.0-dev"
        tags          = @{ env = "dev" }
    } | ConvertTo-Json -Depth 10

    $enrollJson = curl.exe -s -X POST "$BaseUrl/api/v1/enroll" `
        -H "Content-Type: application/json" `
        -d $enrollBody

    $enrollJson
    $enrollObj = $enrollJson | ConvertFrom-Json
    $DeviceId = $enrollObj.device_id
    $DeviceToken = $enrollObj.device_token
}

# ====== Step 3: Fetch effective policy (device) ======
Write-Host "`n== Step 3: GET /api/v1/device/policy =="
$policyJson = curl.exe -s "$BaseUrl/api/v1/device/policy" `
    -H "Authorization: Bearer $DeviceToken"
$policyJson

# ====== Step 4: Submit a minimal report (device) ======
Write-Host "`n== Step 4: POST /api/v1/device/reports (minimal) =="
$now = (Get-Date).ToUniversalTime().ToString("o")

$reportBody = @{
    started_at            = $now
    ended_at              = $now
    status                = "succeeded"
    agent_version         = "0.1.0-dev"
    effective_policy_hash = $null
    policy_snapshot       = @{
        policy_id   = (($policyJson | ConvertFrom-Json).policy_id)
        policy_name = (($policyJson | ConvertFrom-Json).policy_name)
    }
    summary               = @{ itemsTotal = 0; ok = 0; failed = 0 }
    items                 = @()
    logs                  = @(@{ ts = $now; level = "info"; message = "sanity test report"; data = @{ hello = "world" } })
} | ConvertTo-Json -Depth 20

$submitJson = curl.exe -s -X POST "$BaseUrl/api/v1/device/reports" `
    -H "Authorization: Bearer $DeviceToken" `
    -H "Content-Type: application/json" `
    -d $reportBody

$submitJson
$RunId = ($submitJson | ConvertFrom-Json).run_id

# ====== Step 5: List runs (admin) ======
Write-Host "`n== Step 5: GET /api/v1/admin/runs (admin) =="
$runsJson = curl.exe -s "$BaseUrl/api/v1/admin/runs?limit=5&offset=0" `
    -H "X-Admin-Key: $AdminKey"
$runsJson

# ====== Step 6: Run detail (admin) ======
Write-Host "`n== Step 6: GET /api/v1/admin/runs/{run_id} (admin) =="
$detailJson = curl.exe -s "$BaseUrl/api/v1/admin/runs/$RunId" `
    -H "X-Admin-Key: $AdminKey"
$detailJson
