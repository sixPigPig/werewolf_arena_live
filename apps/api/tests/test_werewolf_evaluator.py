import json

from app.werewolf.evaluator import evaluate_replay


def test_evaluator_flags_private_summary_leak_and_forgotten_public_claim(
    tmp_path,
) -> None:
    replay = {
        "session_id": "game_eval",
        "winner": "狼人阵营",
        "players": [],
        "rounds": [
            {
                "number": 2,
                "sheriff_speeches": [
                    {
                        "speaker": "7号玩家",
                        "message": "我是7号预言家，昨晚查验6号，6号是好人。",
                    }
                ],
                "summaries": {},
                "private_summaries": {},
                "debate": [],
            },
            {
                "number": 4,
                "sheriff_speeches": [],
                "summaries": {"10号玩家": "我作为10号狼人，准备夜晚刀9号。"},
                "private_summaries": {},
                "debate": [
                    {"speaker": "1号玩家", "message": "我怀疑6号，他比较划水。"}
                ],
            },
        ],
    }
    path = tmp_path / "game_complete.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    report = evaluate_replay(path)

    assert "private_summary_leak" in report.issue_codes
    assert "public_claim_not_recalled" in report.issue_codes


def test_evaluator_flags_endgame_tomorrow_without_pressure(tmp_path) -> None:
    replay = {
        "session_id": "game_eval_endgame",
        "winner": "",
        "players": [],
        "rounds": [
            {
                "number": 4,
                "summaries": {},
                "sheriff_speeches": [],
                "debate": [
                    {"speaker": "2号玩家", "message": "今天先出3号，明天再看4号。"}
                ],
            }
        ],
    }
    path = tmp_path / "game_complete.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    report = evaluate_replay(path)

    assert "endgame_pressure_miss" in report.issue_codes
