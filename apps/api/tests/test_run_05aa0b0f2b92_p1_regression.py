from __future__ import annotations

import json
from pathlib import Path

from app.werewolf.config import WEREWOLF
from app.werewolf.engine import GameEngine, PublicStageCursor, initialize_game_state
from app.werewolf.judge_narration import dawn_result_cue, self_explosion_cues
from app.werewolf.lm import FakeProvider
from app.werewolf.models import RoundState
from app.werewolf.prompts_zh import build_prompt
from app.werewolf.replay_playback import build_replay_playback
from app.werewolf.rules import get_rule_set
from app.werewolf.voice_stream import (
    build_static_judge_playback_voices,
    build_voice_playback_coverage,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "run_05aa0b0f2b92_p1_regression.json"
)


def test_run_05aa0b0f2b92_p1_self_explosion_context_and_prompt() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    decision = fixture["self_explosion_decision"]
    rule_set = get_rule_set(fixture["rule_set_id"])
    state = initialize_game_state(
        session_id=fixture["source_session_id"],
        villager_model="fixture-model",
        werewolf_model="fixture-model",
        seed=20260714,
        rule_set=rule_set,
    )
    actor = decision["actor"]
    players = state.player_by_name()
    players[actor].role = WEREWOLF
    active_players = list(decision["active_players"])
    for player in state.players:
        if player.name != actor and player.name in active_players:
            player.role = "村民"
        if player.gamestate is not None:
            player.gamestate.current_players = active_players.copy()

    prior_rounds = [
        RoundState(
            number=item["round"],
            players=active_players.copy(),
            werewolf_self_exploded=item["player"],
        )
        for item in decision["prior_explosions"]
    ]
    current = RoundState(number=decision["round_number"], players=active_players.copy())
    state.rounds = [*prior_rounds, current]
    engine = GameEngine(
        state=state,
        provider=FakeProvider([]),
        max_rounds=8,
        rule_set=rule_set,
    )
    cursor = PublicStageCursor(
        stage=decision["stage"],
        ordered_actors=tuple(
            [*decision["completed_actors"], *decision["pending_actors"]]
        ),
        completed_actors=tuple(decision["completed_actors"]),
        current_actor=actor,
        timing="before_actor",
    )

    context = engine._self_explosion_decision_context(
        actor=actor,
        round_state=current,
        active_players=active_players,
        active_wolves=list(decision["active_wolves"]),
        cursor=cursor,
    )
    prompt, schema = build_prompt(
        "werewolf_self_explosion",
        {
            **engine._world_state(players[actor], [], current),
            "options": "自爆、不自爆",
            "self_explosion_stage": "警上发言前",
            "self_explosion_decision_context": context.to_dict(),
        },
    )

    for field, expected in decision["expected"].items():
        assert getattr(context, field) == expected
    assert "连续自爆轮数：2" in prompt
    assert "默认选择不自爆" not in prompt
    assert "依据当前可见规则和事实自行判断" in prompt
    assert "最后一名狼人" in prompt
    assert {"benefit_type", "expected_gain", "primary_risk"} <= set(
        schema["required"]
    )


def test_run_05aa0b0f2b92_p1_narration_privacy_and_terminal_voice() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    narration = fixture["narration"]
    assert [dawn_result_cue([]).cue_id] == narration["peaceful_night"]
    explosion_cues = self_explosion_cues(
        "9号玩家",
        stage="sheriff_speech",
        completed_actors=["4号玩家", "3号玩家", "12号玩家", "11号玩家", "10号玩家"],
        pending_actors=["9号玩家", "5号玩家"],
    )
    assert [cue.cue_id for cue in explosion_cues] == narration["self_explosion"]

    session = {
        "session_id": fixture["source_session_id"],
        "status": "complete",
        "state": {
            "session_id": fixture["source_session_id"],
            "winner": "狼人阵营",
            "players": [
                {"name": f"{seat}号玩家", "role": "村民", "model": "fixture"}
                for seat in range(1, 13)
            ],
            "rounds": [
                {
                    "number": 4,
                    "players": ["5号玩家", "10号玩家", "11号玩家", "12号玩家"],
                    "night_deaths": [],
                    "debate": [],
                    "bids": [],
                    "votes": {"5号玩家": "11号玩家"},
                    "exiled": "5号玩家",
                    "day_deaths": [
                        {"player": "5号玩家", "cause": "vote", "source": None}
                    ],
                }
            ],
        },
        "logs": [{"number": 4}],
    }
    playback = build_replay_playback(session)
    cue_events = [event for event in playback["events"] if event["type"] == "judge_cue"]
    cue_text = json.dumps([event["payload"] for event in cue_events], ensure_ascii=False)
    for forbidden in narration["forbidden_public_cue_terms"]:
        assert forbidden not in cue_text

    terminal_events = [
        event
        for event in playback["events"]
        if event["action"] == "exile_result" or event["type"] == "game_completed"
    ]
    assert [
        event["action"] if event["type"] == "judge_cue" else event["type"]
        for event in terminal_events
    ] == narration["terminal_tail"]
    static_voices = build_static_judge_playback_voices(playback["events"])
    coverage = build_voice_playback_coverage(playback["events"], static_voices)
    terminal_voice_ids = {
        voice["source_event_id"]
        for voice in static_voices
        if voice["source_event_id"] in {event["id"] for event in terminal_events}
    }
    assert terminal_voice_ids == {event["id"] for event in terminal_events}
    assert coverage["terminal_judge_voice_present"] is fixture["voice_coverage"][
        "terminal_judge_voice_present"
    ]
