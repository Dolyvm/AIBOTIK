"""Add nickname to user_settings

Revision ID: a8b9c0d1e2f3
Revises: f7a1b2c3d4e5
Create Date: 2026-02-23 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'f7a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_settings', sa.Column('nickname', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('user_settings', 'nickname')
