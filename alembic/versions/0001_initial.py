"""initial schema — squashed from 17 migrations

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM, JSONB

# revision identifiers, used by Alembic.
revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enums
messagerole_enum = PG_ENUM('USER', 'ASSISTANT', 'SYSTEM', name='messagerole', create_type=False)
transactionsource_enum = PG_ENUM(
    'DAILY_BONUS', 'PURCHASE', 'MESSAGE_SENT', 'IMAGE_GENERATED', 'ADMIN_GRANT',
    name='transactionsource', create_type=False,
)
subscriptionplan_enum = PG_ENUM(
    'free', 'plus_weekly', 'plus_monthly', 'pro',
    name='subscriptionplan', create_type=False,
)


def upgrade() -> None:
    # Create enum types
    messagerole_enum.create(op.get_bind(), checkfirst=True)
    transactionsource_enum.create(op.get_bind(), checkfirst=True)
    subscriptionplan_enum.create(op.get_bind(), checkfirst=True)

    # 1. users
    op.create_table('users',
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
        sa.Column('balance', sa.Integer(), nullable=True),
        sa.Column('subscription_plan', subscriptionplan_enum, nullable=False, server_default='free'),
        sa.Column('subscription_start_date', sa.DateTime(), nullable=True),
        sa.Column('is_subscribed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('subscription_end_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('last_active_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('first_interaction_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('telegram_id')
    )

    # 2. user_settings
    op.create_table('user_settings',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('nsfw_blur', sa.Boolean(), nullable=True),
        sa.Column('language', sa.String(length=10), nullable=True),
        sa.Column('nickname', sa.String(length=50), nullable=True),
        sa.Column('age_confirmed', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
    )

    # 3. characters
    op.create_table('characters',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('short_description', sa.String(length=30), nullable=True, server_default=''),
        sa.Column('personality', sa.Text(), nullable=False),
        sa.Column('visual_data', JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('scenarios', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tags', sa.ARRAY(sa.String()), nullable=True),
        sa.Column('is_nsfw', sa.Boolean(), nullable=True),
        sa.Column('created_by_username_id', sa.BigInteger(), nullable=True),
        sa.Column('created_by_username', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['created_by_username_id'], ['users.telegram_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # 4. worlds
    op.create_table('worlds',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('short_description', sa.String(length=30), nullable=True, server_default=''),
        sa.Column('cover_image', sa.String(length=500), nullable=True),
        sa.Column('scenarios', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('locations', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tags', sa.ARRAY(sa.String()), nullable=True),
        sa.Column('is_nsfw', sa.Boolean(), nullable=True),
        sa.Column('created_by_username_id', sa.BigInteger(), nullable=True),
        sa.Column('created_by_username', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['created_by_username_id'], ['users.telegram_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # 5. chats
    op.create_table('chats',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_type', sa.String(length=20), nullable=False),
        sa.Column('target_id', sa.String(length=100), nullable=False),
        sa.Column('scenario_index', sa.Integer(), nullable=True),
        sa.Column('affinity', sa.Integer(), nullable=True),
        sa.Column('arousal', sa.Integer(), nullable=True),
        sa.Column('current_location', sa.String(length=255), nullable=True),
        sa.Column('current_mood', sa.String(length=100), nullable=True),
        sa.Column('state_meta', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('msgs_since_summary', sa.Integer(), nullable=True),
        sa.Column('last_auto_photo_at', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 6. messages
    op.create_table('messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('chat_id', sa.Integer(), nullable=False),
        sa.Column('role', messagerole_enum, nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tokens_used', sa.Integer(), nullable=True),
        sa.Column('is_auto_generated', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_chat_id'), 'messages', ['chat_id'], unique=False)
    op.create_index(op.f('ix_messages_created_at'), 'messages', ['created_at'], unique=False)

    # 7. generated_images
    op.create_table('generated_images',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_id', sa.Integer(), nullable=True),
        sa.Column('provider_url', sa.String(length=1000), nullable=True),
        sa.Column('local_path', sa.String(length=500), nullable=True),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('content_type', sa.String(length=50), nullable=True),
        sa.Column('nsfw_level', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 8. transactions
    op.create_table('transactions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('source', transactionsource_enum, nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 9. prompts
    op.create_table('prompts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prompts_key'), 'prompts', ['key'], unique=True)
    op.create_index(op.f('ix_prompts_category'), 'prompts', ['category'], unique=False)

    # 10. events
    op.create_table('events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=True),
        sa.Column('entity_id', sa.String(length=100), nullable=True),
        sa.Column('meta', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_events_user_id', 'events', ['user_id'])
    op.create_index('ix_events_event_type', 'events', ['event_type'])
    op.create_index('ix_events_created_at', 'events', ['created_at'])

    # 11. monthly_usage
    op.create_table('monthly_usage',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('messages_sent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('images_generated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('characters_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('worlds_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content_edits', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avatar_generations', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'period', name='uq_monthly_usage_user_period')
    )

    # 12. subscription_payments
    op.create_table('subscription_payments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('plan', subscriptionplan_enum, nullable=False),
        sa.Column('amount_stars', sa.Integer(), nullable=False),
        sa.Column('amount_rub', sa.Integer(), nullable=False),
        sa.Column('telegram_payment_charge_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_subscription_payments_user_id', 'subscription_payments', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_subscription_payments_user_id', table_name='subscription_payments')
    op.drop_table('subscription_payments')
    op.drop_table('monthly_usage')
    op.drop_index('ix_events_created_at', table_name='events')
    op.drop_index('ix_events_event_type', table_name='events')
    op.drop_index('ix_events_user_id', table_name='events')
    op.drop_table('events')
    op.drop_index(op.f('ix_prompts_category'), table_name='prompts')
    op.drop_index(op.f('ix_prompts_key'), table_name='prompts')
    op.drop_table('prompts')
    op.drop_table('transactions')
    op.drop_table('generated_images')
    op.drop_index(op.f('ix_messages_created_at'), table_name='messages')
    op.drop_index(op.f('ix_messages_chat_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_table('chats')
    op.drop_table('worlds')
    op.drop_table('characters')
    op.drop_table('user_settings')
    op.drop_table('users')
    subscriptionplan_enum.drop(op.get_bind(), checkfirst=True)
    transactionsource_enum.drop(op.get_bind(), checkfirst=True)
    messagerole_enum.drop(op.get_bind(), checkfirst=True)
