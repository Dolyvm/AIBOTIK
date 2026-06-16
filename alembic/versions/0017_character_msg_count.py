"""add character total message count

Revision ID: 0017_character_msg_count
Revises: 0016_anime_prompt_pipeline_v2
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0017_character_msg_count"
down_revision: Union[str, None] = "0016_anime_prompt_pipeline_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE characters
        ADD COLUMN IF NOT EXISTS total_message_count INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        UPDATE characters AS c
        SET total_message_count = COALESCE(counts.message_count, 0)
        FROM (
            SELECT chats.target_id, COUNT(messages.id)::integer AS message_count
            FROM chats
            JOIN messages ON messages.chat_id = chats.id
            WHERE chats.chat_type = 'character'
            GROUP BY chats.target_id
        ) AS counts
        WHERE c.id = counts.target_id
          AND c.total_message_count = 0
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE characters
        DROP COLUMN IF EXISTS total_message_count
        """
    )
