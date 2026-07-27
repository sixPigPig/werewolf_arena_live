"""enable thinking with a 16k default budget

Revision ID: 20260727_48
Revises: 20260727_47
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260727_48"
down_revision = "20260727_47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE model_configurations
            SET parameter_values = (
                    parameter_values::jsonb
                    || jsonb_build_object(
                        'thinking', 'enabled',
                        'max_tokens', 16384
                    )
                )::json,
                updated_at = now()
            WHERE supports_thinking
              AND COALESCE(parameter_values ->> 'thinking', 'default') = 'default'
            """
        )
    )


def downgrade() -> None:
    # Preserve explicit runtime configuration instead of discarding later edits.
    pass
