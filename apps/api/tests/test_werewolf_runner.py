import json

import pytest

from app.werewolf.live import NullEventSink
from app.werewolf.runner import GameRunError, run_game


class ScriptedChineseProvider:
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        options = _extract_options(prompt)
        choice = options[0] if options else "1"
        if '"bid"' in prompt:
            return json.dumps({"reasoning": "我需要推动讨论。", "bid": "2"}, ensure_ascii=False)
        if '"say"' in prompt:
            return json.dumps(
                {"reasoning": "我要给出明确怀疑。", "say": "我认为现在最可疑的人需要解释自己的发言。"},
                ensure_ascii=False,
            )
        if '"vote"' in prompt:
            return json.dumps({"reasoning": "他的发言最可疑。", "vote": choice}, ensure_ascii=False)
        if '"investigate"' in prompt:
            return json.dumps(
                {"reasoning": "我想确认他的真实身份。", "investigate": choice},
                ensure_ascii=False,
            )
        if '"remove"' in prompt:
            return json.dumps({"reasoning": "他对狼人阵营威胁最大。", "remove": choice}, ensure_ascii=False)
        if '"protect"' in prompt:
            return json.dumps({"reasoning": "他可能是关键好人。", "protect": choice}, ensure_ascii=False)
        if '"summary"' in prompt:
            return json.dumps(
                {"reasoning": "我需要记录本轮线索。", "summary": "我会继续关注发言矛盾最大的玩家。"},
                ensure_ascii=False,
            )
        raise AssertionError(f"Unexpected prompt: {prompt}")


def _extract_options(prompt: str) -> list[str]:
    marker = "候选人："
    if marker not in prompt:
        return []
    tail = prompt.split(marker, 1)[1].split("。", 1)[0]
    return [option.strip() for option in tail.split("、") if option.strip()]


def test_run_game_with_deepseek_models_writes_complete_chinese_logs(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    assert result.winner in {"好人阵营", "狼人阵营"}
    assert result.session_id.startswith("session_")
    assert result.log_directory.exists()
    assert (result.log_directory / "game_complete.json").exists()
    assert (result.log_directory / "game_logs.json").exists()

    state = json.loads((result.log_directory / "game_complete.json").read_text())
    logs = json.loads((result.log_directory / "game_logs.json").read_text())

    assert state["winner"] == result.winner
    assert len(state["players"]) == 8
    assert state["error_message"] == ""
    assert {player["role"] for player in state["players"]} == {"狼人", "预言家", "医生", "村民"}
    assert any("第" in observation for player in state["players"] for observation in player["observations"])
    assert logs[0]["debate"]
    assert logs[0]["summaries"]
    assert "狼人杀" in logs[0]["debate"][0]["lm_log"]["prompt"]
    assert "我认为" in state["rounds"][0]["debate"][0]["message"]


def test_run_game_is_reproducible_for_same_seed(tmp_path) -> None:
    first = run_game(
        logs_dir=tmp_path / "first",
        seed=11,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )
    second = run_game(
        logs_dir=tmp_path / "second",
        seed=11,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    first_state = json.loads((first.log_directory / "game_complete.json").read_text())
    second_state = json.loads((second.log_directory / "game_complete.json").read_text())

    assert first.winner == second.winner
    assert first_state["players"] == second_state["players"]


def test_run_game_records_partial_log_when_max_rounds_is_exceeded(tmp_path) -> None:
    with pytest.raises(GameRunError) as error:
        run_game(logs_dir=tmp_path, seed=3, max_rounds=0, provider=ScriptedChineseProvider())

    assert error.value.log_directory is not None
    partial_file = error.value.log_directory / "game_partial.json"
    assert partial_file.exists()

    state = json.loads(partial_file.read_text())
    assert "Maximum rounds exceeded" in state["error_message"]


def test_run_game_accepts_custom_session_id(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="session_20260424_120000_ab12cd34",
        event_sink=NullEventSink(),
    )

    assert result.session_id == "session_20260424_120000_ab12cd34"
    assert result.log_directory == tmp_path / "session_20260424_120000_ab12cd34"


class CapturingEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append({"type": event_type, **kwargs})


def test_run_game_publishes_live_events(tmp_path) -> None:
    sink = CapturingEventSink()

    run_game(
        logs_dir=tmp_path,
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="session_20260424_120000_ab12cd34",
        event_sink=sink,
    )

    event_types = [event["type"] for event in sink.events]
    assert "game_started" in event_types
    assert "round_started" in event_types
    assert "action_requested" in event_types
    assert "model_request_started" in event_types
    assert "model_response_received" in event_types
    assert "action_parsed" in event_types
    assert "state_updated" in event_types
