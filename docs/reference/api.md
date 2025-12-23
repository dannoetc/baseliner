# API reference

Placeholder for API docs.

## TODO

- Summarize authentication:
  - Admin: `X-Admin-Key`
  - Device: `Authorization: Bearer <token>`
- Document the most important routes:
  - enrollment
  - device policy fetch
  - report ingestion
  - admin devices/policies/assignments/runs
    - POST /api/v1/admin/assign-policy
    - GET /api/v1/admin/devices/{device_id}/assignments
    - DELETE /api/v1/admin/devices/{device_id}/assignments
    - DELETE /api/v1/admin/devices/{device_id}/assignments/{policy_id}
  - audit log


## Enroll tokens (admin)

- `POST /api/v1/admin/enroll-tokens` → mint a single-use enroll token (returns the raw token once)
- `GET /api/v1/admin/enroll-tokens` → list tokens (metadata only)
- `POST /api/v1/admin/enroll-tokens/{token_id}/revoke` → revoke/expire a token immediately

## Enrollment (device bootstrap)

- `POST /api/v1/enroll` → exchange enroll token + device metadata for a device token



## Device auth tokens (admin)

Baseliner stores **device auth token history** (hashes only) so operators can audit token rotation events
and see when a token was last used.

* `GET /api/v1/admin/devices/{device_id}/tokens`
  * Returns token history **without** exposing raw tokens (only a short hash prefix + timestamps).
  * `last_used_at` updates on successful `POST /api/v1/device/reports` requests.
