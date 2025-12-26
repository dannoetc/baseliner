# Change Summary
- Added admin device lifecycle endpoints for deactivate, reactivate, and token rotation with audit logging and tenant scoping.
- Updated device token handling to support revocation without rotation and added CLI commands for lifecycle operations.
- Expanded tests to cover tenant isolation, token rotation, and audit logging for new device lifecycle flows.
- Added a backwards-compatible DeleteDeviceRequest alias to avoid missing type errors in admin routes.

## Files Modified
- server/src/baseliner_server/db/models.py
- server/src/baseliner_server/services/device_tokens.py
- server/src/baseliner_server/api/v1/admin.py
- server/src/baseliner_server/schemas/admin.py
- server/tests/test_admin_device_lifecycle_contract.py
- tools/admin-cli/src/baseliner_admin/client.py
- tools/admin-cli/src/baseliner_admin/cli.py
- change_summary.md
