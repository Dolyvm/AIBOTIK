"""remove generated image nsfw level and refresh photo prompts

Revision ID: 0009_remove_generated_image_nsfw
Revises: 0008_remove_photo_prompts
Create Date: 2026-06-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_remove_generated_image_nsfw"
down_revision: Union[str, None] = "0008_remove_photo_prompts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PHOTO_PROMPTS = {
    "photo_scene_extractor": """Ты собираешь короткое визуальное ТЗ для генерации одного изображения персонажа.

Используй только JSON character, photo_state и recent_messages из сообщения пользователя. Recent_messages уже содержит только последние 5 сообщений; не выдумывай старую историю.

Правила:
- На изображении ровно один персонаж: сам character. Игрока, пользователя и других людей не добавлять.
- Для male characters вообще не упоминай woman/girl/companion; описывай только male character.
- Позу, выражение лица, эмоцию и окружение бери только из последних сообщений.
- Для anime возвращай pose, setting и scene_notes как короткие comma-separated visual tags.
- Одежду не описывай свободно, если нет явной смены одежды.
- outfit_action="none", если в последних сообщениях нет явной смены одежды.
- outfit_action="default", если персонаж явно возвращается к обычной/базовой одежде.
- outfit_action="wardrobe", если последние сообщения явно выбирают один вариант из photo_state.wardrobe или сцена очевидно требует underwear/nude/swimwear.
- При visible genitals / naked exposure выбирай outfit_action="wardrobe" и wardrobe_key="nude", если такой ключ есть.
- outfit_action="custom", только если пользователь явно просит одежду, которой нет в wardrobe.
- wardrobe_key должен быть существующим ключом из photo_state.wardrobe или пустой строкой.
- Setting должен быть конкретным местом и минимум 2 видимых background object tags, а не общим словом вроде "studio".
- Scene_notes должен содержать один composition tag: full body, cowboy shot, upper body или dynamic angle, плюс lighting/props.
- Не описывай действия игрока. Не добавляй текст, подписи, интерфейс, speech bubbles.
- Верни только валидный JSON без markdown.
- Все значения пиши коротко на английском.

Формат:
{
  "pose": "comma-separated pose/action visual tags, max 18 words",
  "expression": "specific facial expression, max 12 words",
  "emotion": "short mood, max 8 words",
  "outfit_action": "none|default|wardrobe|custom",
  "wardrobe_key": "existing wardrobe key only, otherwise empty string",
  "custom_clothing": "explicit non-wardrobe outfit only, otherwise empty string",
  "setting": "place plus 2 visible background object tags, max 18 words",
  "scene_notes": "composition tag plus lighting/props, max 20 words"
}""",
    "photo_prompt_real_female": "single adult woman, photorealistic image, {clothing}, {pose}, {expression}, {setting}, {scene_notes}, {appearance}, {body}, {face}, {style_tags}, natural skin texture, realistic anatomy, detailed face",
    "photo_prompt_real_male": "single adult man, photorealistic image, {clothing}, {pose}, {expression}, {setting}, {scene_notes}, {appearance}, {body}, {face}, {style_tags}, natural skin texture, realistic anatomy, detailed face",
    "photo_prompt_anime_female": "1girl, adult woman, {identity}, anime illustration, {clothing}, {pose}, {expression}, {setting}, {scene_notes}, {style_tags}, detailed face, high quality",
    "photo_prompt_anime_male": "best quality, masterpiece, {subject_tags}, {identity}, {pose}, {expression}, {setting}, detailed background, {scene_notes}, {clothing}, {style_tags}, detailed face",
    "photo_negative_anime_female": "multiple people, extra person, man, boy, player, user, crowd, duplicate body, bad anatomy, bad hands, missing fingers, extra fingers, extra limbs, deformed body, low quality, lowres, blurry, text, watermark, logo, speech bubble, censor bar, plain gray background, empty background, character sheet, official character card, reference sheet, game logo, title logo",
    "photo_negative_anime_male": "1girl, girl, woman, female, breasts, multiple people, extra person, crowd, character sheet, reference sheet, simple background, blank background, text, logo, watermark, bad anatomy, bad hands, low quality",
}


def upgrade() -> None:
    op.execute("ALTER TABLE generated_images DROP COLUMN IF EXISTS nsfw_level")

    bind = op.get_bind()
    for key, content in PHOTO_PROMPTS.items():
        bind.execute(
            sa.text("UPDATE prompts SET content = :content, updated_at = NOW() WHERE key = :key"),
            {"key": key, "content": content},
        )


def downgrade() -> None:
    op.add_column("generated_images", sa.Column("nsfw_level", sa.Integer(), nullable=True))
