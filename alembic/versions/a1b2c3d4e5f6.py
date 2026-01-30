"""add local_path to generated_images

Revision ID: a1b2c3d4e5f6
Revises: 946b1afaa646
Create Date: 2026-01-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '946b1afaa646'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем новые колонки
    op.add_column('generated_images',
        sa.Column('local_path', sa.String(length=500), nullable=True))
    op.add_column('generated_images',
        sa.Column('file_size', sa.Integer(), nullable=True))
    op.add_column('generated_images',
        sa.Column('content_type', sa.String(length=50), nullable=True))

    # Делаем provider_url nullable (для новых записей может быть пустым)
    op.alter_column('generated_images', 'provider_url',
        existing_type=sa.String(length=1000),
        nullable=True)


def downgrade() -> None:
    op.alter_column('generated_images', 'provider_url',
        existing_type=sa.String(length=1000),
        nullable=False)
    op.drop_column('generated_images', 'content_type')
    op.drop_column('generated_images', 'file_size')
    op.drop_column('generated_images', 'local_path')
