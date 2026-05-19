from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.werewolf.checkpoint import (
    RESUME_CHECKPOINT_FILE,
    ReplayThenLiveProvider,
    game_state_from_dict,
    round_log_from_dict,
)
from app.werewolf.lm import LmLog
from app.werewolf.models import ActionLog, GameState, Player, RoundLog, RoundState
from app.werewolf.replay import ReplayStore
from app.werewolf.runner import GameRunError, resume_game, run_game


class ScriptedProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        self.calls += 1
        options = _extract_options(prompt)
        choice = options[0] if options else "1"
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {"reasoning": "狼人私密沟通。", "target": choice, "message": f"建议袭击{choice}。"},
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps({"reasoning": "狼人统一刀口。", "target": choice}, ensure_ascii=False)
        if '"remove"' in prompt:
            return json.dumps({"reasoning": "优先击杀。", "remove": choice}, ensure_ascii=False)
        if '"protect"' in prompt:
            return json.dumps({"reasoning": "保护关键玩家。", "protect": choice}, ensure_ascii=False)
        if '"investigate"' in prompt:
            return json.dumps({"reasoning": "查验身份。", "investigate": choice}, ensure_ascii=False)
        if '"save"' in prompt:
            return json.dumps({"reasoning": "暂不使用解药。", "save": "不使用解药"}, ensure_ascii=False)
        if '"poison"' in prompt:
            return json.dumps({"reasoning": "暂不使用毒药。", "poison": "不使用毒药"}, ensure_ascii=False)
        if '"shoot"' in prompt:
            return json.dumps({"reasoning": "暂不开枪。", "shoot": "不发动技能"}, ensure_ascii=False)
        if '"run"' in prompt:
            return json.dumps({"reasoning": "不上警。", "run": "不上警"}, ensure_ascii=False)
        if '"withdraw"' in prompt:
            return json.dumps({"reasoning": "不退水。", "withdraw": "不退水"}, ensure_ascii=False)
        if '"speech_order"' in prompt:
            return json.dumps({"reasoning": "默认警左。", "speech_order": choice}, ensure_ascii=False)
        if '"badge"' in prompt:
            return json.dumps({"reasoning": "撕毁警徽。", "badge": choice}, ensure_ascii=False)
        if '"say"' in prompt:
            return json.dumps({"reasoning": "发表观点。", "say": "我会继续观察。"}, ensure_ascii=False)
        if '"vote"' in prompt:
            return json.dumps({"reasoning": "投给最可疑的人。", "vote": choice}, ensure_ascii=False)
        if '"sheriff_vote"' in prompt:
            return json.dumps({"reasoning": "投给首位候选人。", "sheriff_vote": choice}, ensure_ascii=False)
        if '"summary"' in prompt:
            return json.dumps({"reasoning": "记录线索。", "summary": "继续关注发言。"}, ensure_ascii=False)
        raise AssertionError(f"Unexpected prompt: {prompt}")


class FailingAfterProvider(ScriptedProvider):
    def __init__(self, *, fail_after_successes: int) -> None:
        super().__init__()
        self.fail_after_successes = fail_after_successes

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if self.calls >= self.fail_after_successes:
            raise RuntimeError("model provider offline")
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


def test_failed_run_writes_resume_checkpoint(tmp_path: Path) -> None:
    provider = FailingAfterProvider(fail_after_successes=0)

    with pytest.raises(GameRunError) as error:
        run_game(
            logs_dir=tmp_path,
            provider=provider,
            seed=21,
            max_rounds=8,
            rule_set_id="starter_6",
        )

    checkpoint_path = error.value.log_directory / RESUME_CHECKPOINT_FILE
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))

    assert checkpoint["schema_version"] == 1
    assert checkpoint["session_id"] == error.value.log_directory.name
    assert checkpoint["round_number"] == 1
    assert checkpoint["active_players"]
    assert checkpoint["run_params"]["rule_set_id"] == "starter_6"
    assert checkpoint["cached_model_responses"] == []
    assert checkpoint["failed_request"]["error"] == "model provider offline"


def test_resume_game_replays_cached_model_responses_before_live_requests(
    tmp_path: Path,
) -> None:
    failing_provider = FailingAfterProvider(fail_after_successes=1)

    with pytest.raises(GameRunError) as error:
        run_game(
            logs_dir=tmp_path,
            provider=failing_provider,
            seed=21,
            max_rounds=8,
            rule_set_id="starter_6",
        )

    checkpoint_path = error.value.log_directory / RESUME_CHECKPOINT_FILE
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert len(checkpoint["cached_model_responses"]) == 1

    resume_provider = ScriptedProvider()
    result = resume_game(
        logs_dir=tmp_path,
        session_id=error.value.log_directory.name,
        provider=resume_provider,
    )

    assert result.session_id == error.value.log_directory.name
    assert result.winner
    assert resume_provider.calls > 0
    assert not checkpoint_path.exists()
    assert (result.log_directory / "game_complete.json").exists()


def test_replay_then_live_provider_uses_cached_response_first() -> None:
    live_provider = ScriptedProvider()
    provider = ReplayThenLiveProvider(
        cached_model_responses=[
            {
                "actor": "张三",
                "action": "werewolf_kill_vote",
                "phase": "night",
                "model": "deepseek-chat",
                "raw_response": '{"reasoning":"cached","target":"李四"}',
            }
        ],
        delegate=live_provider,
    )

    assert (
        provider.complete_json(model="deepseek-chat", prompt="first", temperature=0.4)
        == '{"reasoning":"cached","target":"李四"}'
    )
    assert live_provider.calls == 0

    response = provider.complete_json(
        model="deepseek-chat",
        prompt='行动："vote"。候选人：李四。',
        temperature=0.4,
    )

    assert json.loads(response)["vote"] == "李四"
    assert live_provider.calls == 1


def test_replay_store_lists_checkpoint_only_session_as_resumable(tmp_path: Path) -> None:
    provider = FailingAfterProvider(fail_after_successes=0)

    with pytest.raises(GameRunError) as error:
        run_game(
            logs_dir=tmp_path,
            provider=provider,
            seed=21,
            max_rounds=8,
            rule_set_id="starter_6",
        )

    partial_path = error.value.log_directory / "game_partial.json"
    partial_path.unlink()

    sessions = ReplayStore(tmp_path).list_sessions()
    session = next(item for item in sessions if item["session_id"] == error.value.log_directory.name)

    assert session["status"] == "partial"
    assert session["resumable"] is True
    assert session["round_count"] == 0


def test_resume_checkpoint_preserves_self_explosion_state() -> None:
    state = GameState(
        session_id="session_self_explosion",
        players=[Player("Alice", "狼人", "wolf-model"), Player("Bob", "村民", "villager-model")],
        sheriff_pre_election_bomb_count=1,
        sheriff_election_pending=True,
    )
    round_state = RoundState(
        number=1,
        players=["Alice", "Bob"],
        werewolf_self_exploded="Alice",
        day_ended_by_self_explosion=True,
        sheriff_pre_election_bomb_count=1,
        sheriff_election_pending=True,
        sheriff_badge_lost_reason="首爆中断警长竞选",
    )
    state.rounds.append(round_state)
    action = ActionLog(
        actor="Alice",
        action="werewolf_self_explosion",
        options=["自爆", "不自爆"],
        choice="自爆",
        lm_log=LmLog(prompt="prompt", raw_response='{"self_explode":"自爆"}', result={"self_explode": "自爆"}),
    )
    round_log = RoundLog(number=1, werewolf_self_explosion=action)

    restored_state = game_state_from_dict(state.to_dict())
    restored_log = round_log_from_dict(round_log.to_dict())

    assert restored_state.sheriff_pre_election_bomb_count == 1
    assert restored_state.sheriff_election_pending is True
    restored_round = restored_state.rounds[0]
    assert restored_round.werewolf_self_exploded == "Alice"
    assert restored_round.day_ended_by_self_explosion is True
    assert restored_round.sheriff_pre_election_bomb_count == 1
    assert restored_round.sheriff_election_pending is True
    assert restored_round.sheriff_badge_lost_reason == "首爆中断警长竞选"
    assert restored_log.werewolf_self_explosion is not None
    assert restored_log.werewolf_self_explosion.choice == "自爆"


def _extract_options(prompt: str) -> list[str]:
    marker = next((candidate for candidate in ("候选人：", "候选选项：") if candidate in prompt), "")
    if not marker:
        return []
    tail = prompt.split(marker, 1)[1].split("。", 1)[0]
    return [option.strip() for option in tail.split("、") if option.strip()]
    return []
