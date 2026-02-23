"""add short_description to characters and worlds

Revision ID: f7a1b2c3d4e5
Revises: ae460fad6849
Create Date: 2026-02-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a1b2c3d4e5'
down_revision: Union[str, None] = 'ae460fad6849'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('short_description', sa.String(30), nullable=True, server_default=''))
    op.add_column('worlds', sa.Column('short_description', sa.String(30), nullable=True, server_default=''))


def downgrade() -> None:
    op.drop_column('worlds', 'short_description')
    op.drop_column('characters', 'short_description')
