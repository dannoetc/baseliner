param(
    [string]$Server = "http://localhost:8000",
    [string]$AdminKey = "change-me-too",
    [string]$DeviceKey = "DESKTOP-FTVVO4A",
    [string]$PolicyName = "smoke-putty-7zip",
    [int]$Priority = 9999
)

$Headers = @{ "X-Admin-Key" = $AdminKey }

function Get-DeviceId {
    $resp = Invoke-RestMethod -Method Get -Uri "$Server/api/v1/admin/devices?limit=500&offset=0" -Headers $Headers
    $d = $resp.items | Where-Object { $_.device_key -eq $DeviceKey } | Select-Object -First 1
    if (-not $d) { throw "Device not found for device_key=$DeviceKey" }
    return $d.id
}

function Upsert-Policy([hashtable]$Policy) {
    Invoke-RestMethod -Method Post -Uri "$Server/api/v1/admin/policies" `
        -Headers $Headers -ContentType "application/json" `
        -Body ($Policy | ConvertTo-Json -Depth 30)
}

function Assign-Policy([string]$DeviceId, [string]$PolicyName) {
    $payload = @{
        device_id   = $DeviceId
        policy_name = $PolicyName
        mode        = "enforce"
        priority    = $Priority
    }
    Invoke-RestMethod -Method Post -Uri "$Server/api/v1/admin/assign-policy" `
        -Headers $Headers -ContentType "application/json" `
        -Body ($payload | ConvertTo-Json -Depth 10) | Out-Null
}

function Get-DeviceHealth {
    (Invoke-RestMethod -Method Get -Uri "$Server/api/v1/admin/devices?include_health=true&limit=500&offset=0" -Headers $Headers).items |
    Where-Object { $_.device_key -eq $DeviceKey } |
    Select-Object -First 1
}

function Print-HealthRow($dev) {
    $dev | Select-Object hostname, device_key,
    @{n = "health"; e = { $_.health.status } },
    @{n = "reason"; e = { $_.health.reason } },
    @{n = "seen_age_s"; e = { $_.health.seen_age_seconds } },
    @{n = "run_age_s"; e = { $_.health.run_age_seconds } },
    @{n = "offline"; e = { $_.health.offline } },
    @{n = "stale"; e = { $_.health.stale } },
    @{n = "last_run"; e = { $_.last_run.id } },
    @{n = "status"; e = { $_.last_run.status } } |
    Format-Table -AutoSize
}

function Get-Run([string]$RunId) {
    Invoke-RestMethod -Method Get -Uri "$Server/api/v1/admin/runs/$RunId" -Headers $Headers
}

function Show-Failures($run) {
    $bad = $run.items | Where-Object {
        $_.status_detect -ne "ok" -or
        $_.status_validate -ne "ok" -or
        $_.status_remediate -eq "fail"
    }

    "`n=== FAILURES / NON-OK ITEMS (run $($run.id)) ===" | Write-Host
    if (-not $bad -or $bad.Count -eq 0) {
        "(none)" | Write-Host
        return
    }

    $bad |
    Select-Object ordinal, name, resource_type, resource_id, status_detect, status_remediate, status_validate,
    compliant_before, compliant_after, changed,
    @{n = "err_type"; e = { $_.error.type } },
    @{n = "err_msg"; e = { $_.error.message } },
    @{n = "rem_exit"; e = { $_.evidence.remediate.exit_code } },
    @{n = "rem_stderr"; e = { $_.evidence.remediate.stderr } } |
    Format-Table -AutoSize
}

function Show-RunItemsOverview($run) {
    "`n=== RUN ITEMS OVERVIEW (run $($run.id)) ===" | Write-Host
    $run.items |
    Select-Object ordinal, resource_type, resource_id, name, status_detect, status_remediate, status_validate |
    Format-Table -AutoSize
}

function Show-WingetItems($run) {
    "`n=== WINGET ITEMS (run $($run.id)) ===" | Write-Host

    $run.items |
    Where-Object { $_.resource_type -eq "winget.package" } |
    ForEach-Object {
        $det = $_.evidence.detect
        $rem = $_.evidence.remediate
        $val = $_.evidence.validate

        [pscustomobject]@{
            ordinal              = $_.ordinal
            name                 = $_.name
            resource_id          = $_.resource_id

            requested_package_id = $det.requested_package_id
            source               = $det.source
            action               = if ($rem) { $rem.action } else { $null }

            status_detect        = $_.status_detect
            status_remediate     = $_.status_remediate
            status_validate      = $_.status_validate

            detect_installed     = $det.installed
            detect_version       = $det.version

            validate_installed   = $val.installed
            validate_version     = $val.version

            compliant_before     = $_.compliant_before
            compliant_after      = $_.compliant_after
            changed              = $_.changed

            remediate_exit       = if ($rem) { $rem.exit_code } else { $null }
        }
    } | Format-Table -AutoSize
}

function To-SemVer([string]$s) {
    $s = ($s ?? "").Trim()
    if (-not $s) { return [version]"0.0.0.0" }

    $clean = ($s -replace "[^0-9\.]", "")
    if (-not $clean) { return [version]"0.0.0.0" }

    $parts = $clean.Split(".") | Where-Object { $_ -ne "" }
    while ($parts.Count -lt 4) { $parts += "0" }
    $fixed = ($parts[0..3] -join ".")
    return [version]$fixed
}

function Find-WingetItem($run, [string]$StableId, [string]$PackageId) {
    $pkgId = ($PackageId ?? "").Trim()
    $sid = ($StableId ?? "").Trim()

    # 1) stable resource id
    $it = $run.items | Where-Object { $_.resource_type -eq "winget.package" -and $_.resource_id -eq $sid } | Select-Object -First 1
    if ($it) { return $it }

    # 2) resource_id equals package id
    if ($pkgId) {
        $it = $run.items | Where-Object { $_.resource_type -eq "winget.package" -and $_.resource_id -eq $pkgId } | Select-Object -First 1
        if ($it) { return $it }
    }

    # 3) evidence.detect.requested_package_id
    if ($pkgId) {
        $it = $run.items | Where-Object {
            $_.resource_type -eq "winget.package" -and
            $_.evidence -and $_.evidence.detect -and
            $_.evidence.detect.requested_package_id -eq $pkgId
        } | Select-Object -First 1
        if ($it) { return $it }
    }

    return $null
}

function Dump-WingetKeys($run) {
    $rows = $run.items | Where-Object { $_.resource_type -eq "winget.package" } | ForEach-Object {
        [pscustomobject]@{
            resource_id          = $_.resource_id
            requested_package_id = $_.evidence.detect.requested_package_id
        }
    }
    "`n--- winget keys present in run ---" | Write-Host
    $rows | Format-Table -AutoSize
}

function Assert-WingetInstalled($run, [string]$StableId, [string]$PackageId, [bool]$ExpectInstalled) {
    $it = Find-WingetItem -run $run -StableId $StableId -PackageId $PackageId
    if (-not $it) {
        Dump-WingetKeys $run
        throw "Missing expected winget item stable_id='$StableId' package_id='$PackageId' in run detail."
    }

    $installed = [bool]$it.evidence.validate.installed
    if ($installed -ne $ExpectInstalled) {
        throw "ASSERT FAILED: $StableId (pkg=$PackageId) validate_installed=$installed expected=$ExpectInstalled"
    }
}

function Assert-WingetVersionExact($run, [string]$StableId, [string]$PackageId, [string]$ExpectVersion) {
    $it = Find-WingetItem -run $run -StableId $StableId -PackageId $PackageId
    if (-not $it) {
        Dump-WingetKeys $run
        throw "Missing expected winget item stable_id='$StableId' package_id='$PackageId' in run detail."
    }

    $installed = [bool]$it.evidence.validate.installed
    $ver = [string]$it.evidence.validate.version

    if (-not $installed) { throw "ASSERT FAILED: $StableId validate_installed=$installed expected=True" }
    if ($ver -ne $ExpectVersion) { throw "ASSERT FAILED: $StableId validate_version='$ver' expected='$ExpectVersion'" }
}

function Assert-WingetVersionMin($run, [string]$StableId, [string]$PackageId, [string]$MinVersion) {
    $it = Find-WingetItem -run $run -StableId $StableId -PackageId $PackageId
    if (-not $it) {
        Dump-WingetKeys $run
        throw "Missing expected winget item stable_id='$StableId' package_id='$PackageId' in run detail."
    }

    $installed = [bool]$it.evidence.validate.installed
    $ver = [string]$it.evidence.validate.version

    if (-not $installed) { throw "ASSERT FAILED: $StableId validate_installed=$installed expected=True" }
    if ( (To-SemVer $ver) -lt (To-SemVer $MinVersion) ) {
        throw "ASSERT FAILED: $StableId validate_version='$ver' expected >= '$MinVersion'"
    }
}

function Run-Phase(
    [string]$PhaseLabel,
    [hashtable]$Policy,
    [hashtable[]]$Expect
) {
    "`n==> Upserting policy ($PhaseLabel)..." | Write-Host
    Upsert-Policy $Policy | ConvertTo-Json -Depth 10 | Write-Host

    "`n==> (Re)assigning policy to device (priority=$Priority)..." | Write-Host
    Assign-Policy -DeviceId $DeviceId -PolicyName $PolicyName

    "`n==> Device health BEFORE $PhaseLabel run:" | Write-Host
    $dev = Get-DeviceHealth
    Print-HealthRow $dev

    "`n*** Now run the agent ON THE DEVICE once, then press Enter here. ***" | Write-Host
    Read-Host | Out-Null

    "`n==> Device health AFTER $PhaseLabel run:" | Write-Host
    $dev = Get-DeviceHealth
    Print-HealthRow $dev

    $run = Get-Run $dev.last_run.id
    Show-Failures $run
    Show-RunItemsOverview $run
    Show-WingetItems $run

    foreach ($e in $Expect) {
        $sid = [string]$e.stable_id
        $pkgId = [string]$e.package_id
        $inst = [bool]$e.installed

        Assert-WingetInstalled -run $run -StableId $sid -PackageId $pkgId -ExpectInstalled $inst

        if ($e.exact) { Assert-WingetVersionExact -run $run -StableId $sid -PackageId $pkgId -ExpectVersion ([string]$e.exact) }
        if ($e.min) { Assert-WingetVersionMin   -run $run -StableId $sid -PackageId $pkgId -MinVersion  ([string]$e.min) }
    }
}

# ---------------------------
# Resources + Policies
# ---------------------------

$DeviceId = Get-DeviceId

$R_Putty_Present = @{ type = "winget.package"; id = "putty"; name = "PuTTY"; package_id = "PuTTY.PuTTY"; ensure = "present" }
$R_Putty_Absent = @{ type = "winget.package"; id = "putty"; name = "PuTTY"; package_id = "PuTTY.PuTTY"; ensure = "absent" }
$R_7Zip_Present = @{ type = "winget.package"; id = "7zip"; name = "7-Zip"; package_id = "7zip.7zip"; ensure = "present" }
$R_7Zip_Absent = @{ type = "winget.package"; id = "7zip"; name = "7-Zip"; package_id = "7zip.7zip"; ensure = "absent" }

$R_Fx_145 = @{
    type = "winget.package"; id = "firefox"; name = "Firefox"
    package_id = "Mozilla.Firefox"; ensure = "present"
    version = "145.0.2"
}
$R_Fx_Min146 = @{
    type = "winget.package"; id = "firefox"; name = "Firefox"
    package_id = "Mozilla.Firefox"; ensure = "present"
    allow_upgrade = $true
    min_version = "146.0"
}

$PolicyA = @{ name = $PolicyName; description = "Phase A"; schema_version = "1"; is_active = $true; document = @{ resources = @($R_Putty_Present, $R_7Zip_Present) } }
$PolicyB = @{ name = $PolicyName; description = "Phase B"; schema_version = "1"; is_active = $true; document = @{ resources = @($R_Putty_Absent, $R_7Zip_Present) } }
$PolicyC = @{ name = $PolicyName; description = "Phase C"; schema_version = "1"; is_active = $true; document = @{ resources = @($R_Putty_Absent, $R_7Zip_Absent) } }
$PolicyD = @{ name = $PolicyName; description = "Phase D"; schema_version = "1"; is_active = $true; document = @{ resources = @($R_Putty_Present, $R_7Zip_Present) } }

$PolicyE = @{ name = $PolicyName; description = "Phase E"; schema_version = "1"; is_active = $true; document = @{ resources = @($R_Putty_Absent, $R_7Zip_Absent, $R_Fx_145) } }
$PolicyF = @{ name = $PolicyName; description = "Phase F"; schema_version = "1"; is_active = $true; document = @{ resources = @($R_Putty_Absent, $R_7Zip_Absent, $R_Fx_Min146) } }

$ExpectA = @(
    @{ stable_id = "putty"; package_id = "PuTTY.PuTTY"; installed = $true },
    @{ stable_id = "7zip"; package_id = "7zip.7zip"; installed = $true }
)
$ExpectB = @(
    @{ stable_id = "putty"; package_id = "PuTTY.PuTTY"; installed = $false },
    @{ stable_id = "7zip"; package_id = "7zip.7zip"; installed = $true }
)
$ExpectC = @(
    @{ stable_id = "putty"; package_id = "PuTTY.PuTTY"; installed = $false },
    @{ stable_id = "7zip"; package_id = "7zip.7zip"; installed = $false }
)
$ExpectD = @(
    @{ stable_id = "putty"; package_id = "PuTTY.PuTTY"; installed = $true },
    @{ stable_id = "7zip"; package_id = "7zip.7zip"; installed = $true }
)
$ExpectE = @(
    @{ stable_id = "putty"; package_id = "PuTTY.PuTTY"; installed = $false },
    @{ stable_id = "7zip"; package_id = "7zip.7zip"; installed = $false },
    @{ stable_id = "firefox"; package_id = "Mozilla.Firefox"; installed = $true; exact = "145.0.2" }
)
$ExpectF = @(
    @{ stable_id = "putty"; package_id = "PuTTY.PuTTY"; installed = $false },
    @{ stable_id = "7zip"; package_id = "7zip.7zip"; installed = $false },
    @{ stable_id = "firefox"; package_id = "Mozilla.Firefox"; installed = $true; min = "146.0" }
)

Run-Phase -PhaseLabel "Phase A" -Policy $PolicyA -Expect $ExpectA
Run-Phase -PhaseLabel "Phase B" -Policy $PolicyB -Expect $ExpectB
Run-Phase -PhaseLabel "Phase C" -Policy $PolicyC -Expect $ExpectC
Run-Phase -PhaseLabel "Phase D" -Policy $PolicyD -Expect $ExpectD

Run-Phase -PhaseLabel "Phase E" -Policy $PolicyE -Expect $ExpectE
Run-Phase -PhaseLabel "Phase F" -Policy $PolicyF -Expect $ExpectF

"`nDone. ✅" | Write-Host
