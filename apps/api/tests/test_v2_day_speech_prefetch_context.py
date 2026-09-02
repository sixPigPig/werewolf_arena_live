from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.user import User  # noqa: F401 - registers the referenced users table
from app.match.day_speech_pipeline_contract import (
    freeze_day_speech_pipeline_contract,
    schema_v3_day_speech_pipeline_contract,
)
from app.match.match_repository import MatchRepository
from app.match.model_context_contract import freeze_model_context_contract
from app.match.model_generation_policy_contract import (
    freeze_model_generation_policy_contract,
)
from app.match.models import (
    GameRecord,
    GameRecordEvent,
    GameRun,
    LivePresentation,
    MatchState,
)
from app.match.repository import (
    ActionRepository,
    ExecutionOwnershipLost,
    GameCanceled,
    PresentationIdentity,
    RepositoryError,
)


GAME_ID = "v2_game_prefetch_context"
RUN_ID = "v2_run_prefetch_context"
PHASE_ID = "day_1"
PHASE_STATE = "public_discussion_open"


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@dataclass(frozen=True)
class _Scenario:
    session_factory: sessionmaker[Session]
    match_repository: MatchRepository
    action_repository: ActionRepository
    previous: PresentationIdentity
    predecessor_claim: Any
    predecessor: PresentationIdentity
    predecessor_source_event_id: int
    predecessor_source_record_seq: int
    cutoff: int

    def prefetch_args(self) -> dict[str, Any]:
        return {
            "game_id": GAME_ID,
            "run_id": RUN_ID,
            "phase_id": PHASE_ID,
            "phase_state": PHASE_STATE,
            "predecessor_presentation_id": self.predecessor.presentation_id,
            "predecessor_action_id": self.predecessor.action_id,
            "predecessor_source_event_id": self.predecessor_source_event_id,
        }


@pytest.fixture
def scenario(session_factory: sessionmaker[Session]) -> _Scenario:
    rule_snapshot: dict[str, Any] = {
        "rule_set": {"id": "prefetch-test", "sheriff_enabled": False},
        "max_rounds": 8,
    }
    rule_snapshot = freeze_model_context_contract(rule_snapshot)
    rule_snapshot = freeze_model_generation_policy_contract(rule_snapshot)
    rule_snapshot = freeze_day_speech_pipeline_contract(rule_snapshot)
    rule_snapshot["day_speech_pipeline_contract"] = schema_v3_day_speech_pipeline_contract()
    with session_factory.begin() as db:
        db.add(
            GameRecord(
                game_id=GAME_ID,
                title="prefetch context test",
                status="ready",
                current_run_id=RUN_ID,
                last_record_seq=0,
                last_presentation_seq=0,
                phase_seq=1,
                phase_id=PHASE_ID,
                phase_state=PHASE_STATE,
                rule_snapshot=rule_snapshot,
                players_snapshot=[],
                judge_voice_snapshot={},
                delivery_snapshot={"schema_version": 1, "mode": "tts"},
                ability_snapshot={"day_actions": [], "policies": {}, "day_policies": {}},
            )
        )
        db.add(
            GameRun(
                run_id=RUN_ID,
                game_id=GAME_ID,
                attempt_no=1,
                status="ready",
                fence_token=0,
            )
        )
        db.add(
            MatchState(
                game_id=GAME_ID,
                round_no=1,
                sheriff_badge_state="disabled",
            )
        )

    actions = ActionRepository(session_factory)
    previous_claim, previous = _open_player_presentation(
        actions,
        action_id="v2_action_previous",
        actor_id="player_1",
        presentation_id="v2_presentation_previous",
        speech_id="v2_speech_previous",
        speech="此前已关闭发言",
    )
    actions.commit_speech_decision(
        claim=previous_claim,
        identity=previous,
        next_live_state="ready",
        next_phase_state=PHASE_STATE,
    )
    actions.complete_text_action(
        identity=previous,
        next_live_state="ready",
        next_phase_state=PHASE_STATE,
    )
    predecessor_claim, predecessor = _open_player_presentation(
        actions,
        action_id="v2_action_predecessor",
        actor_id="player_2",
        presentation_id="v2_presentation_predecessor",
        speech_id="v2_speech_predecessor",
        speech="当前正在展示的完整发言",
    )

    # Deliberately separate durable event identity from record ordering. The
    # closed-only and prefetch histories must use record_seq as their cutoff
    # coordinate rather than assuming event_id == record_seq.
    durable_previous_source_event_id = 800
    durable_source_event_id = 900
    with session_factory.begin() as db:
        previous_presentation = db.get(
            LivePresentation,
            (GAME_ID, previous.presentation_seq),
        )
        assert previous_presentation is not None
        previous_source = db.get(
            GameRecordEvent,
            (GAME_ID, previous_presentation.source_event_id),
        )
        assert previous_source is not None
        previous_source.event_id = durable_previous_source_event_id
        previous_presentation.source_event_id = durable_previous_source_event_id
        presentation = db.get(
            LivePresentation,
            (GAME_ID, predecessor.presentation_seq),
        )
        assert presentation is not None
        source = db.get(
            GameRecordEvent,
            (GAME_ID, presentation.source_event_id),
        )
        assert source is not None
        source_record_seq = source.record_seq
        source.event_id = durable_source_event_id
        presentation.source_event_id = durable_source_event_id
        game = db.get(GameRecord, GAME_ID)
        assert game is not None
        cutoff = game.last_record_seq

    return _Scenario(
        session_factory=session_factory,
        match_repository=MatchRepository(session_factory),
        action_repository=actions,
        previous=previous,
        predecessor_claim=predecessor_claim,
        predecessor=predecessor,
        predecessor_source_event_id=durable_source_event_id,
        predecessor_source_record_seq=source_record_seq,
        cutoff=cutoff,
    )


def _action_context(*, action_id: str, actor_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": "day_debate_speech",
        "game_id": GAME_ID,
        "phase_id": PHASE_ID,
        "actor": {"kind": "player", "id": actor_id},
        "objective": "发表本轮白天讨论发言。",
        "output_contract": {"kind": "speech"},
    }


def _open_player_presentation(
    repository: ActionRepository,
    *,
    action_id: str,
    actor_id: str,
    presentation_id: str,
    speech_id: str,
    speech: str,
) -> tuple[Any, PresentationIdentity]:
    claim = repository.claim_action(
        game_id=GAME_ID,
        action_id=action_id,
        context=_action_context(action_id=action_id, actor_id=actor_id),
        expected_phase_id=PHASE_ID,
        expected_phase_state=PHASE_STATE,
        audience="all",
        context_audience="player_private",
    )
    assert claim is not None
    return claim, repository.open_presentation(
        claim=claim,
        presentation_id=presentation_id,
        speech_id=speech_id,
        voice_asset_id=None,
        subtitle_text=speech,
        sample_rate=24_000,
        actor_kind="player",
        actor_id=actor_id,
    )


def _public_speeches(snapshot: Any) -> list[str]:
    return [
        str(item["payload"]["speech"])
        for item in snapshot.public_history
        if item["event_type"] == "public_player_speech_presented"
    ]


def test_prefetch_snapshot_adds_active_predecessor_once_without_public_leak(
    scenario: _Scenario,
) -> None:
    ordinary_before = scenario.match_repository.snapshot(GAME_ID)
    assert _public_speeches(ordinary_before) == ["此前已关闭发言"]
    assert ordinary_before.audio_mode == "tts"
    assert ordinary_before.day_speech_pipeline_contract.status == "supported"
    assert ordinary_before.day_speech_pipeline_contract.mode == "one_ahead"

    frozen = scenario.match_repository.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())
    snapshot = frozen.match_snapshot
    assert frozen.public_cutoff_record_seq == scenario.cutoff
    assert snapshot.last_record_seq == frozen.public_cutoff_record_seq
    assert _public_speeches(snapshot) == [
        "此前已关闭发言",
        "当前正在展示的完整发言",
    ]
    active_items = [
        item
        for item in snapshot.public_history
        if item["source_event_id"] == scenario.predecessor_source_event_id
    ]
    assert len(active_items) == 1
    assert active_items[0]["record_seq"] == scenario.predecessor_source_record_seq
    assert active_items[0]["record_seq"] != active_items[0]["source_event_id"]
    assert frozen.predecessor_source_record_seq == scenario.predecessor_source_record_seq
    assert frozen.predecessor_sealed_record_seq <= frozen.public_cutoff_record_seq

    ordinary_after = scenario.match_repository.snapshot(GAME_ID)
    assert _public_speeches(ordinary_after) == ["此前已关闭发言"]


def test_snapshot_resolves_missing_pipeline_contract_as_legacy_sequential(
    scenario: _Scenario,
) -> None:
    with scenario.session_factory.begin() as db:
        game = db.get(GameRecord, GAME_ID)
        assert game is not None
        snapshot = dict(game.rule_snapshot)
        snapshot.pop("day_speech_pipeline_contract")
        game.rule_snapshot = snapshot

    ordinary = scenario.match_repository.snapshot(GAME_ID)
    contract = ordinary.day_speech_pipeline_contract
    assert contract.status == "legacy_sequential"
    assert contract.mode == "sequential"
    assert contract.max_lookahead == 0


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("run_id", "v2_run_wrong"),
        ("phase_id", "day_2"),
        ("phase_state", "day_vote_open"),
        ("predecessor_presentation_id", "v2_presentation_wrong"),
        ("predecessor_action_id", "v2_action_wrong"),
        ("predecessor_source_event_id", 901),
    ],
)
def test_prefetch_snapshot_rejects_wrong_lineage_or_phase(
    scenario: _Scenario,
    key: str,
    value: Any,
) -> None:
    arguments = scenario.prefetch_args()
    arguments[key] = value
    with pytest.raises(RepositoryError):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**arguments)


def test_prefetch_snapshot_rejects_wrong_game(scenario: _Scenario) -> None:
    arguments = scenario.prefetch_args()
    arguments["game_id"] = "v2_game_wrong"
    with pytest.raises(RepositoryError, match="unknown game"):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**arguments)


@pytest.mark.parametrize(
    ("field", "value"),
    [("actor_kind", "judge"), ("audience", "god_view")],
)
def test_prefetch_snapshot_rejects_non_public_player_predecessor(
    scenario: _Scenario,
    field: str,
    value: str,
) -> None:
    with scenario.session_factory.begin() as db:
        presentation = db.get(
            LivePresentation,
            (GAME_ID, scenario.predecessor.presentation_seq),
        )
        assert presentation is not None
        setattr(presentation, field, value)

    with pytest.raises(RepositoryError, match="identity is invalid"):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())


@pytest.mark.parametrize("corruption", ["event_type", "text", "audience"])
def test_prefetch_snapshot_rejects_invalid_source_event(
    scenario: _Scenario,
    corruption: str,
) -> None:
    with scenario.session_factory.begin() as db:
        source = db.get(
            GameRecordEvent,
            (GAME_ID, scenario.predecessor_source_event_id),
        )
        assert source is not None
        if corruption == "event_type":
            source.event_type = "speech_opened"
        else:
            payload = dict(source.payload)
            payload[corruption] = "wrong"
            source.payload = payload

    with pytest.raises(RepositoryError, match="source is invalid"):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())


def test_prefetch_snapshot_rejects_unsealed_predecessor(scenario: _Scenario) -> None:
    with scenario.session_factory.begin() as db:
        sealed = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == GAME_ID,
                GameRecordEvent.event_type == "speech_sealed",
                GameRecordEvent.payload["presentation_id"].as_string()
                == scenario.predecessor.presentation_id,
            )
        )
        assert sealed is not None
        db.delete(sealed)
        game = db.get(GameRecord, GAME_ID)
        assert game is not None
        game.last_record_seq = scenario.predecessor_source_record_seq

    with pytest.raises(RepositoryError, match="not sealed"):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())


def test_prefetch_snapshot_rejects_closed_predecessor(scenario: _Scenario) -> None:
    scenario.action_repository.complete_text_action(
        identity=scenario.predecessor,
        next_live_state="ready",
        next_phase_state=PHASE_STATE,
    )
    with pytest.raises(RepositoryError):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())


def test_prefetch_snapshot_accepts_active_technical_skip_judge_cue_without_fake_player_speech(
    scenario: _Scenario,
) -> None:
    scenario.action_repository.commit_speech_decision(
        claim=scenario.predecessor_claim,
        identity=scenario.predecessor,
        next_live_state="ready",
        next_phase_state=PHASE_STATE,
    )
    scenario.action_repository.complete_text_action(
        identity=scenario.predecessor,
        next_live_state="ready",
        next_phase_state=PHASE_STATE,
    )
    public_skip_record_seq = scenario.action_repository.append_event(
        game_id=GAME_ID,
        event_type="action_skipped_technical",
        audience="all",
        payload={
            "action_id": "v2_action_failed_player_2",
            "phase_id": PHASE_ID,
            "round_no": 1,
            "action_type": "day_debate_speech",
            "actor_id": "player_2",
            "player_seat": 2,
            "reason": "technical_failure",
        },
    )
    judge_action_id = "v2_action_judge_technical_skip"
    claim = scenario.action_repository.claim_action(
        game_id=GAME_ID,
        action_id=judge_action_id,
        context={
            "schema_version": 1,
            "action_id": judge_action_id,
            "action_type": "judge_day_speech_technical_skip",
            "game_id": GAME_ID,
            "phase_id": PHASE_ID,
            "actor": {"kind": "judge", "id": "judge"},
            "objective": "播报技术跳过提示",
            "output_contract": {"kind": "speech"},
            "round_no": 1,
            "skipped_player_id": "player_2",
            "speech_round": 1,
            "speech_order": ["player_1", "player_2", "player_3"],
            "public_skip_record_seq": public_skip_record_seq,
        },
        expected_phase_id=PHASE_ID,
        expected_phase_state=PHASE_STATE,
        audience="all",
        context_audience="god_view",
    )
    assert claim is not None
    judge = scenario.action_repository.open_presentation(
        claim=claim,
        presentation_id="v2_presentation_judge_technical_skip",
        speech_id="v2_speech_judge_technical_skip",
        voice_asset_id=None,
        subtitle_text="2号本轮因技术原因未能完成发言，流程继续",
        sample_rate=24_000,
        actor_kind="judge",
        actor_id="judge",
    )

    frozen = scenario.match_repository.snapshot_for_day_speech_prefetch(
        game_id=GAME_ID,
        run_id=RUN_ID,
        phase_id=PHASE_ID,
        phase_state=PHASE_STATE,
        predecessor_presentation_id=judge.presentation_id,
        predecessor_action_id=judge.action_id,
        predecessor_source_event_id=int(judge.source_event_id),
        predecessor_turn_player_id="player_2",
    )

    assert frozen.predecessor_actor_id == "player_2"
    technical = [
        item
        for item in frozen.match_snapshot.public_history
        if item["event_type"] == "action_skipped_technical"
    ]
    assert len(technical) == 1
    assert technical[0]["payload"]["actor_id"] == "player_2"
    assert all(
        item.get("payload", {}).get("player_id") != "judge"
        for item in frozen.match_snapshot.public_history
    )
    assert all(
        item["source_event_id"] != judge.source_event_id
        for item in frozen.match_snapshot.public_history
        if item["event_type"] == "public_player_speech_presented"
    )


def test_prefetch_snapshot_rejects_another_active_presentation(
    scenario: _Scenario,
) -> None:
    with scenario.session_factory.begin() as db:
        predecessor = db.get(
            LivePresentation,
            (GAME_ID, scenario.predecessor.presentation_seq),
        )
        game = db.get(GameRecord, GAME_ID)
        assert predecessor is not None and game is not None
        db.add(
            _copy_presentation(
                predecessor,
                presentation_seq=predecessor.presentation_seq + 1,
                presentation_id="v2_presentation_other_active",
                state="active",
            )
        )
        game.last_presentation_seq = predecessor.presentation_seq + 1

    with pytest.raises(RepositoryError, match="predecessor is not latest"):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())


def test_prefetch_snapshot_rejects_later_closed_presentation(
    scenario: _Scenario,
) -> None:
    with scenario.session_factory.begin() as db:
        predecessor = db.get(
            LivePresentation,
            (GAME_ID, scenario.predecessor.presentation_seq),
        )
        game = db.get(GameRecord, GAME_ID)
        assert predecessor is not None and game is not None
        db.add(
            _copy_presentation(
                predecessor,
                presentation_seq=predecessor.presentation_seq + 1,
                presentation_id="v2_presentation_future_closed",
                state="closed",
                closed_at=datetime.now(tz=UTC),
            )
        )
        game.last_presentation_seq = predecessor.presentation_seq + 1

    with pytest.raises(RepositoryError, match="not latest"):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())


def test_prefetch_snapshot_rejects_record_beyond_frozen_cutoff(
    scenario: _Scenario,
) -> None:
    with scenario.session_factory.begin() as db:
        db.add(
            GameRecordEvent(
                game_id=GAME_ID,
                event_id=901,
                record_seq=scenario.cutoff + 1,
                run_id=RUN_ID,
                event_type="tts_stream_started",
                payload_schema_version=1,
                payload={"audience": "all", "audience_contract_version": 1},
            )
        )

    with pytest.raises(RepositoryError, match="record cutoff is inconsistent"):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())


def test_prefetch_snapshot_enforces_execution_fence(scenario: _Scenario) -> None:
    guarded = MatchRepository(
        scenario.session_factory,
        enforce_execution_fence=True,
    )
    with pytest.raises(ExecutionOwnershipLost):
        guarded.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())


def test_prefetch_snapshot_honors_stop_request(scenario: _Scenario) -> None:
    with scenario.session_factory.begin() as db:
        run = db.get(GameRun, RUN_ID)
        assert run is not None
        run.stop_requested_at = datetime.now(tz=UTC)

    with pytest.raises(GameCanceled):
        scenario.match_repository.snapshot_for_day_speech_prefetch(**scenario.prefetch_args())


def _copy_presentation(
    source: LivePresentation,
    *,
    presentation_seq: int,
    presentation_id: str,
    state: str,
    closed_at: datetime | None = None,
) -> LivePresentation:
    return LivePresentation(
        game_id=source.game_id,
        presentation_seq=presentation_seq,
        presentation_id=presentation_id,
        action_id=source.action_id,
        activation_id=source.activation_id,
        run_id=source.run_id,
        phase_id=source.phase_id,
        actor_kind=source.actor_kind,
        actor_id=source.actor_id,
        audience=source.audience,
        speech_id=source.speech_id,
        segment_index=source.segment_index,
        source_event_id=source.source_event_id,
        state=state,
        subtitle_text=source.subtitle_text,
        subtitle_timings=list(source.subtitle_timings),
        voice_asset_id=source.voice_asset_id,
        audio_asset_id=source.audio_asset_id,
        audio_mime_type=source.audio_mime_type,
        audio_duration_ms=source.audio_duration_ms,
        closed_at=closed_at,
    )
