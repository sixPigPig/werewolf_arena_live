from __future__ import annotations

import hashlib
import json
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260712_16"
down_revision = "20260712_15"
branch_labels = None
depends_on = None


_LEGACY_SNAPSHOT_MATCHES = {
    "e63a962b73bb85d4d75f35c3c9fc7834b991ce39d41e4f892f66c3b68e4c4804": (
        "classic_8",
        "e9fa678e-9b18-5079-91d2-f74835364fb6",
        "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131",
    ),
    "02f31f4aa42e54f83836bf2d9b68c25291181c91a722136ed6a0a9a0e40ea4fc": (
        "starter_6",
        "b607e17e-b86f-5eb0-9dc2-b8df09aa71ab",
        "f2c52827ff3eea2725fbf2f1a01436f69c7e6465a64dec9a92bd7a07a9368f4c",
    ),
    "17ceee957477643a7d97fd31dd181c6ad126676ba1af0bc1fc144d4b4a411e6d": (
        "social_8",
        "2b4a993f-e4e6-5312-b11d-92874851a70a",
        "21e1bd2bb495e4479a346724c85a9722477f840afc2c99c389558a52427a0fbc",
    ),
    "688244c09a67521c10610875af305bafcadbcf16e164e5203cf7add4bd48aa00": (
        "classic_12_seer_witch_hunter_idiot",
        "0489f6ac-16fd-5323-96ce-ee256c98cf32",
        "bcae38e48a7791fa0f7ae236c90f1852056938ea60f5447532e5d879260d6da2",
    ),
}


def _canonical_snapshot_hash(snapshot: object) -> str | None:
    try:
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_rule_set_id(snapshot: object) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    rule_set_id = snapshot.get("id")
    if not isinstance(rule_set_id, str) or not rule_set_id:
        return None
    return rule_set_id


def _revision_values(snapshot: object) -> dict[str, object] | None:
    match = _LEGACY_SNAPSHOT_MATCHES.get(_canonical_snapshot_hash(snapshot))
    if match is None:
        return None
    _rule_set_id, revision_id, content_hash = match
    return {
        "rule_set_revision_id": revision_id,
        "rule_set_revision_no": 1,
        "rule_set_content_hash": content_hash,
    }


def _add_columns() -> None:
    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "rule_set_revision_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "rule_set_revisions.id",
                    name="fk_live_runs_rule_set_revision_id_rule_set_revisions",
                    ondelete="RESTRICT",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("rule_set_revision_no", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("rule_set_content_hash", sa.String(length=64), nullable=True))

    with op.batch_alter_table("game_sessions") as batch_op:
        batch_op.add_column(sa.Column("rule_set_id", sa.String(length=80), nullable=True))
        batch_op.add_column(
            sa.Column(
                "rule_set_revision_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "rule_set_revisions.id",
                    name="fk_game_sessions_rule_set_revision_id_rule_set_revisions",
                    ondelete="RESTRICT",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("rule_set_revision_no", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("rule_set_content_hash", sa.String(length=64), nullable=True))


def _backfill_game_sessions(connection: Any) -> None:
    game_sessions = sa.table(
        "game_sessions",
        sa.column("session_id", sa.String(length=32)),
        sa.column("rule_set_id", sa.String(length=80)),
        sa.column("rule_set_revision_id", sa.String(length=36)),
        sa.column("rule_set_revision_no", sa.Integer()),
        sa.column("rule_set_content_hash", sa.String(length=64)),
        sa.column("rule_set", sa.JSON()),
    )
    rows = connection.execute(
        sa.select(game_sessions.c.session_id, game_sessions.c.rule_set)
    ).mappings()
    for row in rows:
        snapshot = row["rule_set"]
        values: dict[str, object] = {}
        rule_set_id = _snapshot_rule_set_id(snapshot)
        if rule_set_id is not None:
            values["rule_set_id"] = rule_set_id
        revision_values = _revision_values(snapshot)
        if revision_values is not None:
            values.update(revision_values)
        if values:
            connection.execute(
                game_sessions.update()
                .where(game_sessions.c.session_id == row["session_id"])
                .values(**values)
            )


def _backfill_live_runs(connection: Any) -> None:
    live_runs = sa.table(
        "live_runs",
        sa.column("run_id", sa.String(length=32)),
        sa.column("rule_set_revision_id", sa.String(length=36)),
        sa.column("rule_set_revision_no", sa.Integer()),
        sa.column("rule_set_content_hash", sa.String(length=64)),
        sa.column("rule_set", sa.JSON()),
    )
    rows = connection.execute(sa.select(live_runs.c.run_id, live_runs.c.rule_set)).mappings()
    for row in rows:
        values = _revision_values(row["rule_set"])
        if values is not None:
            connection.execute(
                live_runs.update().where(live_runs.c.run_id == row["run_id"]).values(**values)
            )


def _create_indexes() -> None:
    live_runs = sa.table(
        "live_runs",
        sa.column("rule_set_id", sa.String(length=80)),
        sa.column("rule_set_revision_id", sa.String(length=36)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("run_id", sa.String(length=32)),
    )
    game_sessions = sa.table(
        "game_sessions",
        sa.column("rule_set_id", sa.String(length=80)),
        sa.column("rule_set_revision_id", sa.String(length=36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("session_id", sa.String(length=32)),
    )
    op.create_index(
        "ix_live_runs_rule_set_revision_id",
        "live_runs",
        [live_runs.c.rule_set_revision_id],
    )
    op.create_index(
        "ix_live_runs_rule_set_id_updated_at_run_id_desc",
        "live_runs",
        [
            live_runs.c.rule_set_id,
            live_runs.c.updated_at.desc(),
            live_runs.c.run_id.desc(),
        ],
    )
    op.create_index(
        "ix_game_sessions_rule_set_revision_id",
        "game_sessions",
        [game_sessions.c.rule_set_revision_id],
    )
    op.create_index(
        "ix_game_sessions_rule_set_id_created_at_session_id_desc",
        "game_sessions",
        [
            game_sessions.c.rule_set_id,
            game_sessions.c.created_at.desc(),
            game_sessions.c.session_id.desc(),
        ],
    )


def upgrade() -> None:
    _add_columns()
    connection = op.get_bind()
    _backfill_game_sessions(connection)
    _backfill_live_runs(connection)
    _create_indexes()


def downgrade() -> None:
    op.drop_index(
        "ix_game_sessions_rule_set_id_created_at_session_id_desc",
        table_name="game_sessions",
    )
    op.drop_index(
        "ix_game_sessions_rule_set_revision_id",
        table_name="game_sessions",
    )
    op.drop_index(
        "ix_live_runs_rule_set_id_updated_at_run_id_desc",
        table_name="live_runs",
    )
    op.drop_index(
        "ix_live_runs_rule_set_revision_id",
        table_name="live_runs",
    )

    with op.batch_alter_table("game_sessions") as batch_op:
        batch_op.drop_column("rule_set_content_hash")
        batch_op.drop_column("rule_set_revision_no")
        batch_op.drop_column("rule_set_revision_id")
        batch_op.drop_column("rule_set_id")

    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.drop_column("rule_set_content_hash")
        batch_op.drop_column("rule_set_revision_no")
        batch_op.drop_column("rule_set_revision_id")
