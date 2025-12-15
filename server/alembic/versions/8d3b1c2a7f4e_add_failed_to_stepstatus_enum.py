"""add 'failed' to stepstatus enum

Revision ID: 8d3b1c2a7f4e
Revises: 51a4f5ea4b18
Create Date: 2025-12-13
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "8d3b1c2a7f4e"
down_revision = "51a4f5ea4b18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres enums are global types; add the new label if it doesn't already exist.
    # We avoid ALTER TYPE ... IF NOT EXISTS for compatibility across PG versions.
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
    # Postgres does not support dropping enum values directly.
    # If you ever need to remove 'failed', you'd have to do a type-swap migration.
    pass
