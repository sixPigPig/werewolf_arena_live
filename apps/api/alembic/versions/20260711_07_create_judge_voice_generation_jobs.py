from alembic import op
import sqlalchemy as sa

revision = "20260711_07"
down_revision = "20260711_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_voice_generation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("requested_line_ids", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actor_user_id", "idempotency_key", name="uq_voice_job_actor_key"),
    )
    op.create_index("ix_voice_jobs_status_created", "judge_voice_generation_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_voice_jobs_status_created", table_name="judge_voice_generation_jobs")
    op.drop_table("judge_voice_generation_jobs")
