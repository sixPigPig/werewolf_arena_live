"""add the frozen first-night last-words rule

Revision ID: 20260729_51
Revises: 20260728_50
Create Date: 2026-07-29
"""

from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260729_51"
down_revision = "20260728_50"
branch_labels = None
depends_on = None


_revisions = sa.table(
    "rule_set_revisions",
    sa.column("id", sa.String(length=36)),
    sa.column("rule_set_id", sa.String(length=80)),
    sa.column("schema_version", sa.Integer()),
    sa.column("config", sa.JSON()),
    sa.column("content_hash", sa.String(length=64)),
)


def upgrade() -> None:
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.select(
                _revisions.c.id,
                _revisions.c.rule_set_id,
                _revisions.c.schema_version,
                _revisions.c.config,
            )
        ).mappings()
    )
    for row in rows:
        config = dict(row["config"])
        config["first_night_last_words_enabled"] = (
            row["rule_set_id"] == "classic_12_seer_witch_hunter_idiot"
        )
        bind.execute(
            _revisions.update()
            .where(_revisions.c.id == row["id"])
            .values(
                config=config,
                content_hash=_content_hash(
                    schema_version=int(row["schema_version"]),
                    config=config,
                ),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.select(
                _revisions.c.id,
                _revisions.c.schema_version,
                _revisions.c.config,
            )
        ).mappings()
    )
    for row in rows:
        config = dict(row["config"])
        config.pop("first_night_last_words_enabled", None)
        bind.execute(
            _revisions.update()
            .where(_revisions.c.id == row["id"])
            .values(
                config=config,
                content_hash=_content_hash(
                    schema_version=int(row["schema_version"]),
                    config=config,
                ),
            )
        )


def _content_hash(*, schema_version: int, config: dict[str, object]) -> str:
    encoded = json.dumps(
        {
            "schema_version": schema_version,
            "config": config,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
