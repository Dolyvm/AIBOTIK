"""add image generation jobs

Revision ID: 0015_image_generation_jobs
Revises: 0014_gender_anime_nsfw_tags
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0015_image_generation_jobs"
down_revision: Union[str, None] = "0014_gender_anime_nsfw_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "image_generation_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("arq_job_id", sa.String(length=255), nullable=True),
        sa.Column("image_id", sa.Integer(), nullable=True),
        sa.Column(
            "request_payload",
            JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["generated_images.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_image_generation_jobs_chat_id",
        "image_generation_jobs",
        ["chat_id"],
        unique=False,
    )
    op.create_index(
        "ix_image_generation_jobs_user_id",
        "image_generation_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_image_generation_jobs_active_chat",
        "image_generation_jobs",
        ["chat_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_image_generation_jobs_active_chat", table_name="image_generation_jobs")
    op.drop_index("ix_image_generation_jobs_user_id", table_name="image_generation_jobs")
    op.drop_index("ix_image_generation_jobs_chat_id", table_name="image_generation_jobs")
    op.drop_table("image_generation_jobs")
