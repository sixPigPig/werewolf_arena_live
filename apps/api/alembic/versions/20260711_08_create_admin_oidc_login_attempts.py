from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260711_08"
down_revision = "20260711_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_oidc_login_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("oidc_nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("return_to", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_admin_oidc_login_attempts_state_hash",
        "admin_oidc_login_attempts",
        ["state_hash"],
        unique=True,
    )
    op.create_index(
        "ix_admin_oidc_login_attempts_expires_at",
        "admin_oidc_login_attempts",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_oidc_login_attempts_expires_at",
        table_name="admin_oidc_login_attempts",
    )
    op.drop_index(
        "ix_admin_oidc_login_attempts_state_hash",
        table_name="admin_oidc_login_attempts",
    )
    op.drop_table("admin_oidc_login_attempts")
