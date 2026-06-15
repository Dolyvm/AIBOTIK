"""compact anime photo prompts

Revision ID: 0010_compact_anime_prompts
Revises: 0009_remove_generated_image_nsfw
Create Date: 2026-06-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_compact_anime_prompts"
down_revision: Union[str, None] = "0009_remove_generated_image_nsfw"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PHOTO_PROMPTS = {
    "photo_scene_extractor": {
        "name": "Photo Scene Extractor",
        "content": """Ты собираешь короткое визуальное ТЗ для генерации одного изображения персонажа.

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
    },
    "photo_prompt_real_female": {
        "name": "Photo Prompt: Real Female",
        "content": "single woman, {clothing}, {pose}, {expression}, {setting}, {scene_notes}, {appearance}, {body}, {face}, {style_tags}",
    },
    "photo_prompt_real_male": {
        "name": "Photo Prompt: Real Male",
        "content": "single man, {clothing}, {pose}, {expression}, {setting}, {scene_notes}, {appearance}, {body}, {face}, {style_tags}",
    },
    "photo_prompt_anime_female": {
        "name": "Photo Prompt: Anime Female",
        "content": "{setting}, {subject_tags}, {identity}, {body}, {clothing}, {expression}, {pose}, {scene_notes}, {style_tags}",
    },
    "photo_prompt_anime_male": {
        "name": "Photo Prompt: Anime Male",
        "content": "{setting}, {subject_tags}, {identity}, {body}, {clothing}, {expression}, {pose}, {scene_notes}, {style_tags}",
    },
    "photo_negative_anime_female": {
        "name": "Photo Negative Prompt: Anime Female",
        "content": "multiple people, extra person, man, boy, bad anatomy, bad hands, text, watermark, logo",
    },
    "photo_negative_anime_male": {
        "name": "Photo Negative Prompt: Anime Male",
        "content": "woman, girl, multiple people, bad anatomy, bad hands, text, watermark, logo",
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    statement = sa.text(
        """
        INSERT INTO prompts (key, category, name, content, updated_at)
        VALUES (:key, 'photo', :name, :content, NOW())
        ON CONFLICT (key) DO UPDATE SET
            category = EXCLUDED.category,
            name = EXCLUDED.name,
            content = EXCLUDED.content,
            updated_at = NOW()
        """
    )
    for key, prompt in PHOTO_PROMPTS.items():
        bind.execute(statement, {"key": key, **prompt})


def downgrade() -> None:
    pass
