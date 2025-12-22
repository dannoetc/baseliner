# Runbook

This is the “high signal” command list for operating Baseliner.

## Health

```bash
curl -i http://localhost:8000/health
```

If using TLS overlay:

```bash
curl -i https://$BASELINER_DOMAIN/health
```

## Logs

```bash
docker compose logs -f --tail 200 api
```

Overlay:

```bash
docker logs baseliner-nginx --tail 200
docker logs baseliner-certbot --tail 200
```

## Nginx overlay verification

```bash
docker exec baseliner-nginx nginx -t

docker exec baseliner-nginx nginx -T | grep -E "limit_req_zone|limit_conn_zone|real_ip_header|set_real_ip_from" || true
```

## Database quick checks

(Adjust connection details for your environment.)

```sql
-- Recent devices
select id, device_key, status, last_seen_at
from devices
order by last_seen_at desc
limit 20;

-- Recent runs
select id, device_id, started_at, ended_at, status, correlation_id
from runs
order by started_at desc
limit 20;

-- Recent admin actions
select ts, action, target_type, target_id
from audit_logs
order by ts desc
limit 50;
```

## Lifecycle operations

- **Soft delete**: `DELETE /api/v1/admin/devices/{device_id}`
- **Restore**: `POST /api/v1/admin/devices/{device_id}/restore` (returns a new device token)
- **Revoke token**: `POST /api/v1/admin/devices/{device_id}/revoke-token` (rotates token)

## TODO

- Add “backup/restore Postgres” commands
- Add retention guidance (prune old runs, audit retention)
