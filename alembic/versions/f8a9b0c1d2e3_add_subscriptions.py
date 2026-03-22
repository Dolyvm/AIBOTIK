"""add subscription plans and usage tracking

Revision ID: f8a9b0c1d2e3
Revises: e2f3a4b5c6d7
Create Date: 2026-03-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM


# revision identifiers, used by Alembic.
revision: str = 'f8a9b0c1d2e3'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reusable enum — create_type=False so add_column/create_table won't
# attempt CREATE TYPE (we handle that explicitly below).
_sub_enum = PG_ENUM(
    'free', 'plus_weekly', 'plus_monthly', 'pro',
    name='subscriptionplan',
    create_type=False,
)


def upgrade() -> None:
    # 1. Create the enum type (safe if it already exists)
    _sub_enum.create(op.get_bind(), checkfirst=True)

    # 2. Add columns to users
    op.add_column('users', sa.Column('subscription_plan', _sub_enum, nullable=True))
    op.add_column('users', sa.Column('subscription_start_date', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('subscription_end_date', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('subscription_auto_renew', sa.Boolean(), nullable=True))
    op.add_column('users', sa.Column('is_subscribed', sa.Boolean(), nullable=True))

    # 3. Set defaults
    op.execute("UPDATE users SET subscription_plan = 'free' WHERE subscription_plan IS NULL")
    op.execute("UPDATE users SET subscription_auto_renew = false WHERE subscription_auto_renew IS NULL")
    op.execute("UPDATE users SET is_subscribed = false WHERE is_subscribed IS NULL")

    # 4. Make non-nullable after setting defaults
    op.alter_column('users', 'subscription_plan', nullable=False)
    op.alter_column('users', 'subscription_auto_renew', nullable=False,
        server_default=sa.text('false'))
    op.alter_column('users', 'is_subscribed', nullable=False,
        server_default=sa.text('false'))

    # 5. Create monthly_usage table
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

    # 6. Create subscription_payments table
    op.create_table('subscription_payments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('plan', _sub_enum, nullable=False),
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
    op.drop_column('users', 'is_subscribed')
    op.drop_column('users', 'subscription_end_date')
    op.drop_column('users', 'subscription_auto_renew')
    op.drop_column('users', 'subscription_start_date')
    op.drop_column('users', 'subscription_plan')
    _sub_enum.drop(op.get_bind(), checkfirst=True)
