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


def test_evaluator_flags_invalid_abort_empty_logs_and_chain_self_explosion(tmp_path) -> None:
    replay = {
        "session_id": "partial_eval",
        "error_message": "1号玩家 returned invalid witch_poison: None",
        "players": [],
        "rounds": [
            {"number": 1, "werewolf_self_exploded": "2号玩家", "debate": [], "summaries": {}},
            {"number": 2, "werewolf_self_exploded": "7号玩家", "debate": [], "summaries": {}},
            {"number": 3, "werewolf_self_exploded": "8号玩家", "debate": [], "summaries": {}},
        ],
    }
    replay_path = tmp_path / "game_partial.json"
    logs_path = tmp_path / "game_logs.json"
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    logs_path.write_text("[]", encoding="utf-8")

    report = evaluate_replay(replay_path)

    assert "invalid_action_abort" in report.issue_codes
    assert "empty_partial_logs" in report.issue_codes
    assert "chain_self_explosion_overuse" in report.issue_codes


def test_evaluator_flags_term_contradiction_and_self_reference(tmp_path) -> None:
    replay = {
        "session_id": "text_eval",
        "winner": "",
        "players": [],
        "rounds": [
            {
                "number": 3,
                "summaries": {},
                "sheriff_speeches": [],
                "debate": [
                    {"speaker": "1号玩家", "message": "3号预言家查杀5号好人。"},
                    {"speaker": "10号玩家", "message": "我10号是村民，后置位10、11、12都可疑。"},
                ],
            }
        ],
    }
    path = tmp_path / "game_complete.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    report = evaluate_replay(path)

    assert "role_term_contradiction" in report.issue_codes
    assert "self_reference_as_group" in report.issue_codes
