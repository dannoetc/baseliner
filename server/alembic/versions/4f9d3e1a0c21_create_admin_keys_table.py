"""Create admin_keys table

Revision ID: 4f9d3e1a0c21
Revises: 2c7b6c4f2ad1
Create Date: 2025-12-24

SQLite compatibility notes:
- SQLite does not support a native UUID type name; use a string variant.
- SQLite does not have `now()`; use CURRENT_TIMESTAMP.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "4f9d3e1a0c21"
down_revision = "2c7b6c4f2ad1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    UUID_COL = sa.UUID().with_variant(sa.String(36), "sqlite")

    created_at_default = sa.text("CURRENT_TIMESTAMP") if dialect == "sqlite" else sa.text("now()")

    adminscope = sa.Enum("superadmin", "tenant_admin", name="adminscope")

    # On PostgreSQL, ensure the ENUM exists; on SQLite it becomes a CHECK constraint.
    if dialect == "postgresql":
        adminscope.create(bind, checkfirst=True)

    op.create_table(
        "admin_keys",
        sa.Column("id", UUID_COL, nullable=False),
        sa.Column("tenant_id", UUID_COL, nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("scope", adminscope, nullable=False, server_default="tenant_admin"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=created_at_default),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "key_hash", name="uq_admin_keys_tenant_id_key_hash"),
    )

    op.create_index("ix_admin_keys_tenant_id", "admin_keys", ["tenant_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.drop_index("ix_admin_keys_tenant_id", table_name="admin_keys")
    op.drop_table("admin_keys")

    if dialect == "postgresql":
        adminscope = sa.Enum("superadmin", "tenant_admin", name="adminscope")
        adminscope.drop(bind, checkfirst=True)
