from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.v2.action_engine import V2ActionEngine, V2DecisionContract, V2SpeechSpec
from app.v2.control import _event_audience
from app.v2.event_contract import canonical_event_payload, model_event_audience
from app.v2.model_client import V2ModelDecision
from app.v2.model_context_contract import v9_model_context_contract
from app.v2.models import (
    V2AbilityActivation,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2LivePresentation,
    V2VoiceAsset,
)
from app.v2.repository import (
    V2ActionClaim,
    V2ActionRepository,
    _action_snapshot_audience,
    _activation_audience,
)
from app.v2.router import _admin_model_requests


@pytest.mark.parametrize(
    "audience",
    ["all", "public", "god_view", "director", "player_private"],
)
def test_canonical_event_payload_accepts_runtime_and_action_audiences(
    audience: str,
) -> None:
    assert canonical_event_payload({"value": 1}, audience=audience) == {
        "value": 1,
        "audience": audience,
        "audience_contract_version": 1,
    }


@pytest.mark.parametrize("audience", ["", " public ", "spectator_god_view"])
def test_canonical_event_payload_rejects_noncanonical_audience(audience: str) -> None:
    with pytest.raises(ValueError):
        canonical_event_payload({}, audience=audience)


@pytest.mark.parametrize(
    ("action_audience", "actor_kind", "expected"),
    [
        ("all", "player", "player_private"),
        ("public", "player", "player_private"),
        ("all", "judge", "director"),
        ("public", "system", "director"),
        ("god_view", "player", "god_view"),
        ("director", "judge", "director"),
        ("player_private", "player", "player_private"),
    ],
)
def test_model_event_audience_uses_the_narrowest_existing_canonical_scope(
    action_audience: str,
    actor_kind: str,
    expected: str,
) -> None:
    assert (
        model_event_audience(
            action_audience=action_audience,
            actor_kind=actor_kind,
        )
        == expected
    )


def test_legacy_followup_events_fail_closed_without_blocking_operator_paths() -> None:
    event = V2GameRecordEvent(payload={})
    activation = V2AbilityActivation(
        activation_id="v2_activation_legacy01",
        game_id="v2_game_legacyaudience",
        action_id="v2_action_legacyaudience",
    )
    db = MagicMock()
    db.scalar.return_value = None

    assert _event_audience(event) == "god_view"
    assert _action_snapshot_audience({}) == "god_view"
    assert _activation_audience(db, activation) == "god_view"


@pytest.mark.parametrize(
    (
        "event_audience",
        "context_audience",
        "presentation_audience",
        "event_contract_version",
        "expected",
    ),
    [
        ("all", "all", "all", 1, "player_private"),
        ("player_private", "all", "all", 1, "player_private"),
        ("all", "public", "god_view", None, "god_view"),
        ("director", "god_view", None, None, "director"),
        (None, "god_view", None, None, "god_view"),
        (None, None, "public", None, "public"),
        (" public ", "god_view", None, None, "god_view"),
        (None, None, None, None, "legacy_unknown"),
    ],
)
def test_admin_model_request_audience_recovers_then_fails_closed(
    event_audience: str | None,
    context_audience: str | None,
    presentation_audience: str | None,
    event_contract_version: int | None,
    expected: str,
) -> None:
    action_id = "v2_action_legacy_audience"
    context = {
        "phase_id": "first_night",
        "action_type": "werewolf_private_decision",
        "actor": {"kind": "player", "id": "seat_1"},
    }
    if context_audience is not None:
        context["audience"] = context_audience
    start_payload = {
        "attempt_id": "v2_attempt_legacy_audience",
        "action_id": action_id,
        "actor_kind": "player",
        "actor_id": "seat_1",
        "request_kind": "decision",
        "request_payload": {},
    }
    if event_audience is not None:
        start_payload["audience"] = event_audience
    if event_contract_version is not None:
        start_payload["audience_contract_version"] = event_contract_version
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    events = [
        SimpleNamespace(
            event_type="action_opened",
            record_seq=1,
            run_id="v2_run_legacy_audience",
            created_at=now,
            payload={"action_id": action_id, "context": context},
        ),
        SimpleNamespace(
            event_type="model_request_started",
            record_seq=2,
            run_id="v2_run_legacy_audience",
            created_at=now,
            payload=start_payload,
        ),
    ]
    presentations = (
        [
            SimpleNamespace(
                action_id=action_id,
                audience=presentation_audience,
                subtitle_text="legacy presentation",
                created_at=now,
            )
        ]
        if presentation_audience is not None
        else []
    )

    result = _admin_model_requests(events, presentations)

    assert len(result) == 1
    assert result[0].audience == expected


def test_presentation_lifecycle_inherits_claim_audience_and_closes_text_durably() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            V2GameRecord.__table__,
            V2GameRun.__table__,
            V2GameRecordEvent.__table__,
            V2VoiceAsset.__table__,
            V2LivePresentation.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    game_id = "v2_game_audience001"
    run_id = "v2_run_audience0001"
    with Session(engine) as db:
        db.add(
            V2GameRecord(
                game_id=game_id,
                title="audience contract",
                status="generating",
                current_run_id=run_id,
                record_schema_version=1,
                last_record_seq=0,
                last_presentation_seq=0,
                phase_seq=1,
                phase_id="first_night",
                phase_state="night_running",
                rule_snapshot={},
                players_snapshot=[],
                judge_voice_snapshot={},
                delivery_snapshot={"schema_version": 1, "mode": "text_only"},
                ability_snapshot={},
            )
        )
        db.add(
            V2GameRun(
                run_id=run_id,
                game_id=game_id,
                attempt_no=1,
                status="generating",
                fence_token=0,
            )
        )
        db.commit()

    repository = V2ActionRepository(factory)
    claim = V2ActionClaim(
        game_id=game_id,
        run_id=run_id,
        action_id="v2_action_audience01",
        phase_id="first_night",
        audience="god_view",
        audio_mode="text_only",
    )
    identity = repository.open_presentation(
        claim=claim,
        presentation_id="v2_pres_audience001",
        speech_id="v2_speech_audience01",
        voice_asset_id=None,
        subtitle_text="仅定向可见。",
        sample_rate=24_000,
        actor_kind="player",
        actor_id="seat_1",
    )
    repository.complete_text_action(
        identity=identity,
        next_live_state="ready",
        next_phase_state="night_running",
    )

    with Session(engine) as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == game_id)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        presentation = db.get(V2LivePresentation, (game_id, 1))

    assert identity.audience == "god_view"
    assert presentation is not None
    assert presentation.audience == "god_view"
    assert presentation.state == "closed"
    assert [event.event_type for event in events] == [
        "speech_opened",
        "speech_segment_committed",
        "speech_sealed",
        "speech_closed",
        "action_succeeded",
    ]
    assert all(event.payload["audience"] == "god_view" for event in events)
    assert all(event.payload["audience_contract_version"] == 1 for event in events)
    assert all(
        event.payload["presentation_id"] == identity.presentation_id
        for event in events
        if event.event_type.startswith("speech_")
    )


def test_private_tts_failure_keeps_presentation_failure_off_public_audience(tmp_path) -> None:
    class FailingTtsClient:
        enabled = True

        async def synthesize(self, **_kwargs):
            if False:
                yield b""
            raise RuntimeError("scripted private TTS failure")

    class RecordingBroadcaster:
        def __init__(self) -> None:
            self.messages: list[tuple[str, dict[str, object]]] = []
            self.currents: list[tuple[str, object | None]] = []

        async def broadcast_json(
            self,
            value: dict[str, object],
            *,
            audience: str = "all",
        ) -> None:
            self.messages.append((audience, value))

        async def set_current(
            self,
            identity: object | None,
            _sample_cursor: int,
            *,
            audience: str = "all",
        ) -> None:
            self.currents.append((audience, identity))

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            V2GameRecord.__table__,
            V2GameRun.__table__,
            V2GameRecordEvent.__table__,
            V2VoiceAsset.__table__,
            V2LivePresentation.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    game_id = "v2_game_privatefailure"
    run_id = "v2_run_privatefailure"
    with Session(engine) as db:
        db.add(
            V2GameRecord(
                game_id=game_id,
                title="private TTS failure",
                status="ready",
                current_run_id=run_id,
                record_schema_version=1,
                last_record_seq=0,
                last_presentation_seq=0,
                phase_seq=1,
                phase_id="first_night",
                phase_state="night_running",
                rule_snapshot={"model_context_contract": v9_model_context_contract()},
                players_snapshot=[],
                judge_voice_snapshot={},
                delivery_snapshot={"schema_version": 1, "mode": "tts"},
                ability_snapshot={},
            )
        )
        db.add(
            V2GameRun(
                run_id=run_id,
                game_id=game_id,
                attempt_no=1,
                status="ready",
                fence_token=0,
            )
        )
        db.commit()

    repository = V2ActionRepository(factory)
    action_engine = V2ActionEngine(
        repository=repository,
        model_client=MagicMock(),
        tts_client=FailingTtsClient(),
        tts_client_factory=None,
        tts_capability_enabled=True,
        voice_root=tmp_path / "voices",
        sample_rate=24_000,
        judge_configuration_provider=MagicMock(),
    )
    broadcaster = RecordingBroadcaster()
    decision = V2ModelDecision(
        target_player_id=None,
        speech="这是狼人私聊发言。",
        provider_request_id="precomputed-private",
        first_token_ms=1,
        completed_ms=2,
    )
    result = asyncio.run(
        action_engine.present_player_decision(
            game_id=game_id,
            broadcaster=broadcaster,  # type: ignore[arg-type]
            spec=V2SpeechSpec(
                action_type="werewolf_private_discussion",
                phase_id="first_night",
                required_phase_state="night_running",
                objective="在狼人私聊中讨论刀口",
                success_live_state="awaiting_observation",
                success_phase_state="night_running",
                actor_kind="player",
                actor_id="seat_1",
                audience="god_view",
                output_kind="private_speech",
                decision_contract=V2DecisionContract(kind="speech"),
            ),
            decision=decision,
        )
    )

    assert result is False
    failure_messages = [
        (audience, value)
        for audience, value in broadcaster.messages
        if value.get("type") == "presentation.failed"
    ]
    assert len(failure_messages) == 1, broadcaster.messages
    assert failure_messages[0][0] == "god_view"
    assert all(audience not in {"all", "public"} for audience, _value in failure_messages)
    assert broadcaster.currents[-1] == ("god_view", None)
