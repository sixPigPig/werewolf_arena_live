from dataclasses import replace

import pytest

from app.werewolf.checkpoint import round_state_from_dict
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.lm import FakeProvider
from app.werewolf.models import DeathEvent, PublicOutcomeEventV1, RoundState
from app.werewolf.public_outcomes import (
    append_public_outcome,
    conservative_legacy_outcomes,
    render_public_round_summary,
)
from app.werewolf.rules import get_rule_set


class CapturingEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append({"type": event_type, **kwargs})


def test_public_outcome_summary_preserves_cause_order_without_duplicate_players() -> None:
    round_state = RoundState(number=1, players=[])
    night_death = append_public_outcome(
        round_state=round_state,
        session_id="game_123",
        kind="night_death",
        actor_player_id=None,
        target_player_id="4号玩家",
        outcome="eliminated",
        occurred_phase="night",
    )
    append_public_outcome(
        round_state=round_state,
        session_id="game_123",
        kind="hunter_shot",
        actor_player_id="4号玩家",
        target_player_id="3号玩家",
        outcome="eliminated",
        occurred_phase="night",
        caused_by_event_id=night_death.event_id,
    )

    summary = render_public_round_summary(round_state.public_outcome_events)

    assert summary == "4号玩家夜间出局，随后发动猎人技能，带走3号玩家。"
    assert summary.count("4号玩家") == 1
    assert summary.count("3号玩家") == 1


def test_public_outcome_summary_rejects_duplicate_event_ids() -> None:
    event = PublicOutcomeEventV1(
        schema_version=1,
        event_id="outcome_duplicate",
        sequence=1,
        kind="exile",
        actor_player_id=None,
        target_player_id="2号玩家",
        outcome="eliminated",
        caused_by_event_id=None,
        occurred_phase="vote",
    )

    with pytest.raises(ValueError, match="duplicate public outcome event id"):
        render_public_round_summary([event, replace(event, sequence=2)])


def test_public_outcome_sequence_continues_after_checkpoint_restore() -> None:
    source = RoundState(number=2, players=["1号玩家", "2号玩家"])
    append_public_outcome(
        round_state=source,
        session_id="game_restore",
        kind="exile",
        actor_player_id=None,
        target_player_id="2号玩家",
        outcome="eliminated",
        occurred_phase="vote",
    )

    restored = round_state_from_dict(source.to_dict())
    appended = append_public_outcome(
        round_state=restored,
        session_id="game_restore",
        kind="badge_lost",
        actor_player_id="2号玩家",
        target_player_id=None,
        outcome="destroyed",
        occurred_phase="vote",
        caused_by_event_id=restored.public_outcome_events[0].event_id,
    )

    assert [event.sequence for event in restored.public_outcome_events] == [1, 2]
    assert appended.event_id != restored.public_outcome_events[0].event_id
    assert restored.public_outcome_next_sequence == 3


def test_legacy_outcome_projection_does_not_infer_hidden_death_causes() -> None:
    events = conservative_legacy_outcomes(
        {
            "number": 3,
            "night_deaths": [
                {
                    "player": "4号玩家",
                    "cause": "SENTINEL_PRIVATE_CAUSE",
                    "source": "SENTINEL_PRIVATE_SOURCE",
                }
            ],
        }
    )

    assert len(events) == 1
    assert events[0].kind == "night_death"
    assert events[0].target_player_id == "4号玩家"
    assert "SENTINEL_PRIVATE" not in str(events[0].to_dict())


def test_rule_result_live_payload_judge_cue_and_summary_share_public_event() -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="game_public_outcome_integration",
        villager_model="model",
        werewolf_model="model",
        seed=71,
        rule_set=rule_set,
    )
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=FakeProvider([]),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    engine._record_night_deaths(
        [
            DeathEvent(
                active_players[1],
                "SENTINEL_PRIVATE_CAUSE",
                "SENTINEL_PRIVATE_SOURCE",
            )
        ],
        round_state,
        active_players,
    )
    engine._publish_state_updated(
        round_state=round_state,
        phase="night",
        action="night_resolved",
    )
    engine._publish_dawn_result(round_state)

    outcome = round_state.public_outcome_events[0]
    state_event = next(event for event in sink.events if event["type"] == "state_updated")
    judge_event = next(event for event in sink.events if event["type"] == "judge_cue")
    assert outcome.target_player_id == "2号玩家"
    assert state_event["payload"]["public_outcome_events"] == [outcome.to_dict()]
    assert "2号玩家" in str(judge_event["payload"])
    assert "2号玩家夜间出局" in engine._public_round_brief(round_state)
    assert "SENTINEL_PRIVATE" not in str(sink.events)
