"""verification system: is_verified for characters/worlds + is_public for worlds

Revision ID: 0004_verification_system
Revises: 0003_character_likes
Create Date: 2026-04-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0004_verification_system'
down_revision: Union[str, None] = '0003_character_likes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'characters',
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'worlds',
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'worlds',
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.execute(
        "UPDATE characters SET is_verified = TRUE, is_public = TRUE "
        "WHERE created_by_username_id IS NULL"
    )
    op.execute(
        "UPDATE worlds SET is_verified = TRUE, is_public = TRUE "
        "WHERE created_by_username_id IS NULL"
    )


def downgrade() -> None:
    op.drop_column('worlds', 'is_public')
    op.drop_column('worlds', 'is_verified')
    op.drop_column('characters', 'is_verified')
