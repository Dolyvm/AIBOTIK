"""gender specific anime nsfw prompt tags

Revision ID: 0014_gender_anime_nsfw_tags
Revises: 0013_anime_explicit_detail_tags
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_gender_anime_nsfw_tags"
down_revision: Union[str, None] = "0013_anime_explicit_detail_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PHOTO_PROMPTS = {
    "photo_prompt_anime_female": {
        "name": "Photo Prompt: Anime Female",
        "content": "{subject_tags}, {identity}, {rating_tags}, adult, {appearance}, {body}, {clothing}, {explicit_detail_tags}, {expression}, {pose}, {setting}, {scene_notes}, {style_tags}, {quality_tags}",
    },
    "photo_prompt_anime_male": {
        "name": "Photo Prompt: Anime Male",
        "content": "{subject_tags}, {identity}, {rating_tags}, adult, {appearance}, {body}, {clothing}, {explicit_detail_tags}, {expression}, {pose}, {setting}, {scene_notes}, {style_tags}, {quality_tags}",
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    statement = sa.text(
        """
        UPDATE prompts
        SET name = :name,
            content = :content,
            updated_at = NOW()
        WHERE key = :key
        """
    )
    for key, prompt in PHOTO_PROMPTS.items():
        bind.execute(statement, {"key": key, **prompt})


def downgrade() -> None:
    pass
