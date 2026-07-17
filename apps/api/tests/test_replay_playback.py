from app.werewolf.replay_playback import (
    build_public_game_session,
    build_replay_playback,
)


def test_public_game_session_drops_unsafe_state_and_round_public_facts() -> None:
    safe_fact = {
        "round_number": 1,
        "category": "claim",
        "trust_class": "player_claim",
        "text": "5号玩家声称自己是预言家。",
        "extra_private_field": "SENTINEL_EXTRA_FIELD",
        "details": {"secret": "SENTINEL_UNKNOWN_PRIVATE_FIELD"},
    }
    unsafe_facts = [
        {
            "round_number": 1,
            "category": "private_observation",
            "trust_class": "engine_fact",
            "text": "SENTINEL_PRIVATE_OBSERVATION",
        },
        {
            "round_number": 1,
            "category": "future_category",
            "trust_class": "engine_fact",
            "text": "SENTINEL_UNKNOWN_CATEGORY",
        },
        {
            "round_number": 1,
            "category": "claim",
            "trust_class": "player_claim",
            "text": "SENTINEL_PRIVATE_DETAILS",
            "details": {"reasoning": "SENTINEL_REASONING"},
        },
    ]
    session = build_public_game_session(
        {
            "session_id": "game-public-fact-projection",
            "status": "partial",
            "state": {
                "session_id": "game-public-fact-projection",
                "players": [],
                "public_facts": [safe_fact, *unsafe_facts],
                "rounds": [
                    {
                        "number": 1,
                        "players": [],
                        "public_facts": [safe_fact, *unsafe_facts],
                    }
                ],
            },
        }
    )

    state_facts = session["state"]["public_facts"]
    round_facts = session["state"]["rounds"][0]["public_facts"]
    assert [fact["text"] for fact in state_facts] == [safe_fact["text"]]
    assert round_facts == state_facts
    assert state_facts[0]["trust_class"] == "player_claim"
    assert state_facts[0]["details"] == {}
    assert "SENTINEL" not in str(session)


def test_legacy_round_with_votes_and_no_exile_gets_an_explanatory_judge_cue() -> None:
    playback = build_replay_playback(
        {
            "session_id": "game_legacy_no_exile",
            "status": "complete",
            "state": {
                "session_id": "game_legacy_no_exile",
                "players": [
                    {"name": "Alice", "role": "村民", "model": "model"},
                    {"name": "Bob", "role": "狼人", "model": "model"},
                    {"name": "Cora", "role": "村民", "model": "model"},
                ],
                "rounds": [
                    {
                        "number": 1,
                        "players": ["Alice", "Bob", "Cora"],
                        "night_deaths": [],
                        "day_deaths": [],
                        "votes": [{"Alice": "Bob", "Bob": "Alice"}],
                        "exiled": None,
                    }
                ],
                "winner": "好人阵营",
            },
            "logs": [],
        }
    )

    cue = next(
        event
        for event in playback["events"]
        if event["type"] == "judge_cue" and event["action"] == "exile_no_result"
    )

    assert cue["payload"]["visible_text"] == "放逐投票未产生出局玩家，本轮无人被放逐。"
    assert cue["payload"]["params"] == {
        "reason_code": "legacy_no_result",
        "legacy_synthesized": True,
    }


def test_replay_keeps_exile_last_words_before_hunter_settlement() -> None:
    def action_log(actor: str, action: str, key: str, choice: str) -> dict:
        return {
            "actor": actor,
            "action": action,
            "options": [],
            "choice": choice,
            "lm_log": {
                "prompt": "prompt",
                "raw_response": "{}",
                "result": {key: choice},
            },
        }

    playback = build_replay_playback(
        {
            "session_id": "game_last_words_hunter",
            "status": "complete",
            "state": {
                "session_id": "game_last_words_hunter",
                "players": [
                    {"name": "1号玩家", "role": "猎人", "model": "model"},
                    {"name": "2号玩家", "role": "狼人", "model": "model"},
                    {"name": "3号玩家", "role": "村民", "model": "model"},
                ],
                "rounds": [
                    {
                        "number": 1,
                        "players": ["1号玩家", "2号玩家", "3号玩家"],
                        "night_deaths": [],
                        "day_deaths": [
                            {"player": "1号玩家", "cause": "vote_exile"},
                            {"player": "2号玩家", "cause": "hunter_shot"},
                        ],
                        "votes": [{"2号玩家": "1号玩家", "3号玩家": "1号玩家"}],
                        "exiled": "1号玩家",
                        "exile_last_words": {
                            "player": "1号玩家",
                            "message": "请继续复盘票型。",
                            "status": "completed",
                            "reason_code": "completed",
                        },
                        "hunter_shot": "2号玩家",
                    }
                ],
                "winner": "好人阵营",
            },
            "logs": [
                {
                    "number": 1,
                    "exile_last_words": action_log(
                        "1号玩家", "exile_last_words", "say", "请继续复盘票型。"
                    ),
                    "hunter_shoot": action_log(
                        "1号玩家", "hunter_shoot", "shoot", "2号玩家"
                    ),
                }
            ],
        }
    )

    events = playback["events"]
    exile_result_index = next(
        index for index, event in enumerate(events) if event.get("action") == "exile_result"
    )
    last_words_cue_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "judge_cue" and event.get("action") == "exile_last_words"
    )
    last_words_action_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "action_parsed" and event.get("action") == "exile_last_words"
    )
    hunter_start_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "judge_cue" and event.get("action") == "hunter_shot_start"
    )

    assert exile_result_index < last_words_cue_index < last_words_action_index < hunter_start_index
    assert events[-1]["type"] == "game_completed"
    assert events[-1]["payload"] == {"winner": "好人阵营"}


def test_new_terminal_round_without_attached_actions_ends_at_game_completed() -> None:
    playback = build_replay_playback(
        {
            "session_id": "game_terminal_without_attachments",
            "status": "complete",
            "state": {
                "session_id": "game_terminal_without_attachments",
                "players": [
                    {"name": "1号玩家", "role": "狼人", "model": "model"},
                    {"name": "2号玩家", "role": "村民", "model": "model"},
                ],
                "rounds": [
                    {
                        "number": 1,
                        "players": ["1号玩家", "2号玩家"],
                        "night_deaths": [],
                        "day_deaths": [
                            {"player": "2号玩家", "cause": "vote_exile"},
                        ],
                        "votes": [{"1号玩家": "2号玩家"}],
                        "exiled": "2号玩家",
                    }
                ],
                "winner": "狼人阵营",
            },
            "logs": [{"number": 1}],
        }
    )

    events = playback["events"]
    assert not any(
        event.get("action") in {"exile_last_words", "sheriff_badge"}
        for event in events
    )
    assert [event["type"] for event in events].count("game_completed") == 1
    assert events[-1]["type"] == "game_completed"
    assert events[-1]["payload"] == {"winner": "狼人阵营"}


def test_non_terminal_exile_last_words_remain_before_the_next_round() -> None:
    last_words_log = {
        "actor": "3号玩家",
        "action": "exile_last_words",
        "options": [],
        "choice": "我会留下最后的票型判断。",
        "lm_log": {
            "prompt": "prompt",
            "raw_response": "{}",
            "result": {"say": "我会留下最后的票型判断。"},
        },
    }
    playback = build_replay_playback(
        {
            "session_id": "game_non_terminal_last_words",
            "status": "complete",
            "state": {
                "session_id": "game_non_terminal_last_words",
                "players": [
                    {"name": "1号玩家", "role": "村民", "model": "model"},
                    {"name": "2号玩家", "role": "狼人", "model": "model"},
                    {"name": "3号玩家", "role": "村民", "model": "model"},
                    {"name": "4号玩家", "role": "狼人", "model": "model"},
                ],
                "rounds": [
                    {
                        "number": 1,
                        "players": ["1号玩家", "2号玩家", "3号玩家", "4号玩家"],
                        "night_deaths": [],
                        "day_deaths": [
                            {"player": "3号玩家", "cause": "vote_exile"},
                        ],
                        "votes": [{"1号玩家": "3号玩家", "2号玩家": "3号玩家"}],
                        "exiled": "3号玩家",
                        "exile_last_words": {
                            "player": "3号玩家",
                            "message": "我会留下最后的票型判断。",
                            "status": "completed",
                            "reason_code": "completed",
                        },
                    },
                    {
                        "number": 2,
                        "players": ["1号玩家", "2号玩家", "4号玩家"],
                        "night_deaths": [],
                        "day_deaths": [
                            {"player": "2号玩家", "cause": "vote_exile"},
                        ],
                        "votes": [{"1号玩家": "2号玩家", "4号玩家": "2号玩家"}],
                        "exiled": "2号玩家",
                    },
                ],
                "winner": "好人阵营",
            },
            "logs": [
                {"number": 1, "exile_last_words": last_words_log},
                {"number": 2},
            ],
        }
    )

    events = playback["events"]
    last_words_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "action_parsed"
        and event.get("action") == "exile_last_words"
    )
    next_round_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "round_started" and event.get("round") == 2
    )
    assert last_words_index < next_round_index
