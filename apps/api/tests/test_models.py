from datetime import UTC, datetime

import pytest
from sqlalchemy import JSON, LargeBinary, String, Text, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.admin import AdminSession, AuditEvent
from app.models.game_session import (
    ActorMindSnapshotRecord,
    GameReplayPayload,
    GameSessionRecord,
    SpeechTurnReceiptRecord,
    SpeechTurnSegmentRecord,
    VoicePlaybackObservationRecord,
)
from app.models.live import (
    LiveEventRecord,
    LiveRunRecord,
    VoiceAudioChunkRecord,
    VoiceUtteranceRecord,
)
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.public import PublicSession, UserFavoritePlayerProfile
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.models.runtime_worker import RuntimeWorkerRecord
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
        constraint.name == "ck_users_auth_identity_paired" for constraint in table.constraints
    )
    assert any(
        constraint.name == "uq_users_auth_provider_subject" for constraint in table.constraints
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
        "display_name",
        "model_provider",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_image_url",
        "avatar_image_mime",
        "avatar_asset_id",
        "short_description",
        "background_story",
        "speaking_style",
        "gender",
        "tts_speaker",
        "tts_dialect",
        "base_delivery_mood",
        "base_delivery_intensity",
        "base_delivery_pace",
        "base_delivery_instruction",
        "voice_enabled",
        "voice_config_version",
        "catchphrases",
        "strategy_profile",
        "risk_tolerance",
        "bluffing_tendency",
        "trust_tendency",
        "leadership_tendency",
        "talkativeness",
        "example_messages",
        "display_order",
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
    assert table.c.display_name.nullable is False
    _assert_string_column(table.c.model_provider, length=32, nullable=False)
    assert table.c.model.nullable is False
    assert table.c.personality_id.nullable is False
    assert table.c.appearance_id.nullable is False
    _assert_string_column(table.c.gender, length=12, nullable=False)
    _assert_string_column(table.c.tts_speaker, length=160, nullable=False)
    _assert_string_column(table.c.tts_dialect, length=16, nullable=False)
    _assert_string_column(table.c.base_delivery_mood, length=24, nullable=False)
    _assert_string_column(table.c.base_delivery_intensity, length=16, nullable=False)
    _assert_string_column(table.c.base_delivery_pace, length=16, nullable=False)
    _assert_string_column(
        table.c.base_delivery_instruction,
        length=240,
        nullable=False,
    )
    assert table.c.voice_enabled.nullable is False
    assert table.c.voice_config_version.nullable is False
    assert table.c.tags.nullable is False
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None
    assert table.c.status.server_default is not None
    assert table.c.version.server_default is not None
    assert table.c.published_at.server_default is None
    assert table.c.published_by_user_id.foreign_keys
    assert table.c.updated_by_user_id.foreign_keys
    _assert_index(
        table,
        "ix_virtual_player_profiles_status_display_order",
        ["status", "display_order", "id"],
    )
    _assert_index(
        table,
        "uq_virtual_player_profiles_published_display_order",
        ["display_order"],
    )
    _assert_index(
        table,
        "ix_virtual_player_profiles_status_updated_at",
        ["status", "updated_at", "id"],
    )
    _assert_index(
        table,
        "ix_virtual_player_profiles_status_model",
        ["status", "model_provider", "model"],
    )
    assert any(
        constraint.name == "fk_virtual_player_profiles_model_configuration"
        and [column.name for column in constraint.columns]
        == ["model_provider", "model"]
        for constraint in table.foreign_key_constraints
    )


def test_virtual_player_profile_tag_append_is_persisted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        profile = VirtualPlayerProfile(
            id="profile-1",
            display_name="控场位",
            model_provider="deepseek",
            model="gpt-4.1-mini",
            personality_id="balanced",
            personality_text="稳健推进",
            appearance_id="default",
            avatar_image_url="",
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
            model_provider="deepseek",
            model="gpt-4.1-mini",
            personality_id="balanced",
            personality_text="稳健推进",
            appearance_id="default",
            avatar_image_url="",
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
    ):
        assert column_name in table.c
        assert table.c[column_name].nullable is False
    assert "display_order" in table.c
    assert table.c.display_order.nullable is True


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
        "data_base64",
        "sha256",
        "size_bytes",
        "created_at",
    }
    assert table.c.id.primary_key is True
    assert table.c.source.nullable is False
    assert table.c.content_type.nullable is False
    assert table.c.data_base64.nullable is False
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
        "rule_set_id",
        "rule_set_revision_id",
        "rule_set_revision_no",
        "rule_set_content_hash",
        "rule_set",
        "resumable",
        "liveness_experience_revision",
        "liveness_experience_snapshot",
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
        "parent_run_id",
        "resume_from_round",
        "attempt_no",
        "rule_set_id",
        "rule_set_revision_id",
        "rule_set_revision_no",
        "rule_set_content_hash",
        "rule_set",
        "player_configs",
        "lineup_quality_warnings",
        "lineup_quality_report",
        "p2_diagnostics",
        "liveness_experience_revision",
        "liveness_experience_snapshot",
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
    _assert_json_column(table.c.lineup_quality_report, nullable=False)
    _assert_json_column(table.c.p2_diagnostics, nullable=False)
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


def test_run_and_game_models_expose_rule_revision_metadata() -> None:
    live_runs = LiveRunRecord.__table__
    game_sessions = GameSessionRecord.__table__

    for table in (live_runs, game_sessions):
        _assert_string_column(table.c.rule_set_revision_id, length=36, nullable=True)
        assert table.c.rule_set_revision_no.nullable is True
        _assert_string_column(table.c.rule_set_content_hash, length=64, nullable=True)
        _assert_foreign_key(
            table.c.rule_set_revision_id,
            target="rule_set_revisions.id",
            ondelete="RESTRICT",
        )

    _assert_string_column(game_sessions.c.rule_set_id, length=80, nullable=True)
    assert not game_sessions.c.rule_set_id.foreign_keys
    _assert_index(
        live_runs,
        "ix_live_runs_rule_set_revision_id",
        ["rule_set_revision_id"],
    )
    _assert_index(
        live_runs,
        "ix_live_runs_rule_set_id_updated_at_run_id_desc",
        ["rule_set_id", "updated_at", "run_id"],
    )
    _assert_index(
        game_sessions,
        "ix_game_sessions_rule_set_revision_id",
        ["rule_set_revision_id"],
    )
    _assert_index(
        game_sessions,
        "ix_game_sessions_rule_set_id_created_at_session_id_desc",
        ["rule_set_id", "created_at", "session_id"],
    )
    for table, index_name in (
        (live_runs, "ix_live_runs_rule_set_id_updated_at_run_id_desc"),
        (game_sessions, "ix_game_sessions_rule_set_id_created_at_session_id_desc"),
    ):
        index = next(candidate for candidate in table.indexes if candidate.name == index_name)
        assert [str(expression).endswith(" DESC") for expression in index.expressions] == [
            False,
            True,
            True,
        ]


def test_runtime_worker_table_matches_expected_schema() -> None:
    table = RuntimeWorkerRecord.__table__

    assert table.name == "runtime_workers"
    assert set(table.columns.keys()) == {
        "worker_id",
        "worker_type",
        "status",
        "started_at",
        "heartbeat_at",
        "stopped_at",
        "scans_total",
        "recoveries_resumed_total",
        "recoveries_canceled_total",
        "recoveries_failed_total",
        "errors_total",
        "last_error_code",
        "updated_at",
    }
    assert table.c.worker_id.primary_key is True
    _assert_string_column(table.c.worker_id, length=64, nullable=False)
    _assert_string_column(table.c.worker_type, length=40, nullable=False)
    _assert_string_column(table.c.status, length=20, nullable=False)
    assert table.c.started_at.nullable is False
    assert table.c.heartbeat_at.nullable is False
    assert table.c.stopped_at.nullable is True
    assert table.c.scans_total.nullable is False
    assert table.c.recoveries_resumed_total.nullable is False
    assert table.c.errors_total.nullable is False
    _assert_string_column(table.c.last_error_code, length=64, nullable=True)
    assert table.c.updated_at.nullable is False
    _assert_index(
        table,
        "ix_runtime_workers_type_heartbeat_desc",
        ["worker_type", "heartbeat_at"],
    )


def test_rule_set_catalog_tables_match_expected_schema() -> None:
    rule_sets = RuleSetRecord.__table__
    revisions = RuleSetRevisionRecord.__table__

    assert rule_sets.name == "rule_sets"
    assert set(rule_sets.columns.keys()) == {
        "id",
        "status",
        "current_published_revision_id",
        "draft_revision_id",
        "is_default",
        "display_order",
        "lock_version",
        "created_by_user_id",
        "updated_by_user_id",
        "archived_by_user_id",
        "created_at",
        "updated_at",
        "archived_at",
    }
    assert revisions.name == "rule_set_revisions"
    assert set(revisions.columns.keys()) == {
        "id",
        "rule_set_id",
        "revision_no",
        "state",
        "schema_version",
        "content_hash",
        "lock_version",
        "name",
        "description",
        "player_count",
        "role_summary",
        "complexity",
        "estimated_duration",
        "config",
        "created_by_user_id",
        "updated_by_user_id",
        "published_by_user_id",
        "publish_reason",
        "created_at",
        "updated_at",
        "published_at",
    }

    _assert_string_column(rule_sets.c.id, length=80, nullable=False)
    _assert_string_column(
        rule_sets.c.current_published_revision_id,
        length=36,
        nullable=True,
    )
    _assert_string_column(rule_sets.c.draft_revision_id, length=36, nullable=True)
    assert not rule_sets.c.current_published_revision_id.foreign_keys
    assert not rule_sets.c.draft_revision_id.foreign_keys
    assert rule_sets.c.current_published_revision_id.index is True
    assert rule_sets.c.draft_revision_id.index is True

    _assert_string_column(revisions.c.id, length=36, nullable=False)
    _assert_string_column(revisions.c.rule_set_id, length=80, nullable=False)
    _assert_foreign_key(
        revisions.c.rule_set_id,
        target="rule_sets.id",
        ondelete="RESTRICT",
    )
    _assert_string_column(revisions.c.content_hash, length=64, nullable=True)
    _assert_string_column(revisions.c.name, length=120, nullable=False)
    _assert_text_column(revisions.c.description, nullable=False)
    _assert_json_column(revisions.c.config, nullable=False)

    constraint_names = {
        constraint.name
        for table in (rule_sets, revisions)
        for constraint in table.constraints
        if constraint.name is not None
    }
    assert {
        "ck_rule_sets_status",
        "ck_rule_sets_lock_version_positive",
        "ck_rule_sets_display_order_nonnegative",
        "ck_rule_sets_default_published",
        "ck_rule_sets_pointer_state",
        "ck_rule_sets_archive_timestamp",
        "ck_rule_set_revisions_state",
        "ck_rule_set_revisions_revision_positive",
        "ck_rule_set_revisions_schema_version",
        "ck_rule_set_revisions_lock_version_positive",
        "ck_rule_set_revisions_publish_fields",
        "uq_rule_set_revisions_rule_revision",
    } <= constraint_names

    indexes = {index.name: index for table in (rule_sets, revisions) for index in table.indexes}
    expected_predicates = {
        "uq_rule_sets_one_default": {
            "postgresql": "is_default = true",
            "sqlite": "is_default = 1",
        },
        "uq_rule_set_revisions_one_draft": {
            "postgresql": "state = 'draft'",
            "sqlite": "state = 'draft'",
        },
        "uq_rule_set_revisions_one_published": {
            "postgresql": "state = 'published'",
            "sqlite": "state = 'published'",
        },
    }
    for name, predicates in expected_predicates.items():
        assert indexes[name].unique is True
        for dialect_name, predicate in predicates.items():
            assert str(indexes[name].dialect_options[dialect_name]["where"]) == predicate

    assert RuleSetRecord.__mapper__.version_id_col is rule_sets.c.lock_version
    assert RuleSetRevisionRecord.__mapper__.version_id_col is revisions.c.lock_version


def _published_rule_revision(*, revision_id: str) -> RuleSetRevisionRecord:
    return RuleSetRevisionRecord(
        id=revision_id,
        rule_set_id="classic_8",
        revision_no=1,
        state="published",
        schema_version=1,
        content_hash="0" * 64,
        name="经典 8 人局",
        description="官方标准局",
        player_count=8,
        role_summary="2 狼人 / 6 好人",
        complexity="标准",
        estimated_duration="中",
        config={"name": "经典 8 人局"},
        published_at=datetime.now(UTC),
    )


def test_published_rule_revision_only_allows_clean_supersede_transition() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        revision = _published_rule_revision(revision_id="00000000-0000-0000-0000-000000000001")
        session.add(revision)
        session.commit()
        session.refresh(revision)

        revision.name = "被篡改"
        revision.state = "superseded"
        with pytest.raises(ValueError, match="published rule revision content is immutable"):
            session.flush()
        session.rollback()

        revision = session.get(RuleSetRevisionRecord, revision.id)
        assert revision is not None
        revision.state = "superseded"
        session.commit()

        assert revision.state == "superseded"


def test_published_and_superseded_rule_revisions_cannot_be_deleted_or_rewritten() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        published = _published_rule_revision(revision_id="00000000-0000-0000-0000-000000000002")
        session.add(published)
        session.commit()

        session.delete(published)
        with pytest.raises(ValueError, match="only draft rule revisions can be deleted"):
            session.flush()
        session.rollback()

        published = session.get(RuleSetRevisionRecord, published.id)
        assert published is not None
        published.state = "superseded"
        session.commit()
        published.description = "被篡改"
        with pytest.raises(ValueError, match="superseded rule revision is immutable"):
            session.flush()


def test_published_rule_revision_cannot_disguise_as_draft_for_deletion() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        revision = _published_rule_revision(revision_id="00000000-0000-0000-0000-000000000004")
        session.add(revision)
        session.commit()
        revision_id = revision.id

        revision.state = "draft"
        revision.published_at = None
        session.delete(revision)
        with pytest.raises(ValueError, match="only draft rule revisions can be deleted"):
            session.flush()
        session.rollback()

        saved = session.get(RuleSetRevisionRecord, revision_id)
        assert saved is not None
        assert saved.state == "published"
        assert saved.published_at is not None


def test_superseded_rule_revision_cannot_disguise_as_draft_for_deletion() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        revision = _published_rule_revision(revision_id="00000000-0000-0000-0000-000000000005")
        revision.state = "superseded"
        session.add(revision)
        session.commit()
        revision_id = revision.id

        revision.state = "draft"
        revision.published_at = None
        session.delete(revision)
        with pytest.raises(ValueError, match="only draft rule revisions can be deleted"):
            session.flush()
        session.rollback()

        saved = session.get(RuleSetRevisionRecord, revision_id)
        assert saved is not None
        assert saved.state == "superseded"
        assert saved.published_at is not None


def test_draft_with_persisted_publication_marker_cannot_be_deleted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        draft = RuleSetRevisionRecord(
            id="00000000-0000-0000-0000-000000000006",
            rule_set_id="starter_6",
            revision_no=1,
            state="draft",
            schema_version=1,
            content_hash=None,
            name="新手 6 人快局",
            description="带历史发布标记的草稿",
            player_count=6,
            role_summary="1 狼人 / 5 好人",
            complexity="入门",
            estimated_duration="短",
            config={"name": "新手 6 人快局"},
            published_at=datetime.now(UTC),
        )
        session.add(draft)
        session.commit()
        draft_id = draft.id

        draft.published_at = None
        session.delete(draft)
        with pytest.raises(ValueError, match="only draft rule revisions can be deleted"):
            session.flush()
        session.rollback()

        saved = session.get(RuleSetRevisionRecord, draft_id)
        assert saved is not None
        assert saved.state == "draft"
        assert saved.published_at is not None


def test_never_published_draft_revision_can_be_deleted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        draft = RuleSetRevisionRecord(
            id="00000000-0000-0000-0000-000000000003",
            rule_set_id="starter_6",
            revision_no=1,
            state="draft",
            schema_version=1,
            content_hash=None,
            name="新手 6 人快局",
            description="草稿",
            player_count=6,
            role_summary="1 狼人 / 5 好人",
            complexity="入门",
            estimated_duration="短",
            config={"name": "新手 6 人快局"},
        )
        session.add(draft)
        session.commit()
        draft_id = draft.id

        session.delete(draft)
        session.commit()

        assert session.get(RuleSetRevisionRecord, draft_id) is None


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
        "audience",
        "source_event_id",
        "last_source_event_id",
        "presentation_id",
        "request_id",
        "action_id",
        "speech_id",
        "segment_id",
        "segment_index",
        "segment_final",
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
        "tts_started_at",
        "first_audio_chunk_at",
        "subtitle_timings",
        "error_message",
        "effective_delivery",
        "effective_context_texts",
        "tts_dialect",
        "voice_config_version",
        "delivery_mapping_version",
        "tts_request_source",
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
    _assert_string_column(table.c.audience, length=32, nullable=False)
    assert table.c.source_event_id.nullable is False
    assert table.c.last_source_event_id.nullable is False
    _assert_string_column(table.c.presentation_id, length=64, nullable=True)
    _assert_string_column(table.c.request_id, length=80, nullable=True)
    _assert_string_column(table.c.action_id, length=40, nullable=True)
    _assert_string_column(table.c.speech_id, length=40, nullable=True)
    _assert_string_column(table.c.segment_id, length=40, nullable=True)
    assert table.c.segment_index.nullable is True
    assert table.c.segment_final.nullable is True
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
    _assert_json_column(table.c.effective_delivery, nullable=True)
    _assert_json_column(table.c.effective_context_texts, nullable=True)
    _assert_string_column(table.c.tts_dialect, length=16, nullable=True)
    assert table.c.voice_config_version.nullable is True
    _assert_string_column(table.c.delivery_mapping_version, length=40, nullable=True)
    _assert_string_column(table.c.tts_request_source, length=40, nullable=True)
    assert table.c.created_at.nullable is False
    assert table.c.updated_at.nullable is False
    assert table.c.completed_at.nullable is True
    _assert_index(table, "ix_voice_utterances_run_id", ["run_id"])
    _assert_index(table, "ix_voice_utterances_session_id", ["session_id"])
    _assert_index(table, "ix_voice_utterances_run_source_event", ["run_id", "source_event_id"])
    _assert_index(table, "ix_voice_utterances_request_id", ["request_id"])
    _assert_index(table, "ix_voice_utterances_action_id", ["action_id"])
    _assert_index(table, "ix_voice_utterances_speech_id", ["speech_id"])
    _assert_index(table, "ix_voice_utterances_text_hash", ["text_hash"])
    _assert_index(table, "ix_voice_utterances_status", ["status"])
    _assert_index(
        table,
        "ix_voice_utterances_session_audience",
        ["session_id", "audience"],
    )


def test_liveness_runtime_tables_are_private_session_scoped_contracts() -> None:
    actor_minds = ActorMindSnapshotRecord.__table__
    receipts = SpeechTurnReceiptRecord.__table__
    segments = SpeechTurnSegmentRecord.__table__
    observations = VoicePlaybackObservationRecord.__table__

    assert set(actor_minds.primary_key.columns.keys()) == {"session_id", "actor"}
    assert set(receipts.primary_key.columns.keys()) == {"session_id", "action_id"}
    assert set(segments.primary_key.columns.keys()) == {
        "session_id",
        "action_id",
        "segment_index",
    }
    assert set(observations.primary_key.columns.keys()) == {
        "playback_session_id",
        "utterance_id",
    }
    _assert_string_column(receipts.c.speech_stream_mode, length=24, nullable=False)
    assert receipts.c.speech_stream_mode.default.arg == "segments_v2"
    assert receipts.c.final_segment_index.nullable is True
    _assert_string_column(receipts.c.sealed_source_run_id, length=32, nullable=True)
    assert receipts.c.sealed_source_event_id.nullable is True
    assert {
        constraint.name for constraint in receipts.constraints if constraint.name
    } >= {"ck_speech_turn_receipts_stream_mode"}
    _assert_foreign_key(
        actor_minds.c.session_id,
        target="game_sessions.session_id",
        ondelete="CASCADE",
    )
    _assert_foreign_key(
        receipts.c.session_id,
        target="game_sessions.session_id",
        ondelete="CASCADE",
    )
    _assert_foreign_key(
        observations.c.utterance_id,
        target="voice_utterances.utterance_id",
        ondelete="CASCADE",
    )


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
