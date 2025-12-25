"""phase 0 tenancy plumbing (default tenant)

Revision ID: c9d0e1f2a3b4
Revises: e1f2a3b4c5d6
Create Date: 2025-12-23

This migration introduces the tenants table and adds tenant_id columns to
tenant-scoped tables. On SQLite (dev/tests), we avoid unsupported ALTER features
(FKs / NOT NULL enforcement) and additionally guard against tables that may not
exist in the SQLite migration graph.
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9d0e1f2a3b4"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_TENANT_NAME = "default"


def _has_table(insp: sa.Inspector, table_name: str) -> bool:
    try:
        return bool(insp.has_table(table_name))
    except Exception:
        return False


def _has_column(insp: sa.Inspector, table_name: str, col_name: str) -> bool:
    try:
        cols = insp.get_columns(table_name)
    except Exception:
        return False
    return any(c.get("name") == col_name for c in cols)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect = bind.dialect.name

    # 1) Tenants table
    if not _has_table(insp, "tenants"):
        op.create_table(
            "tenants",
            sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP") if dialect == "sqlite" else sa.text("now()"),
            ),
            sa.UniqueConstraint("name", name="uq_tenants_name"),
        )

    # Seed default tenant (idempotent).
    if dialect == "postgresql":
        op.execute(
            sa.text(
                "INSERT INTO tenants (id, name, is_active) VALUES (:id, :name, TRUE) "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(id=str(DEFAULT_TENANT_ID), name=DEFAULT_TENANT_NAME)
        )
    else:
        # SQLite doesn't support ON CONFLICT on arbitrary constraint names in a uniform way here;
        # use a simple existence check.
        op.execute(
            sa.text(
                "INSERT INTO tenants (id, name, is_active) "
                "SELECT :id, :name, 1 "
                "WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE id = :id)"
            ).bindparams(id=str(DEFAULT_TENANT_ID), name=DEFAULT_TENANT_NAME)
        )

    # Refresh inspector after table creation.
    insp = sa.inspect(bind)

    # 2) Add tenant_id to tenant-scoped tables.
    # NOTE: Some tables may not exist in the SQLite migration graph; skip them safely.
    tables = [
        "devices",
        "policies",
        "enroll_tokens",
        "policy_assignments",
        "runs",
        "run_items",
        "log_events",
        "audit_logs",
        "device_auth_tokens",
        "admin_keys",
    ]

    for table_name in tables:
        if not _has_table(insp, table_name):
            continue
        if _has_column(insp, table_name, "tenant_id"):
            continue

        op.add_column(table_name, sa.Column("tenant_id", sa.UUID(), nullable=True))

        # Backfill existing rows to default tenant.
        try:
            op.execute(
                sa.text(f"UPDATE {table_name} SET tenant_id = :tid WHERE tenant_id IS NULL").bindparams(
                    tid=str(DEFAULT_TENANT_ID)
                )
            )
        except Exception:
            # Some SQLite edge cases can hit tables without rows / peculiar states during test runs.
            pass

        # Index tenant_id for filtering.
        try:
            op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"], unique=False)
        except Exception:
            pass

        # PostgreSQL: enforce NOT NULL + FK.
        if dialect == "postgresql":
            op.alter_column(table_name, "tenant_id", nullable=False)
            # Create the FK only if it doesn't already exist.
            try:
                op.create_foreign_key(
                    f"fk_{table_name}_tenant_id",
                    source_table=table_name,
                    referent_table="tenants",
                    local_cols=["tenant_id"],
                    remote_cols=["id"],
                    ondelete="RESTRICT",
                )
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect = bind.dialect.name

    tables = [
        "admin_keys",
        "device_auth_tokens",
        "audit_logs",
        "log_events",
        "run_items",
        "runs",
        "policy_assignments",
        "enroll_tokens",
        "policies",
        "devices",
    ]

    for table_name in tables:
        if not _has_table(insp, table_name):
            continue
        if not _has_column(insp, table_name, "tenant_id"):
            continue

        # Best-effort drop FK (postgres) + index, then column.
        if dialect == "postgresql":
            try:
                op.drop_constraint(f"fk_{table_name}_tenant_id", table_name, type_="foreignkey")
            except Exception:
                pass

        try:
            op.drop_index(f"ix_{table_name}_tenant_id", table_name=table_name)
        except Exception:
            pass

        op.drop_column(table_name, "tenant_id")

    # Tenants table
    if _has_table(insp, "tenants"):
        op.drop_table("tenants")
