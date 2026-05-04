"""add chat target index for message counters

Revision ID: 0006_chat_msg_count_idx
Revises: 0005_verification_invariant
Create Date: 2026-05-04

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006_chat_msg_count_idx"
down_revision: Union[str, None] = "0005_verification_invariant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chats_chat_type_target_id_id "
            "ON chats (chat_type, target_id, id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chats_chat_type_target_id_id")
