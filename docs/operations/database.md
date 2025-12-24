# Database operations

Minimal database operations guidance for PostgreSQL deployments.

## On-demand logical backup (pg_dump)

Create a timestamped SQL dump from the running `db` container. Adjust the
database name/user if you customized your compose file.

```bash
docker compose exec db pg_dump -U baseliner baseliner > baseliner-$(date +%Y%m%d-%H%M%S).sql
```

Notes:
- Prefer taking a backup during a maintenance window to avoid long-running locks.
- Store dumps outside the compose host if you need durability beyond the host lifecycle.

## Restore from a dump

Restore requires an empty target database. Stop the API first to prevent writes, then drop and
recreate the database (or restore to a fresh instance) before loading the dump.

```bash
docker compose down api
docker compose exec -T db psql -U baseliner postgres -c "DROP DATABASE IF EXISTS baseliner;"
docker compose exec -T db psql -U baseliner postgres -c "CREATE DATABASE baseliner;"
cat baseliner-20240101-120000.sql | docker compose exec -T db psql -U baseliner baseliner
```

After restore, restart services and verify the app health checks.

## Migration sanity checklist

Before applying Alembic migrations to production, confirm:

- Backup is recent and tested (see restore instructions above).
- Alembic history shows the expected head: `docker compose exec api alembic heads`.
- Migrations were applied to staging with representative data and app smoke tests passed.
- Review for destructive changes (drops, truncations, data rewrites) and have a rollback plan
  using backups.
- Ensure `downgrade` paths are not used; prefer forward fixes (see policy below).

## Downgrade policy

Database downgrades are **not supported**. If a release needs to be rolled back, restore from a
known-good backup and redeploy the prior app version. For forward fixes, ship a new migration
that repairs data/schema rather than attempting `alembic downgrade`.

## Pre-deploy checklist

- **Backups**: Automated logical backups scheduled, monitored, and stored off-host with retention
  meeting your recovery point objectives.
- **Retention**: Confirm backup retention/rotation covers compliance and operational needs; test
  restore from a recent point.
- **Log shipping**: If using WAL shipping or external log sinks, verify replication/log shipping is
  running and recent.
- **Change window**: Announce maintenance windows when migrations run; pause background tasks that
  could contend with migration locks.
- **Post-deploy verification**: After deploy, run smoke checks and confirm new migrations have
  reached the expected head.
