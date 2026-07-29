from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260729_51_add_first_night_last_words_rule.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "first_night_last_words_rule_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_first_night_last_words_rule_migration_updates_config_and_hash() -> None:
    migration = _load_migration()
    assert migration.revision == "20260729_51"
    assert migration.down_revision == "20260728_50"

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    revisions = sa.Table(
        "rule_set_revisions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_set_id", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    metadata.create_all(engine)
    base = {
        "name": "测试规则",
        "werewolf_self_explosion_enabled": False,
    }

    with engine.begin() as connection:
        connection.execute(
            revisions.insert(),
            [
                {
                    "id": "ordinary",
                    "rule_set_id": "custom_rule",
                    "schema_version": 1,
                    "config": base,
                    "content_hash": "0" * 64,
                },
                {
                    "id": "classic-12",
                    "rule_set_id": "classic_12_seer_witch_hunter_idiot",
                    "schema_version": 1,
                    "config": base,
                    "content_hash": "0" * 64,
                },
            ],
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        upgraded = {
            row.id: row
            for row in connection.execute(
                sa.select(revisions).order_by(revisions.c.id)
            ).mappings()
        }
        assert upgraded["ordinary"]["config"]["first_night_last_words_enabled"] is False
        assert upgraded["classic-12"]["config"]["first_night_last_words_enabled"] is True
        assert all(
            row["content_hash"]
            == migration._content_hash(
                schema_version=1,
                config=dict(row["config"]),
            )
            for row in upgraded.values()
        )

        migration.downgrade()
        downgraded = list(connection.execute(sa.select(revisions)).mappings())
        assert all(
            "first_night_last_words_enabled" not in row["config"]
            for row in downgraded
        )
        assert all(
            row["content_hash"]
            == migration._content_hash(
                schema_version=1,
                config=json.loads(json.dumps(row["config"])),
            )
            for row in downgraded
        )
