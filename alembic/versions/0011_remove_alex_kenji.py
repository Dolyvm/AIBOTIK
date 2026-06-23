"""remove alex and kenji system characters

Revision ID: 0011_remove_alex_kenji
Revises: 0010_nsfw_blur_wardrobe
Create Date: 2026-06-23
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0011_remove_alex_kenji"
down_revision: Union[str, None] = "0010_nsfw_blur_wardrobe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


REMOVED_CHARACTER_IDS = ("alex", "kenji")


def upgrade() -> None:
    quoted_ids = ", ".join(f"'{character_id}'" for character_id in REMOVED_CHARACTER_IDS)
    op.execute(
        f"""
        DELETE FROM chats
        WHERE chat_type = 'character'
          AND target_id IN ({quoted_ids})
        """
    )
    op.execute(
        f"""
        DELETE FROM characters
        WHERE id IN ({quoted_ids})
        """
    )
    op.execute(
        """
        DELETE FROM prompts
        WHERE key LIKE 'character_modifiers_alex_stage_%'
           OR key LIKE 'character_modifiers_kenji_stage_%'
        """
    )


def downgrade() -> None:
    pass
