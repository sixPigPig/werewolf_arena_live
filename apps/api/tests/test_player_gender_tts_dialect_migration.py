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
    / "20260719_30_add_player_gender_and_tts_dialect.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "player_gender_tts_dialect_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_player_gender_tts_dialect_migration_upgrade_and_downgrade() -> None:
    migration = load_migration()
    assert migration.revision == "20260719_30"
    assert migration.down_revision == "20260719_29"

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    profiles = sa.Table(
        "virtual_player_profiles",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tts_speaker", sa.String(160), nullable=False, server_default=""),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            profiles.insert(),
            [
                {"id": "female", "tts_speaker": "zh_female_vv_uranus_bigtts"},
                {"id": "male", "tts_speaker": "zh_male_m191_uranus_bigtts"},
                {"id": "inherit", "tts_speaker": ""},
            ],
        )
        migration.op = Operations(
            MigrationContext.configure(connection, opts={"render_as_batch": True})
        )
        migration.upgrade()

        upgraded = sa.Table(
            "virtual_player_profiles",
            sa.MetaData(),
            autoload_with=connection,
        )
        rows = {
            row.id: (row.gender, row.tts_dialect)
            for row in connection.execute(
                sa.select(
                    upgraded.c.id,
                    upgraded.c.gender,
                    upgraded.c.tts_dialect,
                )
            )
        }
        assert rows == {
            "female": ("female", ""),
            "male": ("male", ""),
            "inherit": ("female", ""),
        }
        constraints = {
            item["name"]
            for item in sa.inspect(connection).get_check_constraints(
                "virtual_player_profiles"
            )
        }
        assert "ck_virtual_player_profiles_gender" in constraints
        assert "ck_virtual_player_profiles_tts_dialect" in constraints

        migration.downgrade()
        columns = {
            item["name"]
            for item in sa.inspect(connection).get_columns("virtual_player_profiles")
        }
        assert columns == {"id", "tts_speaker"}
