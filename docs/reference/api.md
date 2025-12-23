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
