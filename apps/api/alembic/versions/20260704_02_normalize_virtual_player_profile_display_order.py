from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260704_02"
down_revision = "20260704_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _rewrite_display_order(order_descending=True)


def downgrade() -> None:
    _rewrite_display_order(order_descending=False)


def _rewrite_display_order(*, order_descending: bool) -> None:
    connection = op.get_bind()
    profiles = sa.table(
        "virtual_player_profiles",
        sa.column("id", sa.String),
        sa.column("display_order", sa.Integer),
    )
    order_column = (
        profiles.c.display_order.desc()
        if order_descending
        else profiles.c.display_order.asc()
    )
    profile_rows = connection.execute(
        sa.select(profiles.c.id).order_by(order_column, profiles.c.id.asc())
    ).fetchall()

    for display_order, row in enumerate(profile_rows, start=1):
        connection.execute(
            profiles.update()
            .where(profiles.c.id == row.id)
            .values(display_order=display_order)
        )
