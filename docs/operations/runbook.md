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

### List audit events

```bash
python server/scripts/seed_dev.py audit --limit 20
python server/scripts/seed_dev.py audit --limit 50 --action device.delete
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
