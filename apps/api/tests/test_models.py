import pytest
from sqlalchemy import JSON, LargeBinary, String, Text, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.admin import AdminSession, AuditEvent
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import (
    LiveEventRecord,
    LiveRunRecord,
    VoiceAudioChunkRecord,
    VoiceUtteranceRecord,
)
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.public import PublicSession, UserFavoritePlayerProfile
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile


def _assert_string_column(column, *, length: int, nullable: bool) -> None:
    assert isinstance(column.type, String)
    assert column.type.length == length
    assert column.nullable is nullable


def _assert_text_column(column, *, nullable: bool) -> None:
    assert isinstance(column.type, Text)
    assert column.nullable is nullable


def _assert_json_column(column, *, nullable: bool) -> None:
    assert isinstance(column.type, JSON)
    assert column.nullable is nullable


def _assert_index(table, name: str, columns: list[str]) -> None:
    index = next((candidate for candidate in table.indexes if candidate.name == name), None)
    assert index is not None
    assert [column.name for column in index.columns] == columns


def _assert_foreign_key(column, *, target: str, ondelete: str | None) -> None:
    assert len(column.foreign_keys) == 1
    foreign_key = next(iter(column.foreign_keys))
    assert foreign_key.target_fullname == target
    assert foreign_key.ondelete == ondelete


def test_user_table_is_registered_in_metadata() -> None:
    assert User.__table__.name == "users"
    assert "users" in Base.metadata.tables


def test_user_table_matches_expected_schema() -> None:
    table = User.__table__
    column_names = set(table.columns.keys())

    assert column_names == {
        "id",
        "email",
        "display_name",
        "auth_provider",
        "auth_subject",
        "admin_role",
        "admin_version",
        "is_active",
        "created_at",
        "updated_at",
    }
    assert table.c.email.unique is True
    assert table.c.email.index is True
    assert any(index.name == "ix_users_email" for index in table.indexes)
    assert table.c.created_at.server_default is not None
    assert "now" in str(table.c.created_at.server_default.arg).lower()
    assert table.c.admin_role.nullable is True
    assert table.c.auth_provider.nullable is True
    assert table.c.auth_subject.nullable is True
    assert any(
        constraint.name == "ck_users_auth_identity_paired"
        for constraint in table.constraints
    )
    assert any(
        constraint.name == "uq_users_auth_provider_subject"
        for constraint in table.constraints
    )
    assert table.c.admin_role.index is True
    assert table.c.admin_version.nullable is False
    assert table.c.admin_version.server_default is not None
    assert table.c.is_active.nullable is False
    assert table.c.is_active.server_default is not None
    assert table.c.updated_at.server_default is not None


def test_user_auth_identity_must_be_paired_and_unique() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            User(
                email="invalid-guest@example.test",
                display_name="Invalid guest",
                auth_provider="guest",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            User(
                email="guest-one@example.test",
                display_name="Guest one",
                auth_provider="guest",
                auth_subject="browser-subject",
            )
        )
        session.commit()

        session.add(
            User(
                email="guest-two@example.test",
                display_name="Guest two",
                auth_provider="guest",
                auth_subject="browser-subject",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_public_session_table_matches_expected_schema() -> None:
    table = PublicSession.__table__

    assert set(table.columns.keys()) == {
        "id",
        "user_id",
        "token_hash",
        "csrf_token_hash",
        "created_at",
        "expires_at",
        "revoked_at",
    }
    assert table.c.id.primary_key is True
    _assert_foreign_key(table.c.user_id, target="users.id", ondelete="CASCADE")
    _assert_string_column(table.c.token_hash, length=64, nullable=False)
    assert table.c.token_hash.unique is True
    assert table.c.token_hash.index is True
    _assert_string_column(table.c.csrf_token_hash, length=64, nullable=False)
    assert table.c.expires_at.index is True
    assert table.c.revoked_at.index is True


def test_user_favorite_player_profile_table_matches_expected_schema() -> None:
    table = UserFavoritePlayerProfile.__table__

    assert set(table.columns.keys()) == {
        "user_id",
        "player_profile_id",
        "created_at",
    }
    assert table.primary_key.columns.keys() == ["user_id", "player_profile_id"]
    _assert_foreign_key(table.c.user_id, target="users.id", ondelete="CASCADE")
    _assert_foreign_key(
        table.c.player_profile_id,
        target="virtual_player_profiles.id",
        ondelete="CASCADE",
    )
    _assert_index(
        table,
        "ix_user_favorite_player_profiles_profile_user",
        ["player_profile_id", "user_id"],
    )


def test_admin_session_table_matches_expected_schema() -> None:
    table = AdminSession.__table__

    assert set(table.columns.keys()) == {
        "id",
        "user_id",
        "token_hash",
        "csrf_token_hash",
        "created_at",
        "expires_at",
        "revoked_at",
        "ip_address",
        "user_agent",
    }
    _assert_foreign_key(table.c.user_id, target="users.id", ondelete="CASCADE")
    _assert_string_column(table.c.token_hash, length=64, nullable=False)
    assert table.c.token_hash.unique is True
    assert table.c.token_hash.index is True
    _assert_string_column(table.c.csrf_token_hash, length=64, nullable=False)
    assert table.c.expires_at.index is True


def test_audit_event_table_matches_expected_schema() -> None:
    table = AuditEvent.__table__

    assert set(table.columns.keys()) == {
        "id",
        "actor_user_id",
        "action",
        "resource_type",
        "resource_id",
        "result",
        "reason",
        "before",
        "after",
        "request_id",
        "ip_address",
        "created_at",
    }
    _assert_foreign_key(table.c.actor_user_id, target="users.id", ondelete="SET NULL")
    _assert_json_column(table.c.before, nullable=True)
    _assert_json_column(table.c.after, nullable=True)
    _assert_text_column(table.c.reason, nullable=True)
    _assert_index(table, "ix_audit_events_resource", ["resource_type", "resource_id"])


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
        "featured",
        "tags",
        "status",
        "version",
        "published_at",
        "published_by_user_id",
        "updated_by_user_id",
        "deleted_at",
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
    assert table.c.status.server_default is not None
    assert table.c.version.server_default is not None
    assert table.c.published_at.server_default is not None
    assert table.c.published_by_user_id.foreign_keys
    assert table.c.updated_by_user_id.foreign_keys
    _assert_index(
        table,
        "ix_virtual_player_profiles_status_display_order",
        ["status", "display_order", "id"],
    )
    _assert_index(
        table,
        "ix_virtual_player_profiles_status_updated_at",
        ["status", "updated_at", "id"],
    )


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
        "stop_requested_at",
        "worker_id",
        "worker_heartbeat_at",
        "lease_expires_at",
        "control_version",
        "fence_token",
        "recovery_attempts",
        "recovery_last_attempt_at",
        "recovery_not_before",
        "recovery_last_error",
        "updated_at",
    }
    assert table.c.run_id.primary_key is True
    _assert_string_column(table.c.run_id, length=32, nullable=False)
    assert table.c.session_id.index is True
    _assert_string_column(table.c.session_id, length=32, nullable=False)
    _assert_string_column(table.c.status, length=20, nullable=False)
    _assert_string_column(table.c.villager_model, length=120, nullable=False)
    _assert_string_column(table.c.werewolf_model, length=120, nullable=False)
    assert table.c.seed.nullable is True
    assert table.c.max_rounds.nullable is False
    _assert_string_column(table.c.rule_set_id, length=80, nullable=False)
    _assert_json_column(table.c.rule_set, nullable=True)
    _assert_json_column(table.c.player_configs, nullable=False)
    _assert_json_column(table.c.lineup_quality_warnings, nullable=False)
    _assert_string_column(table.c.winner, length=80, nullable=True)
    _assert_text_column(table.c.error, nullable=True)
    assert table.c.created_at.nullable is False
    assert table.c.started_at.nullable is True
    assert table.c.completed_at.nullable is True
    _assert_string_column(table.c.worker_id, length=64, nullable=True)
    assert table.c.worker_heartbeat_at.nullable is True
    assert table.c.lease_expires_at.nullable is True
    assert table.c.control_version.nullable is False
    assert table.c.fence_token.nullable is False
    assert table.c.recovery_attempts.nullable is False
    assert table.c.recovery_last_attempt_at.nullable is True
    assert table.c.recovery_not_before.nullable is True
    _assert_text_column(table.c.recovery_last_error, nullable=True)
    assert table.c.updated_at.nullable is False
    _assert_index(table, "ix_live_runs_session_id", ["session_id"])
    _assert_index(table, "ix_live_runs_status", ["status"])
    _assert_index(table, "ix_live_runs_updated_at", ["updated_at"])
    _assert_index(table, "ix_live_runs_recovery_not_before", ["recovery_not_before"])
    _assert_index(table, "uq_live_runs_active_session", ["session_id"])
    active_session_index = next(
        index for index in table.indexes if index.name == "uq_live_runs_active_session"
    )
    assert active_session_index.unique is True


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
    _assert_string_column(table.c.run_id, length=32, nullable=False)
    _assert_foreign_key(table.c.run_id, target="live_runs.run_id", ondelete="CASCADE")
    assert table.c.event_id.nullable is False
    _assert_string_column(table.c.session_id, length=32, nullable=False)
    _assert_string_column(table.c.type, length=80, nullable=False)
    assert table.c.round.nullable is True
    _assert_string_column(table.c.phase, length=40, nullable=True)
    _assert_string_column(table.c.actor, length=120, nullable=True)
    _assert_string_column(table.c.action, length=80, nullable=True)
    _assert_json_column(table.c.payload, nullable=False)
    assert table.c.created_at.nullable is False
    _assert_index(table, "ix_live_events_run_id_event_id", ["run_id", "event_id"])
    _assert_index(table, "ix_live_events_session_id", ["session_id"])
    _assert_index(table, "ix_live_events_type", ["type"])


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
        "subtitle_timings",
        "error_message",
        "created_at",
        "updated_at",
        "completed_at",
    }
    assert table.c.utterance_id.primary_key is True
    _assert_string_column(table.c.utterance_id, length=40, nullable=False)
    assert table.c.run_id.index is True
    _assert_string_column(table.c.run_id, length=32, nullable=False)
    assert table.c.session_id.index is True
    _assert_string_column(table.c.session_id, length=32, nullable=False)
    assert table.c.source_event_id.nullable is False
    assert table.c.last_source_event_id.nullable is False
    _assert_string_column(table.c.request_id, length=80, nullable=True)
    _assert_string_column(table.c.speaker_kind, length=20, nullable=False)
    _assert_string_column(table.c.speaker_name, length=120, nullable=False)
    _assert_string_column(table.c.speaker, length=160, nullable=False)
    _assert_string_column(table.c.action, length=80, nullable=True)
    _assert_text_column(table.c.text, nullable=False)
    _assert_string_column(table.c.text_hash, length=64, nullable=False)
    _assert_string_column(table.c.audio_format, length=20, nullable=False)
    assert table.c.sample_rate.nullable is False
    _assert_string_column(table.c.mime_type, length=80, nullable=False)
    _assert_string_column(table.c.status, length=30, nullable=False)
    assert table.c.duration_ms.nullable is True
    _assert_json_column(table.c.subtitle_timings, nullable=True)
    _assert_text_column(table.c.error_message, nullable=True)
    assert table.c.created_at.nullable is False
    assert table.c.updated_at.nullable is False
    assert table.c.completed_at.nullable is True
    _assert_index(table, "ix_voice_utterances_run_id", ["run_id"])
    _assert_index(table, "ix_voice_utterances_session_id", ["session_id"])
    _assert_index(table, "ix_voice_utterances_run_source_event", ["run_id", "source_event_id"])
    _assert_index(table, "ix_voice_utterances_request_id", ["request_id"])
    _assert_index(table, "ix_voice_utterances_text_hash", ["text_hash"])
    _assert_index(table, "ix_voice_utterances_status", ["status"])


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
    _assert_string_column(table.c.utterance_id, length=40, nullable=False)
    _assert_foreign_key(
        table.c.utterance_id,
        target="voice_utterances.utterance_id",
        ondelete="CASCADE",
    )
    assert table.c.chunk_index.nullable is False
    assert isinstance(table.c.audio.type, LargeBinary)
    assert table.c.audio.nullable is False
    assert table.c.byte_length.nullable is False
    assert table.c.created_at.nullable is False
