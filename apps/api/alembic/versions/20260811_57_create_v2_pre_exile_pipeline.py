"""create durable V2 pre-exile decision pipeline

Revision ID: 20260811_57
Revises: 20260811_56
Create Date: 2026-08-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_57"
down_revision = "20260811_56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_pre_exile_pipelines",
        sa.Column("pipeline_id", sa.String(length=48), primary_key=True),
        sa.Column(
            "game_id",
            sa.String(length=40),
            sa.ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=40),
            sa.ForeignKey("v2_game_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fence_worker_id", sa.String(length=64), nullable=False),
        sa.Column("fence_token", sa.BigInteger(), nullable=False),
        sa.Column("phase_id", sa.String(length=40), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("predecessor_action_id", sa.String(length=48), nullable=False),
        sa.Column("predecessor_presentation_id", sa.String(length=48), nullable=False),
        sa.Column("predecessor_source_event_id", sa.BigInteger(), nullable=False),
        sa.Column("predecessor_source_record_seq", sa.BigInteger(), nullable=False),
        sa.Column("predecessor_sealed_record_seq", sa.BigInteger(), nullable=False),
        sa.Column("public_cutoff_record_seq", sa.BigInteger(), nullable=False),
        sa.Column("public_history_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=False,
            server_default="collecting",
        ),
        sa.Column("selected_explosion_player_id", sa.String(length=80)),
        sa.Column("vote_batch_id", sa.String(length=180)),
        sa.Column("vote_decision_context_sha256", sa.String(length=64)),
        sa.Column("failure", sa.JSON()),
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
        sa.Column("explosion_resolved_at", sa.DateTime(timezone=True)),
        sa.Column("votes_accepted_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "game_id",
            "run_id",
            "phase_id",
            "round_no",
            name="uq_v2_pre_exile_pipelines_day",
        ),
        sa.UniqueConstraint(
            "game_id",
            "run_id",
            "predecessor_presentation_id",
            name="uq_v2_pre_exile_pipelines_predecessor",
        ),
        sa.CheckConstraint(
            "state IN ('collecting', 'no_explosion', 'explosion_selected', "
            "'votes_accepted', 'consumed', 'canceled', 'invalidated')",
            name="ck_v2_pre_exile_pipelines_state",
        ),
        sa.CheckConstraint(
            "fence_token >= 0",
            name="ck_v2_pre_exile_pipelines_fence_nonnegative",
        ),
        sa.CheckConstraint(
            "round_no >= 1 AND predecessor_source_event_id >= 1 AND "
            "predecessor_source_record_seq >= 1 AND "
            "predecessor_sealed_record_seq > predecessor_source_record_seq AND "
            "public_cutoff_record_seq >= predecessor_sealed_record_seq",
            name="ck_v2_pre_exile_pipelines_cutoff_lineage",
        ),
    )
    op.create_index(
        "ix_v2_pre_exile_pipelines_game_state",
        "v2_pre_exile_pipelines",
        ["game_id", "state"],
    )
    op.create_index(
        "ix_v2_pre_exile_pipelines_run_state",
        "v2_pre_exile_pipelines",
        ["run_id", "state"],
    )

    op.create_table(
        "v2_pre_exile_results",
        sa.Column("result_id", sa.String(length=48), primary_key=True),
        sa.Column(
            "pipeline_id",
            sa.String(length=48),
            sa.ForeignKey("v2_pre_exile_pipelines.pipeline_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "game_id",
            sa.String(length=40),
            sa.ForeignKey("v2_game_records.game_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_player_id", sa.String(length=80), nullable=False),
        sa.Column("result_kind", sa.String(length=24), nullable=False),
        sa.Column(
            "state",
            sa.String(length=24),
            nullable=False,
            server_default="reserved",
        ),
        sa.Column("action_id", sa.String(length=48)),
        sa.Column("recovery_action_id", sa.String(length=48)),
        sa.Column("recovery_attempt_id", sa.String(length=48)),
        sa.Column("recovery_response_record_seq", sa.BigInteger()),
        sa.Column("recovery_terminal_record_seq", sa.BigInteger()),
        sa.Column("attempt_id", sa.String(length=48)),
        sa.Column("response_record_seq", sa.BigInteger()),
        sa.Column("terminal_record_seq", sa.BigInteger()),
        sa.Column("result_record_seq", sa.BigInteger()),
        sa.Column("decision", sa.JSON()),
        sa.Column("failure_record_seq", sa.BigInteger()),
        sa.Column("failure", sa.JSON()),
        sa.Column(
            "private_fact_id",
            sa.String(length=48),
            sa.ForeignKey("v2_knowledge_facts.knowledge_fact_id", ondelete="SET NULL"),
        ),
        sa.Column("private_fact_record_seq", sa.BigInteger()),
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
        sa.Column("generation_started_at", sa.DateTime(timezone=True)),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "pipeline_id",
            "actor_player_id",
            "result_kind",
            name="uq_v2_pre_exile_results_member",
        ),
        sa.UniqueConstraint("action_id", name="uq_v2_pre_exile_results_action"),
        sa.UniqueConstraint(
            "recovery_action_id",
            name="uq_v2_pre_exile_results_recovery_action",
        ),
        sa.UniqueConstraint("attempt_id", name="uq_v2_pre_exile_results_attempt"),
        sa.UniqueConstraint(
            "game_id",
            "response_record_seq",
            name="uq_v2_pre_exile_results_response_event",
        ),
        sa.UniqueConstraint(
            "private_fact_id",
            name="uq_v2_pre_exile_results_private_fact",
        ),
        sa.CheckConstraint(
            "result_kind IN ('self_explosion', 'exile_vote')",
            name="ck_v2_pre_exile_results_kind",
        ),
        sa.CheckConstraint(
            "state IN ('reserved', 'generating', 'ready', 'failed', "
            "'accepted', 'committed', 'discarded')",
            name="ck_v2_pre_exile_results_state",
        ),
    )
    op.create_index(
        "ix_v2_pre_exile_results_pipeline_state",
        "v2_pre_exile_results",
        ["pipeline_id", "state"],
    )
    op.create_index(
        "ix_v2_pre_exile_results_game_actor",
        "v2_pre_exile_results",
        ["game_id", "actor_player_id"],
    )


def downgrade() -> None:
    op.drop_table("v2_pre_exile_results")
    op.drop_table("v2_pre_exile_pipelines")
