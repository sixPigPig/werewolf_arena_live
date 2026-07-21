from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Generator
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.rule_sets.snapshots import resolve_rule_set_snapshot
from app.werewolf.actor_mind import ActorMindReducer, ActorMindV1
from app.werewolf.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    ReplayThenLiveProvider,
    ResumeCheckpointError,
    ResumeCheckpointManager,
    action_log_from_dict,
    game_state_from_dict,
    lifecycle_ledger_from_checkpoint,
    round_log_from_dict,
    round_state_from_dict,
    resolved_rule_set_from_checkpoint,
    terminal_settlement_from_checkpoint,
)
from app.werewolf.engine import GameEngine, NO_HUNTER_SHOT, initialize_game_state
from app.werewolf.live import LiveEvent
from app.werewolf.liveness_store import LivenessRuntimeStore
from app.werewolf.lm import LmLog
from app.werewolf.models import (
    ActionLog,
    DeathEvent,
    GameState,
    Player,
    RoundLog,
    RoundState,
    SheriffBadgeResolution,
    SheriffElectionResolution,
    StageInterruption,
)
from app.werewolf.replay import DatabaseReplayStore
from app.werewolf.rules import (
    WIN_CONDITION_WOLVES_GTE_OTHERS,
    get_rule_set,
    rule_set_snapshot,
)
from app.werewolf.runner import GameRunError, resume_game, run_game
from tests.rule_set_fixtures import (
    complete_resume_checkpoint,
    legacy_official_compiled_rule_set,
    managed_official_compiled_rule_set,
)


@pytest.fixture
def record_store() -> Generator[DatabaseReplayStore, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSessionLocal() as session:
        yield DatabaseReplayStore(session)


class ScriptedProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        self.calls += 1
        options = _extract_options(prompt)
        choice = options[0] if options else "1"
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {"reasoning": "狼人私密沟通。", "target": choice, "message": f"建议袭击{choice}。"},
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps({"reasoning": "狼人统一刀口。", "target": choice}, ensure_ascii=False)
        if '"remove"' in prompt:
            return json.dumps({"reasoning": "优先击杀。", "remove": choice}, ensure_ascii=False)
        if '"protect"' in prompt:
            return json.dumps(
                {"reasoning": "保护关键玩家。", "protect": choice}, ensure_ascii=False
            )
        if '"investigate"' in prompt:
            return json.dumps(
                {"reasoning": "查验身份。", "investigate": choice}, ensure_ascii=False
            )
        if '"save"' in prompt:
            return json.dumps(
                {"reasoning": "暂不使用解药。", "save": "不使用解药"}, ensure_ascii=False
            )
        if '"poison"' in prompt:
            return json.dumps(
                {"reasoning": "暂不使用毒药。", "poison": "不使用毒药"}, ensure_ascii=False
            )
        if '"shoot"' in prompt:
            return json.dumps(
                {"reasoning": "暂不开枪。", "shoot": "不发动技能"}, ensure_ascii=False
            )
        if '"run"' in prompt:
            return json.dumps({"reasoning": "不上警。", "run": "不上警"}, ensure_ascii=False)
        if '"withdraw"' in prompt:
            return json.dumps({"reasoning": "不退水。", "withdraw": "不退水"}, ensure_ascii=False)
        if '"speech_order"' in prompt:
            return json.dumps(
                {"reasoning": "默认警左。", "speech_order": choice}, ensure_ascii=False
            )
        if '"badge"' in prompt:
            return json.dumps({"reasoning": "撕毁警徽。", "badge": choice}, ensure_ascii=False)
        if '"say"' in prompt:
            return json.dumps(
                {"reasoning": "发表观点。", "say": "我会继续观察。"}, ensure_ascii=False
            )
        if '"vote"' in prompt:
            return json.dumps({"reasoning": "投给最可疑的人。", "vote": choice}, ensure_ascii=False)
        if '"sheriff_vote"' in prompt:
            return json.dumps(
                {"reasoning": "投给首位候选人。", "sheriff_vote": choice}, ensure_ascii=False
            )
        if '"summary"' in prompt:
            return json.dumps(
                {"reasoning": "记录线索。", "summary": "继续关注发言。"}, ensure_ascii=False
            )
        raise AssertionError(f"Unexpected prompt: {prompt}")


class FailingAfterProvider(ScriptedProvider):
    def __init__(self, *, fail_after_successes: int) -> None:
        super().__init__()
        self.fail_after_successes = fail_after_successes

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if self.calls >= self.fail_after_successes:
            raise RuntimeError("model provider offline")
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class RecordingRecordStore:
    def __init__(self) -> None:
        self.checkpoints: list[dict[str, object]] = []

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, object]) -> None:
        self.checkpoints.append({"session_id": session_id, "checkpoint": checkpoint.copy()})


class CapturingEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append({"type": event_type, **kwargs})


class IdCapturingEventSink(CapturingEventSink):
    def publish(self, event_type: str, **kwargs: object) -> object:
        super().publish(event_type, **kwargs)
        return SimpleNamespace(id=len(self.events))


class DurableLifecycleEventSink:
    def __init__(self, *, run_id: str | None = None) -> None:
        self.run_id = run_id
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> object:
        event = {"id": len(self.events) + 1, "type": event_type, **kwargs}
        if self.run_id is not None:
            event["run_id"] = self.run_id
        self.events.append(event)
        return SimpleNamespace(id=event["id"])

    def publish_lifecycle(self, event_type: str, **kwargs: object) -> object:
        payload = kwargs.get("payload")
        assert isinstance(payload, dict)
        phase_instance_id = payload["phase_instance_id"]
        matches = [
            event
            for event in self.events
            if event["type"] == event_type
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("phase_instance_id") == phase_instance_id
        ]
        if matches:
            assert len(matches) == 1
            existing = matches[0]
            assert {
                key: value
                for key, value in existing.items()
                if key not in {"id", "type", "run_id"}
            } == kwargs
            return SimpleNamespace(id=existing["id"])
        return self.publish(event_type, **kwargs)

    def lifecycle_events(self) -> list[dict[str, object]]:
        return [
            copy.deepcopy(event)
            for event in self.events
            if event["type"] in {"phase_started", "phase_completed"}
        ]


class CrashBeforeLifecycleCheckpointManager(ResumeCheckpointManager):
    def __init__(self, *args: object, crash_kind: str, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.crash_kind = crash_kind
        self.crashed = False

    def record_lifecycle_event(self, **kwargs: object) -> None:
        if kwargs.get("lifecycle_kind") == self.crash_kind and not self.crashed:
            self.crashed = True
            raise RuntimeError(f"crashed before checkpointing {self.crash_kind}")
        super().record_lifecycle_event(**kwargs)


class CrashBeforeHunterPresentationSink(IdCapturingEventSink):
    def publish(self, event_type: str, **kwargs: object) -> object:
        if event_type == "state_updated" and kwargs.get("action") == "hunter_shot_resolved":
            raise RuntimeError("worker crashed before publishing hunter result")
        return super().publish(event_type, **kwargs)


class CrashAfterHunterPresentationSink(IdCapturingEventSink):
    def publish(self, event_type: str, **kwargs: object) -> object:
        event = super().publish(event_type, **kwargs)
        if event_type == "state_updated" and kwargs.get("action") == "hunter_shot_resolved":
            raise RuntimeError("worker crashed after publishing hunter result")
        return event


class DurableExileLastWordsCrashSink(IdCapturingEventSink):
    def __init__(self, *, record_store: DatabaseReplayStore, session_id: str, after: bool) -> None:
        super().__init__()
        self.record_store = record_store
        self.session_id = session_id
        self.after = after
        self.run_id = "run_resume_parent"

    def publish(self, event_type: str, **kwargs: object) -> object:
        is_crash_boundary = (
            event_type == "state_updated" and kwargs.get("action") == "exile_last_words"
        )
        if is_crash_boundary and not self.after:
            raise RuntimeError("worker crashed before publishing exile last words result")
        published = super().publish(event_type, **kwargs)
        event = LiveEvent(
            id=int(published.id),
            type=event_type,
            run_id=self.run_id,
            session_id=self.session_id,
            created_at="2026-07-21T00:00:00Z",
            round=kwargs.get("round_number") if isinstance(kwargs.get("round_number"), int) else None,
            phase=kwargs.get("phase") if isinstance(kwargs.get("phase"), str) else None,
            actor=kwargs.get("actor") if isinstance(kwargs.get("actor"), str) else None,
            action=kwargs.get("action") if isinstance(kwargs.get("action"), str) else None,
            payload=copy.deepcopy(kwargs.get("payload")) if isinstance(kwargs.get("payload"), dict) else {},
        )
        runtime_store = LivenessRuntimeStore(self.record_store.db)
        runtime_store.stage_committed_segment(event)
        runtime_store.finalize_speech_turn(event)
        self.record_store.db.flush()
        if is_crash_boundary:
            raise RuntimeError("worker crashed after publishing exile last words result")
        return SimpleNamespace(id=published.id, run_id=self.run_id)


class CrashOnRoundStartedSink(IdCapturingEventSink):
    def __init__(self, *, round_number: int) -> None:
        super().__init__()
        self.round_number = round_number

    def publish(self, event_type: str, **kwargs: object) -> object:
        if (
            event_type == "round_started"
            and kwargs.get("round_number") == self.round_number
        ):
            raise RuntimeError("worker crashed in the next round after terminal recovery")
        return super().publish(event_type, **kwargs)


class RejectingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, **_kwargs: object) -> str:
        self.calls += 1
        raise AssertionError("terminal settlement recovery must not request the model")


class PendingHunterRecoveryProvider:
    def __init__(self, *, shoot_choice: str) -> None:
        self.shoot_choice = shoot_choice
        self.actions: list[str] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        if '"shoot"' not in prompt:
            raise AssertionError("terminal recovery must only request the pending hunter shot")
        self.actions.append("hunter_shoot")
        return json.dumps(
            {"reasoning": "恢复合法猎人结算。", "shoot": self.shoot_choice},
            ensure_ascii=False,
        )


class BadgeOnlyRecoveryProvider:
    def __init__(self, *, badge_target: str) -> None:
        self.badge_target = badge_target
        self.actions: list[str] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        if '"badge"' not in prompt:
            raise AssertionError(
                "cleared terminal recovery must not replay hunter or other model actions"
            )
        self.actions.append("sheriff_badge")
        return json.dumps(
            {"reasoning": "恢复未完成的警徽结算。", "badge": self.badge_target},
            ensure_ascii=False,
        )


def test_resume_checkpoint_manager_persists_checkpoint_to_record_store() -> None:
    store = RecordingRecordStore()
    compiled = managed_official_compiled_rule_set("starter_6")
    manager = ResumeCheckpointManager(
        record_store=store,
        session_id="game_1200abcd",
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
            "rule_set_id": "caller-poisoned",
            "revision_id": "caller-poisoned",
            "revision_no": 999,
            "content_hash": "f" * 64,
            "rule_set_snapshot": {"id": "caller-poisoned"},
            "unexpected": "drop-me",
        },
    )
    state = initialize_game_state(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        rule_set=get_rule_set("starter_6"),
    )

    manager.start_round(
        state=state,
        logs=[],
        round_number=1,
        active_players=["1号玩家"],
        rng_state=None,
    )
    manager.record_failure(
        actor="1号玩家",
        action="speech",
        phase="day",
        model="deepseek-chat",
        error="model provider offline",
    )

    assert len(store.checkpoints) == 2
    latest = store.checkpoints[-1]
    assert latest["session_id"] == "game_1200abcd"
    checkpoint = latest["checkpoint"]
    assert checkpoint["schema_version"] == 3 == CHECKPOINT_SCHEMA_VERSION
    assert checkpoint["session_id"] == "game_1200abcd"
    assert checkpoint["last_error"] == "model provider offline"
    run_params = checkpoint["run_params"]
    assert set(run_params) == {
        "villager_model",
        "werewolf_model",
        "seed",
        "max_rounds",
        "player_configs",
        "rule_set_id",
        "revision_id",
        "revision_no",
        "content_hash",
        "rule_set_snapshot",
    }
    assert run_params["rule_set_id"] == compiled.rule_set.id
    assert run_params["revision_id"] == compiled.revision_id
    assert run_params["revision_no"] == compiled.revision_no
    assert run_params["content_hash"] == compiled.content_hash
    assert run_params["rule_set_snapshot"] == compiled.snapshot
    state_snapshot = checkpoint["state_at_round_start"]["rule_set"]
    assert state_snapshot == run_params["rule_set_snapshot"]
    assert state_snapshot is not run_params["rule_set_snapshot"]
    assert state_snapshot is not compiled.snapshot
    assert run_params["rule_set_snapshot"] is not compiled.snapshot


def test_resume_checkpoint_round_trips_private_actor_minds_without_public_state() -> None:
    store = RecordingRecordStore()
    compiled = managed_official_compiled_rule_set("starter_6")
    manager = ResumeCheckpointManager(
        record_store=store,
        session_id="game_1200abcd",
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
    )
    state = initialize_game_state(
        session_id="game_1200abcd",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=compiled.rule_set,
    )
    manager.start_round(
        state=state,
        logs=[],
        round_number=1,
        active_players=[player.name for player in state.players],
        rng_state=None,
    )
    mind = ActorMindReducer().record_behavior(
        ActorMindV1(actor=state.players[0].name),
        speech_act="challenge",
        length_band="brief",
        opening_fingerprint="opening-1",
    )
    manager.record_actor_minds({mind.actor: mind}, at_round_start=True)
    checkpoint = store.checkpoints[-1]["checkpoint"]

    restored = ResumeCheckpointManager(
        record_store=store,
        session_id="game_1200abcd",
        compiled_rule_set=compiled,
        run_params=checkpoint["run_params"],
        initial_checkpoint=checkpoint,
    ).actor_minds()

    assert restored[mind.actor].to_dict() == mind.to_dict()
    assert checkpoint["private_runtime"]["actor_minds_at_round_start"][mind.actor] == mind.to_dict()
    assert "actor_minds" not in checkpoint["state_at_round_start"]


def test_resume_checkpoint_persists_actor_mind_with_cached_response_atomically() -> None:
    store = RecordingRecordStore()
    compiled = managed_official_compiled_rule_set("starter_6")
    manager = ResumeCheckpointManager(
        record_store=store,
        session_id="game_1200abcd",
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
    )
    state = initialize_game_state(
        session_id="game_1200abcd",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=compiled.rule_set,
    )
    manager.start_round(
        state=state,
        logs=[],
        round_number=1,
        active_players=[player.name for player in state.players],
        rng_state=None,
    )
    mind = ActorMindReducer().record_behavior(
        ActorMindV1(actor=state.players[0].name),
        speech_act="challenge",
        length_band="brief",
        opening_fingerprint="opening-atomic",
    )

    manager.record_success(
        actor=mind.actor,
        action="debate",
        phase="day_debate",
        model="villager-model",
        raw_response='{"say":"我不同意。"}',
        prompt="same-resume-prompt",
        actor_minds={mind.actor: mind},
    )

    checkpoint = store.checkpoints[-1]["checkpoint"]
    restored = ResumeCheckpointManager(
        record_store=store,
        session_id="game_1200abcd",
        compiled_rule_set=compiled,
        run_params=checkpoint["run_params"],
        initial_checkpoint=checkpoint,
    )

    assert restored.actor_minds()[mind.actor].to_dict() == mind.to_dict()
    assert restored.cached_model_response_exists(
        actor=mind.actor,
        action="debate",
        phase="day_debate",
        model="villager-model",
        prompt="same-resume-prompt",
    )
    assert len(store.checkpoints) == 2


def test_resume_checkpoint_round_trips_partial_segments_v2_receipt() -> None:
    store = RecordingRecordStore()
    compiled = managed_official_compiled_rule_set("starter_6")
    manager = ResumeCheckpointManager(
        record_store=store,
        session_id="game_1200abcd",
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
    )
    state = initialize_game_state(
        session_id="game_1200abcd",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=compiled.rule_set,
    )
    manager.start_round(
        state=state,
        logs=[],
        round_number=1,
        active_players=[player.name for player in state.players],
        rng_state=None,
    )
    receipt = {
        "speech_id": "sp_resume",
        "speech_stream_mode": "segments_v2",
        "status": "partial",
        "segment_count": 1,
        "segments": [
            {
                "segment_id": "seg_resume",
                "segment_index": 0,
                "text": "这句已经公开。",
                "presentation_id": "pres_resume",
                "source_run_id": "run_previous",
                "source_event_id": 17,
            }
        ],
        "final_text": "这句已经公开。",
        "accepted_renderer_request_id": "req_previous",
    }
    manager.record_speech_turn_receipt("act_resume", receipt)
    checkpoint = store.checkpoints[-1]["checkpoint"]

    restored = ResumeCheckpointManager(
        record_store=store,
        session_id="game_1200abcd",
        compiled_rule_set=compiled,
        run_params=checkpoint["run_params"],
        initial_checkpoint=checkpoint,
    ).speech_turn_receipt("act_resume")

    assert restored == receipt
    assert checkpoint["generation_runtime"]["speech_turn_receipts"]["act_resume"] == receipt
    assert "speech_turn_receipts" not in checkpoint["state_at_round_start"]


def test_resume_checkpoint_manager_preserves_prior_round_logs() -> None:
    store = RecordingRecordStore()
    compiled = managed_official_compiled_rule_set("starter_6")
    prior_log = RoundLog(number=1)
    current_log = RoundLog(number=2)
    manager = ResumeCheckpointManager(
        record_store=store,
        session_id="game_1200abcd",
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
        logs_prefix=[prior_log],
    )
    state = initialize_game_state(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        rule_set=get_rule_set("starter_6"),
    )

    manager.start_round(
        state=state,
        logs=[current_log],
        round_number=3,
        active_players=["1号玩家"],
        rng_state=None,
    )

    checkpoint = store.checkpoints[-1]["checkpoint"]
    assert [entry["number"] for entry in checkpoint["logs_before_round"]] == [
        1,
        2,
    ]


@pytest.mark.parametrize(
    ("compiled_kind", "include_rule_metadata"),
    [("legacy", False), ("managed", True)],
)
def test_checkpoint_reader_accepts_complete_legacy_and_task4_managed_v1(
    compiled_kind: str,
    include_rule_metadata: bool,
) -> None:
    compiled = (
        legacy_official_compiled_rule_set("starter_6")
        if compiled_kind == "legacy"
        else managed_official_compiled_rule_set("starter_6")
    )
    checkpoint = complete_resume_checkpoint(
        "game_1200abcd",
        compiled,
        checkpoint_schema_version=1,
        include_rule_metadata=include_rule_metadata,
    )

    resolved = resolved_rule_set_from_checkpoint(checkpoint)

    assert resolved.snapshot == compiled.snapshot
    assert resolved.revision_id == compiled.revision_id
    assert resolved.revision_no == compiled.revision_no
    assert resolved.content_hash == compiled.content_hash
    assert resolved.snapshot is not checkpoint["state_at_round_start"]["rule_set"]


@pytest.mark.parametrize("compiled_kind", ["legacy", "managed"])
def test_checkpoint_reader_accepts_strict_legacy_and_managed_v2(
    compiled_kind: str,
) -> None:
    compiled = (
        legacy_official_compiled_rule_set("starter_6")
        if compiled_kind == "legacy"
        else managed_official_compiled_rule_set("starter_6")
    )
    checkpoint = complete_resume_checkpoint(
        "game_1200abcd",
        compiled,
        checkpoint_schema_version=2,
    )

    resolved = resolved_rule_set_from_checkpoint(checkpoint)

    assert resolved.snapshot == compiled.snapshot
    assert resolved.revision_id == compiled.revision_id
    assert resolved.revision_no == compiled.revision_no
    assert resolved.content_hash == compiled.content_hash
    assert resolved.snapshot is not checkpoint["run_params"]["rule_set_snapshot"]


@pytest.mark.parametrize(
    ("schema_version", "expected_reason", "expected_message"),
    [
        (None, "invalid_structure", "Resume checkpoint structure is invalid"),
        (True, "invalid_structure", "Resume checkpoint structure is invalid"),
        (0, "unsupported_schema", "Resume checkpoint schema is unsupported"),
        ("2", "invalid_structure", "Resume checkpoint structure is invalid"),
        (4, "unsupported_schema", "Resume checkpoint schema is unsupported"),
    ],
)
def test_checkpoint_reader_rejects_malformed_and_unsupported_schema(
    schema_version: object,
    expected_reason: str,
    expected_message: str,
) -> None:
    checkpoint = complete_resume_checkpoint(
        "game_1200abcd",
        legacy_official_compiled_rule_set("starter_6"),
        checkpoint_schema_version=1,
    )
    checkpoint["schema_version"] = schema_version

    with pytest.raises(ResumeCheckpointError) as error:
        resolved_rule_set_from_checkpoint(checkpoint)

    assert error.value.reason == expected_reason
    assert str(error.value) == expected_message


def test_checkpoint_reader_rejects_missing_schema_as_present_corrupt_data() -> None:
    checkpoint = complete_resume_checkpoint(
        "game_1200abcd",
        legacy_official_compiled_rule_set("starter_6"),
    )
    checkpoint.pop("schema_version")

    with pytest.raises(ResumeCheckpointError) as error:
        resolved_rule_set_from_checkpoint(checkpoint)

    assert error.value.reason == "invalid_structure"
    assert str(error.value) == "Resume checkpoint structure is invalid"


def test_checkpoint_reader_rejects_incomplete_v1_without_catalog_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = complete_resume_checkpoint(
        "game_1200abcd",
        legacy_official_compiled_rule_set("starter_6"),
        checkpoint_schema_version=1,
    )
    checkpoint["state_at_round_start"]["rule_set"] = {"id": "starter_6"}

    def reject_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("checkpoint parsing must not query a rule catalog")

    monkeypatch.setattr("app.werewolf.rules.get_rule_set", reject_lookup)
    monkeypatch.setattr("app.rule_sets.service.resolve_published_rule_set", reject_lookup)

    with pytest.raises(ResumeCheckpointError) as error:
        resolved_rule_set_from_checkpoint(checkpoint)

    assert error.value.reason == "invalid_rule_snapshot"


def test_checkpoint_reader_rejects_partial_v1_duplicate_rule_metadata() -> None:
    checkpoint = complete_resume_checkpoint(
        "game_1200abcd",
        managed_official_compiled_rule_set("starter_6"),
        checkpoint_schema_version=1,
        include_rule_metadata=False,
    )
    checkpoint["run_params"]["revision_id"] = "revision-only"

    with pytest.raises(ResumeCheckpointError) as error:
        resolved_rule_set_from_checkpoint(checkpoint)

    assert error.value.reason == "rule_metadata_mismatch"


@pytest.mark.parametrize("checkpoint_schema_version", [1, 2, 3])
def test_checkpoint_reader_rejects_consistently_untrimmed_managed_revision_id(
    checkpoint_schema_version: int,
) -> None:
    checkpoint = complete_resume_checkpoint(
        "game_1200abcd",
        managed_official_compiled_rule_set("starter_6"),
        checkpoint_schema_version=checkpoint_schema_version,
        include_rule_metadata=checkpoint_schema_version >= 2,
    )
    original_revision_id = checkpoint["state_at_round_start"]["rule_set"]["revision_id"]
    untrimmed = f" {original_revision_id} "
    checkpoint["state_at_round_start"]["rule_set"]["revision_id"] = untrimmed
    if checkpoint_schema_version >= 2:
        checkpoint["run_params"]["revision_id"] = untrimmed
        checkpoint["run_params"]["rule_set_snapshot"]["revision_id"] = untrimmed

    with pytest.raises(ResumeCheckpointError) as error:
        resolved_rule_set_from_checkpoint(checkpoint)

    assert error.value.reason == "rule_metadata_mismatch"


@pytest.mark.parametrize(
    ("tamper", "expected_reason"),
    [
        ("rule_id", "rule_metadata_mismatch"),
        ("revision_id", "rule_metadata_mismatch"),
        ("revision_no", "rule_metadata_mismatch"),
        ("content_hash", "rule_metadata_mismatch"),
        ("run_snapshot", "rule_snapshot_mismatch"),
        ("state_snapshot", "rule_snapshot_mismatch"),
    ],
)
def test_checkpoint_reader_rejects_every_v2_rule_tamper_without_mutation(
    tamper: str,
    expected_reason: str,
) -> None:
    compiled = managed_official_compiled_rule_set("starter_6")
    checkpoint = complete_resume_checkpoint(
        "game_1200abcd",
        compiled,
        checkpoint_schema_version=2,
    )
    if tamper == "rule_id":
        checkpoint["run_params"]["rule_set_id"] = "classic_8"
    elif tamper == "revision_id":
        checkpoint["run_params"]["revision_id"] = "wrong-revision"
    elif tamper == "revision_no":
        checkpoint["run_params"]["revision_no"] = True
    elif tamper == "content_hash":
        checkpoint["run_params"]["content_hash"] = "F" * 64
    elif tamper == "run_snapshot":
        checkpoint["run_params"]["rule_set_snapshot"] = copy.deepcopy(
            managed_official_compiled_rule_set("classic_8").snapshot
        )
    else:
        checkpoint["state_at_round_start"]["rule_set"] = copy.deepcopy(
            managed_official_compiled_rule_set("classic_8").snapshot
        )
    before = copy.deepcopy(checkpoint)

    with pytest.raises(ResumeCheckpointError) as error:
        resolved_rule_set_from_checkpoint(checkpoint)

    assert error.value.reason == expected_reason
    assert checkpoint == before


def test_failed_run_writes_resume_checkpoint(record_store: DatabaseReplayStore) -> None:
    provider = FailingAfterProvider(fail_after_successes=0)

    with pytest.raises(GameRunError) as error:
        run_game(
            record_store=record_store,
            compiled_rule_set=legacy_official_compiled_rule_set("starter_6"),
            provider=provider,
            seed=21,
            max_rounds=8,
        )

    assert error.value.session_id is not None
    checkpoint = record_store.load_resume_checkpoint(error.value.session_id)

    assert checkpoint["schema_version"] == CHECKPOINT_SCHEMA_VERSION == 3
    assert checkpoint["session_id"] == error.value.session_id
    assert checkpoint["round_number"] == 1
    assert checkpoint["active_players"]
    assert checkpoint["run_params"]["rule_set_id"] == "starter_6"
    assert checkpoint["run_params"]["revision_id"] is None
    assert checkpoint["run_params"]["revision_no"] is None
    assert checkpoint["run_params"]["content_hash"]
    assert (
        checkpoint["run_params"]["rule_set_snapshot"]
        == checkpoint["state_at_round_start"]["rule_set"]
    )
    assert checkpoint["cached_model_responses"] == []
    assert checkpoint["failed_request"]["error"] == "model provider offline"


def test_resume_game_replays_cached_model_responses_without_catalog_lookup(
    record_store: DatabaseReplayStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_provider = FailingAfterProvider(fail_after_successes=1)

    with pytest.raises(GameRunError) as error:
        run_game(
            record_store=record_store,
            compiled_rule_set=legacy_official_compiled_rule_set("starter_6"),
            provider=failing_provider,
            seed=21,
            max_rounds=8,
        )

    assert error.value.session_id is not None
    checkpoint = record_store.load_resume_checkpoint(error.value.session_id)
    assert len(checkpoint["cached_model_responses"]) == 1
    assert "prompt" in checkpoint["cached_model_responses"][0]
    assert checkpoint["cached_model_responses"][0]["prompt"]

    def reject_catalog_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("resume must use the checkpoint rule snapshot")

    monkeypatch.setattr("app.werewolf.rules.get_rule_set", reject_catalog_lookup)
    monkeypatch.setattr(
        "app.rule_sets.service.resolve_published_rule_set",
        reject_catalog_lookup,
    )

    resume_provider = ScriptedProvider()
    sink = CapturingEventSink()
    result = resume_game(
        record_store=record_store,
        session_id=error.value.session_id,
        provider=resume_provider,
        event_sink=sink,
    )

    assert result.session_id == error.value.session_id
    assert result.winner
    assert resume_provider.calls > 0
    assert [event["type"] for event in sink.events].count("game_resumed") == 1
    assert "game_started" not in [event["type"] for event in sink.events]
    with pytest.raises(ResumeCheckpointError):
        record_store.load_resume_checkpoint(result.session_id)
    assert record_store.load_session(result.session_id)["status"] == "complete"


def _persist_terminal_settlement_checkpoint(
    *,
    record_store: DatabaseReplayStore,
    state: GameState,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
    terminal_settlement: dict[str, object],
) -> None:
    compiled = legacy_official_compiled_rule_set(state.rule_set["id"])
    manager = ResumeCheckpointManager(
        record_store=record_store,
        session_id=state.session_id,
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
    )
    manager.start_round(
        state=state,
        logs=[],
        round_number=round_state.number,
        active_players=round_state.players,
        rng_state=None,
    )
    state.rounds.append(round_state)
    for player in state.players:
        assert player.gamestate is not None
        player.gamestate.current_players = active_players.copy()
    manager.record_terminal_settlement(
        state=state,
        logs=[round_log],
        active_players=active_players,
        terminal_settlement=terminal_settlement,
    )


def _primary_terminal_settlement(*, stage: str) -> dict[str, object]:
    return {
        "settlement_schema_version": "settlement_v1",
        "stage": stage,
        "primary_outcome_action_id": "outcome:test:vote:exile",
        "settlement_cursor": 1,
        "settlements": [
            {
                "settlement_id": "settlement:test:primary",
                "kind": "death_batch",
                "actor": "2号玩家",
                "status": "applied",
                "accepted_choice": None,
                "details": {"phase": "vote"},
            }
        ],
        "canceled_action_ids": [],
    }


def _hunter_presentation_id(session_id: str, settlement_id: str) -> str:
    digest = hashlib.sha256(
        f"{session_id}:{settlement_id}:presentation".encode()
    ).hexdigest()[:24]
    return f"hp_{digest}"


def _primary_presentation_id(session_id: str, action_id: str) -> str:
    digest = hashlib.sha256(
        f"{session_id}:{action_id}:presentation".encode()
    ).hexdigest()[:24]
    return f"pp_{digest}"


def test_resume_terminal_outcome_applied_commits_winner_without_replaying_action(
    record_store: DatabaseReplayStore,
) -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="game_a0010001",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    goods = [player for player in state.players if player.role != "狼人"][:2]
    before = [wolf.name, *(player.name for player in goods)]
    active = [player.name for player in goods]
    round_state = RoundState(
        number=1,
        players=before,
        exiled=wolf.name,
        day_deaths=[DeathEvent(wolf.name, "vote_exile", "投票")],
    )
    _persist_terminal_settlement_checkpoint(
        record_store=record_store,
        state=state,
        round_state=round_state,
        round_log=RoundLog(number=1),
        active_players=active,
        terminal_settlement=_primary_terminal_settlement(stage="outcome_applied"),
    )
    provider = RejectingProvider()
    sink = IdCapturingEventSink()

    result = resume_game(
        session_id=state.session_id,
        record_store=record_store,
        provider=provider,
        event_sink=sink,
    )

    assert result.winner == "好人阵营"
    assert result.terminal_keep_from_event_id == 2
    assert provider.calls == 0
    assert [event["type"] for event in sink.events] == [
        "game_resumed",
        "state_updated",
        "state_updated",
    ]
    assert sink.events[0]["payload"]["terminal_recovery"] is True
    primary, folded = sink.events[1:]
    assert primary["action"] == "exile_resolved"
    assert primary["payload"]["exiled"] == wolf.name
    assert primary["payload"]["presentation_id"] == _primary_presentation_id(
        state.session_id,
        "outcome:test:vote:exile",
    )
    assert folded["action"] == "day_resolution_completed"
    assert folded["payload"]["exiled"] == wolf.name
    assert folded["payload"]["public_summary"]
    assert "presentation_id" not in folded["payload"]
    replay = record_store.load_session(state.session_id)
    assert replay["state"]["rounds"][0]["exiled"] == wolf.name


def test_resume_winner_committed_only_finishes_without_restoring_aftermath(
    record_store: DatabaseReplayStore,
) -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="game_a0010002",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    goods = [player for player in state.players if player.role != "狼人"][:2]
    before = [wolf.name, *(player.name for player in goods)]
    active = [player.name for player in goods]
    state.winner = "好人阵营"
    round_state = RoundState(
        number=1,
        players=before,
        exiled=wolf.name,
        day_deaths=[DeathEvent(wolf.name, "vote_exile", "投票")],
    )
    _persist_terminal_settlement_checkpoint(
        record_store=record_store,
        state=state,
        round_state=round_state,
        round_log=RoundLog(number=1),
        active_players=active,
        terminal_settlement=_primary_terminal_settlement(stage="winner_committed"),
    )
    provider = RejectingProvider()
    sink = IdCapturingEventSink()

    result = resume_game(
        session_id=state.session_id,
        record_store=record_store,
        provider=provider,
        event_sink=sink,
    )

    assert result.winner == "好人阵营"
    assert result.terminal_keep_from_event_id == 2
    assert provider.calls == 0
    assert [event["type"] for event in sink.events] == [
        "game_resumed",
        "state_updated",
        "state_updated",
    ]
    assert sink.events[0]["payload"]["terminal_recovery"] is True
    primary, folded = sink.events[1:]
    assert primary["action"] == "exile_resolved"
    assert primary["payload"]["presentation_id"] == _primary_presentation_id(
        state.session_id,
        "outcome:test:vote:exile",
    )
    assert folded["action"] == "day_resolution_completed"
    assert folded["payload"]["public_summary"]
    assert "presentation_id" not in folded["payload"]


def test_resume_accepted_hunter_choice_applies_shot_without_requesting_hunter(
    record_store: DatabaseReplayStore,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="game_a0010003",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    hunter = next(player for player in state.players if player.role == "猎人")
    civilian = next(player for player in state.players if player.role == "村民")
    before = [wolf.name, hunter.name, civilian.name]
    active = [wolf.name, civilian.name]
    round_state = RoundState(
        number=1,
        players=before,
        exiled=hunter.name,
        day_deaths=[DeathEvent(hunter.name, "vote_exile", "投票")],
    )
    round_log = RoundLog(
        number=1,
        hunter_shoot=ActionLog(
            actor=hunter.name,
            action="hunter_shoot",
            options=[wolf.name, civilian.name, "不发动技能"],
            choice=wolf.name,
            lm_log=LmLog(
                prompt="cached hunter prompt",
                raw_response=json.dumps(
                    {"reasoning": "已接受的猎人选择。", "shoot": wolf.name},
                    ensure_ascii=False,
                ),
                result={"reasoning": "已接受的猎人选择。", "shoot": wolf.name},
                action_id="act_terminal_hunter",
                request_id="req_terminal_hunter",
            ),
        ),
    )
    settlement = _primary_terminal_settlement(stage="hunter_choice_accepted")
    settlement["terminal_keep_from_event_id"] = 77
    settlement["settlements"].append(
        {
            "settlement_id": "settlement:test:hunter",
            "kind": "hunter_shot",
            "actor": hunter.name,
            "status": "choice_accepted",
            "accepted_choice": wolf.name,
            "details": {
                "actor": hunter.name,
                "death_cause": "vote_exile",
                "phase": "vote",
                "excluded_shot_targets": [],
                "excluded_badge_targets": [],
                "transfer_sheriff_badge": False,
            },
        }
    )
    _persist_terminal_settlement_checkpoint(
        record_store=record_store,
        state=state,
        round_state=round_state,
        round_log=round_log,
        active_players=active,
        terminal_settlement=settlement,
    )
    provider = RejectingProvider()
    sink = IdCapturingEventSink()

    result = resume_game(
        session_id=state.session_id,
        record_store=record_store,
        provider=provider,
        event_sink=sink,
    )

    assert result.winner == "好人阵营"
    assert result.terminal_keep_from_event_id == 2
    assert provider.calls == 0
    assert [event["type"] for event in sink.events].count("action_requested") == 0
    hunter_results = [
        event
        for event in sink.events
        if event.get("action") == "hunter_shot_resolved"
    ]
    assert len(hunter_results) == 1
    assert hunter_results[0]["payload"]["presentation_id"] == _hunter_presentation_id(
        state.session_id,
        "settlement:test:hunter",
    )
    replay = record_store.load_session(state.session_id)
    assert replay["state"]["rounds"][0]["hunter_shot"] == wolf.name
    assert replay["logs"][0]["hunter_shoot"]["choice"] == wolf.name


def test_terminal_hunter_no_shot_cue_starts_live_terminal_keep_interval() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="game_a0010004",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    hunter = next(player for player in state.players if player.role == "猎人")
    civilian = next(player for player in state.players if player.role == "村民")
    active = [wolf.name, civilian.name]
    for player in state.players:
        assert player.gamestate is not None
        player.gamestate.current_players = active.copy()
    round_state = RoundState(
        number=1,
        players=[wolf.name, hunter.name, civilian.name],
        exiled=hunter.name,
        day_deaths=[DeathEvent(hunter.name, "vote_exile", "投票")],
    )
    round_log = RoundLog(number=1)
    settlement = _primary_terminal_settlement(stage="outcome_applied")
    settlement["settlements"].append(
        {
            "settlement_id": "settlement:test:hunter:no-shot",
            "kind": "hunter_shot",
            "actor": hunter.name,
            "status": "pending",
            "accepted_choice": None,
            "details": {"phase": "vote"},
        }
    )
    sink = IdCapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=RejectingProvider(),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )
    engine._terminal_settlement = settlement

    engine._accept_terminal_hunter_choice(
        hunter=hunter,
        shot=NO_HUNTER_SHOT,
        round_state=round_state,
        round_log=round_log,
        active_players=active,
        death_cause="vote_exile",
        phase="vote",
        excluded_shot_targets=set(),
        excluded_badge_targets=None,
        transfer_sheriff_badge=False,
    )

    engine._apply_hunter_shot_choice(
        hunter=hunter,
        shot=NO_HUNTER_SHOT,
        round_state=round_state,
        round_log=round_log,
        active_players=active,
        phase="vote",
        excluded_badge_targets=None,
        transfer_sheriff_badge=False,
    )

    assert engine.terminal_keep_from_event_id == 1
    assert [(event["type"], event.get("action")) for event in sink.events] == [
        ("state_updated", "hunter_shot_resolved")
    ]
    assert sink.events[0]["payload"]["hunter_shot_status"] == "skipped"
    assert sink.events[0]["payload"]["hunter_shot"] is None
    assert sink.events[0]["payload"]["presentation_id"] == (
        _hunter_presentation_id(
            state.session_id,
            "settlement:test:hunter:no-shot",
        )
    )


@pytest.mark.parametrize("takes_shot", [True, False])
def test_nonterminal_hunter_choice_still_publishes_canonical_result(
    takes_shot: bool,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="game_nonterminal_hunter_result",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    hunter = next(player for player in state.players if player.role == "猎人")
    seer = next(player for player in state.players if player.role == "预言家")
    civilians = [player for player in state.players if player.role == "村民"][:3]
    active = [wolf.name, seer.name, *(player.name for player in civilians)]
    shot = civilians[0].name if takes_shot else NO_HUNTER_SHOT
    round_state = RoundState(
        number=2,
        players=[hunter.name, *active],
        day_deaths=[DeathEvent(hunter.name, "vote_exile", "投票")],
    )
    sink = IdCapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=RejectingProvider(),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    engine._apply_hunter_shot_choice(
        hunter=hunter,
        shot=shot,
        round_state=round_state,
        round_log=RoundLog(number=2),
        active_players=active,
        phase="vote",
        excluded_badge_targets=None,
        transfer_sheriff_badge=False,
    )

    assert engine._terminal_settlement is None
    assert engine.terminal_keep_from_event_id is None
    assert len(sink.events) == 1
    result = sink.events[0]
    assert result["type"] == "state_updated"
    assert result["action"] == "hunter_shot_resolved"
    assert result["payload"]["hunter_shot_status"] == (
        "shot" if takes_shot else "skipped"
    )
    assert result["payload"]["hunter_shot"] == (
        civilians[0].name if takes_shot else None
    )
    assert "presentation_id" not in result["payload"]


@pytest.mark.parametrize("takes_shot", [True, False])
@pytest.mark.parametrize("crash_after_publish", [False, True])
def test_hunter_result_is_republished_from_applied_checkpoint_after_publish_crash(
    record_store: DatabaseReplayStore,
    takes_shot: bool,
    crash_after_publish: bool,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    compiled = legacy_official_compiled_rule_set(rule_set.id)
    state = initialize_game_state(
        session_id="game_a0010005",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    hunter = next(player for player in state.players if player.role == "猎人")
    civilian = next(player for player in state.players if player.role == "村民")
    before = [wolf.name, hunter.name, civilian.name]
    active = [wolf.name, civilian.name]
    shot = wolf.name if takes_shot else NO_HUNTER_SHOT
    settlement_id = "settlement:test:hunter:crash-before-publish"
    presentation_id = _hunter_presentation_id(state.session_id, settlement_id)
    round_state = RoundState(
        number=1,
        players=before,
        exiled=hunter.name,
        day_deaths=[DeathEvent(hunter.name, "vote_exile", "投票")],
    )
    round_log = RoundLog(
        number=1,
        hunter_shoot=ActionLog(
            actor=hunter.name,
            action="hunter_shoot",
            options=[wolf.name, civilian.name, NO_HUNTER_SHOT],
            choice=shot,
            lm_log=LmLog(
                prompt="cached hunter prompt",
                raw_response=json.dumps(
                    {"reasoning": "已接受的猎人选择。", "shoot": shot},
                    ensure_ascii=False,
                ),
                result={"reasoning": "已接受的猎人选择。", "shoot": shot},
                action_id="act_terminal_hunter_crash",
                request_id="req_terminal_hunter_crash",
            ),
        ),
    )
    checkpoint_manager = ResumeCheckpointManager(
        record_store=record_store,
        session_id=state.session_id,
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
    )
    checkpoint_manager.start_round(
        state=state,
        logs=[],
        round_number=1,
        active_players=before,
        rng_state=None,
    )
    state.rounds.append(round_state)
    for player in state.players:
        assert player.gamestate is not None
        player.gamestate.current_players = active.copy()
    settlement = _primary_terminal_settlement(stage="hunter_choice_accepted")
    settlement["settlements"].append(
        {
            "settlement_id": settlement_id,
            "kind": "hunter_shot",
            "actor": hunter.name,
            "status": "choice_accepted",
            "accepted_choice": shot,
            "presentation": {
                "presentation_id": presentation_id,
                "kind": "hunter_shot_result",
                "hunter_shot_status": "shot" if takes_shot else "skipped",
                "hunter_shot": wolf.name if takes_shot else None,
            },
            "details": {
                "actor": hunter.name,
                "death_cause": "vote_exile",
                "phase": "vote",
                "excluded_shot_targets": [],
                "excluded_badge_targets": [],
                "transfer_sheriff_badge": False,
            },
        }
    )
    parent_sink = (
        CrashAfterHunterPresentationSink()
        if crash_after_publish
        else CrashBeforeHunterPresentationSink()
    )
    engine = GameEngine(
        state=state,
        provider=RejectingProvider(),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=parent_sink,
        checkpoint_manager=checkpoint_manager,
    )
    engine.logs = [round_log]
    engine._terminal_settlement = settlement

    with pytest.raises(
        RuntimeError,
        match=(
            "worker crashed after publishing hunter result"
            if crash_after_publish
            else "worker crashed before publishing hunter result"
        ),
    ):
        engine._apply_hunter_shot_choice(
            hunter=hunter,
            shot=shot,
            round_state=round_state,
            round_log=round_log,
            active_players=active,
            phase="vote",
            excluded_badge_targets=None,
            transfer_sheriff_badge=False,
        )

    checkpoint = record_store.load_resume_checkpoint(state.session_id)
    persisted = terminal_settlement_from_checkpoint(checkpoint)
    assert persisted is not None
    assert persisted["stage"] == "outcome_applied"
    hunter_settlement = persisted["settlements"][-1]
    assert hunter_settlement["status"] == "applied"
    assert hunter_settlement["presentation"] == {
        "presentation_id": presentation_id,
        "kind": "hunter_shot_result",
        "hunter_shot_status": "shot" if takes_shot else "skipped",
        "hunter_shot": wolf.name if takes_shot else None,
    }
    assert persisted["state"]["rounds"][0]["hunter_shot"] == (
        wolf.name if takes_shot else None
    )

    provider = RejectingProvider()
    recovery_sink = IdCapturingEventSink()
    result = resume_game(
        session_id=state.session_id,
        record_store=record_store,
        provider=provider,
        event_sink=recovery_sink,
    )

    assert result.winner == ("好人阵营" if takes_shot else "狼人阵营")
    assert result.terminal_keep_from_event_id == 2
    assert provider.calls == 0
    hunter_results = [
        event
        for event in recovery_sink.events
        if event.get("action") == "hunter_shot_resolved"
    ]
    assert len(hunter_results) == 1
    assert hunter_results[0]["type"] == "state_updated"
    assert hunter_results[0]["payload"]["presentation_id"] == presentation_id
    assert hunter_results[0]["payload"]["hunter_shot_status"] == (
        "shot" if takes_shot else "skipped"
    )
    assert hunter_results[0]["payload"]["hunter_shot"] == (
        wolf.name if takes_shot else None
    )
    primary_results = [
        event
        for event in recovery_sink.events
        if event.get("action") == "exile_resolved"
        and "presentation_id" in event["payload"]
    ]
    assert len(primary_results) == 1
    assert primary_results[0]["payload"]["presentation_id"] == (
        _primary_presentation_id(state.session_id, "outcome:test:vote:exile")
    )
    assert primary_results[0]["payload"]["day_deaths"] == [
        {"player": hunter.name, "cause": "vote_exile", "source": "投票"},
    ]
    recovered_final_state = next(
        event
        for event in recovery_sink.events
        if event.get("action") == "day_resolution_completed"
    )
    assert recovered_final_state["payload"]["hunter_shot"] == (
        wolf.name if takes_shot else None
    )
    assert recovered_final_state["payload"]["public_summary"]
    assert "presentation_id" not in recovered_final_state["payload"]
    assert (
        recovery_sink.events.index(primary_results[0])
        < recovery_sink.events.index(hunter_results[0])
        < recovery_sink.events.index(recovered_final_state)
    )
    parent_hunter_results = [
        event
        for event in parent_sink.events
        if event.get("action") == "hunter_shot_resolved"
    ]
    assert len(parent_hunter_results) == (1 if crash_after_publish else 0)
    if parent_hunter_results:
        assert parent_hunter_results[0]["payload"]["presentation_id"] == presentation_id
    assert not any(event["type"] == "judge_cue" for event in recovery_sink.events)


@pytest.mark.parametrize("crash_after_publish", [False, True])
def test_recovery_continues_when_hunter_clears_wolves_parity_candidate(
    record_store: DatabaseReplayStore,
    monkeypatch: pytest.MonkeyPatch,
    crash_after_publish: bool,
) -> None:
    rule_set = replace(
        get_rule_set("classic_12_seer_witch_hunter_idiot"),
        win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    )
    compiled = resolve_rule_set_snapshot(rule_set_snapshot(rule_set))
    state = initialize_game_state(
        session_id=(
            "game_cc000002"
            if crash_after_publish
            else "game_cc000001"
        ),
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolves = [player for player in state.players if player.role == "狼人"][:2]
    hunter = next(player for player in state.players if player.role == "猎人")
    civilians = [player for player in state.players if player.role == "村民"][:2]
    before = [
        wolves[0].name,
        wolves[1].name,
        hunter.name,
        civilians[0].name,
        civilians[1].name,
    ]
    active = [
        wolves[0].name,
        wolves[1].name,
        civilians[0].name,
        civilians[1].name,
    ]
    state.sheriff = hunter.name
    hunter.is_sheriff = True
    round_state = RoundState(
        number=2,
        players=before,
        exiled=hunter.name,
        day_deaths=[DeathEvent(hunter.name, "vote_exile", "投票")],
    )
    round_log = RoundLog(number=2)
    checkpoint_manager = ResumeCheckpointManager(
        record_store=record_store,
        session_id=state.session_id,
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
    )
    checkpoint_manager.start_round(
        state=state,
        logs=[],
        round_number=round_state.number,
        active_players=before,
        rng_state=None,
    )
    state.rounds.append(round_state)
    for player in state.players:
        assert player.gamestate is not None
        player.gamestate.current_players = active.copy()
    parent_sink = (
        CrashAfterHunterPresentationSink()
        if crash_after_publish
        else CrashBeforeHunterPresentationSink()
    )
    engine = GameEngine(
        state=state,
        provider=RejectingProvider(),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=parent_sink,
        checkpoint_manager=checkpoint_manager,
    )
    engine.logs = [round_log]
    engine._begin_terminal_settlement(
        round_state=round_state,
        active_players=active,
        phase="vote",
        primary_actor=hunter.name,
        hunter_contexts=[
            {
                "actor": hunter.name,
                "death_cause": "vote_exile",
                "phase": "vote",
                "excluded_shot_targets": [],
                "excluded_badge_targets": [],
                "transfer_sheriff_badge": False,
            }
        ],
        continuation_kind="day_exile_aftermath",
        continuation_transfer_sheriff_badge=True,
        skip_exile_last_words=True,
    )
    engine._accept_terminal_hunter_choice(
        hunter=hunter,
        shot=wolves[0].name,
        round_state=round_state,
        round_log=round_log,
        active_players=active,
        death_cause="vote_exile",
        phase="vote",
        excluded_shot_targets=set(),
        excluded_badge_targets=None,
        transfer_sheriff_badge=False,
    )
    engine._publish_terminal_primary_presentation(
        round_state=round_state,
        active_players=active,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "worker crashed after publishing hunter result"
            if crash_after_publish
            else "worker crashed before publishing hunter result"
        ),
    ):
        engine._apply_hunter_shot_choice(
            hunter=hunter,
            shot=wolves[0].name,
            round_state=round_state,
            round_log=round_log,
            active_players=active,
            phase="vote",
            excluded_badge_targets=None,
            transfer_sheriff_badge=False,
        )

    persisted = terminal_settlement_from_checkpoint(
        record_store.load_resume_checkpoint(state.session_id)
    )
    assert persisted is not None
    assert persisted["stage"] == "outcome_applied"
    assert persisted["continuation"] == {
        "kind": "day_exile_aftermath",
        "status": "pending",
        "skip_exile_last_words": True,
        "transfer_sheriff_badge": True,
    }
    restored_state = game_state_from_dict(persisted["state"])
    restored_logs = [round_log_from_dict(item) for item in persisted["logs"]]
    restored_active = [str(name) for name in persisted["active_players"]]
    recovery_provider = BadgeOnlyRecoveryProvider(badge_target=civilians[0].name)
    recovery_sink = IdCapturingEventSink()
    recovery_engine = GameEngine(
        state=restored_state,
        provider=recovery_provider,
        max_rounds=8,
        rule_set=compiled.rule_set,
        event_sink=recovery_sink,
        checkpoint_manager=checkpoint_manager,
    )
    monkeypatch.setattr(recovery_engine, "_run_private_round_memories", lambda *_: None)

    recovery_engine.recover_terminal_settlement(
        persisted,
        logs=restored_logs,
        active_players=restored_active,
    )

    assert restored_state.winner == ""
    assert restored_active == [
        wolves[1].name,
        civilians[0].name,
        civilians[1].name,
    ]
    assert restored_state.sheriff == civilians[0].name
    assert recovery_provider.actions == ["sheriff_badge"]
    assert restored_state.rounds[-1].exile_last_words is None
    assert restored_state.rounds[-1].success is True
    recovery_actions = [
        event.get("action")
        for event in recovery_sink.events
        if event["type"] == "state_updated"
    ]
    assert recovery_actions.index("exile_resolved") < recovery_actions.index(
        "hunter_shot_resolved"
    )
    primary = next(
        event
        for event in recovery_sink.events
        if event.get("action") == "exile_resolved"
    )
    hunter_result = next(
        event
        for event in recovery_sink.events
        if event.get("action") == "hunter_shot_resolved"
    )
    assert str(primary["payload"]["presentation_id"]).startswith("pp_")
    assert str(hunter_result["payload"]["presentation_id"]).startswith("hp_")
    assert not any(
        event.get("action") in {"hunter_shoot", "exile_last_words"}
        for event in recovery_sink.events
    )
    completed = terminal_settlement_from_checkpoint(
        record_store.load_resume_checkpoint(state.session_id)
    )
    assert completed is not None
    assert completed["stage"] == "candidate_cleared"
    assert completed["continuation"]["status"] == "applied"


def test_second_resume_after_cleared_terminal_candidate_preserves_prior_logs(
    record_store: DatabaseReplayStore,
) -> None:
    rule_set = replace(
        get_rule_set("classic_12_seer_witch_hunter_idiot"),
        win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    )
    compiled = resolve_rule_set_snapshot(rule_set_snapshot(rule_set))
    state = initialize_game_state(
        session_id="game_cc000003",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolves = [player for player in state.players if player.role == "狼人"][:2]
    hunter = next(player for player in state.players if player.role == "猎人")
    civilians = [player for player in state.players if player.role == "村民"][:2]
    before = [
        wolves[0].name,
        wolves[1].name,
        hunter.name,
        civilians[0].name,
        civilians[1].name,
    ]
    active = [wolves[1].name, civilians[0].name, civilians[1].name]
    state.sheriff = hunter.name
    hunter.is_sheriff = True
    hunter.hunter_can_shoot = False
    round_state = RoundState(
        number=1,
        players=before,
        exiled=hunter.name,
        day_deaths=[
            DeathEvent(hunter.name, "vote_exile", "投票"),
            DeathEvent(wolves[0].name, "hunter_shot", "猎人开枪"),
        ],
        hunter_shot=wolves[0].name,
    )
    hunter_response = json.dumps(
        {"reasoning": "终局候选反转。", "shoot": wolves[0].name},
        ensure_ascii=False,
    )
    round_log = RoundLog(
        number=1,
        hunter_shoot=ActionLog(
            actor=hunter.name,
            action="hunter_shoot",
            options=[wolves[0].name, wolves[1].name, *active[1:], NO_HUNTER_SHOT],
            choice=wolves[0].name,
            lm_log=LmLog(
                prompt="persisted hunter prompt",
                raw_response=hunter_response,
                result={"reasoning": "终局候选反转。", "shoot": wolves[0].name},
                action_id="act_double_resume_hunter",
                request_id="req_double_resume_hunter",
            ),
        ),
    )
    settlement_id = "settlement:double-resume:hunter"
    settlement = {
        "settlement_schema_version": "settlement_v1",
        "stage": "outcome_applied",
        "primary_outcome_action_id": "outcome:double-resume:vote:exile",
        "settlement_cursor": 2,
        "settlements": [
            {
                "settlement_id": "settlement:double-resume:primary",
                "kind": "death_batch",
                "actor": hunter.name,
                "status": "applied",
                "accepted_choice": None,
                "details": {"phase": "vote"},
            },
            {
                "settlement_id": settlement_id,
                "kind": "hunter_shot",
                "actor": hunter.name,
                "status": "applied",
                "accepted_choice": wolves[0].name,
                "details": {
                    "actor": hunter.name,
                    "death_cause": "vote_exile",
                    "phase": "vote",
                    "excluded_shot_targets": [],
                    "excluded_badge_targets": [],
                    "transfer_sheriff_badge": False,
                },
                "presentation": {
                    "presentation_id": _hunter_presentation_id(
                        state.session_id,
                        settlement_id,
                    ),
                    "kind": "hunter_shot_result",
                    "hunter_shot_status": "shot",
                    "hunter_shot": wolves[0].name,
                },
            },
        ],
        "canceled_action_ids": [],
        "continuation": {
            "kind": "day_exile_aftermath",
            "status": "pending",
            "skip_exile_last_words": True,
            "transfer_sheriff_badge": True,
        },
    }
    checkpoint_manager = ResumeCheckpointManager(
        record_store=record_store,
        session_id=state.session_id,
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
    )
    checkpoint_manager.start_round(
        state=state,
        logs=[],
        round_number=1,
        active_players=before,
        rng_state=None,
    )
    state.rounds.append(round_state)
    for player in state.players:
        assert player.gamestate is not None
        player.gamestate.current_players = active.copy()
    checkpoint_manager.record_terminal_settlement(
        state=state,
        logs=[round_log],
        active_players=active,
        terminal_settlement=settlement,
    )

    with pytest.raises(
        GameRunError,
        match="worker crashed in the next round after terminal recovery",
    ):
        resume_game(
            session_id=state.session_id,
            record_store=record_store,
            provider=ScriptedProvider(),
            event_sink=CrashOnRoundStartedSink(round_number=2),
        )

    second_checkpoint = record_store.load_resume_checkpoint(state.session_id)
    assert second_checkpoint["round_number"] == 2
    assert "terminal_settlement" not in second_checkpoint
    prior_logs = second_checkpoint["logs_before_round"]
    assert [log["number"] for log in prior_logs] == [1]
    assert prior_logs[0]["hunter_shoot"]["choice"] == wolves[0].name
    badge_choice = prior_logs[0]["sheriff_badge"]["choice"]
    assert badge_choice in active
    assert len(prior_logs[0]["summaries"]) == 3

    result = resume_game(
        session_id=state.session_id,
        record_store=record_store,
        provider=ScriptedProvider(),
    )

    assert result.winner == "狼人阵营"
    replay = record_store.load_session(state.session_id)
    assert [log["number"] for log in replay["logs"]] == [1, 2]
    restored_prior_log = replay["logs"][0]
    assert restored_prior_log["hunter_shoot"]["choice"] == wolves[0].name
    assert restored_prior_log["sheriff_badge"]["choice"] == badge_choice
    assert len(restored_prior_log["summaries"]) == 3


@pytest.mark.parametrize("crash_after_publish", [False, True])
def test_pending_terminal_hunter_recovery_preserves_exile_last_words_across_publish_crash(
    record_store: DatabaseReplayStore,
    crash_after_publish: bool,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    compiled = legacy_official_compiled_rule_set(rule_set.id)
    state = initialize_game_state(
        session_id="game_ad000002" if crash_after_publish else "game_ad000001",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    hunter = next(player for player in state.players if player.role == "猎人")
    seer = next(player for player in state.players if player.role == "预言家")
    civilian = next(player for player in state.players if player.role == "村民")
    before = [wolf.name, hunter.name, seer.name, civilian.name]
    active = before.copy()
    state.sheriff = seer.name
    seer.is_sheriff = True
    round_state = RoundState(number=2, players=before.copy())
    round_log = RoundLog(number=2)
    checkpoint_manager = ResumeCheckpointManager(
        record_store=record_store,
        session_id=state.session_id,
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
    )
    checkpoint_manager.start_round(
        state=state,
        logs=[],
        round_number=round_state.number,
        active_players=before,
        rng_state=None,
    )
    state.rounds.append(round_state)
    for player in state.players:
        assert player.gamestate is not None
        player.gamestate.current_players = before.copy()
    parent_provider = ScriptedProvider()
    parent_sink = DurableExileLastWordsCrashSink(
        record_store=record_store,
        session_id=state.session_id,
        after=crash_after_publish,
    )
    engine = GameEngine(
        state=state,
        provider=parent_provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=parent_sink,
        checkpoint_manager=checkpoint_manager,
    )
    engine.logs = [round_log]

    with pytest.raises(
        RuntimeError,
        match=(
            "worker crashed after publishing exile last words result"
            if crash_after_publish
            else "worker crashed before publishing exile last words result"
        ),
    ):
        engine._resolve_day_exile(
            hunter.name,
            round_state,
            round_log,
            active,
        )

    assert parent_provider.calls == 2
    assert active == [wolf.name, seer.name, civilian.name]
    persisted = terminal_settlement_from_checkpoint(
        record_store.load_resume_checkpoint(state.session_id)
    )
    assert persisted is not None
    assert persisted["stage"] == "outcome_applied"
    assert persisted["continuation"] == {
        "kind": "day_exile_aftermath",
        "status": "pending",
        "skip_exile_last_words": False,
        "transfer_sheriff_badge": True,
    }
    assert persisted["settlements"][-1]["status"] == "pending"
    persisted_round = persisted["state"]["rounds"][-1]
    assert persisted_round["exile_last_words"] == {
        "player": hunter.name,
        "message": "我会继续观察。",
        "status": "completed",
        "reason_code": "completed",
    }
    persisted_last_words_log = persisted["logs"][-1]["exile_last_words"]
    assert persisted_last_words_log["choice"] == "我会继续观察。"
    parent_speech = next(
        event
        for event in parent_sink.events
        if event["type"] == "action_parsed"
        and event.get("action") == "exile_last_words"
    )
    assert str(parent_speech["payload"]["presentation_id"]).startswith("lws_")
    parent_results = [
        event
        for event in parent_sink.events
        if event["type"] == "state_updated"
        and event.get("action") == "exile_last_words"
    ]
    assert len(parent_results) == (1 if crash_after_publish else 0)
    if parent_results:
        assert str(parent_results[0]["payload"]["presentation_id"]).startswith(
            "lwr_"
        )

    recovery_provider = PendingHunterRecoveryProvider(shoot_choice=wolf.name)
    recovery_sink = IdCapturingEventSink()
    result = resume_game(
        session_id=state.session_id,
        record_store=record_store,
        provider=recovery_provider,
        event_sink=recovery_sink,
    )

    assert result.winner == "好人阵营"
    assert result.terminal_keep_from_event_id == 2
    assert recovery_provider.actions == ["hunter_shoot"]
    recovered_primary = next(
        event
        for event in recovery_sink.events
        if event.get("action") == "exile_resolved"
    )
    recovered_speech = next(
        event
        for event in recovery_sink.events
        if event["type"] == "action_parsed"
        and event.get("action") == "exile_last_words"
    )
    recovered_last_words = next(
        event
        for event in recovery_sink.events
        if event["type"] == "state_updated"
        and event.get("action") == "exile_last_words"
    )
    hunter_request = next(
        event
        for event in recovery_sink.events
        if event["type"] == "action_requested"
        and event.get("action") == "hunter_shoot"
    )
    recovered_hunter = next(
        event
        for event in recovery_sink.events
        if event.get("action") == "hunter_shot_resolved"
    )
    assert recovered_speech["payload"] == parent_speech["payload"]
    assert recovered_last_words["payload"]["exile_last_words"] == (
        persisted_round["exile_last_words"]
    )
    speech_presentation_ids = {
        str(event["payload"]["presentation_id"])
        for event in [parent_speech, recovered_speech]
    }
    result_presentation_ids = {
        str(event["payload"]["presentation_id"])
        for event in [*parent_results, recovered_last_words]
    }
    assert len(speech_presentation_ids) == 1
    assert len(result_presentation_ids) == 1
    assert (
        recovery_sink.events.index(recovered_primary)
        < recovery_sink.events.index(recovered_speech)
        < recovery_sink.events.index(recovered_last_words)
        < recovery_sink.events.index(hunter_request)
        < recovery_sink.events.index(recovered_hunter)
    )
    replay = record_store.load_session(state.session_id)
    replay_round = replay["state"]["rounds"][-1]
    assert replay_round["exile_last_words"] == persisted_round["exile_last_words"]
    assert replay["logs"][-1]["exile_last_words"]["choice"] == "我会继续观察。"


@pytest.mark.parametrize("crash_after_publish", [False, True])
def test_recovery_replays_frozen_primary_before_terminal_hunter_result(
    record_store: DatabaseReplayStore,
    crash_after_publish: bool,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    compiled = legacy_official_compiled_rule_set(rule_set.id)
    state = initialize_game_state(
        session_id="game_bf000002" if crash_after_publish else "game_bf000001",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    hunter = next(player for player in state.players if player.role == "猎人")
    seer = next(player for player in state.players if player.role == "预言家")
    civilian = next(player for player in state.players if player.role == "村民")
    before = [wolf.name, hunter.name, seer.name, civilian.name]
    active = [wolf.name, seer.name, civilian.name]
    state.sheriff = seer.name
    seer.is_sheriff = True
    round_state = RoundState(
        number=2,
        players=before,
        exiled=hunter.name,
        day_deaths=[DeathEvent(hunter.name, "vote_exile", "投票")],
    )
    round_log = RoundLog(number=2)
    checkpoint_manager = ResumeCheckpointManager(
        record_store=record_store,
        session_id=state.session_id,
        compiled_rule_set=compiled,
        run_params={
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
    )
    checkpoint_manager.start_round(
        state=state,
        logs=[],
        round_number=round_state.number,
        active_players=before,
        rng_state=None,
    )
    state.rounds.append(round_state)
    for player in state.players:
        assert player.gamestate is not None
        player.gamestate.current_players = active.copy()
    parent_sink = (
        CrashAfterHunterPresentationSink()
        if crash_after_publish
        else CrashBeforeHunterPresentationSink()
    )
    engine = GameEngine(
        state=state,
        provider=RejectingProvider(),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=parent_sink,
        checkpoint_manager=checkpoint_manager,
    )
    engine.logs = [round_log]
    engine._append_public_outcome(
        round_state=round_state,
        kind="exile",
        target_player=hunter.name,
        outcome="eliminated",
        phase="vote",
    )
    engine._begin_terminal_settlement(
        round_state=round_state,
        active_players=active,
        phase="vote",
        primary_actor=hunter.name,
        hunter_contexts=[
            {
                "actor": hunter.name,
                "death_cause": "vote_exile",
                "phase": "vote",
                "excluded_shot_targets": [],
                "excluded_badge_targets": [],
                "transfer_sheriff_badge": False,
            }
        ],
        continuation_kind="day_exile_aftermath",
        continuation_transfer_sheriff_badge=True,
        skip_exile_last_words=False,
    )
    engine._accept_terminal_hunter_choice(
        hunter=hunter,
        shot=wolf.name,
        round_state=round_state,
        round_log=round_log,
        active_players=active,
        death_cause="vote_exile",
        phase="vote",
        excluded_shot_targets=set(),
        excluded_badge_targets=None,
        transfer_sheriff_badge=False,
    )
    engine._publish_terminal_primary_presentation(
        round_state=round_state,
        active_players=active,
    )
    parent_primary = next(
        event
        for event in parent_sink.events
        if event.get("action") == "exile_resolved"
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "worker crashed after publishing hunter result"
            if crash_after_publish
            else "worker crashed before publishing hunter result"
        ),
    ):
        engine._apply_hunter_shot_choice(
            hunter=hunter,
            shot=wolf.name,
            round_state=round_state,
            round_log=round_log,
            active_players=active,
            phase="vote",
            excluded_badge_targets=None,
            transfer_sheriff_badge=False,
        )

    persisted = terminal_settlement_from_checkpoint(
        record_store.load_resume_checkpoint(state.session_id)
    )
    assert persisted is not None
    frozen = persisted["primary_presentation_payload"]
    assert frozen["day_deaths"] == [
        {"player": hunter.name, "cause": "vote_exile", "source": "投票"},
    ]
    assert frozen["active_players"] == [wolf.name, seer.name, civilian.name]
    assert [event["kind"] for event in frozen["public_outcome_events"]] == [
        "exile"
    ]

    provider = RejectingProvider()
    recovery_sink = IdCapturingEventSink()
    result = resume_game(
        session_id=state.session_id,
        record_store=record_store,
        provider=provider,
        event_sink=recovery_sink,
    )

    assert result.winner == "好人阵营"
    assert result.terminal_keep_from_event_id == 2
    assert provider.calls == 0
    recovered_primary = next(
        event
        for event in recovery_sink.events
        if event.get("action") == "exile_resolved"
    )
    recovered_hunter = next(
        event
        for event in recovery_sink.events
        if event.get("action") == "hunter_shot_resolved"
    )
    folded = next(
        event
        for event in recovery_sink.events
        if event.get("action") == "day_resolution_completed"
    )
    assert recovered_primary["payload"] == parent_primary["payload"]
    assert recovered_primary["payload"]["day_deaths"] == [
        {"player": hunter.name, "cause": "vote_exile", "source": "投票"},
    ]
    assert recovered_hunter["payload"]["day_deaths"] == [
        {"player": hunter.name, "cause": "vote_exile", "source": "投票"},
        {"player": wolf.name, "cause": "hunter_shot", "source": hunter.name},
    ]
    assert folded["payload"]["day_deaths"] == recovered_hunter["payload"][
        "day_deaths"
    ]
    assert (
        recovery_sink.events.index(recovered_primary)
        < recovery_sink.events.index(recovered_hunter)
        < recovery_sink.events.index(folded)
    )


def test_terminal_hunter_presentation_validation_is_strict_but_optional_for_legacy() -> None:
    legacy = _primary_terminal_settlement(stage="hunter_choice_accepted")
    legacy.update({"state": {}, "logs": [], "active_players": ["1号玩家"]})
    legacy["settlements"].append(
        {
            "settlement_id": "settlement:test:hunter:legacy",
            "kind": "hunter_shot",
            "actor": "1号玩家",
            "status": "choice_accepted",
            "accepted_choice": NO_HUNTER_SHOT,
            "details": {"phase": "vote"},
        }
    )

    assert terminal_settlement_from_checkpoint({"terminal_settlement": legacy}) is not None

    with_primary = copy.deepcopy(legacy)
    with_primary["primary_presentation"] = {
        "presentation_id": "pp_0123456789abcdef01234567",
        "kind": "exile_result",
    }
    assert (
        terminal_settlement_from_checkpoint({"terminal_settlement": with_primary})
        is not None
    )

    with_frozen_payload = copy.deepcopy(with_primary)
    with_frozen_payload["primary_presentation_payload"] = {
        "exiled": "1号玩家",
        "day_deaths": [
            {"player": "1号玩家", "cause": "vote_exile", "source": "投票"}
        ],
        "active_players": ["2号玩家"],
        "public_outcome_events": [],
        "public_outcome_next_sequence": 1,
    }
    assert (
        terminal_settlement_from_checkpoint(
            {"terminal_settlement": with_frozen_payload}
        )
        is not None
    )

    malformed_frozen_payload = copy.deepcopy(with_frozen_payload)
    malformed_frozen_payload["primary_presentation_payload"]["day_deaths"] = [
        {"player": "2号玩家", "cause": "hunter_shot", "source": "1号玩家"}
    ]
    with pytest.raises(ResumeCheckpointError, match="structure is invalid"):
        terminal_settlement_from_checkpoint(
            {"terminal_settlement": malformed_frozen_payload}
        )

    malformed_primary = copy.deepcopy(with_primary)
    malformed_primary["primary_presentation"]["presentation_id"] = "exile-result-1"
    with pytest.raises(ResumeCheckpointError, match="structure is invalid"):
        terminal_settlement_from_checkpoint(
            {"terminal_settlement": malformed_primary}
        )

    malformed = copy.deepcopy(legacy)
    malformed["settlements"][-1]["presentation"] = {
        "presentation_id": "not-an-opaque-presentation-id",
        "kind": "hunter_shot_result",
        "hunter_shot_status": "shot",
        "hunter_shot": "2号玩家",
    }

    with pytest.raises(ResumeCheckpointError, match="structure is invalid"):
        terminal_settlement_from_checkpoint({"terminal_settlement": malformed})


def test_resume_deferred_hunter_settlement_after_last_wolf_self_explosion(
    record_store: DatabaseReplayStore,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="game_a0010004",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    hunter = next(player for player in state.players if player.role == "猎人")
    seer = next(player for player in state.players if player.role == "预言家")
    civilian = next(player for player in state.players if player.role == "村民")
    before = [wolf.name, hunter.name, seer.name, civilian.name]
    active = [seer.name, civilian.name]
    round_state = RoundState(
        number=1,
        players=before,
        werewolf_self_exploded=wolf.name,
        day_ended_by_self_explosion=True,
        day_deaths=[DeathEvent(wolf.name, "werewolf_self_explosion", wolf.name)],
        night_deaths=[DeathEvent(hunter.name, "werewolf_attack", "狼人")],
    )
    settlement = {
        "settlement_schema_version": "settlement_v1",
        "stage": "outcome_applied",
        "primary_outcome_action_id": "outcome:test:night:death_batch",
        "settlement_cursor": 1,
        "settlements": [
            {
                "settlement_id": "settlement:test:primary",
                "kind": "death_batch",
                "actor": None,
                "status": "applied",
                "accepted_choice": None,
                "details": {"phase": "night"},
            },
            {
                "settlement_id": "settlement:test:hunter",
                "kind": "hunter_shot",
                "actor": hunter.name,
                "status": "pending",
                "accepted_choice": None,
                "details": {
                    "actor": hunter.name,
                    "death_cause": "werewolf_attack",
                    "phase": "night",
                    "excluded_shot_targets": [hunter.name],
                    "excluded_badge_targets": [hunter.name],
                    "transfer_sheriff_badge": False,
                },
            },
        ],
        "canceled_action_ids": [],
    }
    _persist_terminal_settlement_checkpoint(
        record_store=record_store,
        state=state,
        round_state=round_state,
        round_log=RoundLog(number=1),
        active_players=active,
        terminal_settlement=settlement,
    )
    provider = PendingHunterRecoveryProvider(shoot_choice=civilian.name)
    sink = IdCapturingEventSink()

    result = resume_game(
        session_id=state.session_id,
        record_store=record_store,
        provider=provider,
        event_sink=sink,
    )

    assert result.winner == "好人阵营"
    assert provider.actions == ["hunter_shoot"]
    assert [
        event.get("action")
        for event in sink.events
        if event["type"] == "action_requested"
    ] == ["hunter_shoot"]
    replay = record_store.load_session(state.session_id)
    restored_round = replay["state"]["rounds"][0]
    assert restored_round["werewolf_self_exploded"] == wolf.name
    assert [death["player"] for death in restored_round["day_deaths"]] == [wolf.name]
    assert [death["player"] for death in restored_round["night_deaths"]] == [
        hunter.name,
        civilian.name,
    ]
    assert restored_round["hunter_shot"] == civilian.name


def test_complete_v1_resume_normalizes_only_when_next_round_is_written(
    record_store: DatabaseReplayStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GameRunError) as initial_error:
        run_game(
            record_store=record_store,
            compiled_rule_set=legacy_official_compiled_rule_set("starter_6"),
            provider=FailingAfterProvider(fail_after_successes=0),
            seed=21,
            max_rounds=8,
        )
    assert initial_error.value.session_id is not None
    session_id = initial_error.value.session_id
    checkpoint = record_store.load_resume_checkpoint(session_id)
    checkpoint["schema_version"] = 1
    for name in ("revision_id", "revision_no", "content_hash", "rule_set_snapshot"):
        checkpoint["run_params"].pop(name)
    original_v1 = copy.deepcopy(checkpoint)
    record_store.save_resume_checkpoint(session_id, checkpoint)

    assert record_store.load_resume_checkpoint(session_id) == original_v1

    def reject_catalog_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("resume must use the checkpoint rule snapshot")

    monkeypatch.setattr("app.werewolf.rules.get_rule_set", reject_catalog_lookup)
    monkeypatch.setattr(
        "app.rule_sets.service.resolve_published_rule_set",
        reject_catalog_lookup,
    )

    with pytest.raises(GameRunError):
        resume_game(
            record_store=record_store,
            session_id=session_id,
            provider=FailingAfterProvider(fail_after_successes=0),
        )

    rewritten = record_store.load_resume_checkpoint(session_id)
    assert rewritten["schema_version"] == 3
    assert set(rewritten["run_params"]) == {
        "villager_model",
        "werewolf_model",
        "seed",
        "max_rounds",
        "player_configs",
        "rule_set_id",
        "revision_id",
        "revision_no",
        "content_hash",
        "rule_set_snapshot",
    }
    assert checkpoint == original_v1


def test_resume_rejects_worker_checkpoint_snapshot_divergence(
    record_store: DatabaseReplayStore,
) -> None:
    with pytest.raises(GameRunError) as initial_error:
        run_game(
            record_store=record_store,
            compiled_rule_set=legacy_official_compiled_rule_set("starter_6"),
            provider=FailingAfterProvider(fail_after_successes=0),
            seed=21,
            max_rounds=8,
        )
    assert initial_error.value.session_id is not None

    with pytest.raises(GameRunError, match="rule snapshot changed"):
        resume_game(
            record_store=record_store,
            session_id=initial_error.value.session_id,
            provider=ScriptedProvider(),
            expected_compiled_rule_set=legacy_official_compiled_rule_set("classic_8"),
        )


def test_replay_then_live_provider_uses_cached_response_first() -> None:
    live_provider = ScriptedProvider()
    provider = ReplayThenLiveProvider(
        cached_model_responses=[
            {
                "actor": "张三",
                "action": "werewolf_kill_vote",
                "phase": "night",
                "model": "deepseek-chat",
                "raw_response": '{"reasoning":"cached","target":"李四"}',
            }
        ],
        delegate=live_provider,
    )

    assert (
        provider.complete_json(model="deepseek-chat", prompt="first", temperature=0.4)
        == '{"reasoning":"cached","target":"李四"}'
    )
    assert live_provider.calls == 0

    response = provider.complete_json(
        model="deepseek-chat",
        prompt='行动："vote"。候选人：李四。',
        temperature=0.4,
    )

    assert json.loads(response)["vote"] == "李四"
    assert live_provider.calls == 1


def _new_lifecycle_checkpoint_manager(
    *,
    record_store: DatabaseReplayStore,
    state: GameState,
    initial_checkpoint: dict[str, object] | None = None,
    crash_kind: str | None = None,
) -> ResumeCheckpointManager:
    manager_type = (
        CrashBeforeLifecycleCheckpointManager
        if crash_kind is not None
        else ResumeCheckpointManager
    )
    kwargs: dict[str, object] = {
        "record_store": record_store,
        "session_id": state.session_id,
        "compiled_rule_set": legacy_official_compiled_rule_set("starter_6"),
        "run_params": {
            "villager_model": "villager-model",
            "werewolf_model": "werewolf-model",
            "seed": 21,
            "max_rounds": 8,
            "player_configs": [],
        },
        "initial_checkpoint": initial_checkpoint,
    }
    if crash_kind is not None:
        kwargs["crash_kind"] = crash_kind
    manager = manager_type(**kwargs)
    if initial_checkpoint is None:
        manager.start_round(
            state=state,
            logs=[],
            round_number=1,
            active_players=[player.name for player in state.players],
            rng_state=None,
        )
    return manager


def _new_lifecycle_engine(
    *,
    state: GameState,
    sink: DurableLifecycleEventSink,
    manager: ResumeCheckpointManager,
) -> GameEngine:
    return GameEngine(
        state=state,
        provider=RejectingProvider(),
        max_rounds=8,
        rule_set=get_rule_set("starter_6"),
        event_sink=sink,
        checkpoint_manager=manager,
        execution_mode="resume",
        resume_from_round=1,
    )


def _complete_test_phase(
    engine: GameEngine,
    *,
    phase: str,
    next_phase: str | None,
) -> None:
    engine._complete_phase(
        round_number=1,
        phase=phase,
        completion_status="completed",
        completion_reason=f"{phase}_completed",
        next_phase=next_phase,
        terminal=False,
    )


def _captured_lifecycle_kinds(
    sink: DurableLifecycleEventSink,
) -> list[tuple[str, str, str]]:
    return [
        (
            str(event["type"]),
            str(event["phase"]),
            str(event["payload"]["phase_instance_id"]),
        )
        for event in sink.events
        if event["type"] in {"phase_started", "phase_completed"}
    ]


def test_lifecycle_recovery_reconciles_started_published_before_checkpoint(
    record_store: DatabaseReplayStore,
) -> None:
    state = initialize_game_state(
        session_id="game_1a000001",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=get_rule_set("starter_6"),
    )
    sink = DurableLifecycleEventSink()
    crashing_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
        crash_kind="phase_started",
    )
    engine = _new_lifecycle_engine(
        state=state,
        sink=sink,
        manager=crashing_manager,
    )

    with pytest.raises(RuntimeError, match="checkpointing phase_started"):
        engine._start_phase(round_number=1, phase="night", payload={})

    stale_checkpoint = record_store.load_resume_checkpoint(state.session_id)
    assert lifecycle_ledger_from_checkpoint(stale_checkpoint)["events"] == []
    recovered_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
        initial_checkpoint=stale_checkpoint,
    )
    recovered = _new_lifecycle_engine(
        state=state,
        sink=sink,
        manager=recovered_manager,
    )
    assert recovered._start_phase(round_number=1, phase="night", payload={}) == (
        "phase:r1:night:1"
    )
    _complete_test_phase(recovered, phase="night", next_phase="dawn_reveal")
    recovered._start_phase(round_number=1, phase="dawn_reveal", payload={})
    _complete_test_phase(recovered, phase="dawn_reveal", next_phase="day")

    assert _captured_lifecycle_kinds(sink) == [
        ("phase_started", "night", "phase:r1:night:1"),
        ("phase_completed", "night", "phase:r1:night:1"),
        ("phase_started", "dawn_reveal", "phase:r1:dawn_reveal:1"),
        ("phase_completed", "dawn_reveal", "phase:r1:dawn_reveal:1"),
    ]
    ledger = lifecycle_ledger_from_checkpoint(
        record_store.load_resume_checkpoint(state.session_id)
    )
    assert len(ledger["events"]) == 4


def test_lifecycle_recovery_reconciles_completed_published_before_checkpoint_twice(
    record_store: DatabaseReplayStore,
) -> None:
    state = initialize_game_state(
        session_id="game_1a000002",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=get_rule_set("starter_6"),
    )
    sink = DurableLifecycleEventSink()
    crashing_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
        crash_kind="phase_completed",
    )
    engine = _new_lifecycle_engine(
        state=state,
        sink=sink,
        manager=crashing_manager,
    )
    engine._start_phase(round_number=1, phase="night", payload={})

    with pytest.raises(RuntimeError, match="checkpointing phase_completed"):
        _complete_test_phase(engine, phase="night", next_phase="dawn_reveal")

    stale_checkpoint = record_store.load_resume_checkpoint(state.session_id)
    assert len(lifecycle_ledger_from_checkpoint(stale_checkpoint)["events"]) == 1
    first_recovery_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
        initial_checkpoint=stale_checkpoint,
    )
    first_recovery = _new_lifecycle_engine(
        state=state,
        sink=sink,
        manager=first_recovery_manager,
    )
    first_recovery._start_phase(round_number=1, phase="night", payload={})
    before_suppressed_action = len(sink.events)
    first_recovery._publish(
        "action_requested",
        round_number=1,
        phase="night",
        action="remove",
        payload={},
    )
    assert len(sink.events) == before_suppressed_action
    _complete_test_phase(first_recovery, phase="night", next_phase="dawn_reveal")

    second_checkpoint = record_store.load_resume_checkpoint(state.session_id)
    second_recovery_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
        initial_checkpoint=second_checkpoint,
    )
    second_recovery = _new_lifecycle_engine(
        state=state,
        sink=sink,
        manager=second_recovery_manager,
    )
    second_recovery._start_phase(round_number=1, phase="night", payload={})
    _complete_test_phase(second_recovery, phase="night", next_phase="dawn_reveal")

    assert _captured_lifecycle_kinds(sink) == [
        ("phase_started", "night", "phase:r1:night:1"),
        ("phase_completed", "night", "phase:r1:night:1"),
    ]
    assert len(lifecycle_ledger_from_checkpoint(second_checkpoint)["events"]) == 2


def test_lifecycle_recovery_closes_checkpointed_open_phase_once(
    record_store: DatabaseReplayStore,
) -> None:
    state = initialize_game_state(
        session_id="game_1a000003",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=get_rule_set("starter_6"),
    )
    sink = DurableLifecycleEventSink()
    manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
    )
    engine = _new_lifecycle_engine(state=state, sink=sink, manager=manager)
    engine._start_phase(round_number=1, phase="night", payload={})

    checkpoint = record_store.load_resume_checkpoint(state.session_id)
    recovered_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
        initial_checkpoint=checkpoint,
    )
    recovered = _new_lifecycle_engine(
        state=state,
        sink=sink,
        manager=recovered_manager,
    )
    recovered._start_phase(round_number=1, phase="night", payload={})
    recovered._publish(
        "action_requested",
        round_number=1,
        phase="night",
        action="remove",
        payload={},
    )
    _complete_test_phase(recovered, phase="night", next_phase="dawn_reveal")

    assert _captured_lifecycle_kinds(sink) == [
        ("phase_started", "night", "phase:r1:night:1"),
        ("phase_completed", "night", "phase:r1:night:1"),
    ]
    assert [event["type"] for event in sink.events].count("action_requested") == 1


def test_lifecycle_recovery_starts_new_occurrence_after_forced_failure(
    record_store: DatabaseReplayStore,
) -> None:
    state = initialize_game_state(
        session_id="game_1a000005",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=get_rule_set("starter_6"),
    )
    sink = DurableLifecycleEventSink()
    manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
    )
    engine = _new_lifecycle_engine(state=state, sink=sink, manager=manager)
    engine._start_phase(round_number=1, phase="night", payload={})
    engine._complete_phase(
        round_number=1,
        phase="night",
        completion_status="canceled",
        completion_reason="forced_failure",
        next_phase=None,
        terminal=False,
    )

    checkpoint = record_store.load_resume_checkpoint(state.session_id)
    recovered_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
        initial_checkpoint=checkpoint,
    )
    recovered = _new_lifecycle_engine(
        state=state,
        sink=sink,
        manager=recovered_manager,
    )
    assert recovered._start_phase(round_number=1, phase="night", payload={}) == (
        "phase:r1:night:2"
    )
    _complete_test_phase(recovered, phase="night", next_phase="dawn_reveal")

    assert _captured_lifecycle_kinds(sink) == [
        ("phase_started", "night", "phase:r1:night:1"),
        ("phase_completed", "night", "phase:r1:night:1"),
        ("phase_started", "night", "phase:r1:night:2"),
        ("phase_completed", "night", "phase:r1:night:2"),
    ]


def test_lifecycle_ledger_scopes_local_event_ids_across_parent_and_child_runs(
    record_store: DatabaseReplayStore,
) -> None:
    state = initialize_game_state(
        session_id="game_1a000007",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=get_rule_set("starter_6"),
    )
    parent_sink = DurableLifecycleEventSink(run_id="run_parent")
    parent_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
    )
    parent = _new_lifecycle_engine(
        state=state,
        sink=parent_sink,
        manager=parent_manager,
    )
    parent._start_phase(round_number=1, phase="night", payload={})
    _complete_test_phase(parent, phase="night", next_phase="dawn_reveal")
    parent_checkpoint = record_store.load_resume_checkpoint(state.session_id)

    child_sink = DurableLifecycleEventSink(run_id="run_child")
    child_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
        initial_checkpoint=parent_checkpoint,
    )
    child = _new_lifecycle_engine(
        state=state,
        sink=child_sink,
        manager=child_manager,
    )
    child._start_phase(round_number=1, phase="night", payload={})
    _complete_test_phase(child, phase="night", next_phase="dawn_reveal")
    assert child_sink.events == []
    child._start_phase(round_number=1, phase="dawn_reveal", payload={})
    _complete_test_phase(child, phase="dawn_reveal", next_phase="day")

    ledger = lifecycle_ledger_from_checkpoint(
        record_store.load_resume_checkpoint(state.session_id)
    )
    assert {
        (event["stream_id"], event["event_id"])
        for event in ledger["events"]
    } == {
        ("run_parent", 1),
        ("run_parent", 2),
        ("run_child", 1),
        ("run_child", 2),
    }


def test_terminal_settlement_recovery_closes_persisted_open_vote_phase(
    record_store: DatabaseReplayStore,
) -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="game_1a000006",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    goods = [player for player in state.players if player.role != "狼人"][:2]
    before = [wolf.name, *(player.name for player in goods)]
    active = [player.name for player in goods]
    round_state = RoundState(
        number=1,
        players=before,
        exiled=wolf.name,
        day_deaths=[DeathEvent(wolf.name, "vote_exile", "投票")],
        exile_resolution_reason="unique_highest",
    )
    round_log = RoundLog(number=1)
    sink = DurableLifecycleEventSink()
    manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
    )
    engine = GameEngine(
        state=state,
        provider=RejectingProvider(),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        checkpoint_manager=manager,
    )
    engine._start_phase(
        round_number=1,
        phase="vote",
        payload={"active_players": before.copy()},
    )
    state.rounds.append(round_state)
    for player in state.players:
        assert player.gamestate is not None
        player.gamestate.current_players = active.copy()
    manager.record_terminal_settlement(
        state=state,
        logs=[round_log],
        active_players=active,
        terminal_settlement=_primary_terminal_settlement(stage="outcome_applied"),
    )

    provider = RejectingProvider()
    result = resume_game(
        session_id=state.session_id,
        record_store=record_store,
        provider=provider,
        event_sink=sink,
    )

    assert result.winner == "好人阵营"
    assert provider.calls == 0
    assert _captured_lifecycle_kinds(sink) == [
        ("phase_started", "vote", "phase:r1:vote:1"),
        ("phase_completed", "vote", "phase:r1:vote:1"),
    ]
    completion = next(
        event for event in sink.events if event["type"] == "phase_completed"
    )
    assert completion["payload"]["completion_status"] == "terminal"
    assert completion["payload"]["completion_reason"] == "unique_highest"


def test_legacy_checkpoint_without_lifecycle_ledger_rehydrates_from_event_store(
    record_store: DatabaseReplayStore,
) -> None:
    state = initialize_game_state(
        session_id="game_1a000004",
        villager_model="villager-model",
        werewolf_model="werewolf-model",
        seed=21,
        rule_set=get_rule_set("starter_6"),
    )
    sink = DurableLifecycleEventSink()
    manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
    )
    engine = _new_lifecycle_engine(state=state, sink=sink, manager=manager)
    engine._start_phase(round_number=1, phase="night", payload={})
    _complete_test_phase(engine, phase="night", next_phase="dawn_reveal")
    legacy_checkpoint = record_store.load_resume_checkpoint(state.session_id)
    legacy_checkpoint.pop("lifecycle_ledger")
    record_store.save_resume_checkpoint(state.session_id, legacy_checkpoint)

    recovered_manager = _new_lifecycle_checkpoint_manager(
        record_store=record_store,
        state=state,
        initial_checkpoint=legacy_checkpoint,
    )
    recovered = _new_lifecycle_engine(
        state=state,
        sink=sink,
        manager=recovered_manager,
    )
    recovered._start_phase(round_number=1, phase="night", payload={})
    _complete_test_phase(recovered, phase="night", next_phase="dawn_reveal")

    assert len(_captured_lifecycle_kinds(sink)) == 2
    rewritten = record_store.load_resume_checkpoint(state.session_id)
    assert len(lifecycle_ledger_from_checkpoint(rewritten)["events"]) == 2


def test_lifecycle_ledger_rejects_duplicate_kind_or_wrong_source_event() -> None:
    start = {
        "lifecycle_kind": "phase_started",
        "phase_instance_id": "phase:r1:night:1",
        "round_number": 1,
        "phase": "night",
        "event_id": 4,
        "payload": {"phase_instance_id": "phase:r1:night:1"},
    }
    duplicate = copy.deepcopy(start)
    duplicate["event_id"] = 5
    completion = {
        "lifecycle_kind": "phase_completed",
        "phase_instance_id": "phase:r1:night:1",
        "round_number": 1,
        "phase": "night",
        "event_id": 6,
        "payload": {
            "phase_instance_id": "phase:r1:night:1",
            "completion_status": "completed",
            "completion_reason": "night_completed",
            "next_phase": "dawn_reveal",
            "terminal": False,
            "source_event_id": 3,
        },
    }

    with pytest.raises(ResumeCheckpointError, match="structure is invalid"):
        lifecycle_ledger_from_checkpoint(
            {
                "lifecycle_ledger": {
                    "schema_version": 1,
                    "events": [start, duplicate],
                }
            }
        )
    with pytest.raises(ResumeCheckpointError, match="structure is invalid"):
        lifecycle_ledger_from_checkpoint(
            {
                "lifecycle_ledger": {
                    "schema_version": 1,
                    "events": [start, completion],
                }
            }
        )


def test_replay_then_live_provider_drops_legacy_invalid_cached_response() -> None:
    live_provider = ScriptedProvider()
    provider = ReplayThenLiveProvider(
        cached_model_responses=[
            {
                "actor": "林言",
                "action": "debate",
                "phase": "day",
                "model": "deepseek-chat",
                "raw_response": "\n--- retry ---\n",
            }
        ],
        delegate=live_provider,
    )

    response = provider.complete_json(
        model="deepseek-chat",
        prompt='行动："vote"。候选人：李四。',
        temperature=0.4,
    )

    assert json.loads(response)["vote"] == "李四"
    assert live_provider.calls == 1


def test_replay_provider_matches_cached_responses_by_prompt_when_available() -> None:
    delegate = ScriptedProvider()
    provider = ReplayThenLiveProvider(
        cached_model_responses=[
            {
                "actor": "Alice",
                "action": "vote",
                "phase": "vote",
                "model": "model-a",
                "prompt": "prompt-a",
                "raw_response": '{"reasoning":"A","vote":"Bob"}',
            },
            {
                "actor": "Bob",
                "action": "vote",
                "phase": "vote",
                "model": "model-b",
                "prompt": "prompt-b",
                "raw_response": '{"reasoning":"B","vote":"Alice"}',
            },
        ],
        delegate=delegate,
    )

    second = provider.complete_json(model="model-b", prompt="prompt-b", temperature=0.4)
    first = provider.complete_json(model="model-a", prompt="prompt-a", temperature=0.4)

    assert json.loads(second)["vote"] == "Alice"
    assert json.loads(first)["vote"] == "Bob"
    assert delegate.calls == 0


def test_replay_provider_does_not_consume_prompt_cache_on_prompt_miss() -> None:
    delegate = ScriptedProvider()
    provider = ReplayThenLiveProvider(
        cached_model_responses=[
            {
                "actor": "Alice",
                "action": "vote",
                "phase": "vote",
                "model": "model-a",
                "prompt": "p1",
                "raw_response": '{"reasoning":"one","vote":"Bob"}',
            },
            {
                "actor": "Bob",
                "action": "vote",
                "phase": "vote",
                "model": "model-a",
                "prompt": "p2",
                "raw_response": '{"reasoning":"two","vote":"Alice"}',
            },
        ],
        delegate=delegate,
    )

    miss = provider.complete_json(
        model="model-a",
        prompt='行动："vote"。候选人：Live。',
        temperature=0.4,
    )
    cached = provider.complete_json(model="model-a", prompt="p1", temperature=0.4)

    assert json.loads(miss)["vote"] == "Live"
    assert json.loads(cached)["vote"] == "Bob"
    assert delegate.calls == 1


def test_replay_provider_keeps_prompt_and_legacy_cache_consumption_separate() -> None:
    delegate = ScriptedProvider()
    provider = ReplayThenLiveProvider(
        cached_model_responses=[
            {
                "actor": "Legacy One",
                "action": "vote",
                "phase": "vote",
                "model": "model-a",
                "raw_response": '{"reasoning":"legacy-one","vote":"L1"}',
            },
            {
                "actor": "Prompt One",
                "action": "vote",
                "phase": "vote",
                "model": "model-a",
                "prompt": "p1",
                "raw_response": '{"reasoning":"prompt-one","vote":"P1"}',
            },
            {
                "actor": "Legacy Two",
                "action": "vote",
                "phase": "vote",
                "model": "model-a",
                "raw_response": '{"reasoning":"legacy-two","vote":"L2"}',
            },
            {
                "actor": "Prompt Two",
                "action": "vote",
                "phase": "vote",
                "model": "model-a",
                "prompt": "p2",
                "raw_response": '{"reasoning":"prompt-two","vote":"P2"}',
            },
        ],
        delegate=delegate,
    )

    first_legacy = provider.complete_json(model="model-a", prompt="legacy-1", temperature=0.4)
    second_prompt = provider.complete_json(model="model-a", prompt="p2", temperature=0.4)
    second_legacy = provider.complete_json(model="model-a", prompt="legacy-2", temperature=0.4)
    first_prompt = provider.complete_json(model="model-a", prompt="p1", temperature=0.4)
    miss = provider.complete_json(
        model="model-a",
        prompt='行动："vote"。候选人：Live。',
        temperature=0.4,
    )

    assert json.loads(first_legacy)["vote"] == "L1"
    assert json.loads(second_prompt)["vote"] == "P2"
    assert json.loads(second_legacy)["vote"] == "L2"
    assert json.loads(first_prompt)["vote"] == "P1"
    assert json.loads(miss)["vote"] == "Live"
    assert delegate.calls == 1


def test_replay_store_lists_checkpoint_only_session_as_resumable(
    record_store: DatabaseReplayStore,
) -> None:
    provider = FailingAfterProvider(fail_after_successes=0)

    with pytest.raises(GameRunError) as error:
        run_game(
            record_store=record_store,
            compiled_rule_set=legacy_official_compiled_rule_set("starter_6"),
            provider=provider,
            seed=21,
            max_rounds=8,
        )

    assert error.value.session_id is not None
    sessions = record_store.list_sessions()
    session = next(item for item in sessions if item["session_id"] == error.value.session_id)

    assert session["status"] == "partial"
    assert session["resumable"] is True
    assert session["round_count"] == 1


def test_resume_checkpoint_preserves_self_explosion_state() -> None:
    state = GameState(
        session_id="session_self_explosion",
        players=[Player("Alice", "狼人", "wolf-model"), Player("Bob", "村民", "villager-model")],
        sheriff_pre_election_bomb_count=1,
        sheriff_election_pending=True,
    )
    round_state = RoundState(
        number=1,
        players=["Alice", "Bob"],
        werewolf_self_exploded="Alice",
        day_ended_by_self_explosion=True,
        sheriff_pre_election_bomb_count=1,
        sheriff_election_pending=True,
        sheriff_badge_lost_reason="首爆中断警长竞选",
    )
    state.rounds.append(round_state)
    action = ActionLog(
        actor="Alice",
        action="werewolf_self_explosion",
        options=["自爆", "不自爆"],
        choice="自爆",
        lm_log=LmLog(
            prompt="prompt", raw_response='{"self_explode":"自爆"}', result={"self_explode": "自爆"}
        ),
    )
    round_log = RoundLog(number=1, werewolf_self_explosion=action)

    restored_state = game_state_from_dict(state.to_dict())
    restored_log = round_log_from_dict(round_log.to_dict())

    assert restored_state.sheriff_pre_election_bomb_count == 1
    assert restored_state.sheriff_election_pending is True
    restored_round = restored_state.rounds[0]
    assert restored_round.werewolf_self_exploded == "Alice"
    assert restored_round.day_ended_by_self_explosion is True
    assert restored_round.sheriff_pre_election_bomb_count == 1
    assert restored_round.sheriff_election_pending is True
    assert restored_round.sheriff_badge_lost_reason == "首爆中断警长竞选"
    assert restored_log.werewolf_self_explosion is not None
    assert restored_log.werewolf_self_explosion.choice == "自爆"
    assert restored_log.werewolf_self_explosion.decision_schema == "legacy"


def test_round_state_from_dict_defaults_new_summary_fields() -> None:
    round_state = round_state_from_dict({"number": 1, "players": ["1号玩家"]})

    assert round_state.public_summary == ""
    assert round_state.private_summaries == {}
    assert round_state.interruption is None


def test_exile_last_words_round_trip_without_being_requested_again() -> None:
    last_words = ActionLog(
        actor="Alice",
        action="exile_last_words",
        options=[],
        choice="请继续复盘票型。",
        lm_log=LmLog(
            prompt="prompt",
            raw_response='{"say":"请继续复盘票型。"}',
            result={"say": "请继续复盘票型。"},
        ),
    )
    source = RoundState(
        number=2,
        players=["Alice", "Bob"],
        exiled="Alice",
        exile_last_words={
            "player": "Alice",
            "message": "请继续复盘票型。",
            "status": "completed",
            "reason_code": "completed",
        },
    )

    restored_state = round_state_from_dict(source.to_dict())
    restored_log = round_log_from_dict(
        RoundLog(number=2, exile_last_words=last_words).to_dict()
    )

    assert restored_state.exile_last_words == source.exile_last_words
    assert restored_log.exile_last_words is not None
    assert restored_log.exile_last_words.choice == "请继续复盘票型。"


def test_round_state_sheriff_resolutions_round_trip_through_checkpoint_payload() -> None:
    source = RoundState(
        number=4,
        players=["5号玩家", "10号玩家"],
        sheriff_election_resolution=SheriffElectionResolution(
            schema_version=1,
            outcome="badge_lost",
            reason_code="no_off_sheriff_voters",
            reason_text="警下无人可投票",
            sheriff=None,
            candidates=["5号玩家", "10号玩家"],
            withdrawn=[],
            final_candidates=["5号玩家", "10号玩家"],
            voters=[],
            votes={},
            pk_candidates=[],
            runoff_votes={},
            badge_lost=True,
            election_pending=False,
        ),
        sheriff_badge_resolution=SheriffBadgeResolution(
            schema_version=1,
            outcome="destroyed",
            from_player="5号玩家",
            to_player=None,
            reason_code="destroyed_by_owner",
        ),
    )

    restored = round_state_from_dict(source.to_dict())

    assert restored.sheriff_election_resolution == source.sheriff_election_resolution
    assert restored.sheriff_badge_resolution == source.sheriff_badge_resolution


def test_round_state_from_legacy_checkpoint_defaults_sheriff_resolutions() -> None:
    restored = round_state_from_dict({"number": 1, "players": ["1号玩家"]})

    assert restored.sheriff_election_resolution is None
    assert restored.sheriff_badge_resolution is None


def test_round_state_interruption_round_trips_through_checkpoint_payload() -> None:
    interruption = StageInterruption(
        stage="sheriff_speech",
        interrupted_by="werewolf_self_explosion",
        actor="9号玩家",
        timing="before_actor",
        last_completed_speaker="10号玩家",
        completed_actors=["4号玩家", "3号玩家", "10号玩家"],
        pending_actors=["9号玩家", "5号玩家"],
    )
    source = RoundState(
        number=3,
        players=["4号玩家", "3号玩家", "10号玩家", "9号玩家", "5号玩家"],
        interruption=interruption,
    )

    restored = round_state_from_dict(source.to_dict())

    assert restored.interruption == interruption


def test_action_log_serializes_invalid_and_fallback_metadata() -> None:
    action_log = ActionLog(
        actor="1号玩家",
        action="witch_poison",
        options=["6号玩家", "12号玩家", "不使用毒药"],
        choice="不使用毒药",
        lm_log=LmLog(
            prompt="prompt",
            raw_response='{"poison":"10号玩家"}',
            result={"poison": "10号玩家"},
            invalid_attempts=[
                {
                    "value": "10号玩家",
                    "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
                    "result_key": "poison",
                }
            ],
        ),
        invalid_value="10号玩家",
        fallback_choice="不使用毒药",
        fallback_reason="optional_action_invalid",
        attempt_count=3,
    )

    payload = action_log.to_dict()

    assert payload["invalid_value"] == "10号玩家"
    assert payload["fallback_choice"] == "不使用毒药"
    assert payload["fallback_reason"] == "optional_action_invalid"
    assert payload["attempt_count"] == 3
    assert payload["lm_log"]["invalid_attempts"][0]["value"] == "10号玩家"


def test_action_log_round_trips_choice_normalization_metadata() -> None:
    source = ActionLog(
        actor="4号玩家",
        action="hunter_shoot",
        options=["3号玩家", "5号玩家", "不发动技能"],
        choice="5号玩家",
        lm_log=LmLog(
            prompt="prompt",
            raw_response='{"shoot":5}',
            result={"shoot": 5},
            raw_choice=5,
            choice_normalization_kind="seat_alias",
        ),
        raw_choice=5,
        choice_normalization_kind="seat_alias",
    )

    restored = action_log_from_dict(source.to_dict())

    assert restored.choice == "5号玩家"
    assert restored.raw_choice == 5
    assert restored.choice_normalization_kind == "seat_alias"
    assert restored.lm_log.raw_choice == 5
    assert restored.lm_log.choice_normalization_kind == "seat_alias"


def test_action_log_round_trips_speech_quality_metadata_without_rejected_draft() -> None:
    source = ActionLog(
        actor="2号玩家",
        action="debate",
        options=[],
        choice="3号玩家改票5号玩家，这个变化需要解释。",
        lm_log=LmLog(
            prompt="final prompt",
            raw_response='{"say":"3号玩家改票5号玩家，这个变化需要解释。"}',
            result={"say": "3号玩家改票5号玩家，这个变化需要解释。"},
        ),
        speech_mission={
            "schema_version": 1,
            "kind": "vote_analyst",
            "instruction": "解释票型变化。",
            "reason_code": "round_robin",
        },
        speech_quality_report={
            "schema_version": 1,
            "mission_kind": "vote_analyst",
            "mission_completed": True,
            "novelty_score": 1.0,
            "lexical_similarity": 0.0,
            "new_proposition_count": 1,
            "proposition_signatures": [],
            "issues": [],
            "requires_rewrite": False,
        },
        speech_quality_attempt_count=2,
        speech_quality_retry_exhausted=False,
        speech_quality_initial_codes=["repeated_debate_phrase"],
    )

    payload = source.to_dict()
    restored = action_log_from_dict(payload)

    assert "被拒绝的第一版草稿" not in str(payload)
    assert restored.speech_mission == source.speech_mission
    assert restored.speech_quality_report == source.speech_quality_report
    assert restored.speech_quality_attempt_count == 2
    assert restored.speech_quality_retry_exhausted is False
    assert restored.speech_quality_initial_codes == ["repeated_debate_phrase"]


def test_action_log_round_trips_execution_budget_metadata() -> None:
    source = ActionLog(
        actor="4号玩家",
        action="vote",
        options=["2号玩家", "3号玩家"],
        choice="3号玩家",
        lm_log=LmLog(
            prompt="prompt",
            raw_response='{"vote":"3号玩家"}',
            result={"vote": "3号玩家"},
        ),
        fallback_choice="3号玩家",
        fallback_reason="batch_deadline_deterministic_legal_choice",
        execution_status="fallback",
        duration_ms=15000,
        budget_ms=15000,
        first_token_ms=840,
    )

    restored = action_log_from_dict(source.to_dict())

    assert restored.execution_status == "fallback"
    assert restored.duration_ms == 15000
    assert restored.budget_ms == 15000
    assert restored.first_token_ms == 840
    assert restored.fallback_reason == "batch_deadline_deterministic_legal_choice"


def test_action_log_from_dict_defaults_invalid_and_fallback_metadata() -> None:
    action_log = action_log_from_dict(
        {
            "actor": "1号玩家",
            "action": "witch_poison",
            "options": ["不使用毒药"],
            "choice": "不使用毒药",
            "lm_log": {
                "prompt": "prompt",
                "raw_response": "{}",
                "result": {"poison": "不使用毒药"},
            },
        }
    )

    assert action_log.invalid_value is None
    assert action_log.fallback_choice is None
    assert action_log.fallback_reason is None
    assert action_log.attempt_count == 1
    assert action_log.lm_log.invalid_attempts == []
    assert action_log.execution_status == "completed"
    assert action_log.duration_ms == 0
    assert action_log.budget_ms is None
    assert action_log.first_token_ms is None


def test_action_log_from_dict_restores_invalid_attempts_with_deep_copy() -> None:
    source = {
        "actor": "1号玩家",
        "action": "witch_poison",
        "options": ["6号玩家", "12号玩家", "不使用毒药"],
        "choice": "不使用毒药",
        "lm_log": {
            "prompt": "prompt",
            "raw_response": '{"poison":"10号玩家"}',
            "result": {"poison": "10号玩家"},
            "invalid_attempts": [
                {
                    "value": "10号玩家",
                    "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
                    "result_key": "poison",
                }
            ],
        },
    }

    action_log = action_log_from_dict(source)

    source["lm_log"]["invalid_attempts"][0]["value"] = "mutated"
    source["lm_log"]["invalid_attempts"][0]["allowed_values"].append("mutated")

    assert action_log.lm_log.invalid_attempts == [
        {
            "value": "10号玩家",
            "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
            "result_key": "poison",
        }
    ]


def _extract_options(prompt: str) -> list[str]:
    marker = next(
        (candidate for candidate in ("候选人：", "候选选项：") if candidate in prompt), ""
    )
    if not marker:
        return []
    tail = prompt.split(marker, 1)[1].split("。", 1)[0]
    return [option.strip() for option in tail.split("、") if option.strip()]
    return []
