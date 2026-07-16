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
