# Runbook

This is the “high signal” command list for operating Baseliner.

Examples assume:

```bash
export BASE="http://localhost:8000"
export ADMIN_KEY="change-me-too"
```

If using TLS overlay:

```bash
export BASE="https://$BASELINER_DOMAIN"
```

## Health

```bash
curl -i "$BASE/health"
```

## Logs

```bash
docker compose logs -f --tail 200 api
docker compose logs -f --tail 200 db
```

TLS overlay:

```bash
docker logs baseliner-nginx --tail 200
docker logs baseliner-certbot --tail 200
```

## Dev seeding

### One-shot seed (token + policy + optional assignment)

```bash
python server/scripts/seed_dev.py seed --create-token --policy-file policies/baseliner-windows-core.json --device-key DESKTOP-FTVVO4A
```

### Create enroll token only

```bash
python server/scripts/seed_dev.py create-enroll-token --expires-hours 24 --note "dev enroll token"
```
### Enroll token lifecycle (create/list/revoke)

Create via Admin API (recommended for ops tooling):

```bash
curl -sS -X POST "$BASE/api/v1/admin/enroll-tokens" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ttl_seconds":86400,"note":"24h token"}'
```

List tokens (metadata only):

```bash
curl -sS "$BASE/api/v1/admin/enroll-tokens?limit=50&offset=0&include_used=false" \
  -H "X-Admin-Key: $ADMIN_KEY"
```

Revoke a token (expires it immediately):

```bash
curl -sS -X POST "$BASE/api/v1/admin/enroll-tokens/$TOKEN_ID/revoke" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason":"lost token"}'
```

Notes:
- Tokens are **single-use** (server marks them used on successful enrollment).
- Revocation is implemented by setting `expires_at` to “now”, so enrollment treats it as expired.


### List audit events

```bash
python server/scripts/seed_dev.py audit --limit 20
python server/scripts/seed_dev.py audit --limit 50 --action device.delete
```



### Device auth token history (audit)

Each enrolled device authenticates with a **device token** (never stored in plaintext). Baseliner stores only a
**hash** of each token in a `device_auth_tokens` history table.

* On **re-enroll**, **restore**, or **admin revoke-token**, the previous active token is marked revoked and a new
  token is minted.
* `last_used_at` updates when the device successfully posts a report (`POST /api/v1/device/reports`).

To inspect token history for a device:

```powershell
Invoke-RestMethod -Headers $Headers -Method GET `
  "$Base/api/v1/admin/devices/$DeviceId/tokens"
```

## Enroll a device (manual)

```bash
curl -sS -X POST "$BASE/api/v1/enroll"   -H "Content-Type: application/json"   -d '{
    "enroll_token": "'"$ENROLL_TOKEN"'",
    "device_key": "DESKTOP-FTVVO4A",
    "hostname": "DESKTOP-FTVVO4A",
    "os": "windows",
    "os_version": "10",
    "arch": "AMD64",
    "agent_version": "0.1.0-dev",
    "tags": {"env": "dev"}
  }'
```

## Device lifecycle

### Soft delete a device

```bash
curl -sS -X DELETE "$BASE/api/v1/admin/devices/$DEVICE_ID?reason=testing"   -H "X-Admin-Key: $ADMIN_KEY"
```

### Restore a device (returns a new device token)

```bash
curl -sS -X POST "$BASE/api/v1/admin/devices/$DEVICE_ID/restore"   -H "X-Admin-Key: $ADMIN_KEY"
```

### Revoke/rotate a device token (returns a new device token)

```bash
curl -sS -X POST "$BASE/api/v1/admin/devices/$DEVICE_ID/revoke-token"   -H "X-Admin-Key: $ADMIN_KEY"
```

## Audit log

List newest:

```bash
curl -sS "$BASE/api/v1/admin/audit?limit=20" -H "X-Admin-Key: $ADMIN_KEY"
```

Filter:

```bash
curl -sS "$BASE/api/v1/admin/audit?limit=50&action=device.delete" -H "X-Admin-Key: $ADMIN_KEY"
```

Cursor pagination:

```bash
curl -sS "$BASE/api/v1/admin/audit?limit=100&cursor=$CURSOR" -H "X-Admin-Key: $ADMIN_KEY"
```

## Retention / pruning runs

### Dry run first

```bash
curl -sS -X POST "$BASE/api/v1/admin/maintenance/prune"   -H "X-Admin-Key: $ADMIN_KEY"   -H "Content-Type: application/json"   -d '{"keep_days":30,"keep_runs_per_device":50,"batch_size":500,"dry_run":true}'
```

### Execute delete

```bash
curl -sS -X POST "$BASE/api/v1/admin/maintenance/prune"   -H "X-Admin-Key: $ADMIN_KEY"   -H "Content-Type: application/json"   -d '{"keep_days":30,"keep_runs_per_device":50,"batch_size":500,"dry_run":false}'
```

### Simple cron (host-side)

Prefer a host-side script that exports `ADMIN_KEY` from a secret manager, then runs the prune call.
Example idea:

- Daily at 03:15
- `keep_days=30`
- `keep_runs_per_device=50`

(Exact cron wiring depends on how you inject secrets on your host.)
