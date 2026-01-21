"""add_unique_constraint_user_target

Revision ID: 7640c3edee72
Revises: 3f18c6807b1c
Create Date: 2026-01-21 07:45:31.966509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7640c3edee72'
down_revision: Union[str, None] = '3f18c6807b1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
