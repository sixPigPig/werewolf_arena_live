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
    / "20260721_33_seed_default_virtual_players.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "default_virtual_player_roster_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_roster_is_complete_diverse_and_reversible() -> None:
    migration = load_migration()
    assert migration.revision == "20260721_33"
    assert migration.down_revision == "20260720_32"

    metadata = sa.MetaData()
    profiles = sa.Table(
        "virtual_player_profiles",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("personality_id", sa.String(40), nullable=False),
        sa.Column("personality_text", sa.Text(), nullable=False),
        sa.Column("appearance_id", sa.String(40), nullable=False),
        sa.Column("avatar_image_url", sa.Text(), nullable=False),
        sa.Column("avatar_image_mime", sa.String(80), nullable=False),
        sa.Column("avatar_asset_id", sa.String(80), nullable=False),
        sa.Column("short_description", sa.String(160), nullable=False),
        sa.Column("background_story", sa.Text(), nullable=False),
        sa.Column("speaking_style", sa.Text(), nullable=False),
        sa.Column("gender", sa.String(12), nullable=False),
        sa.Column("tts_speaker", sa.String(160), nullable=False),
        sa.Column("catchphrases", sa.JSON(), nullable=False),
        sa.Column("strategy_profile", sa.String(40), nullable=False),
        sa.Column("risk_tolerance", sa.Integer(), nullable=False),
        sa.Column("bluffing_tendency", sa.Integer(), nullable=False),
        sa.Column("trust_tendency", sa.Integer(), nullable=False),
        sa.Column("leadership_tendency", sa.Integer(), nullable=False),
        sa.Column("talkativeness", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("base_delivery_mood", sa.String(24), nullable=False),
        sa.Column("base_delivery_intensity", sa.String(16), nullable=False),
        sa.Column("base_delivery_pace", sa.String(16), nullable=False),
        sa.Column("base_delivery_instruction", sa.String(240), nullable=False),
    )
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        rows = connection.execute(sa.select(profiles)).mappings().all()
        assert len(rows) == 12
        assert len({row["display_name"] for row in rows}) == 12
        assert len({row["personality_id"] for row in rows}) == 5
        assert len({row["strategy_profile"] for row in rows}) == 6
        assert len({row["appearance_id"] for row in rows}) == 4
        assert {row["gender"] for row in rows} == {"female", "male"}
        assert all(row["tts_speaker"] for row in rows)

        migration.downgrade()
        assert connection.scalar(sa.select(sa.func.count()).select_from(profiles)) == 0
