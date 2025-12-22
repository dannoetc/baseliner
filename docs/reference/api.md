# API reference

Baseliner exposes a small device-facing API and an admin API.

All routes are prefixed with `/api/v1` except `GET /health`.

## Authentication

### Admin

Admin routes require:

- Header: `X-Admin-Key: <BASELINER_ADMIN_KEY>`

Applies to routes under `/api/v1/admin/*`.

### Device

Device routes require:

- Header: `Authorization: Bearer <device_token>`

The `device_token` is returned by `POST /api/v1/enroll`.

## Core routes

### Health

- `GET /health` → `{"status":"ok"}`

### Enroll

- `POST /api/v1/enroll`

Body includes `enroll_token` + basic device metadata. Returns:

- `device_id`
- `device_token` (store this on the device; used as Bearer token)

### Device policy fetch

- `GET /api/v1/device/policy`

Returns the effective compiled policy for the authenticated device.

### Device report ingestion

- `POST /api/v1/device/reports`

Creates a run, run items, and optional log events. If you send an `X-Correlation-ID` header, the server
echoes it and persists it on the created run for later debugging via admin endpoints.

## Admin routes

### Policies and assignments

- `POST /api/v1/admin/policies` (upsert policy)
- `POST /api/v1/admin/assign-policy` (assign a policy to a device)
- `GET /api/v1/admin/devices/{device_id}/assignments` (list assignments)
- `DELETE /api/v1/admin/devices/{device_id}/assignments` (clear assignments)

### Devices

- `GET /api/v1/admin/devices` (device list + optional health)
- `GET /api/v1/admin/devices/{device_id}/debug` (operator “bundle” view)
- `GET /api/v1/admin/devices/{device_id}/runs` (recent runs for a device)

#### Lifecycle

Baseliner treats “delete” as a **soft delete**:

- `DELETE /api/v1/admin/devices/{device_id}`  
  Deactivates the device, records `deleted_at`, and revokes the current device token.

- `POST /api/v1/admin/devices/{device_id}/restore`  
  Reactivates the device and mints a fresh device token.

- `POST /api/v1/admin/devices/{device_id}/revoke-token`  
  Rotates the device token without deleting the device.

### Runs

- `GET /api/v1/admin/runs` (paged)
- `GET /api/v1/admin/runs/{run_id}` (detail: items + logs)
- `POST /api/v1/admin/compile?device_id=<uuid>` (debug compile)

### Audit log

- `GET /api/v1/admin/audit` (newest first, cursor pagination)

Supports filters: `action`, `target_type`, `target_id`.

### Maintenance

- `POST /api/v1/admin/maintenance/prune`  
  Deletes old runs/items/logs to bound DB growth. Use `dry_run=true` first.

## Common status codes

- `401 Unauthorized`  
  Missing/invalid admin key or device token.

- `403 Forbidden`  
  Device is deactivated or token is revoked.

- `409 Conflict`  
  Device is active/inactive in a way that makes the requested lifecycle action invalid.

- `413 Payload Too Large` / `429 Too Many Requests`  
  Returned when request size and/or rate limits are enabled.
