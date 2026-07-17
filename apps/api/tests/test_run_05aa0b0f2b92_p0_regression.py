import json
import time
from pathlib import Path

import pytest

from app.werewolf.config import SEER, VILLAGER, WEREWOLF
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.live import LiveEvent
from app.werewolf.lm import FakeProvider
from app.werewolf.models import RoundLog, RoundState, StageInterruption
from app.werewolf.prompts_zh import build_prompt
from app.werewolf.replay_playback import (
    build_public_game_session,
    build_replay_playback,
    filter_public_playback_events,
    filter_public_playback_voices,
    private_round_memory_event_ids,
)
from app.werewolf.rules import ACTION_DEBATE, get_rule_set
from app.werewolf.voice import VoiceSpeakerConfig, event_to_voice_utterance


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "run_05aa0b0f2b92_p0_regression.json"
MODEL_EVENT_TYPES = {
    "action_requested",
    "model_request_started",
    "model_thinking_tick",
    "model_thinking_delta",
    "model_response_delta",
    "model_response_received",
    "action_parsed",
}


class TimedEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append(
            {
                "type": event_type,
                "_at_ns": time.perf_counter_ns(),
                **kwargs,
            }
        )


def test_run_05aa0b0f2b92_p0_fixture_full_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    rule_set = get_rule_set(fixture["rule_set_id"])
    state = initialize_game_state(
        session_id=fixture["source_session_id"],
        villager_model="fixture-model",
        werewolf_model="fixture-model",
        seed=20260714,
        rule_set=rule_set,
    )
    terminal = fixture["terminal"]
    players_by_name = state.player_by_name()
    role_by_name = terminal["roles"]
    for name, role in role_by_name.items():
        players_by_name[name].role = role
    assert players_by_name["5号玩家"].role == SEER
    assert players_by_name["10号玩家"].role == VILLAGER
    assert players_by_name["11号玩家"].role == WEREWOLF

    active_players = list(terminal["active_before"])
    for player in state.players:
        if player.gamestate is not None:
            player.gamestate.current_players = active_players.copy()

    sink = TimedEventSink()
    sentinel = fixture["privacy"]["sentinel"]
    provider = FakeProvider([{"reasoning": "留下公开判断。", "say": "请继续复盘票型。"}])
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    critical_fact = fixture["critical_fact"]
    engine._add_public_fact(
        critical_fact["round_number"],
        critical_fact["category"],
        critical_fact["text"],
        stage=critical_fact["stage"],
        actor=critical_fact["actor"],
        retention=critical_fact["retention"],
    )
    interruption_data = fixture["interruption"]
    interruption = StageInterruption(
        stage=interruption_data["stage"],
        interrupted_by=interruption_data["interrupted_by"],
        actor=interruption_data["actor"],
        timing=interruption_data["timing"],
        last_completed_speaker=interruption_data["last_completed_speaker"],
        completed_actors=list(interruption_data["completed_actors"]),
        pending_actors=list(interruption_data["pending_actors"]),
    )
    state.rounds.append(
        RoundState(
            number=interruption_data["round_number"],
            players=active_players.copy(),
            interruption=interruption,
        )
    )

    round_state = RoundState(
        number=critical_fact["expected_prompt_round"],
        players=active_players.copy(),
    )
    state.rounds.append(round_state)
    world_state = engine._world_state(
        players_by_name[critical_fact["actor"]],
        [],
        round_state,
    )
    prompt, _schema = build_prompt(ACTION_DEBATE, world_state)

    acceptance = fixture["acceptance"]
    assert prompt.count(critical_fact["text"]) >= acceptance[
        "critical_fact_prompt_occurrences_min"
    ]
    assert critical_fact["text"] in world_state["public_self_history"]
    for name in interruption_data["completed_actors"]:
        assert name in prompt
    for name in interruption_data["pending_actors"]:
        assert name in prompt
    assert "尚未获得发言机会" in prompt
    assert "不能将其视为主动沉默" in prompt

    round_log = RoundLog(number=round_state.number)
    monkeypatch.setattr(engine, "_run_sheriff_election_if_needed", lambda *_: False)
    monkeypatch.setattr(engine, "_run_debate_phase", lambda *_: False)
    monkeypatch.setattr(
        engine,
        "_run_voting",
        lambda *_: (dict(terminal["votes"]), []),
    )

    engine._run_day_phase(round_state, round_log, active_players)
    sink.publish("game_completed", payload={"winner": state.winner})

    assert round_state.exiled == terminal["exiled"]
    assert active_players == terminal["active_after"]
    assert state.winner == terminal["winner"]
    assert provider.calls == 0
    assert round_state.exile_last_words is None
    assert round_log.summaries == []
    assert round_state.private_summaries == {}

    decisive_index = next(
        index
        for index, event in enumerate(sink.events)
        if event["type"] == "state_updated"
        and event.get("phase") == "vote"
        and (event.get("payload") or {}).get("exiled") == terminal["exiled"]
    )
    completed_index = next(
        index for index, event in enumerate(sink.events) if event["type"] == "game_completed"
    )
    intervening_model_events = sum(
        event["type"] in MODEL_EVENT_TYPES
        for event in sink.events[decisive_index + 1 : completed_index]
    )
    terminal_latency_ms = (
        int(sink.events[completed_index]["_at_ns"])
        - int(sink.events[decisive_index]["_at_ns"])
    ) / 1_000_000
    intervening_actions = {
        event.get("action")
        for event in sink.events[decisive_index + 1 : completed_index]
        if event["type"] in MODEL_EVENT_TYPES
    }
    assert intervening_model_events == acceptance["post_terminal_model_events"]
    assert intervening_actions == set()
    assert terminal_latency_ms < acceptance["terminal_publish_latency_ms_max"]

    raw_state = state.to_dict()
    raw_state["rounds"][-1]["private_summaries"] = {"11号玩家": sentinel}
    raw_session = {
        "session_id": fixture["source_session_id"],
        "status": "complete",
        "state": raw_state,
        "logs": [
            {
                "number": round_state.number,
                "summaries": [
                    {
                        "actor": "11号玩家",
                        "action": "summarize",
                        "choice": sentinel,
                        "lm_log": {"raw_response": sentinel},
                    }
                ],
            }
        ],
    }
    public_game = build_public_game_session(raw_session)
    playback = build_replay_playback(raw_session)

    legacy_event_payload = fixture["privacy"]["legacy_event"]
    legacy_event = LiveEvent(**legacy_event_payload)
    private_event_ids = private_round_memory_event_ids([legacy_event.to_dict()])
    public_historical_events = filter_public_playback_events([legacy_event.to_dict()])
    public_historical_voices = filter_public_playback_voices(
        [
            {
                "source_event_id": legacy_event.id,
                "last_source_event_id": legacy_event.id,
                "text": sentinel,
            }
        ],
        private_event_ids=private_event_ids,
    )
    legacy_voice = event_to_voice_utterance(
        legacy_event,
        VoiceSpeakerConfig(player_speaker="fixture-player", judge_speaker="fixture-judge"),
    )

    assert public_historical_events == []
    assert public_historical_voices == []
    assert legacy_voice is None
    public_serializations = json.dumps(
        {
            "live": sink.events,
            "game": public_game,
            "playback": playback,
            "historical_events": public_historical_events,
            "historical_voices": public_historical_voices,
        },
        ensure_ascii=False,
    )
    assert public_serializations.count(sentinel) == acceptance[
        "private_sentinel_public_occurrences"
    ]
    assert all(event.get("action") != "summarize" for event in playback["events"])
