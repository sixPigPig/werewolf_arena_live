from alembic import op
import sqlalchemy as sa


revision = "20260516_01"
down_revision = "20260422_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "virtual_player_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("personality_id", sa.String(length=40), nullable=False, server_default="balanced"),
        sa.Column("personality_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("appearance_id", sa.String(length=40), nullable=False, server_default="default"),
        sa.Column("avatar_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index("ix_virtual_player_profiles_owner_user_id", "virtual_player_profiles", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_virtual_player_profiles_owner_user_id", table_name="virtual_player_profiles")
    op.drop_table("virtual_player_profiles")
