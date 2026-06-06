"""add platega payment fields and remove renewal flag

Revision ID: 0007_platega_payments
Revises: 0006_chat_msg_count_idx
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_platega_payments"
down_revision: Union[str, None] = "0006_chat_msg_count_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscription_payments",
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="telegram_stars"),
    )
    op.add_column(
        "subscription_payments",
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "subscription_payments",
        sa.Column("provider_payment_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "subscription_payments",
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="XTR"),
    )
    op.add_column(
        "subscription_payments",
        sa.Column("provider_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_subscription_payments_provider_payment_id",
        "subscription_payments",
        ["provider", "provider_payment_id"],
    )

    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS " + "subscription_" + "auto_" + "renew")


def downgrade() -> None:
    op.drop_index("ix_subscription_payments_provider_payment_id", table_name="subscription_payments")
    op.drop_column("subscription_payments", "provider_payload")
    op.drop_column("subscription_payments", "currency")
    op.drop_column("subscription_payments", "provider_payment_url")
    op.drop_column("subscription_payments", "provider_payment_id")
    op.drop_column("subscription_payments", "provider")
