"""add audit log

Revision ID: a3f4b5c6d7e8
Revises: 6b7c8d9e0f1a
Create Date: 2025-12-21 00:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


JSON_COL = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()),
    "postgresql",
)
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f4b5c6d7e8"
down_revision: Union[str, None] = "6b7c8d9e0f1a"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("request_method", sa.String(length=8), nullable=True),
        sa.Column("request_path", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("remote_addr", sa.String(length=64), nullable=True),
        sa.Column("data", JSON_COL, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_audit_logs_ts", "audit_logs", ["ts"], unique=False)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index(
        "ix_audit_logs_target", "audit_logs", ["target_type", "target_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_target", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_ts", table_name="audit_logs")
    op.drop_table("audit_logs")
