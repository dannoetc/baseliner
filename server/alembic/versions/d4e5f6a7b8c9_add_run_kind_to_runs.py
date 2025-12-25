"""add run kind to runs

Revision ID: d4e5f6a7b8c9
Revises: f3a1d2c4b5e6
Create Date: 2025-12-22
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "f3a1d2c4b5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Create enum type (postgres) / check constraint (sqlite).
    runkind = sa.Enum("apply", "heartbeat", name="runkind")
    runkind.create(bind, checkfirst=True)

    op.add_column(
        "runs",
        sa.Column(
            "kind",
            runkind,
            nullable=False,
            server_default="apply",
        ),
    )

    # Backfill existing rows (mainly for sqlite).
    try:
        op.execute("UPDATE runs SET kind = 'apply' WHERE kind IS NULL")
    except Exception:
        pass

    # SQLite cannot DROP DEFAULT via ALTER COLUMN; leaving the default in place is fine for dev/tests.
    if bind.dialect.name != "sqlite":
        op.alter_column("runs", "kind", server_default=None)

    op.create_index(
        "ix_runs_device_id_kind_started_at",
        "runs",
        ["device_id", "kind", "started_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_runs_device_id_kind_started_at", table_name="runs")
    op.drop_column("runs", "kind")

    runkind = sa.Enum("apply", "heartbeat", name="runkind")
    runkind.drop(bind, checkfirst=True)
