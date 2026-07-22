"""create live v2 ability runtime

Revision ID: 20260722_40
Revises: 20260722_39
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260722_40"
down_revision = "20260722_39"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "v2_game_records",
        sa.Column(
            "ability_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "v2_game_records",
        sa.Column("ability_snapshot_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "v2_role_assignments",
        sa.Column("role_key", sa.String(length=80), server_default="legacy", nullable=False),
    )
    op.execute(sa.text("UPDATE v2_role_assignments SET role_key = role"))
    op.add_column(
        "v2_live_presentations",
        sa.Column("activation_id", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "v2_live_presentations",
        sa.Column("audience", sa.String(length=32), server_default="all", nullable=False),
    )
    op.create_index(
        "ix_v2_live_presentations_activation_id",
        "v2_live_presentations",
        ["activation_id"],
    )
    op.add_column(
        "v2_voice_assets",
        sa.Column("activation_id", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "v2_voice_assets",
        sa.Column("audience", sa.String(length=32), server_default="all", nullable=False),
    )
    op.create_index(
        "ix_v2_voice_assets_activation_id",
        "v2_voice_assets",
        ["activation_id"],
    )

    op.create_table(
        "v2_player_states",
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("player_id", sa.String(length=80), nullable=False),
        sa.Column("seat", sa.Integer(), nullable=False),
        sa.Column("alive", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("death_cause", sa.String(length=40), nullable=True),
        sa.Column("death_window_seq", sa.Integer(), nullable=True),
        sa.Column(
            "state", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("game_id", "player_id"),
    )
    op.create_table(
        "v2_action_windows",
        sa.Column("window_id", sa.String(length=48), nullable=False),
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("window_seq", sa.Integer(), nullable=False),
        sa.Column("window_type", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("ability_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("plan", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("result", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["v2_game_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("window_id"),
        sa.UniqueConstraint("game_id", "window_seq", name="uq_v2_action_windows_game_seq"),
    )
    op.create_index("ix_v2_action_windows_game_id", "v2_action_windows", ["game_id"])
    op.create_index("ix_v2_action_windows_run_id", "v2_action_windows", ["run_id"])
    op.create_index("ix_v2_action_windows_state", "v2_action_windows", ["state"])
    op.create_table(
        "v2_ability_instances",
        sa.Column("ability_instance_id", sa.String(length=48), nullable=False),
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("ability_id", sa.String(length=80), nullable=False),
        sa.Column("ability_version", sa.Integer(), nullable=False),
        sa.Column("owner_scope", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("owner_role_key", sa.String(length=80), nullable=False),
        sa.Column("state", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("ability_instance_id"),
        sa.UniqueConstraint(
            "game_id", "ability_id", "owner_id", name="uq_v2_ability_instances_owner"
        ),
    )
    op.create_index("ix_v2_ability_instances_game_id", "v2_ability_instances", ["game_id"])
    op.create_table(
        "v2_ability_activations",
        sa.Column("activation_id", sa.String(length=48), nullable=False),
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("window_id", sa.String(length=48), nullable=False),
        sa.Column("ability_instance_id", sa.String(length=48), nullable=False),
        sa.Column("occurrence", sa.Integer(), server_default="1", nullable=False),
        sa.Column("action_id", sa.String(length=48), nullable=True),
        sa.Column("decision_id", sa.String(length=48), nullable=True),
        sa.Column("actor_player_id", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("skip_reason", sa.String(length=80), nullable=True),
        sa.Column(
            "knowledge_fact_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False
        ),
        sa.Column("decision", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("result", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["ability_instance_id"],
            ["v2_ability_instances.ability_instance_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["v2_game_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["window_id"], ["v2_action_windows.window_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("activation_id"),
        sa.UniqueConstraint(
            "game_id",
            "window_id",
            "ability_instance_id",
            "occurrence",
            name="uq_v2_ability_activations_occurrence",
        ),
    )
    for column in ("game_id", "run_id", "window_id", "ability_instance_id", "action_id", "status"):
        op.create_index(
            f"ix_v2_ability_activations_{column}", "v2_ability_activations", [column]
        )
    op.create_table(
        "v2_effect_intents",
        sa.Column("effect_intent_id", sa.String(length=48), nullable=False),
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("window_id", sa.String(length=48), nullable=False),
        sa.Column("activation_id", sa.String(length=48), nullable=False),
        sa.Column("effect_type", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.String(length=80), nullable=True),
        sa.Column("target_player_id", sa.String(length=80), nullable=True),
        sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("state", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["activation_id"], ["v2_ability_activations.activation_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["window_id"], ["v2_action_windows.window_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("effect_intent_id"),
    )
    for column in ("game_id", "window_id", "activation_id", "effect_type"):
        op.create_index(f"ix_v2_effect_intents_{column}", "v2_effect_intents", [column])
    op.create_table(
        "v2_knowledge_facts",
        sa.Column("knowledge_fact_id", sa.String(length=48), nullable=False),
        sa.Column("game_id", sa.String(length=40), nullable=False),
        sa.Column("source_activation_id", sa.String(length=48), nullable=True),
        sa.Column("owner_scope", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.String(length=80), nullable=False),
        sa.Column("fact_type", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["v2_game_records.game_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_activation_id"],
            ["v2_ability_activations.activation_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("knowledge_fact_id"),
    )
    op.create_index("ix_v2_knowledge_facts_game_id", "v2_knowledge_facts", ["game_id"])
    op.create_index(
        "ix_v2_knowledge_facts_source_activation_id",
        "v2_knowledge_facts",
        ["source_activation_id"],
    )
    op.create_index("ix_v2_knowledge_facts_owner_id", "v2_knowledge_facts", ["owner_id"])


def downgrade() -> None:
    op.drop_table("v2_knowledge_facts")
    op.drop_table("v2_effect_intents")
    op.drop_table("v2_ability_activations")
    op.drop_table("v2_ability_instances")
    op.drop_table("v2_action_windows")
    op.drop_table("v2_player_states")
    op.drop_index("ix_v2_voice_assets_activation_id", table_name="v2_voice_assets")
    op.drop_column("v2_voice_assets", "audience")
    op.drop_column("v2_voice_assets", "activation_id")
    op.drop_index(
        "ix_v2_live_presentations_activation_id", table_name="v2_live_presentations"
    )
    op.drop_column("v2_live_presentations", "audience")
    op.drop_column("v2_live_presentations", "activation_id")
    op.drop_column("v2_role_assignments", "role_key")
    op.drop_column("v2_game_records", "ability_snapshot_hash")
    op.drop_column("v2_game_records", "ability_snapshot")
