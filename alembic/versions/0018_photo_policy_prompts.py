"""add editable photo policy prompts

Revision ID: 0018_photo_policy_prompts
Revises: 0017_character_msg_count
Create Date: 2026-06-16 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018_photo_policy_prompts"
down_revision: Union[str, None] = "0017_character_msg_count"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PHOTO_POLICY_PROMPTS = [
    ("photo_policy_anime_filler_tags", "Anime Filler Tags", "anime style, anime illustration, detailed background, detailed face, high quality, best quality"),
    ("photo_policy_anime_user_quality_tags", "Anime User Quality Tags", "masterpiece, masterpiec, best quality, high quality, great quality, low quality, absurdres"),
    ("photo_policy_anime_rating_safe", "Anime Rating Tags: Safe", "safe"),
    ("photo_policy_anime_rating_nsfw", "Anime Rating Tags: NSFW", "nsfw"),
    ("photo_policy_anime_rating_explicit", "Anime Rating Tags: Explicit", "explicit, nsfw"),
    ("photo_policy_anime_nudity_tags", "Anime Nudity Tags", "nude"),
    ("photo_policy_anime_focus_tags", "Anime Focus Tags", "uncensored"),
    ("photo_policy_anime_quality_tags", "Anime Quality Tags", "high score, great score"),
    ("photo_policy_anime_avatar_quality_tags", "Anime Avatar Quality Tags", "high score"),
    ("photo_policy_anime_subject_female", "Anime Subject Tags: Female", "1girl, solo"),
    ("photo_policy_anime_subject_male", "Anime Subject Tags: Male", "1boy, solo"),
    ("photo_policy_anime_negative_explicit", "Anime Negative Tags: Explicit", "censored, censor bar, mosaic censoring"),
    ("photo_policy_avatar_scene", "Avatar Scene JSON", '{"pose":"looking at viewer","expression":"soft smile","composition":"upper body","setting":"simple background","exposure_intent":"safe","emotion":"calm","scene_notes":""}'),
    ("photo_policy_avatar_default_outfit", "Avatar Default Outfit", "casual outfit"),
    ("photo_policy_real_default_outfit", "Real Default Outfit", "casual modern outfit"),
    ("photo_policy_real_clothed_prefix", "Real Clothed Prefix", "fully clothed"),
    ("photo_policy_real_default_outfit_priority", "Real Outfit Wardrobe Priority", "casual, formal, business, office, everyday, sleepwear, gym"),
    ("photo_policy_default_style_tags_real", "Default Style Tags: Real", "soft natural lighting, film photography, warm tones"),
    ("photo_policy_default_style_tags_anime", "Default Style Tags: Anime", ""),
    ("photo_policy_default_style_tags_manhwa", "Default Style Tags: Manhwa", ""),
    ("photo_policy_manhwa_style_tags", "Manhwa Fallback Style Tags", "manhwa style, webtoon style, clean line art"),
    ("photo_policy_default_wardrobe_female", "Default Wardrobe JSON: Female", '{"nude":"nothing, showing her naked body","underwear":"white bra, white panties"}'),
    ("photo_policy_default_wardrobe_male", "Default Wardrobe JSON: Male", '{"nude":"nothing, showing his naked body","underwear":"black boxer briefs"}'),
]


def upgrade() -> None:
    bind = op.get_bind()
    statement = sa.text(
        """
        INSERT INTO prompts (key, category, name, content)
        VALUES (:key, 'photo_policy', :name, :content)
        ON CONFLICT (key) DO UPDATE
        SET category = EXCLUDED.category,
            name = EXCLUDED.name
        """
    )
    for key, name, content in PHOTO_POLICY_PROMPTS:
        bind.execute(statement, {"key": key, "name": name, "content": content})


def downgrade() -> None:
    bind = op.get_bind()
    statement = sa.text("DELETE FROM prompts WHERE key = :key")
    for key, _name, _content in PHOTO_POLICY_PROMPTS:
        bind.execute(statement, {"key": key})
