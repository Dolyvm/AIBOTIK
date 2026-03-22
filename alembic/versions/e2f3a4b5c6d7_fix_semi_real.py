"""fix semi_real model_type to real

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-03-21

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE characters
        SET visual_data = jsonb_set(visual_data, '{model_type}', '"real"')
        WHERE visual_data->>'model_type' = 'semi_real'
    """)


def downgrade() -> None:
    pass
