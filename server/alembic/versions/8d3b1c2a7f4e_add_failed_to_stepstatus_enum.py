"""add 'failed' to stepstatus enum

Revision ID: 8d3b1c2a7f4e
Revises: 51a4f5ea4b18
Create Date: 2025-12-18

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "8d3b1c2a7f4e"
down_revision = "51a4f5ea4b18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL uses a real ENUM type; SQLite uses a CHECK constraint for SQLAlchemy Enum
    # and does not require (or support) altering a type. So this migration is a no-op on SQLite.
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                WHERE t.typname = 'stepstatus'
                  AND e.enumlabel = 'failed'
            ) THEN
                ALTER TYPE stepstatus ADD VALUE 'failed';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # PostgreSQL cannot easily remove an enum value without a type rebuild; keep as no-op.
    return
