from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260728_50_add_voice_tts_dialect.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "voice_tts_dialect_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_voice_tts_dialect_migration_upgrade_and_downgrade() -> None:
    migration = load_migration()
    assert migration.revision == "20260728_50"
    assert migration.down_revision == "20260728_49"

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    for table_name in ("voice_materialization_jobs", "voice_utterances"):
        sa.Table(
            table_name,
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
        )
    metadata.create_all(engine)

    with engine.begin() as connection:
        migration.op = Operations(
            MigrationContext.configure(connection, opts={"render_as_batch": True})
        )
        migration.upgrade()

        for table_name in ("voice_materialization_jobs", "voice_utterances"):
            columns = {
                item["name"]: item for item in sa.inspect(connection).get_columns(table_name)
            }
            assert columns["tts_dialect"]["type"].length == 16
            assert columns["tts_dialect"]["nullable"] is True

        migration.downgrade()
        for table_name in ("voice_materialization_jobs", "voice_utterances"):
            columns = {item["name"] for item in sa.inspect(connection).get_columns(table_name)}
            assert columns == {"id"}
