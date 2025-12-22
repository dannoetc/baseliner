"""add correlation_id to runs

Revision ID: f3a1d2c4b5e6
Revises: c2a9d2f9a3b1
Create Date: 2025-12-18
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a1d2c4b5e6"
down_revision = "c2a9d2f9a3b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("correlation_id", sa.String(length=128), nullable=True))
    op.create_index("ix_runs_correlation_id", "runs", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_correlation_id", table_name="runs")
    op.drop_column("runs", "correlation_id")
