from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260517_02"
down_revision = "20260517_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "virtual_player_profiles",
        sa.Column("short_description", sa.String(length=160), nullable=False, server_default=""),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("background_story", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("speaking_style", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("catchphrases", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column(
            "strategy_profile",
            sa.String(length=40),
            nullable=False,
            server_default="balanced",
        ),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("risk_tolerance", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("bluffing_tendency", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("trust_tendency", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("leadership_tendency", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("talkativeness", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("example_messages", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("virtual_player_profiles", "favorite")
    op.drop_column("virtual_player_profiles", "example_messages")
    op.drop_column("virtual_player_profiles", "talkativeness")
    op.drop_column("virtual_player_profiles", "leadership_tendency")
    op.drop_column("virtual_player_profiles", "trust_tendency")
    op.drop_column("virtual_player_profiles", "bluffing_tendency")
    op.drop_column("virtual_player_profiles", "risk_tolerance")
    op.drop_column("virtual_player_profiles", "strategy_profile")
    op.drop_column("virtual_player_profiles", "catchphrases")
    op.drop_column("virtual_player_profiles", "speaking_style")
    op.drop_column("virtual_player_profiles", "background_story")
    op.drop_column("virtual_player_profiles", "short_description")
