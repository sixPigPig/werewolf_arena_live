"""replace slow virtual player models

Revision ID: 20260715_22
Revises: 20260715_21
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_22"
down_revision = "20260715_21"
branch_labels = None
depends_on = None


SLOW_MODEL_REPLACEMENTS = (
    ("doubao-seed-2-0-pro-260215", "deepseek-v4-flash"),
    ("kimi-k2.7-code", "deepseek-v4-flash"),
    ("minimax-m2.7", "minimax-m3"),
    ("kimi-k2.6", "glm-5-2-260617"),
)

# Keep the current curated roster balanced at three profiles per retained model.
PROFILE_MODEL_OVERRIDES = {
    "46b6dfa5-d7d6-46b8-a37b-001aa0f3edca": (
        "kimi-k2.7-code",
        "doubao-seed-2-0-lite-260215",
    ),
}


def upgrade() -> None:
    profiles = sa.table(
        "virtual_player_profiles",
        sa.column("id", sa.String),
        sa.column("model", sa.String),
        sa.column("version", sa.Integer),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()

    for profile_id, (old_model, new_model) in PROFILE_MODEL_OVERRIDES.items():
        connection.execute(
            profiles.update()
            .where(profiles.c.id == profile_id, profiles.c.model == old_model)
            .values(
                model=new_model,
                version=profiles.c.version + 1,
                updated_at=sa.func.now(),
            )
        )

    for old_model, new_model in SLOW_MODEL_REPLACEMENTS:
        connection.execute(
            profiles.update()
            .where(profiles.c.model == old_model)
            .values(
                model=new_model,
                version=profiles.c.version + 1,
                updated_at=sa.func.now(),
            )
        )


def downgrade() -> None:
    # The old model assignment cannot be reconstructed safely after profiles have
    # been edited, and restoring retired models would make them selectable again.
    pass
