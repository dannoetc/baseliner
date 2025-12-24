# Data model

## Tenancy (Phase 0)

Baseliner now has a **Tenant** concept. In **Phase 0** there is exactly one tenant:

- `tenants.id = 00000000-0000-0000-0000-000000000001`
- `tenants.name = "default"`

All existing rows are backfilled to this tenant and all new rows are stamped with this `tenant_id`.

## Core tables

- `tenants`
- `devices`
- `device_auth_tokens`
- `enroll_tokens`
- `policies`
- `policy_assignments`
- `runs`, `run_items`, `log_events`
- `audit_logs`

## Tenant-scoped columns

The following tables have a required `tenant_id` foreign key to `tenants.id`:

- `devices`
- `device_auth_tokens`
- `enroll_tokens`
- `policies`
- `policy_assignments`
- `runs`
- `run_items`
- `log_events`
- `audit_logs`

In Phase 0, the API still behaves as single-tenant; the tenant plumbing exists so we can enforce isolation in Phase 1+ without invasive schema changes.
