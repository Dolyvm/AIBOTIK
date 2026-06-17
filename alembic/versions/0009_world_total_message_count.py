"""add persistent world message counters

Revision ID: 0009_world_total_message_count
Revises: 0008_sync_schema_after_0007
Create Date: 2026-06-17
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0009_world_total_message_count"
down_revision: Union[str, None] = "0008_sync_schema_after_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE worlds
        ADD COLUMN IF NOT EXISTS total_message_count INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        UPDATE worlds AS w
        SET total_message_count = COALESCE(counts.message_count, 0)
        FROM (
            SELECT chats.target_id, COUNT(messages.id)::integer AS message_count
            FROM chats
            JOIN messages ON messages.chat_id = chats.id
            WHERE chats.chat_type = 'world'
            GROUP BY chats.target_id
        ) AS counts
        WHERE w.id = counts.target_id
          AND w.total_message_count = 0
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE worlds DROP COLUMN IF EXISTS total_message_count")
