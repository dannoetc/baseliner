"""add run_items (run_id, ordinal) index

Revision ID: c2a9d2f9a3b1
Revises: 8d3b1c2a7f4e
Create Date: 2025-12-16
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c2a9d2f9a3b1"
down_revision = "8d3b1c2a7f4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_run_items_run_id_ordinal",
        "run_items",
        ["run_id", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_items_run_id_ordinal", table_name="run_items")
