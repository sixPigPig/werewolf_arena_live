"""add live run lineage

Revision ID: 20260715_23
Revises: 20260715_22
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_23"
down_revision = "20260715_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("live_runs", sa.Column("parent_run_id", sa.String(length=32), nullable=True))
    op.add_column("live_runs", sa.Column("resume_from_round", sa.Integer(), nullable=True))
    op.add_column(
        "live_runs",
        sa.Column("attempt_no", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_foreign_key(
        "fk_live_runs_parent_run_id_live_runs",
        "live_runs",
        "live_runs",
        ["parent_run_id"],
        ["run_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_live_runs_parent_run_id", "live_runs", ["parent_run_id"])

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    run_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY session_id ORDER BY created_at ASC, run_id ASC
                    ) AS derived_attempt_no,
                    LAG(run_id) OVER (
                        PARTITION BY session_id ORDER BY created_at ASC, run_id ASC
                    ) AS derived_parent_run_id,
                    (
                        SELECT MIN(live_events.round)
                        FROM live_events
                        WHERE live_events.run_id = live_runs.run_id
                          AND live_events.round IS NOT NULL
                    ) AS derived_resume_from_round
                FROM live_runs
            )
            UPDATE live_runs
            SET
                attempt_no = (
                    SELECT derived_attempt_no FROM ranked WHERE ranked.run_id = live_runs.run_id
                ),
                parent_run_id = (
                    SELECT derived_parent_run_id FROM ranked WHERE ranked.run_id = live_runs.run_id
                ),
                resume_from_round = CASE
                    WHEN (
                        SELECT derived_attempt_no FROM ranked WHERE ranked.run_id = live_runs.run_id
                    ) > 1
                    THEN COALESCE(
                        (
                            SELECT derived_resume_from_round
                            FROM ranked
                            WHERE ranked.run_id = live_runs.run_id
                        ),
                        1
                    )
                    ELSE NULL
                END
            """
        )
    )

    op.create_unique_constraint(
        "uq_live_runs_session_attempt_no",
        "live_runs",
        ["session_id", "attempt_no"],
    )
    op.create_check_constraint(
        "ck_live_runs_attempt_no_positive",
        "live_runs",
        "attempt_no > 0",
    )
    op.create_check_constraint(
        "ck_live_runs_resume_lineage",
        "live_runs",
        "(attempt_no = 1 AND parent_run_id IS NULL AND resume_from_round IS NULL) OR "
        "(attempt_no > 1 AND parent_run_id IS NOT NULL AND resume_from_round > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_live_runs_resume_lineage", "live_runs", type_="check")
    op.drop_constraint("ck_live_runs_attempt_no_positive", "live_runs", type_="check")
    op.drop_constraint("uq_live_runs_session_attempt_no", "live_runs", type_="unique")
    op.drop_index("ix_live_runs_parent_run_id", table_name="live_runs")
    op.drop_constraint(
        "fk_live_runs_parent_run_id_live_runs",
        "live_runs",
        type_="foreignkey",
    )
    op.drop_column("live_runs", "attempt_no")
    op.drop_column("live_runs", "resume_from_round")
    op.drop_column("live_runs", "parent_run_id")
