"""add bonus limit columns to monthly_usage

Revision ID: 0002_monthly_usage_bonus
Revises: 0001_initial
Create Date: 2026-04-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002_monthly_usage_bonus'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('monthly_usage', sa.Column('bonus_messages_sent', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('monthly_usage', sa.Column('bonus_images_generated', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('monthly_usage', sa.Column('bonus_characters_created', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('monthly_usage', sa.Column('bonus_worlds_created', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('monthly_usage', sa.Column('bonus_content_edits', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('monthly_usage', sa.Column('bonus_avatar_generations', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('monthly_usage', 'bonus_avatar_generations')
    op.drop_column('monthly_usage', 'bonus_content_edits')
    op.drop_column('monthly_usage', 'bonus_worlds_created')
    op.drop_column('monthly_usage', 'bonus_characters_created')
    op.drop_column('monthly_usage', 'bonus_images_generated')
    op.drop_column('monthly_usage', 'bonus_messages_sent')
