from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260710_03"
down_revision = "20260710_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("auth_provider", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("auth_subject", sa.String(length=255), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_users_auth_identity_paired",
            "(auth_provider IS NULL AND auth_subject IS NULL) OR "
            "(auth_provider IS NOT NULL AND auth_subject IS NOT NULL)",
        )
        batch_op.create_unique_constraint(
            "uq_users_auth_provider_subject",
            ["auth_provider", "auth_subject"],
        )

    op.create_table(
        "public_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_public_sessions_user_id", "public_sessions", ["user_id"])
    op.create_index(
        "ix_public_sessions_token_hash",
        "public_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_public_sessions_expires_at",
        "public_sessions",
        ["expires_at"],
    )
    op.create_index(
        "ix_public_sessions_revoked_at",
        "public_sessions",
        ["revoked_at"],
    )

    op.create_table(
        "user_favorite_player_profiles",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "player_profile_id",
            sa.String(length=36),
            sa.ForeignKey("virtual_player_profiles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_user_favorite_player_profiles_profile_user",
        "user_favorite_player_profiles",
        ["player_profile_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_favorite_player_profiles_profile_user",
        table_name="user_favorite_player_profiles",
    )
    op.drop_table("user_favorite_player_profiles")

    op.drop_index("ix_public_sessions_revoked_at", table_name="public_sessions")
    op.drop_index("ix_public_sessions_expires_at", table_name="public_sessions")
    op.drop_index("ix_public_sessions_token_hash", table_name="public_sessions")
    op.drop_index("ix_public_sessions_user_id", table_name="public_sessions")
    op.drop_table("public_sessions")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_auth_provider_subject", type_="unique")
        batch_op.drop_constraint("ck_users_auth_identity_paired", type_="check")
        batch_op.drop_column("auth_subject")
        batch_op.drop_column("auth_provider")
