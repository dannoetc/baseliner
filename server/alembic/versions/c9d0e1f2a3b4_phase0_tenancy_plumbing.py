"""phase 0 tenancy plumbing (default tenant)

Revision ID: c9d0e1f2a3b4
Revises: e1f2a3b4c5d6
Create Date: 2025-12-23

"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "c9d0e1f2a3b4"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_TENANT_NAME = "default"


def upgrade() -> None:
    # 1) Tenants table
    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_tenants_name", "tenants", ["name"], unique=False)

    # Insert default tenant row (best-effort: ignore if it already exists).
    tenants_tbl = sa.table(
        "tenants",
        sa.column("id", sa.UUID()),
        sa.column("name", sa.String()),
    )
    op.bulk_insert(
        tenants_tbl,
        [
            {
                "id": DEFAULT_TENANT_ID,
                "name": DEFAULT_TENANT_NAME,
            }
        ],
    )

    # 2) Add tenant_id columns (nullable first), backfill, then enforce NOT NULL + FKs.
    tables = [
        ("devices", "ix_devices_tenant_id", ["tenant_id"]),
        ("device_auth_tokens", "ix_device_auth_tokens_tenant_id", ["tenant_id"]),
        ("enroll_tokens", "ix_enroll_tokens_tenant_id", ["tenant_id"]),
        ("audit_logs", "ix_audit_logs_tenant_id_ts", ["tenant_id", "ts"]),
        ("policies", "ix_policies_tenant_id", ["tenant_id"]),
        ("policy_assignments", "ix_policy_assignments_tenant_id", ["tenant_id"]),
        ("runs", "ix_runs_tenant_id_started_at", ["tenant_id", "started_at"]),
        ("run_items", "ix_run_items_tenant_id_run_id", ["tenant_id", "run_id"]),
        ("log_events", "ix_log_events_tenant_id_run_id_ts", ["tenant_id", "run_id", "ts"]),
    ]

    for table_name, index_name, index_cols in tables:
        op.add_column(table_name, sa.Column("tenant_id", sa.UUID(), nullable=True))
        op.create_index(index_name, table_name, index_cols, unique=False)

    # Backfill: set tenant_id on existing rows.
    for table_name, _, _ in tables:
        op.execute(
            sa.text(f"UPDATE {table_name} SET tenant_id = :tid WHERE tenant_id IS NULL").bindparams(
                sa.bindparam("tid", value=DEFAULT_TENANT_ID, type_=sa.UUID())
            )
        )

    # Enforce NOT NULL + add FKs.
    for table_name, _, _ in tables:
        op.alter_column(table_name, "tenant_id", existing_type=sa.UUID(), nullable=False)
        op.create_foreign_key(
            f"fk_{table_name}_tenant_id",
            table_name,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    # Drop FKs + columns in reverse dependency order.
    tables = [
        ("log_events", "ix_log_events_tenant_id_run_id_ts"),
        ("run_items", "ix_run_items_tenant_id_run_id"),
        ("runs", "ix_runs_tenant_id_started_at"),
        ("policy_assignments", "ix_policy_assignments_tenant_id"),
        ("policies", "ix_policies_tenant_id"),
        ("audit_logs", "ix_audit_logs_tenant_id_ts"),
        ("enroll_tokens", "ix_enroll_tokens_tenant_id"),
        ("device_auth_tokens", "ix_device_auth_tokens_tenant_id"),
        ("devices", "ix_devices_tenant_id"),
    ]

    for table_name, index_name in tables:
        op.drop_constraint(f"fk_{table_name}_tenant_id", table_name, type_="foreignkey")
        op.drop_index(index_name, table_name=table_name)
        op.drop_column(table_name, "tenant_id")

    op.drop_index("ix_tenants_name", table_name="tenants")
    op.drop_table("tenants")
