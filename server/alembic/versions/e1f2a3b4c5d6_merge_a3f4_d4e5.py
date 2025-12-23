"""Merge heads a3f4b5c6d7e8 and d4e5f6a7b8c9.

Revision ID: e1f2a3b4c5d6
Revises: a3f4b5c6d7e8, d4e5f6a7b8c9
Create Date: 2025-12-22

This is an Alembic *merge revision* to resolve multiple heads.
No schema changes occur here; it simply merges the audit-log head and
run-kind head into a single linear history.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, tuple[str, str], None] = (
    "a3f4b5c6d7e8",
    "d4e5f6a7b8c9",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge revision: no-op.
    pass


def downgrade() -> None:
    # Merge revision: no-op.
    pass
