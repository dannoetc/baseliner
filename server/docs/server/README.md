# Server

## Migrations

From the `server/` directory:

```bash
alembic upgrade head
```

## Tenancy (Phase 0)

The server now has a `tenants` table and a required `tenant_id` column on core tables.

Phase 0 remains **single-tenant**:

- A default tenant is created with id `00000000-0000-0000-0000-000000000001`.
- All existing rows are backfilled to the default tenant.
- API behavior is unchanged (admin keys remain global), but all read/write paths are now tenant-stamped/scoped so that Phase 1 multi-tenant work is mostly additive.

See `docs/architecture/data-model.md` for the table list.
