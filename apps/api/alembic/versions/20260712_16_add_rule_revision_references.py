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

_BACKFILL_BATCH_SIZE = 500

_POSTGRESQL_INDEX_SPECS = (
    (
        "ix_live_runs_rule_set_revision_id",
        "live_runs",
        (("rule_set_revision_id", False),),
    ),
    (
        "ix_live_runs_rule_set_id_updated_at_run_id_desc",
        "live_runs",
        (("rule_set_id", False), ("updated_at", True), ("run_id", True)),
    ),
    (
        "ix_game_sessions_rule_set_revision_id",
        "game_sessions",
        (("rule_set_revision_id", False),),
    ),
    (
        "ix_game_sessions_rule_set_id_created_at_session_id_desc",
        "game_sessions",
        (("rule_set_id", False), ("created_at", True), ("session_id", True)),
    ),
)


def _canonical_snapshot_hash(snapshot: object) -> str | None:
    try:
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _reject_nonfinite_json(_value: str) -> None:
    raise ValueError("non-finite JSON value")


def _parse_snapshot(raw_snapshot: object) -> dict[str, object] | None:
    if not isinstance(raw_snapshot, str):
        return None
    try:
        snapshot = json.loads(raw_snapshot, parse_constant=_reject_nonfinite_json)
        if not isinstance(snapshot, dict):
            return None
        json.dumps(snapshot, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None
    return snapshot


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


def _add_columns(connection: Any) -> None:
    live_existing = {column["name"] for column in sa.inspect(connection).get_columns("live_runs")}
    live_columns = (
        sa.Column(
            "rule_set_revision_id",
            sa.String(length=36),
            sa.ForeignKey(
                "rule_set_revisions.id",
                name="fk_live_runs_rule_set_revision_id_rule_set_revisions",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column("rule_set_revision_no", sa.Integer(), nullable=True),
        sa.Column("rule_set_content_hash", sa.String(length=64), nullable=True),
    )
    missing_live = [column for column in live_columns if column.name not in live_existing]
    if missing_live:
        with op.batch_alter_table("live_runs") as batch_op:
            for column in missing_live:
                batch_op.add_column(column)

    game_existing = {
        column["name"] for column in sa.inspect(connection).get_columns("game_sessions")
    }
    game_columns = (
        sa.Column("rule_set_id", sa.String(length=80), nullable=True),
        sa.Column(
            "rule_set_revision_id",
            sa.String(length=36),
            sa.ForeignKey(
                "rule_set_revisions.id",
                name="fk_game_sessions_rule_set_revision_id_rule_set_revisions",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column("rule_set_revision_no", sa.Integer(), nullable=True),
        sa.Column("rule_set_content_hash", sa.String(length=64), nullable=True),
    )
    missing_game = [column for column in game_columns if column.name not in game_existing]
    if missing_game:
        with op.batch_alter_table("game_sessions") as batch_op:
            for column in missing_game:
                batch_op.add_column(column)


def _backfill_game_sessions(connection: Any) -> None:
    game_sessions = sa.table(
        "game_sessions",
        sa.column("session_id", sa.String(length=32)),
        sa.column("rule_set_id", sa.String(length=80)),
        sa.column("rule_set_revision_id", sa.String(length=36)),
        sa.column("rule_set_revision_no", sa.Integer()),
        sa.column("rule_set_content_hash", sa.String(length=64)),
        sa.column("rule_set"),
    )
    raw_rule_set = sa.cast(game_sessions.c.rule_set, sa.Text()).label("raw_rule_set")
    stable_update = (
        game_sessions.update()
        .where(game_sessions.c.session_id == sa.bindparam("row_session_id"))
        .values(rule_set_id=sa.bindparam("target_rule_set_id"))
    )
    exact_update = (
        game_sessions.update()
        .where(game_sessions.c.session_id == sa.bindparam("row_session_id"))
        .values(
            rule_set_id=sa.bindparam("target_rule_set_id"),
            rule_set_revision_id=sa.bindparam("target_revision_id"),
            rule_set_revision_no=sa.bindparam("target_revision_no"),
            rule_set_content_hash=sa.bindparam("target_content_hash"),
        )
    )
    last_session_id: str | None = None
    while True:
        query = (
            sa.select(
                game_sessions.c.session_id,
                raw_rule_set,
                game_sessions.c.rule_set_id,
                game_sessions.c.rule_set_revision_id,
                game_sessions.c.rule_set_revision_no,
                game_sessions.c.rule_set_content_hash,
            )
            .order_by(game_sessions.c.session_id)
            .limit(_BACKFILL_BATCH_SIZE)
        )
        if last_session_id is not None:
            query = query.where(game_sessions.c.session_id > last_session_id)
        rows = connection.execute(query).mappings().all()
        if not rows:
            break

        stable_parameters: list[dict[str, object]] = []
        exact_parameters: list[dict[str, object]] = []
        for row in rows:
            snapshot = _parse_snapshot(row["raw_rule_set"])
            rule_set_id = _snapshot_rule_set_id(snapshot)
            revision_values = _revision_values(snapshot)
            if rule_set_id is None:
                continue
            if revision_values is None:
                if row["rule_set_id"] != rule_set_id:
                    stable_parameters.append(
                        {
                            "row_session_id": row["session_id"],
                            "target_rule_set_id": rule_set_id,
                        }
                    )
                continue
            if (
                row["rule_set_id"] == rule_set_id
                and row["rule_set_revision_id"] == revision_values["rule_set_revision_id"]
                and row["rule_set_revision_no"] == revision_values["rule_set_revision_no"]
                and row["rule_set_content_hash"] == revision_values["rule_set_content_hash"]
            ):
                continue
            exact_parameters.append(
                {
                    "row_session_id": row["session_id"],
                    "target_rule_set_id": rule_set_id,
                    "target_revision_id": revision_values["rule_set_revision_id"],
                    "target_revision_no": revision_values["rule_set_revision_no"],
                    "target_content_hash": revision_values["rule_set_content_hash"],
                }
            )

        if stable_parameters:
            connection.execute(stable_update, stable_parameters)
        if exact_parameters:
            connection.execute(exact_update, exact_parameters)
        last_session_id = rows[-1]["session_id"]
        if len(rows) < _BACKFILL_BATCH_SIZE:
            break


def _backfill_live_runs(connection: Any) -> None:
    live_runs = sa.table(
        "live_runs",
        sa.column("run_id", sa.String(length=32)),
        sa.column("rule_set_revision_id", sa.String(length=36)),
        sa.column("rule_set_revision_no", sa.Integer()),
        sa.column("rule_set_content_hash", sa.String(length=64)),
        sa.column("rule_set"),
    )
    raw_rule_set = sa.cast(live_runs.c.rule_set, sa.Text()).label("raw_rule_set")
    exact_update = (
        live_runs.update()
        .where(live_runs.c.run_id == sa.bindparam("row_run_id"))
        .values(
            rule_set_revision_id=sa.bindparam("target_revision_id"),
            rule_set_revision_no=sa.bindparam("target_revision_no"),
            rule_set_content_hash=sa.bindparam("target_content_hash"),
        )
    )
    last_run_id: str | None = None
    while True:
        query = (
            sa.select(
                live_runs.c.run_id,
                raw_rule_set,
                live_runs.c.rule_set_revision_id,
                live_runs.c.rule_set_revision_no,
                live_runs.c.rule_set_content_hash,
            )
            .order_by(live_runs.c.run_id)
            .limit(_BACKFILL_BATCH_SIZE)
        )
        if last_run_id is not None:
            query = query.where(live_runs.c.run_id > last_run_id)
        rows = connection.execute(query).mappings().all()
        if not rows:
            break

        exact_parameters: list[dict[str, object]] = []
        for row in rows:
            revision_values = _revision_values(_parse_snapshot(row["raw_rule_set"]))
            if revision_values is None:
                continue
            if (
                row["rule_set_revision_id"] == revision_values["rule_set_revision_id"]
                and row["rule_set_revision_no"] == revision_values["rule_set_revision_no"]
                and row["rule_set_content_hash"] == revision_values["rule_set_content_hash"]
            ):
                continue
            exact_parameters.append(
                {
                    "row_run_id": row["run_id"],
                    "target_revision_id": revision_values["rule_set_revision_id"],
                    "target_revision_no": revision_values["rule_set_revision_no"],
                    "target_content_hash": revision_values["rule_set_content_hash"],
                }
            )

        if exact_parameters:
            connection.execute(exact_update, exact_parameters)
        last_run_id = rows[-1]["run_id"]
        if len(rows) < _BACKFILL_BATCH_SIZE:
            break


def _postgresql_index_needs_replacement(
    catalog_entry: Any | None,
    *,
    table_name: str,
    columns: tuple[tuple[str, bool], ...],
) -> bool:
    if catalog_entry is None:
        return False
    expected_column_names = tuple(column_name for column_name, _descending in columns)
    expected_descending = tuple(descending for _column_name, descending in columns)
    return not (
        catalog_entry["table_name"] == table_name
        and catalog_entry["is_valid"] is True
        and catalog_entry["is_ready"] is True
        and catalog_entry["is_unique"] is False
        and catalog_entry["access_method"] == "btree"
        and catalog_entry["has_predicate"] is False
        and catalog_entry["has_expressions"] is False
        and catalog_entry["key_count"] == len(columns)
        and catalog_entry["total_column_count"] == len(columns)
        and tuple(catalog_entry["column_names"]) == expected_column_names
        and tuple(catalog_entry["descending"]) == expected_descending
    )


def _load_postgresql_index_catalog(connection: Any) -> dict[str, Any]:
    index_names = [index_name for index_name, _table_name, _columns in _POSTGRESQL_INDEX_SPECS]
    statement = sa.text(
        """
        SELECT index_relation.relname AS index_name,
               table_relation.relname AS table_name,
               index_metadata.indisvalid AS is_valid,
               index_metadata.indisready AS is_ready,
               index_metadata.indisunique AS is_unique,
               access_method.amname AS access_method,
               index_metadata.indpred IS NOT NULL AS has_predicate,
               index_metadata.indexprs IS NOT NULL AS has_expressions,
               index_metadata.indnkeyatts AS key_count,
               index_metadata.indnatts AS total_column_count,
               ARRAY(
                   SELECT table_attribute.attname
                   FROM unnest(index_metadata.indkey::smallint[])
                        WITH ORDINALITY AS key_column(attribute_number, position)
                   LEFT JOIN pg_catalog.pg_attribute AS table_attribute
                     ON table_attribute.attrelid = index_metadata.indrelid
                    AND table_attribute.attnum = key_column.attribute_number
                   WHERE key_column.position <= index_metadata.indnkeyatts
                   ORDER BY key_column.position
               ) AS column_names,
               ARRAY(
                   SELECT (sort_option.option_value & 1) = 1
                   FROM unnest(index_metadata.indoption::smallint[])
                        WITH ORDINALITY AS sort_option(option_value, position)
                   WHERE sort_option.position <= index_metadata.indnkeyatts
                   ORDER BY sort_option.position
               ) AS descending
        FROM pg_catalog.pg_class AS index_relation
        JOIN pg_catalog.pg_namespace AS index_namespace
          ON index_namespace.oid = index_relation.relnamespace
        JOIN pg_catalog.pg_index AS index_metadata
          ON index_metadata.indexrelid = index_relation.oid
        JOIN pg_catalog.pg_class AS table_relation
          ON table_relation.oid = index_metadata.indrelid
        JOIN pg_catalog.pg_am AS access_method
          ON access_method.oid = index_relation.relam
        WHERE index_namespace.nspname = current_schema()
          AND index_relation.relname IN :index_names
        """
    ).bindparams(sa.bindparam("index_names", expanding=True))
    rows = connection.execute(statement, {"index_names": index_names}).mappings()
    return {row["index_name"]: dict(row) for row in rows}


def _repair_postgresql_indexes(connection: Any) -> None:
    catalog = _load_postgresql_index_catalog(connection)
    for index_name, table_name, columns in _POSTGRESQL_INDEX_SPECS:
        if _postgresql_index_needs_replacement(
            catalog.get(index_name),
            table_name=table_name,
            columns=columns,
        ):
            op.drop_index(
                index_name,
                table_name=table_name,
                if_exists=True,
                postgresql_concurrently=True,
            )


def _create_indexes(*, postgresql_concurrently: bool) -> None:
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
    index_options: dict[str, bool] = {"if_not_exists": True}
    if postgresql_concurrently:
        index_options["postgresql_concurrently"] = True
    op.create_index(
        "ix_live_runs_rule_set_revision_id",
        "live_runs",
        [live_runs.c.rule_set_revision_id],
        **index_options,
    )
    op.create_index(
        "ix_live_runs_rule_set_id_updated_at_run_id_desc",
        "live_runs",
        [
            live_runs.c.rule_set_id,
            live_runs.c.updated_at.desc(),
            live_runs.c.run_id.desc(),
        ],
        **index_options,
    )
    op.create_index(
        "ix_game_sessions_rule_set_revision_id",
        "game_sessions",
        [game_sessions.c.rule_set_revision_id],
        **index_options,
    )
    op.create_index(
        "ix_game_sessions_rule_set_id_created_at_session_id_desc",
        "game_sessions",
        [
            game_sessions.c.rule_set_id,
            game_sessions.c.created_at.desc(),
            game_sessions.c.session_id.desc(),
        ],
        **index_options,
    )


def _drop_indexes(*, postgresql_concurrently: bool) -> None:
    index_options: dict[str, bool] = {"if_exists": True}
    if postgresql_concurrently:
        index_options["postgresql_concurrently"] = True
    op.drop_index(
        "ix_game_sessions_rule_set_id_created_at_session_id_desc",
        table_name="game_sessions",
        **index_options,
    )
    op.drop_index(
        "ix_game_sessions_rule_set_revision_id",
        table_name="game_sessions",
        **index_options,
    )
    op.drop_index(
        "ix_live_runs_rule_set_id_updated_at_run_id_desc",
        table_name="live_runs",
        **index_options,
    )
    op.drop_index(
        "ix_live_runs_rule_set_revision_id",
        table_name="live_runs",
        **index_options,
    )


def _drop_columns() -> None:
    with op.batch_alter_table("game_sessions") as batch_op:
        batch_op.drop_column("rule_set_content_hash")
        batch_op.drop_column("rule_set_revision_no")
        batch_op.drop_column("rule_set_revision_id")
        batch_op.drop_column("rule_set_id")

    with op.batch_alter_table("live_runs") as batch_op:
        batch_op.drop_column("rule_set_content_hash")
        batch_op.drop_column("rule_set_revision_no")
        batch_op.drop_column("rule_set_revision_id")


def upgrade() -> None:
    connection = op.get_bind()
    _add_columns(connection)
    if connection.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            autocommit_connection = op.get_bind()
            _backfill_game_sessions(autocommit_connection)
            _backfill_live_runs(autocommit_connection)
            _repair_postgresql_indexes(autocommit_connection)
            _create_indexes(postgresql_concurrently=True)
        return
    _backfill_game_sessions(connection)
    _backfill_live_runs(connection)
    _create_indexes(postgresql_concurrently=False)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            _drop_indexes(postgresql_concurrently=True)
    else:
        _drop_indexes(postgresql_concurrently=False)
    _drop_columns()
