from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import (
    LiveEventRecord,
    LiveRunRecord,
    VoiceAudioChunkRecord,
    VoiceUtteranceRecord,
)
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile


def test_user_table_is_registered_in_metadata() -> None:
    assert User.__table__.name == "users"
    assert "users" in Base.metadata.tables


def test_user_table_matches_expected_schema() -> None:
    table = User.__table__
    column_names = set(table.columns.keys())

    assert column_names == {"id", "email", "display_name", "created_at"}
    assert table.c.email.unique is True
    assert table.c.email.index is True
    assert any(index.name == "ix_users_email" for index in table.indexes)
    assert table.c.created_at.server_default is not None
    assert "now" in str(table.c.created_at.server_default.arg).lower()


def test_virtual_player_profile_table_is_registered_in_metadata() -> None:
    assert VirtualPlayerProfile.__table__.name == "virtual_player_profiles"
    assert "virtual_player_profiles" in Base.metadata.tables


def test_virtual_player_profile_table_matches_expected_schema() -> None:
    table = VirtualPlayerProfile.__table__
    column_names = set(table.columns.keys())

    assert column_names == {
        "id",
        "owner_user_id",
        "display_name",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_prompt",
        "avatar_image_url",
        "avatar_image_path",
        "avatar_image_mime",
        "avatar_asset_id",
        "short_description",
        "background_story",
        "speaking_style",
        "catchphrases",
        "strategy_profile",
        "risk_tolerance",
        "bluffing_tendency",
        "trust_tendency",
        "leadership_tendency",
        "talkativeness",
        "example_messages",
        "display_order",
        "favorite",
        "tags",
        "created_at",
        "updated_at",
    }
    assert table.c.id.primary_key is True
    assert table.c.owner_user_id.foreign_keys
    assert table.c.owner_user_id.index is True
    assert table.c.display_name.nullable is False
    assert table.c.model.nullable is False
    assert table.c.personality_id.nullable is False
    assert table.c.appearance_id.nullable is False
    assert table.c.tags.nullable is False
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None


def test_virtual_player_profile_tag_append_is_persisted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        profile = VirtualPlayerProfile(
            id="profile-1",
            display_name="控场位",
            model="gpt-4.1-mini",
            personality_id="balanced",
            personality_text="稳健推进",
            appearance_id="default",
            avatar_prompt="",
            avatar_image_url="",
            avatar_image_path="",
            avatar_image_mime="",
            tags=[],
        )
        session.add(profile)
        session.commit()

        profile.tags.append("控场")
        session.commit()
        session.expunge_all()

        saved_profile = session.get(VirtualPlayerProfile, "profile-1")

    assert saved_profile is not None
    assert saved_profile.tags == ["控场"]


def test_virtual_player_profile_rich_list_appends_are_persisted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        profile = VirtualPlayerProfile(
            id="profile-1",
            display_name="控场位",
            model="gpt-4.1-mini",
            personality_id="balanced",
            personality_text="稳健推进",
            appearance_id="default",
            avatar_prompt="",
            avatar_image_url="",
            avatar_image_path="",
            avatar_image_mime="",
            catchphrases=[],
            example_messages=[],
            tags=[],
        )
        session.add(profile)
        session.commit()

        profile.catchphrases.append("我先盘票型")
        profile.example_messages.append("先听后置位补充。")
        session.commit()
        session.expunge_all()

        saved_profile = session.get(VirtualPlayerProfile, "profile-1")

    assert saved_profile is not None
    assert saved_profile.catchphrases == ["我先盘票型"]
    assert saved_profile.example_messages == ["先听后置位补充。"]


def test_virtual_player_profile_has_rich_character_columns() -> None:
    table = VirtualPlayerProfile.__table__

    for column_name in (
        "short_description",
        "background_story",
        "speaking_style",
        "catchphrases",
        "strategy_profile",
        "risk_tolerance",
        "bluffing_tendency",
        "trust_tendency",
        "leadership_tendency",
        "talkativeness",
        "example_messages",
        "display_order",
        "favorite",
    ):
        assert column_name in table.c
        assert table.c[column_name].nullable is False


def test_player_avatar_asset_table_is_registered_in_metadata() -> None:
    assert PlayerAvatarAsset.__table__.name == "player_avatar_assets"
    assert "player_avatar_assets" in Base.metadata.tables


def test_player_avatar_asset_table_matches_expected_schema() -> None:
    table = PlayerAvatarAsset.__table__
    column_names = set(table.columns.keys())

    assert column_names == {
        "id",
        "source",
        "content_type",
        "data",
        "sha256",
        "size_bytes",
        "created_at",
    }
    assert table.c.id.primary_key is True
    assert table.c.source.nullable is False
    assert table.c.content_type.nullable is False
    assert table.c.data.nullable is False
    assert table.c.sha256.nullable is False
    assert table.c.sha256.index is True
    assert table.c.size_bytes.nullable is False
    assert table.c.created_at.server_default is not None


def test_virtual_player_profile_has_avatar_asset_reference() -> None:
    table = VirtualPlayerProfile.__table__

    assert "avatar_asset_id" in table.columns
    assert table.c.avatar_asset_id.nullable is True
    assert table.c.avatar_asset_id.foreign_keys


def test_game_session_table_is_registered_in_metadata() -> None:
    assert GameSessionRecord.__table__.name == "game_sessions"
    assert "game_sessions" in Base.metadata.tables


def test_game_session_table_matches_expected_schema() -> None:
    table = GameSessionRecord.__table__
    column_names = set(table.columns.keys())

    assert column_names == {
        "session_id",
        "status",
        "winner",
        "round_count",
        "rule_set",
        "resumable",
        "created_at",
        "updated_at",
    }
    assert table.c.session_id.primary_key is True
    assert table.c.status.nullable is False
    assert table.c.round_count.nullable is False
    assert table.c.resumable.nullable is False
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None
    assert any(index.name == "ix_game_sessions_status" for index in table.indexes)
    assert any(index.name == "ix_game_sessions_updated_at" for index in table.indexes)


def test_game_replay_payload_table_matches_expected_schema() -> None:
    table = GameReplayPayload.__table__
    column_names = set(table.columns.keys())

    assert column_names == {"session_id", "state", "logs", "checkpoint"}
    assert table.c.session_id.primary_key is True
    assert table.c.session_id.foreign_keys
    foreign_key = next(iter(table.c.session_id.foreign_keys))
    assert foreign_key.ondelete == "CASCADE"
    assert table.c.state.nullable is False
    assert table.c.logs.nullable is False
    assert table.c.checkpoint.nullable is True


def test_live_run_table_matches_expected_schema() -> None:
    table = LiveRunRecord.__table__

    assert table.name == "live_runs"
    assert set(table.columns.keys()) == {
        "run_id",
        "session_id",
        "status",
        "villager_model",
        "werewolf_model",
        "seed",
        "max_rounds",
        "rule_set_id",
        "rule_set",
        "player_configs",
        "lineup_quality_warnings",
        "winner",
        "error",
        "created_at",
        "started_at",
        "completed_at",
        "updated_at",
    }
    assert table.c.run_id.primary_key is True
    assert table.c.session_id.index is True
    assert any(index.name == "ix_live_runs_status" for index in table.indexes)
    assert any(index.name == "ix_live_runs_updated_at" for index in table.indexes)


def test_live_event_table_matches_expected_schema() -> None:
    table = LiveEventRecord.__table__

    assert table.name == "live_events"
    assert set(table.columns.keys()) == {
        "run_id",
        "event_id",
        "session_id",
        "type",
        "round",
        "phase",
        "actor",
        "action",
        "payload",
        "created_at",
    }
    assert table.primary_key.columns.keys() == ["run_id", "event_id"]
    assert table.c.run_id.foreign_keys
    assert any(index.name == "ix_live_events_run_id_event_id" for index in table.indexes)
    assert any(index.name == "ix_live_events_session_id" for index in table.indexes)
    assert any(index.name == "ix_live_events_type" for index in table.indexes)


def test_voice_utterance_table_matches_expected_schema() -> None:
    table = VoiceUtteranceRecord.__table__

    assert table.name == "voice_utterances"
    assert set(table.columns.keys()) == {
        "utterance_id",
        "run_id",
        "session_id",
        "source_event_id",
        "last_source_event_id",
        "request_id",
        "speaker_kind",
        "speaker_name",
        "speaker",
        "action",
        "text",
        "text_hash",
        "audio_format",
        "sample_rate",
        "mime_type",
        "status",
        "duration_ms",
        "error_message",
        "created_at",
        "updated_at",
        "completed_at",
    }
    assert table.c.utterance_id.primary_key is True
    assert any(index.name == "ix_voice_utterances_run_source_event" for index in table.indexes)
    assert any(index.name == "ix_voice_utterances_request_id" for index in table.indexes)
    assert any(index.name == "ix_voice_utterances_text_hash" for index in table.indexes)
    assert any(index.name == "ix_voice_utterances_status" for index in table.indexes)


def test_voice_audio_chunk_table_matches_expected_schema() -> None:
    table = VoiceAudioChunkRecord.__table__

    assert table.name == "voice_audio_chunks"
    assert set(table.columns.keys()) == {
        "utterance_id",
        "chunk_index",
        "audio",
        "byte_length",
        "created_at",
    }
    assert table.primary_key.columns.keys() == ["utterance_id", "chunk_index"]
    assert table.c.utterance_id.foreign_keys
    foreign_key = next(iter(table.c.utterance_id.foreign_keys))
    assert foreign_key.ondelete == "CASCADE"
