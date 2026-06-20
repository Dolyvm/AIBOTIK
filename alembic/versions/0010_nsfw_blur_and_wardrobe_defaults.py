"""set nsfw blur and nude wardrobe defaults

Revision ID: 0010_nsfw_blur_and_wardrobe_defaults
Revises: 0009_world_total_message_count
Create Date: 2026-06-20
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0010_nsfw_blur_and_wardrobe_defaults"
down_revision: Union[str, None] = "0009_world_total_message_count"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_settings ALTER COLUMN nsfw_blur SET DEFAULT false")
    op.execute("UPDATE user_settings SET nsfw_blur = false WHERE nsfw_blur IS DISTINCT FROM false")
    op.execute(
        """
        UPDATE prompts
        SET content = CASE key
            WHEN 'photo_policy_default_wardrobe_female'
                THEN '{"nude":"nude, showing her pussy","underwear":"white bra, white panties"}'
            WHEN 'photo_policy_default_wardrobe_male'
                THEN '{"nude":"nude, showing his penis","underwear":"black boxer briefs"}'
            ELSE content
        END
        WHERE key IN (
            'photo_policy_default_wardrobe_female',
            'photo_policy_default_wardrobe_male'
        )
        """
    )
    op.execute(
        """
        UPDATE characters
        SET visual_data = jsonb_set(
            CASE
                WHEN jsonb_typeof(visual_data->'wardrobe') = 'object'
                    THEN visual_data
                ELSE jsonb_set(visual_data, '{wardrobe}', '{}'::jsonb, true)
            END,
            '{wardrobe,nude}',
            to_jsonb(
                CASE
                    WHEN visual_data->>'gender' = 'male'
                        THEN 'nude, showing his penis'
                    ELSE 'nude, showing her pussy'
                END
            ),
            true
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings ALTER COLUMN nsfw_blur DROP DEFAULT")
    op.execute(
        """
        UPDATE prompts
        SET content = CASE key
            WHEN 'photo_policy_default_wardrobe_female'
                THEN '{"nude":"nothing, showing her naked body","underwear":"white bra, white panties"}'
            WHEN 'photo_policy_default_wardrobe_male'
                THEN '{"nude":"nothing, showing his naked body","underwear":"black boxer briefs"}'
            ELSE content
        END
        WHERE key IN (
            'photo_policy_default_wardrobe_female',
            'photo_policy_default_wardrobe_male'
        )
        """
    )
