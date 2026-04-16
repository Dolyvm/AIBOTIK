"""enforce verification invariant and repair state

Revision ID: 0005_verification_invariant
Revises: 0004_verification_system
Create Date: 2026-04-15

"""
from typing import Sequence, Union

from alembic import op

revision: str = '0005_verification_invariant'
down_revision: Union[str, None] = '0004_verification_system'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE characters SET is_verified = TRUE, is_public = TRUE "
        "WHERE created_by_username_id IS NULL"
    )
    op.execute(
        "UPDATE worlds SET is_verified = TRUE, is_public = TRUE "
        "WHERE created_by_username_id IS NULL"
    )

    op.execute("UPDATE characters SET is_verified = FALSE WHERE is_public = FALSE")
    op.execute("UPDATE worlds SET is_verified = FALSE WHERE is_public = FALSE")

    op.execute("UPDATE characters SET is_public = TRUE WHERE is_verified = TRUE")
    op.execute("UPDATE worlds SET is_public = TRUE WHERE is_verified = TRUE")


def downgrade() -> None:
    pass
