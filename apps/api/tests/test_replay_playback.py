from app.werewolf.replay_playback import build_replay_playback


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
