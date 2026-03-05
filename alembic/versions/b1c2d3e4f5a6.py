"""add author fields to worlds

Revision ID: b1c2d3e4f5a6
Revises: a8b9c0d1e2f3
Create Date: 2026-03-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('worlds', sa.Column('created_by_username_id', sa.BigInteger(), sa.ForeignKey('users.telegram_id', ondelete='SET NULL'), nullable=True))
    op.add_column('worlds', sa.Column('created_by_username', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('worlds', 'created_by_username')
    op.drop_column('worlds', 'created_by_username_id')
