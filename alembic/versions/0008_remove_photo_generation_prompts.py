"""remove photo generation prompts

Revision ID: 0008_remove_photo_generation_prompts
Revises: 0007_platega_payments_no_auto_renew
Create Date: 2026-06-14
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0008_remove_photo_generation_prompts"
down_revision: Union[str, None] = "0007_platega_payments_no_auto_renew"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM prompts
        WHERE category IN ('image', 'scene_analysis')
           OR key LIKE 'nsfw_level_%'
           OR key IN (
                'anime_base_positive',
                'anime_base_negative',
                'real_base_positive',
                'real_base_negative',
                'real_base_positive_female',
                'real_base_negative_female',
                'real_base_positive_male',
                'real_base_negative_male',
                'manhwa_base_positive',
                'manhwa_base_negative',
                'scene_analyzer_prompt',
                'scene_analyzer_prompt_sfw'
           )
        """
    )


def downgrade() -> None:
    # Removed photo-generation prompts are intentionally not restored.
    pass
