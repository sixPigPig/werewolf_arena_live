"""require model max output tokens

Revision ID: 20260727_47
Revises: 20260727_46
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260727_47"
down_revision = "20260727_46"
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
                    'max_tokens',
                    CASE
                        WHEN supports_thinking
                             AND COALESCE(parameter_values ->> 'thinking', 'default')
                                 <> 'disabled'
                        THEN 2048
                        ELSE 512
                    END
                )
            )::json
            WHERE NOT (parameter_values::jsonb ? 'max_tokens')
               OR parameter_values::jsonb -> 'max_tokens' = 'null'::jsonb
            """
        )
    )


def downgrade() -> None:
    # Keep the populated values: removing them would discard user configuration.
    pass
