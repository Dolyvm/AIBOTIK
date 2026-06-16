"""add anime rating and framing prompt tags

Revision ID: 0012_anime_nsfw_prompt_tags
Revises: 0011_photo_outfit_stability
Create Date: 2026-06-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_anime_nsfw_prompt_tags"
down_revision: Union[str, None] = "0011_photo_outfit_stability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PHOTO_SCENE_EXTRACTOR = """Ты собираешь короткое визуальное ТЗ для генерации одного изображения персонажа.

Используй только JSON character, photo_state и recent_messages из сообщения пользователя. Recent_messages уже содержит только последние 5 сообщений; не выдумывай старую историю.

Правила:
- На изображении ровно один персонаж: сам character. Игрока, пользователя и других людей не добавлять.
- Для male characters вообще не упоминай woman/girl/companion; описывай только male character.
- Позу, выражение лица, эмоцию и окружение бери только из последних сообщений.
- Для anime возвращай pose, setting и scene_notes как короткие comma-separated visual tags.
- Одежда заблокирована через photo_state.current_outfit. Не меняй её по настроению, локации, позе или общей атмосфере.
- outfit_action="none" почти всегда: если в последних сообщениях нет явной смены одежды, раздевания или возврата к обычной одежде.
- outfit_action="default", только если персонаж явно возвращается к обычной/базовой одежде.
- outfit_action="wardrobe", только если последние сообщения явно выбирают один вариант из photo_state.wardrobe или сцена очевидно требует underwear/nude/swimwear.
- При visible genitals / naked exposure выбирай outfit_action="wardrobe" и wardrobe_key="nude", если такой ключ есть.
- outfit_action="custom", только если пользователь явно просит одежду, которой нет в wardrobe, в том числе nude.
- wardrobe_key должен быть существующим ключом из photo_state.wardrobe или пустой строкой.
- custom_clothing не заполняй, если outfit_action не "custom".
- Не добавляй clothing/outfit tags в pose, setting или scene_notes.
- Setting должен быть конкретным местом и минимум 2 видимых background object tags, а не общим словом вроде "studio".
- Scene_notes должен содержать один composition tag: full body, cowboy shot, upper body или dynamic angle, плюс lighting/props.
- Для nude/naked/exposure сцен не выбирай upper body, portrait, close-up или cropped; выбирай full body или cowboy shot.
- Не описывай действия игрока. Не добавляй текст, подписи, интерфейс, speech bubbles.
- Верни только валидный JSON без markdown.
- Все значения пиши коротко на английском.

Формат:
{
  "pose": "comma-separated pose/action visual tags, max 4 words",
  "expression": "specific facial expression, max 3 words",
  "emotion": "short mood, max 3 words",
  "outfit_action": "none|default|wardrobe|custom",
  "wardrobe_key": "existing wardrobe key only, otherwise empty string",
  "custom_clothing": "explicit non-wardrobe outfit only, otherwise empty string",
  "setting": "place plus 2 visible background object tags, max 5 words",
  "scene_notes": "composition tag plus lighting/props, max 5 words"
}"""


PHOTO_PROMPTS = {
    "photo_scene_extractor": {
        "name": "Photo Scene Extractor",
        "content": PHOTO_SCENE_EXTRACTOR,
    },
    "photo_prompt_real_female": {
        "name": "Photo Prompt: Real Female",
        "content": "single adult woman, {clothing}, {pose}, {expression}, {setting}, {scene_notes}, {appearance}, {body}, {face}, {style_tags}",
    },
    "photo_prompt_real_male": {
        "name": "Photo Prompt: Real Male",
        "content": "single adult man, {clothing}, {pose}, {expression}, {setting}, {scene_notes}, {appearance}, {body}, {face}, {style_tags},",
    },
    "photo_prompt_anime_female": {
        "name": "Photo Prompt: Anime Female",
        "content": "{subject_tags}, {identity}, {rating_tags}, adult, {appearance}, {body}, {clothing}, {expression}, {pose}, {setting}, {scene_notes}, {style_tags}, {quality_tags}",
    },
    "photo_prompt_anime_male": {
        "name": "Photo Prompt: Anime Male",
        "content": "{subject_tags}, {identity}, {rating_tags}, adult, {appearance}, {body}, {clothing}, {expression}, {pose}, {setting}, {scene_notes}, {style_tags}, {quality_tags}",
    },
    "photo_negative_anime_female": {
        "name": "Photo Negative Prompt: Anime Female",
        "content": "multiple people, man, boy, bad anatomy, bad hands, extra fingers, low quality, text, watermark, logo, censored, censor bar, mosaic censoring, cropped, out of frame",
    },
    "photo_negative_anime_male": {
        "name": "Photo Negative Prompt: Anime Male",
        "content": "woman, girl, multiple people, bad anatomy, bad hands, low quality, text, watermark, logo, censored, censor bar, mosaic censoring, cropped, out of frame",
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
