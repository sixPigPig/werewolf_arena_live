from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260711_06"
down_revision = "20260711_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_voice_assets",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("template_id", sa.String(length=80), nullable=True),
        sa.Column("seat_number", sa.Integer(), nullable=True),
        sa.Column("audio_format", sa.String(length=20), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("subtitle_timings", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_judge_voice_assets_size"),
        sa.CheckConstraint("sample_rate > 0", name="ck_judge_voice_assets_sample_rate"),
        sa.CheckConstraint(
            "seat_number IS NULL OR (seat_number >= 1 AND seat_number <= 12)",
            name="ck_judge_voice_assets_seat_number",
        ),
    )
    op.create_index(
        "ix_judge_voice_assets_category_id",
        "judge_voice_assets",
        ["category", "id"],
    )
    op.create_index("ix_judge_voice_assets_sha256", "judge_voice_assets", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_judge_voice_assets_sha256", table_name="judge_voice_assets")
    op.drop_index("ix_judge_voice_assets_category_id", table_name="judge_voice_assets")
    op.drop_table("judge_voice_assets")
