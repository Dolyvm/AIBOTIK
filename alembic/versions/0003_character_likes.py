"""add character_likes table

Revision ID: 0003_character_likes
Revises: 0002_monthly_usage_bonus
Create Date: 2026-04-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003_character_likes'
down_revision: Union[str, None] = '0002_monthly_usage_bonus'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'character_likes',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('character_id', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'character_id'),
    )
    op.create_index('ix_character_likes_character_id', 'character_likes', ['character_id'])


def downgrade() -> None:
    op.drop_index('ix_character_likes_character_id', table_name='character_likes')
    op.drop_table('character_likes')
