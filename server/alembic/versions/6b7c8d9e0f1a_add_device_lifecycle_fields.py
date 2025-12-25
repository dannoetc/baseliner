"""add device lifecycle fields (soft delete + token revocation)

Revision ID: 6b7c8d9e0f1a
Revises: f3a1d2c4b5e6
Create Date: 2025-12-20
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "6b7c8d9e0f1a"
down_revision = "f3a1d2c4b5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    device_status = sa.Enum("active", "deleted", name="devicestatus")
    bind = op.get_bind()
    device_status.create(bind, checkfirst=True)

    op.add_column(
        "devices",
        sa.Column("status", device_status, nullable=False, server_default="active"),
    )
    op.add_column("devices", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("deleted_reason", sa.Text(), nullable=True))

    op.add_column(
        "devices", sa.Column("token_revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "devices", sa.Column("revoked_auth_token_hash", sa.String(length=255), nullable=True)
    )

    op.create_index("ix_devices_status", "devices", ["status"])
    op.create_index("ix_devices_token_revoked_at", "devices", ["token_revoked_at"])

    # Avoid leaving a persistent default on the column.
    # SQLite cannot DROP DEFAULT via ALTER COLUMN; leaving it is fine for dev/tests.
    if bind.dialect.name != "sqlite":
        op.alter_column("devices", "status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_devices_token_revoked_at", table_name="devices")
    op.drop_index("ix_devices_status", table_name="devices")

    op.drop_column("devices", "revoked_auth_token_hash")
    op.drop_column("devices", "token_revoked_at")
    op.drop_column("devices", "deleted_reason")
    op.drop_column("devices", "deleted_at")
    op.drop_column("devices", "status")

    device_status = sa.Enum("active", "deleted", name="devicestatus")
    device_status.drop(op.get_bind(), checkfirst=True)
