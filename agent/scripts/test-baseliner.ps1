Write-Host ""
Write-Host "Latest run:" -ForegroundColor Cyan
[pscustomobject]@{
    id                           = $latestMeta.id
    started_at                   = $latestMeta.started_at
    status                       = $latestMeta.status
    detect_state_hash            = $latestDetect
    validate_state_hash          = $latestValidate
    observed_state_hash_reported = $latest.summary.observed_state_hash
} | Format-List
