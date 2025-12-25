"""Create admin_keys table

Revision ID: 4f9d3e1a0c21
Revises: 2c7b6c4f2ad1
Create Date: 2025-12-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "4f9d3e1a0c21"
down_revision = "2c7b6c4f2ad1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the enum type used by admin_keys.scope (Postgres)
    adminscope = sa.Enum("superadmin", "tenant_admin", name="adminscope")
    adminscope.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "admin_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "scope",
            adminscope,
            nullable=False,
            server_default=sa.text("'tenant_admin'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
    )

    # Composite tenant-scoped uniqueness
    op.create_index(
        "uq_admin_keys_tenant_id_key_hash",
        "admin_keys",
        ["tenant_id", "key_hash"],
        unique=True,
    )

    # Helpful lookup index
    op.create_index(
        "ix_admin_keys_tenant_id",
        "admin_keys",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_keys_tenant_id", table_name="admin_keys")
    op.drop_index("uq_admin_keys_tenant_id_key_hash", table_name="admin_keys")
    op.drop_table("admin_keys")

    adminscope = sa.Enum("superadmin", "tenant_admin", name="adminscope")
    adminscope.drop(op.get_bind(), checkfirst=True)
