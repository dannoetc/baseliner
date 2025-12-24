"""merge alembic heads

Revision ID: 0f13df607edd
Revises: 80db49404b4c, 1e9c7f65bd41
Create Date: 2025-12-24 16:45:17.787210

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "0f13df607edd"
down_revision: Union[str, None] = ("80db49404b4c", "1e9c7f65bd41")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
