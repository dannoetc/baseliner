"""add idempotency key to runs

Revision ID: 1e9c7f65bd41
Revises: f3a1d2c4b5e6
Create Date: 2025-02-20
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "1e9c7f65bd41"
down_revision = "f3a1d2c4b5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.create_unique_constraint(
        "uq_runs_device_id_idempotency_key", "runs", ["device_id", "idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_runs_device_id_idempotency_key", table_name="runs", type_="unique"
    )
    op.drop_column("runs", "idempotency_key")
