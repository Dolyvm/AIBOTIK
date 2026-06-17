"""sync schema after platega payments

Revision ID: 0008_sync_schema_after_0007
Revises: 0007_platega_payments
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_sync_schema_after_0007"
down_revision: Union[str, None] = "0007_platega_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PHOTO_PROMPT_ROWS = [('photo_scene_extractor',
  'photo',
  'Photo Scene Extractor',
  'Ты собираешь короткое визуальное ТЗ для генерации одного изображения персонажа.\n'
  '\n'
  'Используй только JSON character, photo_state и recent_messages из сообщения пользователя. '
  'Recent_messages уже содержит только последние 5 сообщений; не выдумывай старую историю.\n'
  '\n'
  'Правила:\n'
  '- На изображении ровно один персонаж: сам character. Игрока, пользователя и других людей не '
  'добавлять.\n'
  '- Для male characters не упоминай woman/girl/companion; описывай только male character.\n'
  '- Позу, выражение лица, эмоцию и окружение бери только из последних сообщений.\n'
  '- Не добавляй clothing/outfit tags в pose, setting или composition.\n'
  '- primary_pose — только положение тела или действие. Не используй looking at viewer, hands, '
  'camera angle или framing как primary_pose.\n'
  '- pose_modifiers — gaze, hands, legs, small secondary pose details.\n'
  '- composition — кадрирование/угол: full body, cowboy shot, upper body, dynamic angle, '
  'close-up.\n'
  '- setting разделяй на place, background_objects и lighting.\n'
  '- exposure_intent: safe, nude или explicit_focus. Nude/naked без явного visible/expose '
  'гениталий = nude, не explicit_focus.\n'
  '- Одежда заблокирована через photo_state.current_outfit. Не меняй её по настроению, локации, '
  'позе или общей атмосфере.\n'
  '- outfit_action="none" почти всегда: если в последних сообщениях нет явной смены одежды, '
  'раздевания или возврата к обычной одежде.\n'
  '- outfit_action="default", только если персонаж явно возвращается к обычной/базовой одежде.\n'
  '- outfit_action="wardrobe", только если последние сообщения явно выбирают один вариант из '
  'photo_state.wardrobe или сцена очевидно требует underwear/nude/swimwear.\n'
  '- При nude/naked выбирай outfit_action="wardrobe" и wardrobe_key="nude", если такой ключ есть.\n'
  '- outfit_action="custom", только если пользователь явно просит одежду, которой нет в wardrobe, '
  'в том числе nude.\n'
  '- wardrobe_key должен быть существующим ключом из photo_state.wardrobe или пустой строкой.\n'
  '- custom_clothing не заполняй, если outfit_action не "custom".\n'
  '- Не описывай действия игрока. Не добавляй текст, подписи, интерфейс, speech bubbles.\n'
  '- Верни только валидный JSON без markdown.\n'
  '- Все значения пиши коротко на английском.\n'
  '\n'
  'Формат:\n'
  '{\n'
  '  "primary_pose": "body pose/action only, max 6 words",\n'
  '  "pose_modifiers": "comma-separated gaze/hands/legs details, max 8 words",\n'
  '  "expression": "specific facial expression, max 3 words",\n'
  '  "emotion": "short mood, max 3 words",\n'
  '  "composition": "single framing/camera tag",\n'
  '  "place": "specific place",\n'
  '  "background_objects": "2-3 visible background object tags",\n'
  '  "lighting": "short lighting tag",\n'
  '  "exposure_intent": "safe|nude|explicit_focus",\n'
  '  "outfit_action": "none|default|wardrobe|custom",\n'
  '  "wardrobe_key": "existing wardrobe key only, otherwise empty string",\n'
  '  "custom_clothing": "explicit non-wardrobe outfit only, otherwise empty string"\n'
  '}'),
 ('photo_prompt_real_female',
  'photo',
  'Photo Prompt: Real Female',
  'A realistic photograph of a single adult woman. {scene_description} She is wearing {clothing}. '
  '{appearance} {body} {face}. {style_tags}'),
 ('photo_prompt_real_male',
  'photo',
  'Photo Prompt: Real Male',
  'A realistic photograph of a single adult man. {scene_description} He is wearing {clothing}. '
  '{appearance} {body} {face}. {style_tags}'),
 ('photo_prompt_anime_female',
  'photo',
  'Photo Prompt: Anime Female',
  '{subject_tags}, {appearance}, {body}, {face}, {clothing}, {rating_tags}, {nudity_tags}, '
  '{focus_tags}, {expression}, {pose}, {composition}, {setting}, {style_tags}, {quality_tags}'),
 ('photo_prompt_anime_male',
  'photo',
  'Photo Prompt: Anime Male',
  '{subject_tags}, {appearance}, {body}, {face}, {clothing}, {rating_tags}, {nudity_tags}, '
  '{focus_tags}, {expression}, {pose}, {composition}, {setting}, {style_tags}, {quality_tags}'),
 ('photo_negative_anime_female',
  'photo',
  'Photo Negative Prompt: Anime Female',
  'multiple people, man, boy, bad anatomy, bad hands, extra fingers, low quality, text, watermark, '
  'logo, cropped, out of frame'),
 ('photo_negative_anime_male',
  'photo',
  'Photo Negative Prompt: Anime Male',
  'woman, girl, multiple people, bad anatomy, bad hands, low quality, text, watermark, logo, '
  'cropped, out of frame'),
 ('photo_policy_anime_filler_tags',
  'photo_policy',
  'Anime Filler Tags',
  'anime style, anime illustration, detailed background, detailed face, high quality, best '
  'quality'),
 ('photo_policy_anime_user_quality_tags',
  'photo_policy',
  'Anime User Quality Tags',
  'masterpiece, masterpiec, best quality, high quality, great quality, low quality, absurdres'),
 ('photo_policy_anime_rating_safe', 'photo_policy', 'Anime Rating Tags: Safe', 'safe'),
 ('photo_policy_anime_rating_nsfw', 'photo_policy', 'Anime Rating Tags: NSFW', 'nsfw'),
 ('photo_policy_anime_rating_explicit',
  'photo_policy',
  'Anime Rating Tags: Explicit',
  'explicit, nsfw'),
 ('photo_policy_anime_nudity_tags', 'photo_policy', 'Anime Nudity Tags', 'nude'),
 ('photo_policy_anime_focus_tags', 'photo_policy', 'Anime Focus Tags', 'uncensored'),
 ('photo_policy_anime_quality_tags',
  'photo_policy',
  'Anime Quality Tags',
  'high score, great score'),
 ('photo_policy_anime_avatar_quality_tags',
  'photo_policy',
  'Anime Avatar Quality Tags',
  'high score'),
 ('photo_policy_anime_subject_female', 'photo_policy', 'Anime Subject Tags: Female', '1girl, solo'),
 ('photo_policy_anime_subject_male', 'photo_policy', 'Anime Subject Tags: Male', '1boy, solo'),
 ('photo_policy_anime_negative_explicit',
  'photo_policy',
  'Anime Negative Tags: Explicit',
  'censored, censor bar, mosaic censoring'),
 ('photo_policy_avatar_scene',
  'photo_policy',
  'Avatar Scene JSON',
  '{"pose":"looking at viewer","expression":"soft smile","composition":"upper '
  'body","setting":"simple '
  'background","exposure_intent":"safe","emotion":"calm","scene_notes":""}'),
 ('photo_policy_avatar_default_outfit', 'photo_policy', 'Avatar Default Outfit', 'casual outfit'),
 ('photo_policy_real_default_outfit',
  'photo_policy',
  'Real Default Outfit',
  'casual modern outfit'),
 ('photo_policy_real_clothed_prefix', 'photo_policy', 'Real Clothed Prefix', 'fully clothed'),
 ('photo_policy_real_default_outfit_priority',
  'photo_policy',
  'Real Outfit Wardrobe Priority',
  'casual, formal, business, office, everyday, sleepwear, gym'),
 ('photo_policy_default_style_tags_real',
  'photo_policy',
  'Default Style Tags: Real',
  'soft natural lighting, film photography, warm tones'),
 ('photo_policy_default_style_tags_anime', 'photo_policy', 'Default Style Tags: Anime', ''),
 ('photo_policy_default_style_tags_manhwa', 'photo_policy', 'Default Style Tags: Manhwa', ''),
 ('photo_policy_manhwa_style_tags',
  'photo_policy',
  'Manhwa Fallback Style Tags',
  'manhwa style, webtoon style, clean line art'),
 ('photo_policy_default_wardrobe_female',
  'photo_policy',
  'Default Wardrobe JSON: Female',
  '{"nude":"nothing, showing her naked body","underwear":"white bra, white panties"}'),
 ('photo_policy_default_wardrobe_male',
  'photo_policy',
  'Default Wardrobe JSON: Male',
  '{"nude":"nothing, showing his naked body","underwear":"black boxer briefs"}')]

PHOTO_PROMPT_ROWS.extend([
    (
        "photo_scene_extractor_real",
        "photo",
        "Photo Scene Extractor: Real",
        """Ты собираешь короткое фотографическое описание для real photo generation через Z-Image-Turbo.

Используй только JSON character, photo_state и recent_messages из сообщения пользователя. Recent_messages уже содержит только последние 5 сообщений; не выдумывай старую историю.

Правила:
- На изображении ровно один взрослый персонаж: сам character. Игрока, пользователя и других людей не добавлять.
- scene_description пиши на английском как 1-2 связных предложения, не как CSV/tags.
- Пиши литературно-фотографически: framing, pose, hands/legs, background, lighting, camera feel.
- Для chat photos предпочитай full-body, cowboy shot или dynamic framing, если сцена явно не просит close-up/portrait.
- Не используй upper body по умолчанию. Upper body допустим только если последние сообщения явно про портрет/лицо/крупный план.
- Не добавляй одежду в scene_description; одежда приходит отдельно через photo_state/outfit.
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

Формат:
{
  "scene_description": "A full-body realistic photograph of her standing in a dim hotel room, one hand on the doorframe and the other resting on her hip. Warm bedside light falls across the curtains and wooden floor.",
  "exposure_intent": "safe|nude|explicit_focus",
  "expression": "specific facial expression, max 4 words",
  "outfit_action": "none|default|wardrobe|custom",
  "wardrobe_key": "existing wardrobe key only, otherwise empty string",
  "custom_clothing": "explicit non-wardrobe outfit only, otherwise empty string"
}""",
    ),
    (
        "photo_scene_extractor_anime",
        "photo",
        "Photo Scene Extractor: Anime",
        PHOTO_PROMPT_ROWS[0][3],
    ),
    (
        "photo_scene_extractor_manhwa",
        "photo",
        "Photo Scene Extractor: Manhwa",
        """Ты собираешь короткое tag-style ТЗ для генерации одного manhwa/webtoon изображения male character.

Используй только JSON character, photo_state и recent_messages из сообщения пользователя. Recent_messages уже содержит только последние 5 сообщений; не выдумывай старую историю.

Правила:
- На изображении ровно один male character. Игрока, пользователя, woman/girl/companion и других людей не добавлять.
- Все значения пиши коротко на английском, как SDXL/Illustrious tags.
- primary_pose — только положение тела или действие. Не используй looking at viewer, hands, camera angle или framing как primary_pose.
- pose_modifiers — gaze, hands, legs, small secondary pose details.
- composition — кадрирование/угол: full body, cowboy shot, dynamic angle, upper body, close-up.
- Для chat photos предпочитай full body/cowboy shot/dynamic angle, если сцена явно не портретная.
- setting разделяй на place, background_objects и lighting.
- exposure_intent: safe, nude или explicit_focus. Nude/naked без явного visible/expose гениталий = nude, не explicit_focus.
- Одежда заблокирована через photo_state.current_outfit. Не меняй её по настроению, локации, позе или общей атмосфере.
- outfit_action="none" почти всегда: если в последних сообщениях нет явной смены одежды, раздевания или возврата к обычной одежде.
- outfit_action="default", только если персонаж явно возвращается к обычной/базовой одежде.
- outfit_action="wardrobe", только если последние сообщения явно выбирают один вариант из photo_state.wardrobe или сцена очевидно требует underwear/nude.
- При nude/naked выбирай outfit_action="wardrobe" и wardrobe_key="nude", если такой ключ есть.
- outfit_action="custom", только если пользователь явно просит одежду, которой нет в wardrobe, в том числе nude.
- wardrobe_key должен быть существующим ключом из photo_state.wardrobe или пустой строкой.
- custom_clothing не заполняй, если outfit_action не "custom".
- Не описывай действия игрока. Не добавляй текст, подписи, интерфейс, speech bubbles.
- Верни только валидный JSON без markdown.

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
}""",
    ),
    (
        "photo_prompt_manhwa_male",
        "photo",
        "Photo Prompt: Manhwa Male",
        "{subject_tags}, {rating_tags}, {nudity_tags}, {focus_tags}, {pose}, {composition}, {expression}, {clothing}, {appearance}, {face}, {body}, {setting}, {style_tags}, {quality_tags}",
    ),
    (
        "photo_negative_manhwa_male",
        "photo",
        "Photo Negative Prompt: Manhwa Male",
        "woman, girl, female, multiple people, child, teen, shota, bad anatomy, bad hands, low quality, text, watermark, logo, cropped, out of frame",
    ),
])


PROMPT_UPSERT = sa.text(
    """
    INSERT INTO prompts (key, category, name, content, updated_at)
    VALUES (:key, :category, :name, :content, NOW())
    ON CONFLICT (key) DO UPDATE SET
        category = EXCLUDED.category,
        name = EXCLUDED.name,
        content = EXCLUDED.content,
        updated_at = NOW()
    """
)


def upgrade() -> None:
    op.execute("ALTER TABLE generated_images DROP COLUMN IF EXISTS nsfw_level")
    op.execute(
        """
        ALTER TABLE generated_images
        ADD COLUMN IF NOT EXISTS prompt_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute("ALTER TABLE generated_images ALTER COLUMN prompt_metadata DROP DEFAULT")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS image_generation_jobs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
            chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'queued',
            arq_job_id VARCHAR(255),
            image_id INTEGER REFERENCES generated_images(id) ON DELETE SET NULL,
            request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_code VARCHAR(100),
            error_message VARCHAR(500),
            created_at TIMESTAMP DEFAULT now(),
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_image_generation_jobs_chat_id
        ON image_generation_jobs (chat_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_image_generation_jobs_user_id
        ON image_generation_jobs (user_id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_image_generation_jobs_active_chat
        ON image_generation_jobs (chat_id)
        WHERE status IN ('queued', 'running')
        """
    )

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

    bind = op.get_bind()
    for key, category, name, content in PHOTO_PROMPT_ROWS:
        bind.execute(
            PROMPT_UPSERT,
            {
                "key": key,
                "category": category,
                "name": name,
                "content": content,
            },
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_image_generation_jobs_active_chat")
    op.execute("DROP INDEX IF EXISTS ix_image_generation_jobs_user_id")
    op.execute("DROP INDEX IF EXISTS ix_image_generation_jobs_chat_id")
    op.execute("DROP TABLE IF EXISTS image_generation_jobs")
    op.execute("ALTER TABLE characters DROP COLUMN IF EXISTS total_message_count")
    op.execute("ALTER TABLE generated_images DROP COLUMN IF EXISTS prompt_metadata")
    op.execute("ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS nsfw_level INTEGER")
