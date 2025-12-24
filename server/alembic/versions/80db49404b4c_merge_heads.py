"""merge heads

Revision ID: 80db49404b4c
Revises: b7c8d9e0a1b2, c9d0e1f2a3b4
Create Date: 2025-12-24 01:50:38.532095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80db49404b4c'
down_revision: Union[str, None] = ('b7c8d9e0a1b2', 'c9d0e1f2a3b4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
