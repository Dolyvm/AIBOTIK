"""add gender to characters visual_data

Revision ID: d1e2f3a4b5c6
Revises: 17f615f52b5f
Create Date: 2026-03-21

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = '17f615f52b5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE characters
        SET visual_data = visual_data || '{"gender": "female"}'
        WHERE visual_data->>'gender' IS NULL
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE characters
        SET visual_data = visual_data - 'gender'
    """)
