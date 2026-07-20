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
    / "20260719_31_add_liveness_runtime_contracts.py"
)
VOICE_TIMING_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260720_32_add_liveness_voice_timings.py"
)
ROLLOUT_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260720_33_add_liveness_rollout_config.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("liveness_runtime_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_voice_timing_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "liveness_voice_timing_migration",
        VOICE_TIMING_MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_rollout_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "liveness_rollout_migration",
        ROLLOUT_MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_liveness_runtime_migration_upgrade_and_downgrade() -> None:
    migration = load_migration()
    assert migration.revision == "20260719_31"
    assert migration.down_revision == "20260719_30"

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "game_sessions",
        metadata,
        sa.Column("session_id", sa.String(32), primary_key=True),
    )
    sa.Table(
        "live_runs",
        metadata,
        sa.Column("run_id", sa.String(32), primary_key=True),
    )
    sa.Table(
        "voice_utterances",
        metadata,
        sa.Column("utterance_id", sa.String(40), primary_key=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        migration.op = Operations(
            MigrationContext.configure(connection, opts={"render_as_batch": True})
        )
        migration.upgrade()

        inspector = sa.inspect(connection)
        assert {
            "actor_mind_snapshots",
            "speech_turn_receipts",
            "speech_turn_segments",
            "voice_playback_observations",
        } <= set(inspector.get_table_names())
        for table_name in ("game_sessions", "live_runs"):
            columns = {item["name"] for item in inspector.get_columns(table_name)}
            assert {
                "liveness_experience_revision",
                "liveness_experience_snapshot",
                "liveness_experiment_id",
                "liveness_experiment_variant",
            } <= columns
        voice_columns = {item["name"] for item in inspector.get_columns("voice_utterances")}
        assert {
            "action_id",
            "speech_id",
            "segment_id",
            "segment_index",
            "segment_final",
        } <= voice_columns

        migration.downgrade()

        inspector = sa.inspect(connection)
        assert {
            "actor_mind_snapshots",
            "speech_turn_receipts",
            "speech_turn_segments",
            "voice_playback_observations",
        }.isdisjoint(inspector.get_table_names())
        assert {item["name"] for item in inspector.get_columns("game_sessions")} == {"session_id"}
        assert {item["name"] for item in inspector.get_columns("live_runs")} == {"run_id"}
        assert {item["name"] for item in inspector.get_columns("voice_utterances")} == {
            "utterance_id"
        }


def test_liveness_voice_timing_migration_upgrade_and_downgrade() -> None:
    migration = load_voice_timing_migration()
    assert migration.revision == "20260720_32"
    assert migration.down_revision == "20260719_31"

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "voice_utterances",
        metadata,
        sa.Column("utterance_id", sa.String(40), primary_key=True),
    )
    sa.Table(
        "voice_playback_observations",
        metadata,
        sa.Column("playback_session_id", sa.String(64), primary_key=True),
        sa.Column("utterance_id", sa.String(40), primary_key=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        migration.op = Operations(
            MigrationContext.configure(connection, opts={"render_as_batch": True})
        )
        migration.upgrade()
        inspector = sa.inspect(connection)
        assert {
            "tts_started_at",
            "first_audio_chunk_at",
        } <= {item["name"] for item in inspector.get_columns("voice_utterances")}
        assert {
            "playback_started_at",
            "playback_finished_at",
            "ack_received_at",
        } <= {item["name"] for item in inspector.get_columns("voice_playback_observations")}

        migration.downgrade()
        inspector = sa.inspect(connection)
        assert {item["name"] for item in inspector.get_columns("voice_utterances")} == {
            "utterance_id"
        }
        assert {item["name"] for item in inspector.get_columns("voice_playback_observations")} == {
            "playback_session_id",
            "utterance_id",
        }


def test_liveness_rollout_migration_upgrade_and_downgrade() -> None:
    migration = load_rollout_migration()
    assert migration.revision == "20260720_33"
    assert migration.down_revision == "20260720_32"

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = sa.inspect(connection)
        assert "liveness_rollout_configs" in inspector.get_table_names()
        columns = {item["name"]: item for item in inspector.get_columns("liveness_rollout_configs")}
        assert set(columns) == {
            "id",
            "revision",
            "experience_revision",
            "experiment_id",
            "treatment_percent",
            "updated_by_user_id",
            "created_at",
            "updated_at",
        }
        assert columns["id"]["primary_key"] == 1
        assert columns["updated_by_user_id"]["nullable"] is True

        migration.downgrade()
        assert "liveness_rollout_configs" not in sa.inspect(connection).get_table_names()
