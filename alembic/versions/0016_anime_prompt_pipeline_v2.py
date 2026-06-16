"""anime prompt pipeline v2

Revision ID: 0016_anime_prompt_pipeline_v2
Revises: 0015_image_generation_jobs
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0016_anime_prompt_pipeline_v2"
down_revision: Union[str, None] = "0015_image_generation_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PHOTO_SCENE_EXTRACTOR = """Ты собираешь короткое визуальное ТЗ для генерации одного изображения персонажа.

Используй только JSON character, photo_state и recent_messages из сообщения пользователя. Recent_messages уже содержит только последние 5 сообщений; не выдумывай старую историю.

Правила:
- На изображении ровно один персонаж: сам character. Игрока, пользователя и других людей не добавлять.
- Для male characters не упоминай woman/girl/companion; описывай только male character.
- Позу, выражение лица, эмоцию и окружение бери только из последних сообщений.
- Не добавляй clothing/outfit tags в pose, setting или composition.
- primary_pose — только положение тела или действие. Не используй looking at viewer, hands, camera angle или framing как primary_pose.
- pose_modifiers — gaze, hands, legs, small secondary pose details.
- composition — кадрирование/угол: full body, cowboy shot, upper body, dynamic angle, close-up.
- setting разделяй на place, background_objects и lighting.
- exposure_intent: safe, nude или explicit_focus. Nude/naked без явного visible/expose гениталий = nude, не explicit_focus.
- Одежда заблокирована через photo_state.current_outfit. Не меняй её по настроению, локации, позе или общей атмосфере.
- outfit_action="none" почти всегда: если в последних сообщениях нет явной смены одежды, раздевания или возврата к обычной одежде.
- outfit_action="default", только если персонаж явно возвращается к обычной/базовой одежде.
- outfit_action="wardrobe", только если последние сообщения явно выбирают один вариант из photo_state.wardrobe или сцена очевидно требует underwear/nude/swimwear.
- При nude/naked выбирай outfit_action="wardrobe" и wardrobe_key="nude", если такой ключ есть.
- outfit_action="custom", только если пользователь явно просит одежду, которой нет в wardrobe, в том числе nude.
- wardrobe_key должен быть существующим ключом из photo_state.wardrobe или пустой строкой.
- custom_clothing не заполняй, если outfit_action не "custom".
- Не описывай действия игрока. Не добавляй текст, подписи, интерфейс, speech bubbles.
- Верни только валидный JSON без markdown.
- Все значения пиши коротко на английском.

Формат:
{
  "primary_pose": "body pose/action only, max 6 words",
  "pose_modifiers": "comma-separated gaze/hands/legs details, max 8 words",
  "expression": "specific facial expression, max 3 words",
  "emotion": "short mood, max 3 words",
  "composition": "single framing/camera tag",
  "place": "specific place",
  "background_objects": "2-3 visible background object tags",
  "lighting": "short lighting tag",
  "exposure_intent": "safe|nude|explicit_focus",
  "outfit_action": "none|default|wardrobe|custom",
  "wardrobe_key": "existing wardrobe key only, otherwise empty string",
  "custom_clothing": "explicit non-wardrobe outfit only, otherwise empty string"
}"""


PHOTO_PROMPTS = {
    "photo_scene_extractor": {
        "name": "Photo Scene Extractor",
        "content": PHOTO_SCENE_EXTRACTOR,
    },
    "photo_prompt_anime_female": {
        "name": "Photo Prompt: Anime Female",
        "content": "{subject_tags}, {appearance}, {body}, {face}, {clothing}, {rating_tags}, {nudity_tags}, {focus_tags}, {expression}, {pose}, {composition}, {setting}, {style_tags}, {quality_tags}",
    },
    "photo_prompt_anime_male": {
        "name": "Photo Prompt: Anime Male",
        "content": "{subject_tags}, {appearance}, {body}, {face}, {clothing}, {rating_tags}, {nudity_tags}, {focus_tags}, {expression}, {pose}, {composition}, {setting}, {style_tags}, {quality_tags}",
    },
    "photo_negative_anime_female": {
        "name": "Photo Negative Prompt: Anime Female",
        "content": "multiple people, man, boy, bad anatomy, bad hands, extra fingers, low quality, text, watermark, logo, cropped, out of frame",
    },
    "photo_negative_anime_male": {
        "name": "Photo Negative Prompt: Anime Male",
        "content": "woman, girl, multiple people, bad anatomy, bad hands, low quality, text, watermark, logo, cropped, out of frame",
    },
}


def upgrade() -> None:
    op.add_column(
        "generated_images",
        sa.Column(
            "prompt_metadata",
            JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("generated_images", "prompt_metadata", server_default=None)

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
    op.drop_column("generated_images", "prompt_metadata")
