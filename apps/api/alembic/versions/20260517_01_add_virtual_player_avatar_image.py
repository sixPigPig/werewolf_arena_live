from alembic import op
import sqlalchemy as sa


revision = "20260517_01"
down_revision = "20260516_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "virtual_player_profiles",
        sa.Column("avatar_image_url", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("avatar_image_path", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("avatar_image_mime", sa.String(length=80), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("virtual_player_profiles", "avatar_image_mime")
    op.drop_column("virtual_player_profiles", "avatar_image_path")
    op.drop_column("virtual_player_profiles", "avatar_image_url")
