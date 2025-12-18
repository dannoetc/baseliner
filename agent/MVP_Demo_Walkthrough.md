## MVP Demo: enroll → assign baseline → run agent → debug & verify

This walkthrough demonstrates the core operator loop:
1) upsert a baseline policy  
2) assign it to a device  
3) run the agent (Scheduled Task)  
4) verify via debug bundle + run detail  

### Prereqs
- Server running locally at `http://localhost:8000`
- Admin key set (default dev): `change-me-too`
- A device already enrolled (you have a `DeviceId` UUID)
- Windows Scheduled Task exists: **Baseliner Agent**
- Demo policy file present at: `policies/baseliner-windows-core.json`

### 1) Upsert the baseline policy
From PowerShell (run from repo root):

```powershell
$Server="http://localhost:8000"
$Headers=@{ "X-Admin-Key"="change-me-too"; "Accept"="application/json" }

$Policy = Get-Content ".\policies\baseliner-windows-core.json" -Raw
Invoke-RestMethod -Method POST `
  -Uri "$Server/api/v1/admin/policies" `
  -Headers $Headers `
  -ContentType "application/json" `
  -Body $Policy | Format-List
```

### 2) Assign the policy to a device

```powershell
$DeviceId="PUT-DEVICE-UUID-HERE"

# (optional) clear existing assignments
Invoke-RestMethod -Method DELETE `
  -Uri "$Server/api/v1/admin/devices/$DeviceId/assignments" `
  -Headers $Headers | Out-Null

# assign baseline (priority 100, enforce)
Invoke-RestMethod -Method POST `
  -Uri "$Server/api/v1/admin/assign-policy" `
  -Headers $Headers `
  -ContentType "application/json" `
  -Body (@{ device_id=$DeviceId; policy_name="baseliner-windows-core"; priority=100; mode="enforce" } | ConvertTo-Json)
```

### 3) Run the agent (Scheduled Task)

```powershell
Start-ScheduledTask -TaskName "Baseliner Agent"
Start-Sleep -Seconds 20
try { Stop-ScheduledTask -TaskName "Baseliner Agent" } catch { }
```

### 4) Debug the device (operator workflow)

```powershell
$dbg = Invoke-RestMethod -Method GET `
  -Uri "$Server/api/v1/admin/devices/$DeviceId/debug" `
  -Headers $Headers

$dbg | ConvertTo-Json -Depth 20 | Set-Content ".\device_debug.json"
"Saved debug payload to .\device_debug.json"

# quick view
$dbg.last_run
```

### 5) Verify run detail

```powershell
$runId = $dbg.last_run.id

Invoke-RestMethod -Method GET `
  -Uri "$Server/api/v1/admin/runs/$runId" `
  -Headers $Headers `
  | ConvertTo-Json -Depth 30 `
  | Set-Content ".\run_detail.json"

"Saved run detail to .\run_detail.json"
```

### Expected outcomes
- `effective_policy.document.resources` shows the baseline resources (e.g., Firefox + marker script).
- Latest run shows `status=succeeded` after first successful remediation.
- Script evidence includes `exit_code`, `stdout`, and `stderr` (truncated).
- Subsequent runs should show the script detect passing (compliant) with `changed=false`.
