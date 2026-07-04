from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260704_01"
down_revision = "20260701_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "virtual_player_profiles",
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
    )
    _backfill_display_order()


def downgrade() -> None:
    op.drop_column("virtual_player_profiles", "display_order")


def _backfill_display_order() -> None:
    connection = op.get_bind()
    profiles = sa.table(
        "virtual_player_profiles",
        sa.column("id", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("display_order", sa.Integer),
    )
    profile_rows = connection.execute(
        sa.select(profiles.c.id).order_by(profiles.c.created_at.asc(), profiles.c.id.asc())
    ).fetchall()

    for display_order, row in enumerate(profile_rows, start=1):
        connection.execute(
            profiles.update()
            .where(profiles.c.id == row.id)
            .values(display_order=display_order)
        )
