import copy
import json
import multiprocessing
import queue
import random
import threading
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.werewolf.config import HUNTER, SEER, WEREWOLF, WITCH
from app.werewolf.checkpoint import player_from_dict, round_log_from_dict, round_state_from_dict
from app.werewolf.engine import (
    GameEngine,
    MaxRoundsExceeded,
    NO_HUNTER_SHOT,
    NO_WITCH_POISON,
    PublicStageCursor,
    WEREWOLF_NO_SELF_EXPLODE,
    WEREWOLF_SELF_EXPLODE,
    initialize_game_state,
)
from app.werewolf.execution_budget import (
    ActionExecutionBudgetV1,
    ModelDeadlineExceeded,
)
from app.werewolf.live import NullEventSink
from app.werewolf.lm import FakeProvider
from app.werewolf.models import DeathEvent, DebateEntry, RoundLog, RoundState
from app.werewolf.player_configs import PlayerConfig
from app.werewolf.player_profile_prompts import compose_player_profile_prompt
from app.werewolf.prompts_zh import build_prompt
from app.werewolf.replay import DatabaseReplayStore
from app.werewolf.rules import (
    ACTION_DEBATE,
    ACTION_SHERIFF_PK_SPEECH,
    ACTION_SHERIFF_SPEECH,
    ACTION_WEREWOLF_SELF_EXPLOSION,
    ACTION_WITCH_POISON,
    MODEL_GROUP_WEREWOLF,
    get_rule_set,
)
from app.werewolf.runner import GameRunError, run_game
from tests.rule_set_fixtures import (
    legacy_official_compiled_rule_set,
    managed_official_compiled_rule_set,
)


@pytest.fixture
def record_store() -> Generator[DatabaseReplayStore, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSessionLocal() as session:
        yield DatabaseReplayStore(session)


@pytest.fixture
def second_record_store() -> Generator[DatabaseReplayStore, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSessionLocal() as session:
        yield DatabaseReplayStore(session)


class ScriptedChineseProvider:
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        options = _extract_options(prompt)
        choice = options[0] if options else "1"
        if '"say"' in prompt:
            return json.dumps(
                {
                    "reasoning": "我要给出明确怀疑。",
                    "say": "我认为现在最可疑的人需要解释自己的发言。",
                },
                ensure_ascii=False,
            )
        if '"vote"' in prompt:
            return json.dumps({"reasoning": "他的发言最可疑。", "vote": choice}, ensure_ascii=False)
        if '"investigate"' in prompt:
            return json.dumps(
                {"reasoning": "我想确认他的真实身份。", "investigate": choice},
                ensure_ascii=False,
            )
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {"reasoning": "狼人私密沟通。", "target": choice, "message": f"建议袭击{choice}。"},
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps({"reasoning": "狼人统一刀口。", "target": choice}, ensure_ascii=False)
        if '"remove"' in prompt:
            return json.dumps(
                {"reasoning": "他对狼人阵营威胁最大。", "remove": choice}, ensure_ascii=False
            )
        if '"protect"' in prompt:
            return json.dumps(
                {"reasoning": "他可能是关键好人。", "protect": choice}, ensure_ascii=False
            )
        if '"save"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认不使用解药。", "save": "不使用解药"},
                ensure_ascii=False,
            )
        if '"poison"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认不使用毒药。", "poison": "不使用毒药"},
                ensure_ascii=False,
            )
        if '"shoot"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认不开枪。", "shoot": "不发动技能"},
                ensure_ascii=False,
            )
        if '"summary"' in prompt:
            return json.dumps(
                {
                    "reasoning": "我需要记录本轮线索。",
                    "summary": "我会继续关注发言矛盾最大的玩家。",
                },
                ensure_ascii=False,
            )
        if '"self_explode"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认不自爆。", "self_explode": "不自爆"},
                ensure_ascii=False,
            )
        if '"run"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认参与警长竞选。", "run": choice}, ensure_ascii=False
            )
        if '"withdraw"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认不退水。", "withdraw": "不退水"},
                ensure_ascii=False,
            )
        if '"sheriff_vote"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认投给首位候选人。", "sheriff_vote": choice},
                ensure_ascii=False,
            )
        if '"speech_order"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认从警左发言。", "speech_order": choice},
                ensure_ascii=False,
            )
        if '"badge"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认撕毁警徽。", "badge": choice},
                ensure_ascii=False,
            )
        raise AssertionError(f"Unexpected prompt: {prompt}")


class StreamingSpeechProvider(ScriptedChineseProvider):
    def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
        del model, temperature
        if '"say"' in prompt:
            return ['{"reasoning":"公开发言",', '"say":"我', "不是", '狼"}']
        return [self.complete_json(model="deepseek-chat", prompt=prompt, temperature=0.4)]


class WerewolfConsensusProvider(ScriptedChineseProvider):
    def __init__(
        self,
        *,
        vote_rounds: list[dict[str, str]],
        discussion_targets: dict[str, str] | None = None,
        protect_choice: str | None = None,
        save_choice: str = "不使用解药",
        poison_choice: str = "不使用毒药",
        shoot_choice: str = "不发动技能",
    ) -> None:
        self.vote_rounds = vote_rounds
        self.discussion_targets = discussion_targets or {}
        self.protect_choice = protect_choice
        self.save_choice = save_choice
        self.poison_choice = poison_choice
        self.shoot_choice = shoot_choice
        self.vote_calls = 0
        self.actions: list[tuple[str, str, str]] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        options = _extract_options(prompt)
        if '"message"' in prompt and '"target"' in prompt:
            target = self.discussion_targets.get(name, options[0])
            self.actions.append(("werewolf_discuss", name, target))
            return json.dumps(
                {
                    "reasoning": "夜晚私密沟通。",
                    "target": target,
                    "message": f"建议今晚袭击{target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            wolves_in_round = max(1, len(self.vote_rounds[0]))
            round_index = min(self.vote_calls // wolves_in_round, len(self.vote_rounds) - 1)
            target = self.vote_rounds[round_index][name]
            self.vote_calls += 1
            self.actions.append(("werewolf_kill_vote", name, target))
            return json.dumps(
                {"reasoning": "形成统一刀口。", "target": target},
                ensure_ascii=False,
            )
        if '"protect"' in prompt and self.protect_choice:
            return json.dumps(
                {"reasoning": "测试守卫守护狼刀目标。", "protect": self.protect_choice},
                ensure_ascii=False,
            )
        if '"save"' in prompt:
            return json.dumps(
                {"reasoning": "测试女巫解药选择。", "save": self.save_choice},
                ensure_ascii=False,
            )
        if '"poison"' in prompt:
            return json.dumps(
                {"reasoning": "测试女巫毒药选择。", "poison": self.poison_choice},
                ensure_ascii=False,
            )
        if '"shoot"' in prompt:
            return json.dumps(
                {"reasoning": "测试猎人开枪选择。", "shoot": self.shoot_choice},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class SheriffFlowProvider(ScriptedChineseProvider):
    def __init__(
        self,
        *,
        candidates: set[str],
        sheriff_vote_targets: dict[str, str],
        withdraw: set[str] | None = None,
        runoff_vote_targets: dict[str, str] | None = None,
        speech_order_choice: str = "警左发言",
        badge_choice: str = "撕毁警徽",
    ) -> None:
        self.candidates = candidates
        self.sheriff_vote_targets = sheriff_vote_targets
        self.withdraw = withdraw or set()
        self.runoff_vote_targets = runoff_vote_targets or sheriff_vote_targets
        self.speech_order_choice = speech_order_choice
        self.badge_choice = badge_choice
        self.actions: list[tuple[str, str]] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            self.actions.append(("sheriff_run", name))
            choice = "上警" if name in self.candidates else "不上警"
            return json.dumps(
                {"reasoning": "根据身份争取警徽。", "run": choice}, ensure_ascii=False
            )
        if '"withdraw"' in prompt:
            self.actions.append(("sheriff_withdraw", name))
            choice = "退水" if name in self.withdraw else "不退水"
            return json.dumps(
                {"reasoning": "根据警上形势决定是否退水。", "withdraw": choice}, ensure_ascii=False
            )
        if '"say"' in prompt and "警上竞选发言" in prompt:
            self.actions.append(("sheriff_speech", name))
            return json.dumps(
                {"reasoning": "争取警徽。", "say": f"{name} 警上发言。"}, ensure_ascii=False
            )
        if '"say"' in prompt and "PK 发言" in prompt:
            self.actions.append(("sheriff_pk_speech", name))
            return json.dumps(
                {"reasoning": "争取二轮票。", "say": f"{name} PK 发言。"}, ensure_ascii=False
            )
        if '"sheriff_vote"' in prompt and "行动：二轮警下投票" in prompt:
            self.actions.append(("sheriff_runoff_vote", name))
            choice = self.runoff_vote_targets[name]
            return json.dumps(
                {"reasoning": "二轮选择。", "sheriff_vote": choice}, ensure_ascii=False
            )
        if '"sheriff_vote"' in prompt:
            self.actions.append(("sheriff_vote", name))
            choice = self.sheriff_vote_targets[name]
            return json.dumps(
                {"reasoning": "选择最适合带队的人。", "sheriff_vote": choice}, ensure_ascii=False
            )
        if '"speech_order"' in prompt:
            self.actions.append(("speech_order", name))
            return json.dumps(
                {"reasoning": "让关键位置最后归票。", "speech_order": self.speech_order_choice},
                ensure_ascii=False,
            )
        if '"badge"' in prompt:
            self.actions.append(("sheriff_badge", name))
            options = _extract_options(prompt)
            choice = self.badge_choice if self.badge_choice in options else "撕毁警徽"
            return json.dumps({"reasoning": "处理警徽。", "badge": choice}, ensure_ascii=False)
        if '"vote"' in prompt:
            options = _extract_options(prompt)
            living_players = _extract_living_players(prompt)
            if name in living_players:
                choice = living_players[(living_players.index(name) + 1) % len(living_players)]
                if choice not in options:
                    choice = options[0] if options else "1"
            else:
                choice = options[0] if options else "1"
            return json.dumps({"reasoning": "测试放逐票。", "vote": choice}, ensure_ascii=False)
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class ConcurrentSheriffRunProvider(ScriptedChineseProvider):
    def __init__(self, expected_calls: int) -> None:
        self.barrier = threading.Barrier(expected_calls)
        self.actions: list[tuple[str, str]] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            self.actions.append(("sheriff_run", name))
            self.barrier.wait(timeout=1.0)
            return json.dumps(
                {"reasoning": "本轮不上警。", "run": "不上警"},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class StreamingSheriffRunFallbackProvider(ScriptedChineseProvider):
    def __init__(self, expected_calls: int) -> None:
        self.barrier = threading.Barrier(expected_calls)
        self.actions: list[tuple[str, str]] = []

    def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            self.actions.append(("stream_sheriff_run", name))
            raise RuntimeError("stream failed before first chunk")
        return [self.complete_json(model=model, prompt=prompt, temperature=temperature)]

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            self.actions.append(("complete_sheriff_run", name))
            self.barrier.wait(timeout=2.0)
            return json.dumps(
                {"reasoning": "stream 失败后回退到非流式。", "run": "不上警"},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class RetryingSheriffRunProvider(ScriptedChineseProvider):
    def __init__(self, expected_calls: int) -> None:
        self.barrier = threading.Barrier(expected_calls)
        self.attempts_by_actor: dict[str, int] = {}
        self.lock = threading.Lock()
        self.actions: list[tuple[str, str, int]] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            with self.lock:
                attempt = self.attempts_by_actor.get(name, 0) + 1
                self.attempts_by_actor[name] = attempt
                self.actions.append(("complete_sheriff_run", name, attempt))
            if attempt == 1:
                return "invalid json"
            self.barrier.wait(timeout=2.0)
            return json.dumps(
                {"reasoning": "重试后返回有效选择。", "run": "不上警"},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class RecordingSheriffRunProvider(ScriptedChineseProvider):
    def __init__(self) -> None:
        self.actions: list[str] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            self.actions.append(name)
            return json.dumps(
                {"reasoning": "记录上警批量请求。", "run": "不上警"},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class FailingSheriffRunProvider(ScriptedChineseProvider):
    def __init__(self, *, fail_actor: str) -> None:
        self.fail_actor = fail_actor
        self.actions: list[str] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            self.actions.append(name)
            if name == self.fail_actor:
                raise RuntimeError("batched model failure")
            return json.dumps(
                {"reasoning": "失败批次中的成功响应。", "run": "不上警"},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class InvalidSheriffRunProvider(ScriptedChineseProvider):
    def __init__(self, *, invalid_actor: str) -> None:
        self.invalid_actor = invalid_actor
        self.actions: list[str] = []
        self.first_actions: list[str] = []
        self.attempts_by_actor: dict[str, int] = {}
        self.lock = threading.Lock()

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            with self.lock:
                self.actions.append(name)
                self.attempts_by_actor[name] = self.attempts_by_actor.get(name, 0) + 1
                if self.attempts_by_actor[name] == 1:
                    self.first_actions.append(name)
            run_choice = "无效上警选择" if name == self.invalid_actor else "不上警"
            return json.dumps(
                {"reasoning": "测试无效批量响应。", "run": run_choice},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class RecordingCheckpointManager:
    def __init__(self) -> None:
        self.successes: list[dict[str, object]] = []
        self.failures: list[dict[str, object]] = []

    def start_round(self, **kwargs: object) -> None:
        del kwargs

    def record_success(self, **kwargs: object) -> None:
        self.successes.append(dict(kwargs))

    def record_failure(self, **kwargs: object) -> None:
        self.failures.append(dict(kwargs))


class BarrierActionProvider(ScriptedChineseProvider):
    def __init__(
        self,
        *,
        action_key: str,
        result_key: str,
        response_value_by_actor: dict[str, str],
        expected_calls: int,
    ) -> None:
        self.action_key = action_key
        self.result_key = result_key
        self.response_value_by_actor = response_value_by_actor
        self.barrier = threading.Barrier(expected_calls)
        self.actions: list[tuple[str, str]] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if f'"{self.result_key}"' in prompt and self._matches_action(prompt):
            self.actions.append((self.action_key, name))
            self.barrier.wait(timeout=1.0)
            return json.dumps(
                {
                    "reasoning": "并发批量测试。",
                    self.result_key: self.response_value_by_actor[name],
                },
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)

    def _matches_action(self, prompt: str) -> bool:
        marker_by_action = {
            "vote": "行动：投票放逐。",
            "sheriff_withdraw": "行动：退水选择。",
            "sheriff_vote": "行动：警长投票。",
            "sheriff_runoff_vote": "行动：二轮警下投票。",
            "werewolf_self_explosion": "行动：狼人自爆判断。",
            "werewolf_kill_vote": "行动：狼人夜晚狼刀投票。",
            "summarize": "行动：回合总结。",
        }
        marker = marker_by_action.get(self.action_key)
        return marker is None or marker in prompt


class BarrierSheriffProvider(BarrierActionProvider):
    def __init__(
        self,
        *,
        action_key: str,
        result_key: str,
        response_value_by_actor: dict[str, str],
        expected_calls: int,
        candidates: set[str],
        first_round_vote_targets: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            action_key=action_key,
            result_key=result_key,
            response_value_by_actor=response_value_by_actor,
            expected_calls=expected_calls,
        )
        self.candidates = candidates
        self.first_round_vote_targets = first_round_vote_targets or {}

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            choice = "上警" if name in self.candidates else "不上警"
            return json.dumps({"reasoning": "测试警长竞选。", "run": choice}, ensure_ascii=False)
        if (
            self.action_key == "sheriff_runoff_vote"
            and '"sheriff_vote"' in prompt
            and "行动：警长投票。" in prompt
        ):
            return json.dumps(
                {
                    "reasoning": "测试首轮平票。",
                    "sheriff_vote": self.first_round_vote_targets[name],
                },
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


def _run_sheriff_stream_fallback_batch(
    queue: multiprocessing.Queue,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_stream_fallback_sheriff_run",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=32,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    provider = StreamingSheriffRunFallbackProvider(expected_calls=len(active_players))
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)

    try:
        engine._run_sheriff_election_if_needed(round_state, round_log, active_players)
    except Exception as exc:
        queue.put({"error": repr(exc)})
        return

    queue.put(
        {
            "actions": provider.actions,
            "active_players": active_players,
            "sheriff_candidates": round_state.sheriff_candidates,
            "sheriff_voters": round_state.sheriff_voters,
        }
    )


def _run_sheriff_complete_retry_batch(
    queue: multiprocessing.Queue,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_complete_retry_sheriff_run",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=33,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    provider = RetryingSheriffRunProvider(expected_calls=len(active_players))
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)

    try:
        engine._run_sheriff_election_if_needed(round_state, round_log, active_players)
    except Exception as exc:
        queue.put({"error": repr(exc)})
        return

    queue.put(
        {
            "actions": provider.actions,
            "active_players": active_players,
            "sheriff_candidates": round_state.sheriff_candidates,
            "sheriff_voters": round_state.sheriff_voters,
        }
    )


class FailingModelStartEventSink:
    def __init__(self, *, fail_actor: str) -> None:
        self.fail_actor = fail_actor

    def publish(self, event_type: str, **kwargs: object) -> None:
        if (
            event_type == "model_request_started"
            and kwargs.get("action") == "sheriff_run"
            and kwargs.get("actor") == self.fail_actor
        ):
            raise RuntimeError("event sink failed before provider")


def _run_sheriff_model_start_failure_batch(
    queue: multiprocessing.Queue,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_model_start_failure_sheriff_run",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=37,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    provider = RecordingSheriffRunProvider()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=FailingModelStartEventSink(fail_actor=active_players[0]),
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)

    try:
        engine._run_sheriff_election_if_needed(round_state, round_log, active_players)
    except Exception as exc:
        queue.put(
            {
                "error": str(exc),
                "active_players": active_players,
                "provider_actions": provider.actions,
            }
        )
        return

    queue.put({"error": None})


class SelfExplosionProvider(SheriffFlowProvider):
    def __init__(
        self,
        *,
        self_exploders: list[str],
        candidates: set[str],
        sheriff_vote_targets: dict[str, str] | None = None,
        badge_choice: str = "撕毁警徽",
    ) -> None:
        super().__init__(
            candidates=candidates,
            sheriff_vote_targets=sheriff_vote_targets or {},
            badge_choice=badge_choice,
        )
        self.self_exploders = self_exploders

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"self_explode"' in prompt:
            self.actions.append(("werewolf_self_explosion", name))
            choice = "自爆" if name in self.self_exploders else "不自爆"
            if choice == "自爆":
                self.self_exploders.remove(name)
            return json.dumps(
                {"reasoning": "测试自爆判断。", "self_explode": choice}, ensure_ascii=False
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class StageTriggeredSelfExplosionProvider(SelfExplosionProvider):
    def __init__(
        self,
        *,
        exploding_wolf: str,
        trigger_stage: str,
        candidates: set[str],
        sheriff_vote_targets: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            self_exploders=[exploding_wolf],
            candidates=candidates,
            sheriff_vote_targets=sheriff_vote_targets,
        )
        self.trigger_stage = trigger_stage

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"self_explode"' in prompt and self.trigger_stage not in prompt:
            name = _extract_actor_name(prompt)
            self.actions.append(("werewolf_self_explosion", name))
            return json.dumps(
                {"reasoning": "等待关键发言后再自爆。", "self_explode": "不自爆"},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class FirstNightSelfExplosionProvider(SelfExplosionProvider):
    def __init__(
        self,
        *,
        remove_target: str,
        self_exploders: list[str],
        candidates: set[str],
    ) -> None:
        super().__init__(self_exploders=self_exploders, candidates=candidates)
        self.remove_target = remove_target

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {
                    "reasoning": "制造首夜 pending 死亡。",
                    "target": self.remove_target,
                    "message": f"建议袭击{self.remove_target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps(
                {"reasoning": "制造首夜 pending 死亡。", "target": self.remove_target},
                ensure_ascii=False,
            )
        if '"remove"' in prompt:
            return json.dumps(
                {"reasoning": "制造首夜 pending 死亡。", "remove": self.remove_target},
                ensure_ascii=False,
            )
        if '"save"' in prompt:
            return json.dumps(
                {"reasoning": "测试不救。", "save": "不使用解药"},
                ensure_ascii=False,
            )
        if '"poison"' in prompt:
            return json.dumps(
                {"reasoning": "测试不毒。", "poison": "不使用毒药"},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class FirstNightSheriffDeathProvider(SheriffFlowProvider):
    def __init__(self, *, remove_target: str, candidates: set[str], badge_choice: str) -> None:
        super().__init__(
            candidates=candidates,
            sheriff_vote_targets={},
            badge_choice=badge_choice,
        )
        self.remove_target = remove_target

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {
                    "reasoning": "首夜刀中未来警长。",
                    "target": self.remove_target,
                    "message": f"建议袭击{self.remove_target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps(
                {"reasoning": "首夜刀中未来警长。", "target": self.remove_target},
                ensure_ascii=False,
            )
        if '"remove"' in prompt:
            return json.dumps(
                {"reasoning": "首夜刀中未来警长。", "remove": self.remove_target},
                ensure_ascii=False,
            )
        if '"save"' in prompt:
            return json.dumps(
                {"reasoning": "测试不救。", "save": "不使用解药"},
                ensure_ascii=False,
            )
        if '"poison"' in prompt:
            return json.dumps(
                {"reasoning": "测试不毒。", "poison": "不使用毒药"},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class FirstNightPoisonBadgeProvider(FirstNightSheriffDeathProvider):
    def __init__(
        self,
        *,
        remove_target: str,
        poison_choice: str,
        candidates: set[str],
        badge_choice: str,
    ) -> None:
        super().__init__(
            remove_target=remove_target,
            candidates=candidates,
            badge_choice=badge_choice,
        )
        self.poison_choice = poison_choice

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"poison"' in prompt:
            return json.dumps(
                {"reasoning": "测试毒死接警徽候选。", "poison": self.poison_choice},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class FirstNightHunterShotBadgeProvider(SheriffFlowProvider):
    def __init__(
        self,
        *,
        remove_target: str,
        shoot_choice: str,
        candidates: set[str],
        sheriff_vote_targets: dict[str, str],
        badge_choice: str,
    ) -> None:
        super().__init__(
            candidates=candidates,
            sheriff_vote_targets=sheriff_vote_targets,
            badge_choice=badge_choice,
        )
        self.remove_target = remove_target
        self.shoot_choice = shoot_choice

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {
                    "reasoning": "首夜刀中猎人。",
                    "target": self.remove_target,
                    "message": f"建议袭击{self.remove_target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps(
                {"reasoning": "首夜刀中猎人。", "target": self.remove_target},
                ensure_ascii=False,
            )
        if '"remove"' in prompt:
            return json.dumps(
                {"reasoning": "首夜刀中猎人。", "remove": self.remove_target},
                ensure_ascii=False,
            )
        if '"save"' in prompt:
            return json.dumps(
                {"reasoning": "测试不救。", "save": "不使用解药"},
                ensure_ascii=False,
            )
        if '"poison"' in prompt:
            return json.dumps(
                {"reasoning": "测试不毒。", "poison": "不使用毒药"},
                ensure_ascii=False,
            )
        if '"shoot"' in prompt:
            options = _extract_options(prompt)
            choice = self.shoot_choice if self.shoot_choice in options else "不发动技能"
            return json.dumps(
                {"reasoning": "猎人开枪带走警长。", "shoot": choice},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class NoInvestigateProvider(ScriptedChineseProvider):
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"investigate"' in prompt:
            raise AssertionError("Investigate should be skipped when there are no candidates.")
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class NoBidOrderedSpeechProvider(ScriptedChineseProvider):
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"bid"' in prompt:
            raise AssertionError("Bid should not be requested in ordered speech flow.")
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class ProtectedNightProvider:
    def __init__(self, target: str) -> None:
        self.target = target

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {
                    "reasoning": "测试狼人袭击被守护目标。",
                    "target": self.target,
                    "message": f"建议袭击{self.target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps(
                {"reasoning": "测试狼人袭击被守护目标。", "target": self.target},
                ensure_ascii=False,
            )
        if '"remove"' in prompt:
            return json.dumps(
                {"reasoning": "测试狼人袭击被守护目标。", "remove": self.target},
                ensure_ascii=False,
            )
        if '"protect"' in prompt:
            return json.dumps(
                {"reasoning": "测试守卫守护被袭击目标。", "protect": self.target},
                ensure_ascii=False,
            )
        if '"investigate"' in prompt:
            options = _extract_options(prompt)
            choice = next((option for option in options if option != self.target), options[0])
            return json.dumps(
                {"reasoning": "测试预言家正常查验。", "investigate": choice},
                ensure_ascii=False,
            )
        raise AssertionError(f"Unexpected prompt: {prompt}")


class TargetedInvestigationProvider(ScriptedChineseProvider):
    def __init__(self, *, investigate_target: str, remove_target: str) -> None:
        self.investigate_target = investigate_target
        self.remove_target = remove_target

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {
                    "reasoning": "测试狼人夜晚袭击。",
                    "target": self.remove_target,
                    "message": f"建议袭击{self.remove_target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps(
                {"reasoning": "测试狼人夜晚袭击。", "target": self.remove_target},
                ensure_ascii=False,
            )
        if '"remove"' in prompt:
            return json.dumps(
                {"reasoning": "测试狼人夜晚袭击。", "remove": self.remove_target},
                ensure_ascii=False,
            )
        if '"investigate"' in prompt:
            return json.dumps(
                {"reasoning": "测试预言家查验神职。", "investigate": self.investigate_target},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class NoWinnerRoundProvider(ScriptedChineseProvider):
    def __init__(self, *, protected_target: str) -> None:
        self.protected_target = protected_target

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {
                    "reasoning": "测试狼人袭击被守护目标。",
                    "target": self.protected_target,
                    "message": f"建议袭击{self.protected_target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps(
                {"reasoning": "测试狼人袭击被守护目标。", "target": self.protected_target},
                ensure_ascii=False,
            )
        if '"remove"' in prompt:
            return json.dumps(
                {"reasoning": "测试狼人袭击被守护目标。", "remove": self.protected_target},
                ensure_ascii=False,
            )
        if '"protect"' in prompt:
            return json.dumps(
                {"reasoning": "测试守卫守护被袭击目标。", "protect": self.protected_target},
                ensure_ascii=False,
            )
        if '"vote"' in prompt:
            name = _extract_actor_name(prompt)
            options = _extract_options(prompt)
            living_players = _extract_living_players(prompt)
            if name in living_players:
                choice = living_players[(living_players.index(name) + 1) % len(living_players)]
                if choice in options:
                    return json.dumps(
                        {"reasoning": "测试分散投票。", "vote": choice}, ensure_ascii=False
                    )
            choice = options[0] if options else "1"
            return json.dumps({"reasoning": "测试分散投票。", "vote": choice}, ensure_ascii=False)
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class FirstNightPeacefulSheriffProvider(SheriffFlowProvider):
    def __init__(
        self,
        *,
        protected_target: str,
        candidates: set[str],
        sheriff_vote_targets: dict[str, str],
    ) -> None:
        super().__init__(candidates=candidates, sheriff_vote_targets=sheriff_vote_targets)
        self.protected_target = protected_target

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {
                    "reasoning": "测试首夜袭击会被救下的目标。",
                    "target": self.protected_target,
                    "message": f"建议袭击{self.protected_target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps(
                {"reasoning": "测试首夜袭击会被救下的目标。", "target": self.protected_target},
                ensure_ascii=False,
            )
        if '"remove"' in prompt:
            return json.dumps(
                {"reasoning": "测试首夜袭击会被救下的目标。", "remove": self.protected_target},
                ensure_ascii=False,
            )
        if '"save"' in prompt:
            return json.dumps(
                {"reasoning": "测试女巫首夜救人。", "save": self.protected_target},
                ensure_ascii=False,
            )
        if '"poison"' in prompt:
            return json.dumps(
                {"reasoning": "测试首夜不毒人。", "poison": "不使用毒药"},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class WitchChoiceProvider:
    def __init__(self, *, remove_target: str, save_choice: str, poison_choice: str) -> None:
        self.remove_target = remove_target
        self.save_choice = save_choice
        self.poison_choice = poison_choice
        self.actions: list[str] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {
                    "reasoning": "选择夜晚袭击目标。",
                    "target": self.remove_target,
                    "message": f"建议袭击{self.remove_target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps(
                {"reasoning": "选择夜晚袭击目标。", "target": self.remove_target},
                ensure_ascii=False,
            )
        if '"remove"' in prompt:
            self.actions.append("remove")
            return json.dumps(
                {"reasoning": "选择夜晚袭击目标。", "remove": self.remove_target},
                ensure_ascii=False,
            )
        if '"investigate"' in prompt:
            self.actions.append("investigate")
            choice = _extract_options(prompt)[0]
            return json.dumps(
                {"reasoning": "查验可疑玩家。", "investigate": choice},
                ensure_ascii=False,
            )
        if '"save"' in prompt:
            self.actions.append("witch_save")
            return json.dumps(
                {"reasoning": "根据局势决定是否救人。", "save": self.save_choice},
                ensure_ascii=False,
            )
        if '"poison"' in prompt:
            self.actions.append("witch_poison")
            return json.dumps(
                {"reasoning": "根据局势决定是否毒人。", "poison": self.poison_choice},
                ensure_ascii=False,
            )
        if '"shoot"' in prompt:
            self.actions.append("hunter_shoot")
            return json.dumps(
                {"reasoning": "不发动技能。", "shoot": "不发动技能"},
                ensure_ascii=False,
            )
        raise AssertionError(f"Unexpected prompt: {prompt}")


class HunterShotProvider(WitchChoiceProvider):
    def __init__(
        self,
        *,
        remove_target: str,
        save_choice: str,
        poison_choice: str,
        shoot_choice: str,
    ) -> None:
        super().__init__(
            remove_target=remove_target,
            save_choice=save_choice,
            poison_choice=poison_choice,
        )
        self.shoot_choice = shoot_choice

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"shoot"' in prompt:
            self.actions.append("hunter_shoot")
            options = _extract_options(prompt)
            choice = self.shoot_choice if self.shoot_choice in options else "不发动技能"
            return json.dumps(
                {"reasoning": "猎人带走最可疑玩家。", "shoot": choice},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


class HunterShotBadgeProvider(HunterShotProvider):
    def __init__(
        self,
        *,
        remove_target: str,
        save_choice: str,
        poison_choice: str,
        shoot_choice: str,
        badge_choice: str,
    ) -> None:
        super().__init__(
            remove_target=remove_target,
            save_choice=save_choice,
            poison_choice=poison_choice,
            shoot_choice=shoot_choice,
        )
        self.badge_choice = badge_choice

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"badge"' in prompt:
            self.actions.append("sheriff_badge")
            options = _extract_options(prompt)
            choice = self.badge_choice if self.badge_choice in options else "撕毁警徽"
            return json.dumps(
                {"reasoning": "移交警徽给可信玩家。", "badge": choice},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)


def test_round_state_serializes_werewolf_consensus_fields() -> None:
    round_state = RoundState(number=1, players=["Wolf", "Alice"])
    round_state.werewolf_discussion.append(
        {
            "round": 1,
            "speaker": "Wolf",
            "target": "Alice",
            "message": "建议袭击 Alice。",
        }
    )
    round_state.werewolf_vote_rounds.append(
        {
            "round": 1,
            "candidates": ["Alice"],
            "votes": {"Wolf": "Alice"},
            "tally": {"Alice": 1},
            "unanimous": True,
            "result": "Alice",
        }
    )

    payload = round_state.to_dict()

    assert payload["werewolf_discussion"] == [
        {
            "round": 1,
            "speaker": "Wolf",
            "target": "Alice",
            "message": "建议袭击 Alice。",
        }
    ]
    assert payload["werewolf_vote_rounds"] == [
        {
            "round": 1,
            "candidates": ["Alice"],
            "votes": {"Wolf": "Alice"},
            "tally": {"Alice": 1},
            "unanimous": True,
            "result": "Alice",
        }
    ]


def test_round_state_deserializes_werewolf_consensus_fields() -> None:
    payload = {
        "number": 1,
        "players": ["Wolf", "Alice"],
        "werewolf_discussion": [
            {
                "round": 1,
                "speaker": "Wolf",
                "target": "Alice",
                "message": "建议袭击 Alice。",
            }
        ],
        "werewolf_vote_rounds": [
            {
                "round": 1,
                "candidates": ["Alice"],
                "votes": {"Wolf": "Alice"},
                "tally": {"Alice": 1},
                "unanimous": True,
                "result": "Alice",
            }
        ],
    }

    round_state = round_state_from_dict(payload)

    assert round_state.werewolf_discussion == payload["werewolf_discussion"]
    assert round_state.werewolf_vote_rounds == payload["werewolf_vote_rounds"]
    serialized = round_state.to_dict()
    assert serialized["werewolf_discussion"] == payload["werewolf_discussion"]
    assert serialized["werewolf_vote_rounds"] == payload["werewolf_vote_rounds"]


def test_round_log_serializes_werewolf_consensus_logs() -> None:
    lm_log = SimpleNamespace(to_dict=lambda: {"prompt": "p", "raw_response": "{}", "result": {}})
    discussion_log = SimpleNamespace(
        to_dict=lambda: {
            "actor": "Wolf",
            "action": "werewolf_discuss",
            "options": ["Alice"],
            "choice": "Alice",
            "lm_log": lm_log.to_dict(),
        }
    )
    vote_log = SimpleNamespace(
        to_dict=lambda: {
            "actor": "Wolf",
            "action": "werewolf_kill_vote",
            "options": ["Alice"],
            "choice": "Alice",
            "lm_log": lm_log.to_dict(),
        }
    )
    round_log = RoundLog(number=1)
    round_log.werewolf_discussion.append(discussion_log)
    round_log.werewolf_votes.append([vote_log])

    payload = round_log.to_dict()

    assert payload["werewolf_discussion"][0]["action"] == "werewolf_discuss"
    assert payload["werewolf_votes"][0][0]["action"] == "werewolf_kill_vote"


def test_model_summaries_are_private_and_public_brief_is_safe() -> None:
    round_state = RoundState(number=4, players=["10号玩家", "12号玩家"])
    round_state.private_summaries["10号玩家"] = "本轮我作为10号狼人，准备夜晚刀9号。"
    round_state.public_summary = "第4轮：1号玩家被放逐，票型记录已更新。"

    payload = round_state.to_dict()

    assert payload["public_summary"] == "第4轮：1号玩家被放逐，票型记录已更新。"
    assert payload["summaries"] == {}
    assert payload["private_summaries"]["10号玩家"] == "本轮我作为10号狼人，准备夜晚刀9号。"


def test_summary_phase_does_not_publish_private_summaries() -> None:
    class CapturingSink:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def publish(self, event_type: str, **kwargs: object) -> None:
            self.events.append({"type": event_type, **kwargs})

    sink = CapturingSink()
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="summary_test",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260614,
        rule_set=rule_set,
    )
    provider = ScriptedChineseProvider()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=1,
        rule_set=rule_set,
        event_sink=sink,
        rng=random.Random(1),
    )
    round_state = RoundState(number=1, players=[player.name for player in state.players])
    round_log = RoundLog(number=1)
    active_players = [player.name for player in state.players]

    engine._run_summaries(round_state, round_log, active_players)

    summary_events = [
        event
        for event in sink.events
        if event["type"] == "state_updated" and event.get("phase") == "summary"
    ]
    assert len(summary_events) == 1
    assert summary_events[0]["action"] == "public_round_brief"
    assert summary_events[0]["payload"]["public_summary"] == "第1轮；没有公开出局。"
    assert all("private_summaries" not in (event.get("payload") or {}) for event in summary_events)
    assert all("summaries" not in (event.get("payload") or {}) for event in summary_events)


def test_terminal_exile_skips_private_round_memories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="terminal_exile_skips_memories",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=20260714,
        rule_set=rule_set,
    )
    wolf = next(player.name for player in state.players if player.role == WEREWOLF)
    target = next(player.name for player in state.players if player.role == "村民")
    other_good = next(
        player.name for player in state.players if player.role != WEREWOLF and player.name != target
    )
    active_players = [wolf, target, other_good]
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    provider = FakeProvider([{"reasoning": "不应调用", "summary": "SENTINEL_PRIVATE_SUMMARY"}])
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )
    votes = {wolf: target, target: other_good, other_good: target}
    monkeypatch.setattr(engine, "_run_sheriff_election_if_needed", lambda *_: False)
    monkeypatch.setattr(engine, "_run_debate_phase", lambda *_: False)
    monkeypatch.setattr(engine, "_run_voting", lambda *_: (votes, []))

    engine._run_day_phase(round_state, round_log, active_players)

    assert state.winner == "狼人阵营"
    assert provider.calls == 0
    assert round_log.summaries == []
    assert round_state.private_summaries == {}
    assert round_state.public_summary == f"第2轮；{target}被放逐。"
    assert any(
        event["type"] == "state_updated" and event["action"] == "public_round_brief"
        for event in sink.events
    )
    assert all(event.get("action") != "summarize" for event in sink.events)


def test_terminal_hunter_shot_waits_for_shot_then_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="terminal_hunter_shot",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=20260714,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == WEREWOLF)
    hunter = next(player for player in state.players if player.role == HUNTER)
    civilian = next(player for player in state.players if player.role == "村民")
    active_players = [wolf.name, hunter.name, civilian.name]
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    provider = HunterShotProvider(
        remove_target=hunter.name,
        save_choice="不使用解药",
        poison_choice="不使用毒药",
        shoot_choice=wolf.name,
    )
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
    )
    votes = {
        wolf.name: hunter.name,
        hunter.name: wolf.name,
        civilian.name: hunter.name,
    }
    monkeypatch.setattr(engine, "_run_sheriff_election_if_needed", lambda *_: False)
    monkeypatch.setattr(engine, "_run_debate_phase", lambda *_: False)
    monkeypatch.setattr(engine, "_run_voting", lambda *_: (votes, []))

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.exiled == hunter.name
    assert round_state.hunter_shot == wolf.name
    assert [death.player for death in round_state.day_deaths] == [hunter.name, wolf.name]
    assert active_players == [civilian.name]
    assert state.winner == "好人阵营"
    assert provider.actions == ["hunter_shoot"]
    assert round_log.summaries == []
    assert round_state.private_summaries == {}


def test_terminal_self_explosion_skips_remaining_day_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="terminal_self_explosion",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=20260714,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == WEREWOLF)
    seer = next(player for player in state.players if player.role == SEER)
    civilian = next(player for player in state.players if player.role == "村民")
    active_players = [wolf.name, seer.name, civilian.name]
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    provider = SelfExplosionProvider(self_exploders=[wolf.name], candidates=set())
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
    )
    monkeypatch.setattr(engine, "_run_sheriff_election_if_needed", lambda *_: False)
    monkeypatch.setattr(
        engine,
        "_run_voting",
        lambda *_: pytest.fail("a terminal self-explosion must skip voting"),
    )

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.werewolf_self_exploded == wolf.name
    assert active_players == [seer.name, civilian.name]
    assert state.winner == "好人阵营"
    assert round_state.votes == []
    assert round_log.summaries == []
    assert round_state.private_summaries == {}


def test_terminal_deferred_night_deaths_skip_debate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="terminal_deferred_night_deaths",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=20260714,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == WEREWOLF)
    seer = next(player for player in state.players if player.role == SEER)
    civilian = next(player for player in state.players if player.role == "村民")
    active_players = [wolf.name, seer.name, civilian.name]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = FakeProvider([{"reasoning": "不应调用", "say": "不应发言"}])
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
    )
    monkeypatch.setattr(engine, "_run_sheriff_election_if_needed", lambda *_: False)
    monkeypatch.setattr(
        engine,
        "_run_debate_phase",
        lambda *_: pytest.fail("terminal deferred deaths must skip debate"),
    )

    engine._run_day_phase(
        round_state,
        round_log,
        active_players,
        [DeathEvent(seer.name, "werewolf_attack", "狼人")],
    )

    assert [death.player for death in round_state.night_deaths] == [seer.name]
    assert active_players == [wolf.name, civilian.name]
    assert state.winner == "狼人阵营"
    assert provider.calls == 0


def test_terminal_witch_multi_death_resolves_all_deaths_before_win_check() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="terminal_witch_multi_death",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=20260714,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == WEREWOLF)
    seer = next(player for player in state.players if player.role == SEER)
    witch = next(player for player in state.players if player.role == WITCH)
    civilian = next(player for player in state.players if player.role == "村民")
    active_players = [wolf.name, seer.name, witch.name, civilian.name]
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    provider = WitchChoiceProvider(
        remove_target=seer.name,
        save_choice="不使用解药",
        poison_choice=civilian.name,
    )
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
    )

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert [(death.player, death.cause) for death in round_state.night_deaths] == [
        (seer.name, "werewolf_attack"),
        (civilian.name, "witch_poison"),
    ]
    assert active_players == [wolf.name, witch.name]
    assert state.winner == "狼人阵营"


def test_decisive_state_precedes_game_completed_without_model_events_between(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="terminal_event_order",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=20260714,
        rule_set=rule_set,
    )
    wolf = next(player.name for player in state.players if player.role == WEREWOLF)
    target = next(player.name for player in state.players if player.role == "村民")
    other_good = next(
        player.name for player in state.players if player.role != WEREWOLF and player.name != target
    )
    active_players = [wolf, target, other_good]
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=FakeProvider([]),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )
    votes = {wolf: target, target: other_good, other_good: target}
    monkeypatch.setattr(engine, "_run_sheriff_election_if_needed", lambda *_: False)
    monkeypatch.setattr(engine, "_run_debate_phase", lambda *_: False)
    monkeypatch.setattr(engine, "_run_voting", lambda *_: (votes, []))

    engine._run_day_phase(round_state, round_log, active_players)
    sink.publish("game_completed", payload={"winner": state.winner})

    decisive_index = next(
        index
        for index, event in enumerate(sink.events)
        if event["type"] == "state_updated"
        and event.get("phase") == "vote"
        and (event.get("payload") or {}).get("exiled") == target
    )
    completed_index = next(
        index for index, event in enumerate(sink.events) if event["type"] == "game_completed"
    )
    model_event_types = {
        "action_requested",
        "model_request_started",
        "model_thinking_tick",
        "model_thinking_delta",
        "model_response_delta",
        "model_response_received",
        "action_parsed",
    }

    assert decisive_index < completed_index
    assert not any(
        event["type"] in model_event_types
        for event in sink.events[decisive_index + 1 : completed_index]
    )


def test_player_action_is_rejected_after_winner_is_set() -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="terminal_action_guard",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=20260714,
        rule_set=rule_set,
    )
    provider = FakeProvider([{"reasoning": "不应调用", "say": "不应发言"}])
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )
    round_state = RoundState(number=1, players=[player.name for player in state.players])
    state.winner = "狼人阵营"

    with pytest.raises(
        RuntimeError,
        match="Cannot request player action after game is terminal",
    ):
        engine._player_action(
            player=state.players[0],
            action="debate",
            options=[],
            result_key="say",
            round_state=round_state,
            phase="day",
        )

    assert provider.calls == 0
    assert sink.events == []


def test_world_state_includes_public_facts_for_late_day_actions() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="facts_test",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260614,
        rule_set=rule_set,
    )
    state.public_facts.append(
        {
            "round_number": 2,
            "category": "claim",
            "text": "7号玩家警上声明6号玩家为好人。",
        }
    )
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    players = state.player_by_name()
    round_state = RoundState(number=4, players=[player.name for player in state.players])

    world_state = engine._world_state(players["1号玩家"], [], round_state)

    assert "7号玩家警上声明6号玩家为好人。" in world_state["public_facts"]


def test_fact_prompt_coverage_uses_the_same_public_seat_projection() -> None:
    rule_set = get_rule_set("starter_6")
    custom_names = ["阿青", "白石", "南风", "岚", "乌木", "烛火"]
    state = initialize_game_state(
        session_id="fact_public_projection",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260715,
        rule_set=rule_set,
        player_configs=[
            PlayerConfig(
                seat=index,
                profile_id=None,
                name=name,
                model="",
                personality_id="balanced",
                personality="",
                appearance_id="default",
                avatar_prompt="",
                tags=(),
            )
            for index, name in enumerate(custom_names, start=1)
        ],
    )
    state.public_facts.append(
        {
            "round_number": 1,
            "category": "vote",
            "text": "阿青投票给白石。",
            "retention": "critical",
        }
    )
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    round_state = RoundState(number=1, players=custom_names.copy())

    request = engine._build_player_action_request(
        player=state.players[0],
        action="debate",
        options=[],
        result_key="say",
        round_state=round_state,
        phase="day",
    )

    assert "1号玩家投票给2号玩家。" in request.world_state["public_facts"]
    assert request.fact_prompt_coverage["expected_critical_count"] == 1
    assert request.fact_prompt_coverage["included_critical_count"] == 1


def test_world_state_carries_detached_exact_rule_snapshot() -> None:
    compiled = managed_official_compiled_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="pinned_prompt_world_state",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260712,
        rule_set=compiled.rule_set,
    )
    state.rule_set = copy.deepcopy(compiled.snapshot)
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=compiled.rule_set,
        rng=random.Random(1),
    )
    round_state = RoundState(number=1, players=[player.name for player in state.players])

    world_state = engine._world_state(state.players[0], [], round_state)
    snapshot = world_state["rule_set_snapshot"]

    assert snapshot == state.rule_set
    assert snapshot is not state.rule_set
    assert isinstance(snapshot, dict)
    assert snapshot["roles"] is not state.rule_set["roles"]
    snapshot["roles"][0]["role"] = "tampered"
    assert state.rule_set["roles"][0]["role"] != "tampered"
    assert world_state["sheriff_election_open"] is True

    state.sheriff_badge_lost = True
    post_election_world_state = engine._world_state(state.players[0], [], round_state)
    assert post_election_world_state["sheriff_election_open"] is False


def test_world_state_marks_four_player_endgame_pressure() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="endgame_test",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260614,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    players = state.player_by_name()
    active_players = ["6号玩家", "9号玩家", "10号玩家", "12号玩家"]
    round_state = RoundState(number=5, players=active_players)
    for player in state.players:
        if player.gamestate:
            player.gamestate.current_players = active_players

    world_state = engine._world_state(players["6号玩家"], [], round_state)

    assert any("当前存活 4 人" in line for line in world_state["endgame_context"])
    assert any("错误放逐" in line for line in world_state["endgame_context"])


def test_world_state_includes_debate_guidance_for_current_speaker() -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="debate_guidance_world_state",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=2026061504,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    active_players = [player.name for player in state.players]
    player = state.players[1]
    player.personality = "常用表达: 我先盘票型；这里不急着站死"
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.debate.append(
        DebateEntry(speaker=active_players[0], message="我先盘票型。第一轮先听发言。")
    )

    world_state = engine._world_state(player, [], round_state)

    assert "debate_guidance" in world_state
    assert any("第 2/6 位" in line for line in world_state["debate_guidance"])
    assert any("避免复用" in line for line in world_state["debate_guidance"])


def test_world_state_debate_guidance_uses_round_speech_order() -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="debate_guidance_speech_order",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=2026061504,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    active_players = [player.name for player in state.players]
    player = state.players[1]
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.speech_order = [
        active_players[0],
        active_players[2],
        active_players[3],
        active_players[4],
        active_players[1],
        active_players[5],
    ]

    world_state = engine._world_state(player, [], round_state)

    assert any("第 5/6 位" in line for line in world_state["debate_guidance"])


def test_player_action_prompt_uses_seat_labels_and_maps_choice_to_internal_name() -> None:
    class SeatLabelChoiceProvider:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            del model, temperature
            self.prompts.append(prompt)
            return json.dumps(
                {"reasoning": "2号玩家发言前后矛盾。", "vote": "2号玩家"},
                ensure_ascii=False,
            )

    rule_set = get_rule_set("starter_6")
    custom_names = ["阿青", "白石", "南风", "岚", "乌木", "烛火"]
    state = initialize_game_state(
        session_id="seat_label_prompt_mapping",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260709,
        rule_set=rule_set,
        player_configs=[
            PlayerConfig(
                seat=index,
                profile_id=None,
                name=name,
                model="",
                personality_id="balanced",
                personality="",
                appearance_id="default",
                avatar_prompt="",
                tags=(),
            )
            for index, name in enumerate(custom_names, start=1)
        ],
    )
    provider = SeatLabelChoiceProvider()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=1,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())

    choice, action_log = engine._player_action(
        player=state.players[0],
        action="vote",
        options=[state.players[1].name],
        result_key="vote",
        round_state=round_state,
        phase="day",
    )

    assert choice == "白石"
    assert action_log.choice == "白石"
    assert action_log.lm_log.result == {
        "reasoning": "2号玩家发言前后矛盾。",
        "vote": "2号玩家",
    }
    assert provider.prompts
    prompt = provider.prompts[0]
    assert "你是1号玩家，身份是" in prompt
    assert "当前存活玩家：1号玩家、2号玩家、3号玩家、4号玩家、5号玩家、6号玩家" in prompt
    assert "候选人：2号玩家" in prompt
    for name in custom_names:
        assert name not in prompt


def test_action_quality_warning_event_is_published_for_stage_mismatch() -> None:
    class CapturingSink:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def publish(self, event_type: str, **kwargs: object) -> None:
            self.events.append({"type": event_type, **kwargs})

    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="quality_test",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=20260614,
        rule_set=rule_set,
    )
    sink = CapturingSink()
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
        event_sink=sink,
        rng=random.Random(1),
    )
    round_state = RoundState(number=2, players=[player.name for player in state.players])

    engine._publish_action_quality_warnings(
        round_state=round_state,
        phase="day",
        actor="3号玩家",
        action="sheriff_speech",
        text="我退水，警徽投给8号。",
    )

    warning_events = [event for event in sink.events if event["type"] == "action_quality_warning"]
    assert warning_events
    assert warning_events[0]["payload"]["warnings"] == ["sheriff_speech_mentions_withdraw"]


def test_debate_action_quality_warning_uses_prior_round_context() -> None:
    sink = CapturingEventSink()
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="debate_quality_warning",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=2026061505,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
        event_sink=sink,
        rng=random.Random(1),
    )
    player = state.players[1]
    player.personality = "常用表达: 我先盘票型；这里不急着站死"
    round_state = RoundState(number=1, players=[player.name for player in state.players])
    round_state.debate.append(
        DebateEntry(
            speaker=state.players[0].name,
            message="我先盘票型。第一轮全票挂警徽定狼。",
        )
    )

    engine._publish_action_quality_warnings(
        round_state=round_state,
        phase="day",
        actor=player.name,
        action=ACTION_DEBATE,
        text="我先盘票型。第一轮全票挂警徽定狼，这里不急着站死。",
        prior_texts=[entry.message for entry in round_state.debate],
        personality=player.personality,
    )

    warning_event = next(
        event for event in sink.events if event["type"] == "action_quality_warning"
    )
    assert "catchphrase_overuse" in warning_event["payload"]["warnings"]
    assert "repeated_debate_phrase" in warning_event["payload"]["warnings"]


def test_round_log_deserializes_werewolf_consensus_logs() -> None:
    payload = {
        "number": 1,
        "werewolf_discussion": [
            {
                "actor": "Wolf",
                "action": "werewolf_discuss",
                "options": ["Alice", "Bob"],
                "choice": "Alice",
                "lm_log": {
                    "prompt": "discussion prompt",
                    "raw_response": "{}",
                    "result": {"target": "Alice", "message": "建议袭击 Alice。"},
                },
            }
        ],
        "werewolf_votes": [
            [
                {
                    "actor": "Wolf",
                    "action": "werewolf_kill_vote",
                    "options": ["Alice"],
                    "choice": "Alice",
                    "lm_log": {
                        "prompt": "vote prompt",
                        "raw_response": "{}",
                        "result": {"target": "Alice"},
                    },
                }
            ]
        ],
    }

    round_log = round_log_from_dict(payload)

    assert round_log.werewolf_discussion[0].action == "werewolf_discuss"
    assert round_log.werewolf_discussion[0].lm_log.result == {
        "target": "Alice",
        "message": "建议袭击 Alice。",
    }
    assert round_log.werewolf_votes[0][0].action == "werewolf_kill_vote"
    assert round_log.werewolf_votes[0][0].lm_log.result == {"target": "Alice"}
    serialized = round_log.to_dict()
    default_action_metadata = {
        "invalid_value": None,
        "fallback_choice": None,
        "fallback_reason": None,
        "attempt_count": 1,
    }
    assert serialized["werewolf_discussion"] == [
        {**payload["werewolf_discussion"][0], **default_action_metadata}
    ]
    assert serialized["werewolf_votes"] == [
        [{**payload["werewolf_votes"][0][0], **default_action_metadata}]
    ]


def test_werewolf_kill_vote_requests_active_wolves_concurrently() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_parallel_werewolf_kill_vote",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=500,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    active_wolves = [player.name for player in state.players if player.role == "狼人"]
    non_wolves = [player.name for player in state.players if player.role != "狼人"]
    target = non_wolves[0]
    provider = BarrierActionProvider(
        action_key="werewolf_kill_vote",
        result_key="target",
        response_value_by_actor={wolf: target for wolf in active_wolves},
        expected_calls=len(active_wolves),
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    attacked = engine._run_werewolf_kill_consensus(
        round_state,
        round_log,
        active_players,
        active_wolves,
        non_wolves,
    )

    assert attacked == target
    assert [
        actor for action, actor in provider.actions if action == "werewolf_kill_vote"
    ] == active_wolves
    assert round_state.werewolf_vote_rounds[0]["votes"] == {wolf: target for wolf in active_wolves}
    assert [log.actor for log in round_log.werewolf_votes[0]] == active_wolves


def _extract_options(prompt: str) -> list[str]:
    marker = next(
        (candidate for candidate in ("候选人：", "候选选项：") if candidate in prompt), ""
    )
    if not marker:
        return []
    tail = prompt.split(marker, 1)[1].split("。", 1)[0]
    return [option.strip() for option in tail.split("、") if option.strip()]


def _extract_actor_name(prompt: str) -> str:
    marker = "- 你是"
    if marker not in prompt:
        return ""
    return prompt.split(marker, 1)[1].split("，", 1)[0]


def _extract_living_players(prompt: str) -> list[str]:
    marker = "- 当前存活玩家："
    if marker not in prompt:
        return []
    line = prompt.split(marker, 1)[1].splitlines()[0]
    return [name.strip() for name in line.split("、") if name.strip()]


def test_initialize_game_state_applies_player_config_snapshot() -> None:
    rule_set = get_rule_set("classic_8")
    config = PlayerConfig(
        seat=1,
        profile_id="profile-alpha",
        name="控场位",
        model="profile-model",
        personality_id="analytical",
        personality="重视票型和前后逻辑。",
        appearance_id="moonlit",
        avatar_prompt="silver moon portrait",
        tags=("控场", "夜晚"),
        avatar_image_url="/api/v1/player-profiles/avatar/profile-alpha.png",
    )

    state = initialize_game_state(
        session_id="session_test_player_config",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=7,
        rule_set=rule_set,
        player_configs=[config],
    )

    player = state.players[0]
    assert player.name == "控场位"
    assert player.model == "profile-model"
    assert player.profile_id == "profile-alpha"
    assert player.personality_id == "analytical"
    assert player.personality == "重视票型和前后逻辑。"
    assert player.appearance_id == "moonlit"
    assert player.avatar_prompt == "silver moon portrait"
    assert player.avatar_image_url == "/api/v1/player-profiles/avatar/profile-alpha.png"
    assert player.tags == ["控场", "夜晚"]
    assert state.players[1].gamestate is not None
    assert state.players[1].gamestate.current_players[0] == "控场位"


def test_initialize_game_state_rejects_duplicate_config_seats() -> None:
    rule_set = get_rule_set("classic_8")
    configs = [
        PlayerConfig(
            seat=1,
            profile_id=None,
            name="一号位",
            model="",
            personality_id="balanced",
            personality="",
            appearance_id="default",
            avatar_prompt="",
            tags=(),
        ),
        PlayerConfig(
            seat=1,
            profile_id=None,
            name="重复一号位",
            model="",
            personality_id="balanced",
            personality="",
            appearance_id="default",
            avatar_prompt="",
            tags=(),
        ),
    ]

    with pytest.raises(ValueError, match="Duplicate player config seat: 1"):
        initialize_game_state(
            session_id="session_test_duplicate_config_seats",
            villager_model="villager-model",
            werewolf_model="wolf-model",
            seed=7,
            rule_set=rule_set,
            player_configs=configs,
        )


def test_initialize_game_state_rejects_duplicate_effective_names() -> None:
    rule_set = get_rule_set("classic_8")
    configs = [
        PlayerConfig(
            seat=1,
            profile_id=None,
            name="同名玩家",
            model="",
            personality_id="balanced",
            personality="",
            appearance_id="default",
            avatar_prompt="",
            tags=(),
        ),
        PlayerConfig(
            seat=2,
            profile_id=None,
            name="同名玩家",
            model="",
            personality_id="balanced",
            personality="",
            appearance_id="default",
            avatar_prompt="",
            tags=(),
        ),
    ]

    with pytest.raises(ValueError, match="Duplicate player name: 同名玩家"):
        initialize_game_state(
            session_id="session_test_duplicate_effective_names",
            villager_model="villager-model",
            werewolf_model="wolf-model",
            seed=7,
            rule_set=rule_set,
            player_configs=configs,
        )


def test_player_config_without_model_falls_back_to_role_model() -> None:
    rule_set = get_rule_set("classic_8")
    configs = [
        PlayerConfig(
            seat=seat,
            profile_id=f"profile-{seat}",
            name=f"席位{seat}",
            model="",
            personality_id="balanced",
            personality="稳健推进。",
            appearance_id="default",
            avatar_prompt="",
            tags=(),
        )
        for seat in range(1, rule_set.player_count + 1)
    ]

    state = initialize_game_state(
        session_id="session_test_player_config_model_fallback",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=7,
        rule_set=rule_set,
        player_configs=configs,
    )

    model_group_by_role = {role_spec.role: role_spec.model_group for role_spec in rule_set.roles}
    for player in state.players:
        if model_group_by_role[player.role] == MODEL_GROUP_WEREWOLF:
            assert player.model == "wolf-model"
        else:
            assert player.model == "villager-model"


def test_world_state_includes_player_personality() -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_world_state_personality",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=7,
        rule_set=rule_set,
    )
    state.players[0].personality = "主动施压，寻找发言矛盾。"
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )

    world_state = engine._world_state(
        state.players[0],
        ["选项A"],
        RoundState(number=1, players=[player.name for player in state.players]),
    )

    assert world_state["personality"] == "主动施压，寻找发言矛盾。"
    prompt, _schema = build_prompt("debate", world_state)
    assert "- 你的性格设定：主动施压，寻找发言矛盾。" in prompt


def test_compose_player_profile_prompt_includes_rich_strategy_fields() -> None:
    prompt = compose_player_profile_prompt(
        SimpleNamespace(
            short_description="",
            background_story="",
            speaking_style="分点发言，先归纳再判断。",
            strategy_profile="logic_leader",
            risk_tolerance=3,
            bluffing_tendency=3,
            trust_tendency=3,
            leadership_tendency=3,
            talkativeness=4,
            catchphrases=[],
            example_messages=["我先把票型和发言顺序对一下。"],
        ),
        "先找矛盾，再给站边。",
    )

    assert "先找矛盾，再给站边。" in prompt
    assert "发言风格: 分点发言，先归纳再判断。" in prompt
    assert "狼人杀策略: 偏逻辑带队，主动整理票型、发言顺序和矛盾链。" in prompt
    assert "发言活跃: 4/5" in prompt
    assert "示例发言: 我先把票型和发言顺序对一下。" in prompt


def test_compose_player_profile_prompt_falls_back_for_unknown_strategy() -> None:
    prompt = compose_player_profile_prompt(
        SimpleNamespace(
            strategy_profile="legacy_unknown_strategy",
            catchphrases=[],
            example_messages=[],
        ),
        "稳健观察。",
    )

    assert "稳健观察。" in prompt
    assert "狼人杀策略: 稳健观察，按证据推进，不轻易极端站边。" in prompt


def test_player_from_dict_defaults_legacy_profile_fields() -> None:
    player = player_from_dict(
        {
            "name": "张三",
            "role": "狼人",
            "model": "deepseek-chat",
            "observations": [],
        }
    )

    assert player.profile_id is None
    assert player.personality_id == "balanced"
    assert player.personality == ""
    assert player.appearance_id == "default"
    assert player.avatar_prompt == ""
    assert player.avatar_image_url == ""
    assert player.tags == []


def test_run_game_with_deepseek_models_writes_complete_chinese_logs(
    record_store: DatabaseReplayStore,
) -> None:
    result = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )
    replay = record_store.load_session(result.session_id)
    state = replay["state"]
    logs = replay["logs"]

    assert result.winner in {"好人阵营", "狼人阵营"}
    assert result.session_id.startswith("game_")
    assert replay["status"] == "complete"
    assert replay["resumable"] is False
    assert state["winner"] == result.winner
    assert len(state["players"]) == 8
    assert state["error_message"] == ""
    assert {player["role"] for player in state["players"]} == {"狼人", "预言家", "守卫", "村民"}
    assert any(
        "第" in observation for player in state["players"] for observation in player["observations"]
    )
    assert logs[0]["debate"]
    assert logs[0]["summaries"]
    assert "狼人杀" in logs[0]["debate"][0]["lm_log"]["prompt"]
    assert "我认为" in state["rounds"][0]["debate"][0]["message"]


def test_run_game_executes_and_saves_the_supplied_managed_snapshot_without_catalog_lookup(
    monkeypatch: pytest.MonkeyPatch,
    record_store: DatabaseReplayStore,
) -> None:
    compiled = managed_official_compiled_rule_set("starter_6")
    expected_snapshot = copy.deepcopy(compiled.snapshot)

    def reject_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("new-game execution must not query a rule catalog")

    def capturing_initializer(**kwargs: object):
        assert kwargs["rule_set"] is compiled.rule_set
        return initialize_game_state(**kwargs)

    def capturing_engine(**kwargs: object):
        assert kwargs["rule_set"] is compiled.rule_set
        return GameEngine(**kwargs)

    monkeypatch.setattr("app.werewolf.runner.get_rule_set", reject_lookup, raising=False)
    monkeypatch.setattr("app.werewolf.rules.get_rule_set", reject_lookup)
    monkeypatch.setattr(
        "app.rule_sets.service.resolve_published_rule_set",
        reject_lookup,
    )
    monkeypatch.setattr("app.werewolf.runner.initialize_game_state", capturing_initializer)
    monkeypatch.setattr("app.werewolf.runner.GameEngine", capturing_engine)

    result = run_game(
        record_store=record_store,
        compiled_rule_set=compiled,
        seed=31,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    state = record_store.load_session(result.session_id)["state"]
    assert state["rule_set"] == expected_snapshot
    assert state["rule_set"]["revision_id"] == compiled.revision_id
    assert state["rule_set"]["revision_no"] == compiled.revision_no
    assert state["rule_set"]["schema_version"] == compiled.schema_version
    assert state["rule_set"]["content_hash"] == compiled.content_hash
    assert len(state["players"]) == compiled.rule_set.player_count
    assert compiled.snapshot == expected_snapshot


def test_run_game_checkpoint_uses_independent_exact_compiled_snapshot_copies() -> None:
    compiled = managed_official_compiled_rule_set("starter_6")
    caller_snapshot = copy.deepcopy(compiled.snapshot)

    class CapturingRecordStore:
        def __init__(self) -> None:
            self.checkpoints: list[dict[str, object]] = []
            self.saved_state = None

        def save_resume_checkpoint(
            self,
            _session_id: str,
            checkpoint: dict[str, object],
        ) -> None:
            self.checkpoints.append(checkpoint)

        def save_game(self, state, _logs) -> None:
            self.saved_state = state

        def clear_resume_checkpoint(self, _session_id: str) -> None:
            raise AssertionError("a failed run must retain its checkpoint")

    class FailingProvider:
        def complete_json(self, **_request: object) -> str:
            raise RuntimeError("model provider offline")

    store = CapturingRecordStore()
    with pytest.raises(GameRunError, match="model provider offline"):
        run_game(
            record_store=store,
            compiled_rule_set=compiled,
            villager_model="villager-model",
            werewolf_model="werewolf-model",
            seed=23,
            max_rounds=8,
            provider=FailingProvider(),
            session_id="game_1200abcd",
        )

    assert store.saved_state is not None
    assert store.checkpoints
    checkpoint = store.checkpoints[-1]
    run_params = checkpoint["run_params"]
    assert isinstance(run_params, dict)
    assert set(run_params) == {
        "villager_model",
        "werewolf_model",
        "seed",
        "max_rounds",
        "player_configs",
        "rule_set_id",
        "revision_id",
        "revision_no",
        "content_hash",
        "rule_set_snapshot",
    }
    assert run_params["rule_set_id"] == compiled.rule_set.id
    assert run_params["revision_id"] == compiled.revision_id
    assert run_params["revision_no"] == compiled.revision_no
    assert run_params["content_hash"] == compiled.content_hash
    assert run_params["rule_set_snapshot"] == caller_snapshot
    assert store.saved_state.rule_set == caller_snapshot
    checkpoint_state = checkpoint["state_at_round_start"]
    assert isinstance(checkpoint_state, dict)
    assert checkpoint_state["rule_set"] == run_params["rule_set_snapshot"]
    assert checkpoint_state["rule_set"] is not run_params["rule_set_snapshot"]
    assert store.saved_state.rule_set is not compiled.snapshot
    assert run_params["rule_set_snapshot"] is not compiled.snapshot
    assert run_params["rule_set_snapshot"] is not store.saved_state.rule_set

    compiled.snapshot["name"] = "caller-only mutation"
    assert store.saved_state.rule_set == caller_snapshot
    assert run_params["rule_set_snapshot"] == caller_snapshot
    store.saved_state.rule_set["name"] = "state-only mutation"
    assert run_params["rule_set_snapshot"] == caller_snapshot


def test_run_game_rejects_the_removed_rule_set_id_only_contract(
    record_store: DatabaseReplayStore,
) -> None:
    with pytest.raises(TypeError):
        run_game(
            record_store=record_store,
            rule_set_id="starter_6",
            seed=3,
            max_rounds=0,
            provider=ScriptedChineseProvider(),
        )


def test_run_game_defaults_to_agent_plan_when_plan_key_is_configured(
    tmp_path,
    monkeypatch,
    record_store: DatabaseReplayStore,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_MODEL=deepseek-v4-flash\n"
        "ARK_AGENT_PLAN_API_KEY=agent-plan-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    state = record_store.load_session(result.session_id)["state"]

    assert {player["model"] for player in state["players"]} == {"doubao-seed-2-0-lite-260215"}


def test_run_game_is_reproducible_for_same_seed(
    record_store: DatabaseReplayStore,
    second_record_store: DatabaseReplayStore,
) -> None:
    first = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=11,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )
    second = run_game(
        record_store=second_record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=11,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    first_state = record_store.load_session(first.session_id)["state"]
    second_state = second_record_store.load_session(second.session_id)["state"]

    assert first.winner == second.winner
    assert first_state["players"] == second_state["players"]


def test_run_game_records_partial_state_when_max_rounds_is_exceeded(
    record_store: DatabaseReplayStore,
) -> None:
    with pytest.raises(GameRunError) as error:
        run_game(
            record_store=record_store,
            compiled_rule_set=legacy_official_compiled_rule_set(),
            seed=3,
            max_rounds=0,
            provider=ScriptedChineseProvider(),
        )

    assert error.value.session_id is not None
    replay = record_store.load_session(error.value.session_id)
    assert replay["status"] == "partial"
    assert "Maximum rounds exceeded" in replay["state"]["error_message"]


def test_engine_raises_max_rounds_after_positive_limit_without_winner() -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_positive_max_rounds",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=202,
        rule_set=rule_set,
    )
    target = next(player.name for player in state.players if player.role == SEER)
    engine = GameEngine(
        state=state,
        provider=NoWinnerRoundProvider(protected_target=target),
        max_rounds=1,
        rule_set=rule_set,
    )

    with pytest.raises(MaxRoundsExceeded):
        engine.run()

    assert not state.winner
    assert len(state.rounds) == 1


def test_run_game_accepts_custom_session_id(record_store: DatabaseReplayStore) -> None:
    result = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
        event_sink=NullEventSink(),
    )

    assert result.session_id == "game_1200abcd"
    assert record_store.load_session("game_1200abcd")["status"] == "complete"


class CapturingEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append({"type": event_type, **kwargs})


def test_run_game_publishes_live_events(record_store: DatabaseReplayStore) -> None:
    sink = CapturingEventSink()

    run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
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


def test_run_game_publishes_streaming_model_events(record_store: DatabaseReplayStore) -> None:
    sink = CapturingEventSink()

    with pytest.raises(GameRunError, match="Maximum rounds exceeded"):
        run_game(
            record_store=record_store,
            compiled_rule_set=legacy_official_compiled_rule_set(),
            seed=21,
            max_rounds=1,
            provider=StreamingSpeechProvider(),
            session_id="game_1200abcd",
            event_sink=sink,
        )

    event_types = [event["type"] for event in sink.events]
    assert "model_request_started" in event_types
    assert "model_response_delta" in event_types
    assert "model_response_received" in event_types
    assert "action_parsed" in event_types

    started_event = next(event for event in sink.events if event["type"] == "model_request_started")
    delta_event = next(event for event in sink.events if event["type"] == "model_response_delta")
    response_event = next(
        event for event in sink.events if event["type"] == "model_response_received"
    )
    assert started_event["payload"]["request_id"].startswith("req_")
    assert "world_state" not in started_event["payload"]
    assert "prompt" not in started_event["payload"]
    assert delta_event["payload"]["request_id"].startswith("req_")
    assert delta_event["payload"]["field"] == "say"
    assert delta_event["payload"]["is_public"] is True
    assert response_event["payload"]["request_id"].startswith("req_")
    assert "prompt" not in response_event["payload"]
    assert "raw_response" not in response_event["payload"]


def test_protected_night_attack_records_attack_without_eliminating_target() -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_protected_attack",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=202,
        rule_set=rule_set,
    )
    target = next(player.name for player in state.players if player.role == SEER)
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=ProtectedNightProvider(target),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.attacked == target
    assert round_state.protected == target
    assert round_state.eliminated is None
    assert target in active_players
    state_event = [event for event in sink.events if event["type"] == "state_updated"][-1]
    payload = state_event["payload"]
    assert payload["attacked"] == target
    assert payload["protected"] == target
    assert payload["eliminated"] is None
    assert target in payload["active_players"]


def test_run_game_event_sink_does_not_change_final_logs(
    record_store: DatabaseReplayStore,
    second_record_store: DatabaseReplayStore,
) -> None:
    baseline = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
    )
    with_sink = run_game(
        record_store=second_record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
        event_sink=CapturingEventSink(),
    )

    assert _read_db_outputs(second_record_store, with_sink.session_id) == _read_db_outputs(
        record_store,
        baseline.session_id,
    )


def test_live_model_events_do_not_publish_internal_model_payloads(
    record_store: DatabaseReplayStore,
) -> None:
    sink = CapturingEventSink()
    run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
        event_sink=sink,
    )

    model_events = [
        event
        for event in sink.events
        if event["type"] in {"model_request_started", "model_response_received", "action_parsed"}
    ]
    assert model_events
    for event in model_events:
        payload = event.get("payload")
        assert isinstance(payload, dict)
        assert "world_state" not in payload
        assert "prompt" not in payload
        assert "raw_response" not in payload
        result = payload.get("result")
        if isinstance(result, dict):
            assert "reasoning" not in result


def test_run_game_uses_starter_6_rule_set(record_store: DatabaseReplayStore) -> None:
    result = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set("starter_6"),
        seed=31,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    state = record_store.load_session(result.session_id)["state"]

    assert state["rule_set"]["id"] == "starter_6"
    assert state["rule_set"]["name"] == "新手 6 人快局"
    assert len(state["players"]) == 6
    assert _role_counts(state["players"]) == {"狼人": 1, "预言家": 1, "守卫": 1, "村民": 3}


def test_run_game_uses_social_8_rule_set_without_divine_actions(
    record_store: DatabaseReplayStore,
) -> None:
    result = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set("social_8"),
        seed=37,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    replay = record_store.load_session(result.session_id)
    state = replay["state"]
    logs = replay["logs"]

    assert len(state["players"]) == 8
    assert _role_counts(state["players"]) == {"狼人": 2, "村民": 6}
    assert logs[0]["protect"] is None
    assert logs[0]["investigate"] is None


def test_run_game_uses_explicit_legacy_classic_8_rule_set(
    record_store: DatabaseReplayStore,
) -> None:
    result = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=41,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    state = record_store.load_session(result.session_id)["state"]

    assert state["rule_set"]["id"] == "classic_8"
    assert len(state["players"]) == 8


def test_run_game_uses_12_player_seer_witch_hunter_idiot_rule_set(
    record_store: DatabaseReplayStore,
) -> None:
    result = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set("classic_12_seer_witch_hunter_idiot"),
        seed=54,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    replay = record_store.load_session(result.session_id)
    state = replay["state"]
    logs = replay["logs"]

    assert state["rule_set"]["id"] == "classic_12_seer_witch_hunter_idiot"
    assert len(state["players"]) == 12
    assert _role_counts(state["players"]) == {
        "狼人": 4,
        "预言家": 1,
        "女巫": 1,
        "猎人": 1,
        "白痴": 1,
        "村民": 4,
    }
    assert "night_deaths" in state["rounds"][0]
    assert "day_deaths" in state["rounds"][0]
    assert "witch_save" in logs[0]
    assert "witch_poison" in logs[0]
    assert "hunter_shoot" in logs[0]


def test_12_player_initialization_sets_role_counts_and_wolf_teammates() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_12_player_init",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=42,
        rule_set=rule_set,
    )

    assert len(state.players) == 12
    assert _role_counts([player.to_dict() for player in state.players]) == {
        "狼人": 4,
        "预言家": 1,
        "女巫": 1,
        "猎人": 1,
        "白痴": 1,
        "村民": 4,
    }
    wolves = [player for player in state.players if player.role == "狼人"]
    for wolf in wolves:
        assert wolf.gamestate is not None
        assert sorted(wolf.gamestate.wolf_teammates) == sorted(
            teammate.name for teammate in wolves if teammate.name != wolf.name
        )


def test_12_player_initialization_shuffles_roles_across_seats() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_12_player_shuffled_roles",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=42,
        rule_set=rule_set,
    )
    repeated_state = initialize_game_state(
        session_id="session_test_12_player_shuffled_roles_repeated",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=42,
        rule_set=rule_set,
    )
    rule_order = [role_spec.role for role_spec in rule_set.roles for _ in range(role_spec.count)]
    roles_by_seat = [player.role for player in state.players]
    non_wolf_roles_by_seat = [role for role in roles_by_seat if role != WEREWOLF]

    assert roles_by_seat != rule_order
    assert roles_by_seat[:4] != [WEREWOLF, WEREWOLF, WEREWOLF, WEREWOLF]
    assert non_wolf_roles_by_seat[0] != SEER
    assert [(player.name, player.role) for player in state.players] == [
        (player.name, player.role) for player in repeated_state.players
    ]


def test_sheriff_state_serializes_to_game_and_round_payloads() -> None:
    state = initialize_game_state(
        session_id="session_test_sheriff_payload",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=42,
        rule_set=get_rule_set("classic_12_seer_witch_hunter_idiot"),
    )
    state.sheriff = state.players[0].name
    state.players[0].is_sheriff = True
    round_state = RoundState(number=1, players=[player.name for player in state.players])
    round_state.sheriff = state.sheriff
    round_state.sheriff_candidates = [state.players[0].name, state.players[1].name]
    round_state.sheriff_speeches = [{"speaker": state.players[0].name, "message": "我上警争警徽。"}]
    round_state.sheriff_speech_order = [state.players[1].name, state.players[0].name]
    round_state.sheriff_speech_direction = "逆时针"
    round_state.sheriff_withdrawn = [state.players[1].name]
    round_state.sheriff_final_candidates = [state.players[0].name]
    round_state.sheriff_voters = [state.players[2].name]
    round_state.sheriff_votes = {state.players[2].name: state.players[0].name}
    round_state.sheriff_pk_candidates = [state.players[0].name, state.players[3].name]
    round_state.sheriff_pk_speeches = [{"speaker": state.players[3].name, "message": "我进入 PK。"}]
    round_state.sheriff_runoff_votes = {state.players[2].name: state.players[3].name}
    round_state.sheriff_elected = state.players[0].name
    round_state.speech_order = [player.name for player in state.players]
    round_state.vote_weights = {state.players[0].name: 1.5}
    state.rounds.append(round_state)

    payload = state.to_dict()

    assert payload["sheriff"] == state.players[0].name
    assert payload["players"][0]["is_sheriff"] is True
    round_payload = payload["rounds"][0]
    assert round_payload["sheriff"] == state.players[0].name
    assert round_payload["sheriff_candidates"] == [state.players[0].name, state.players[1].name]
    assert round_payload["sheriff_speeches"] == [
        {"speaker": state.players[0].name, "message": "我上警争警徽。"}
    ]
    assert round_payload["sheriff_speech_order"] == [
        state.players[1].name,
        state.players[0].name,
    ]
    assert round_payload["sheriff_speech_direction"] == "逆时针"
    assert round_payload["sheriff_withdrawn"] == [state.players[1].name]
    assert round_payload["sheriff_final_candidates"] == [state.players[0].name]
    assert round_payload["sheriff_voters"] == [state.players[2].name]
    assert round_payload["sheriff_votes"] == {state.players[2].name: state.players[0].name}
    assert round_payload["sheriff_pk_candidates"] == [
        state.players[0].name,
        state.players[3].name,
    ]
    assert round_payload["sheriff_pk_speeches"] == [
        {"speaker": state.players[3].name, "message": "我进入 PK。"}
    ]
    assert round_payload["sheriff_runoff_votes"] == {state.players[2].name: state.players[3].name}
    assert round_payload["sheriff_elected"] == state.players[0].name
    assert round_payload["speech_order"] == [player.name for player in state.players]
    assert round_payload["vote_weights"] == {state.players[0].name: 1.5}


def test_sheriff_action_logs_serialize_new_election_steps() -> None:
    from app.werewolf.lm import LmLog
    from app.werewolf.models import ActionLog

    log = RoundLog(number=1)
    action = ActionLog(
        actor="Alice",
        action="sheriff_speech",
        options=[],
        choice="我竞选警长。",
        lm_log=LmLog(prompt="prompt", raw_response="{}", result={"say": "我竞选警长。"}),
    )
    log.sheriff_speech.append(action)
    log.sheriff_withdraw.append(
        ActionLog(
            actor="Alice",
            action="sheriff_withdraw",
            options=["退水", "不退水"],
            choice="不退水",
            lm_log=LmLog(prompt="prompt", raw_response="{}", result={"withdraw": "不退水"}),
        )
    )
    log.sheriff_pk_speech.append(
        ActionLog(
            actor="Alice",
            action="sheriff_pk_speech",
            options=[],
            choice="我进行 PK 发言。",
            lm_log=LmLog(prompt="prompt", raw_response="{}", result={"say": "我进行 PK 发言。"}),
        )
    )
    log.sheriff_runoff_votes.append(
        ActionLog(
            actor="Bob",
            action="sheriff_runoff_vote",
            options=["Alice", "Cora"],
            choice="Alice",
            lm_log=LmLog(prompt="prompt", raw_response="{}", result={"sheriff_vote": "Alice"}),
        )
    )

    payload = log.to_dict()

    assert payload["sheriff_speech"][0]["action"] == "sheriff_speech"
    assert payload["sheriff_withdraw"][0]["choice"] == "不退水"
    assert payload["sheriff_pk_speech"][0]["action"] == "sheriff_pk_speech"
    assert payload["sheriff_runoff_votes"][0]["choice"] == "Alice"


def test_sheriff_prompt_actions_render_chinese_instructions() -> None:
    world_state = {
        "round": 1,
        "name": "Alice",
        "role": "村民",
        "remaining_players": "Alice、Bob、Cora",
        "options": "Alice、Bob",
        "observations": [],
        "debate": [],
        "rule_text": "你正在进行一局数字版狼人杀。",
    }

    run_prompt, run_schema = build_prompt("sheriff_run", world_state)
    speech_prompt, speech_schema = build_prompt("sheriff_speech", world_state)
    withdraw_prompt, withdraw_schema = build_prompt("sheriff_withdraw", world_state)
    vote_prompt, vote_schema = build_prompt("sheriff_vote", world_state)
    pk_prompt, pk_schema = build_prompt("sheriff_pk_speech", world_state)
    runoff_prompt, runoff_schema = build_prompt("sheriff_runoff_vote", world_state)
    order_prompt, order_schema = build_prompt("speech_order", world_state)
    badge_prompt, badge_schema = build_prompt("sheriff_badge", world_state)

    assert "警长竞选" in run_prompt
    assert run_schema["required"] == ["reasoning", "run"]
    assert "警上竞选发言" in speech_prompt
    assert speech_schema["required"] == ["reasoning", "say"]
    assert "退水" in withdraw_prompt
    assert withdraw_schema["required"] == ["reasoning", "withdraw"]
    assert "警长投票" in vote_prompt
    assert vote_schema["required"] == ["reasoning", "sheriff_vote"]
    assert "PK 发言" in pk_prompt
    assert pk_schema["required"] == ["reasoning", "say"]
    assert "二轮警下投票" in runoff_prompt
    assert runoff_schema["required"] == ["reasoning", "sheriff_vote"]
    assert "发言方向" in order_prompt
    assert order_schema["required"] == ["reasoning", "speech_order"]
    assert "移交警徽" in badge_prompt
    assert badge_schema["required"] == ["reasoning", "badge"]


def test_sheriff_speech_prompt_separates_badge_use_from_seer_investigation_plan() -> None:
    world_state = {
        "round": 1,
        "name": "Alice",
        "role": "村民",
        "remaining_players": "Alice、Bob、Cora",
        "options": "",
        "observations": [],
        "debate": [],
        "rule_text": "你正在进行一局数字版狼人杀。",
    }

    villager_prompt, _schema = build_prompt("sheriff_speech", world_state)
    seer_prompt, _schema = build_prompt(
        "sheriff_speech",
        {**world_state, "role": "预言家"},
    )

    assert "发言方向、归票和警徽移交原则" in villager_prompt
    assert "警徽流专指预言家的后续查验计划" in villager_prompt
    assert "不要承诺“先验、再验、今晚验”" in villager_prompt
    assert "需要公开说明竞选警长的理由、警徽流思路" not in villager_prompt
    assert "已公开的查验结果" in seer_prompt
    assert "这种查验计划才叫警徽流" in seer_prompt


def test_sheriff_speech_prompt_compacts_prior_speeches_without_duplicate_public_fact() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_compact_sheriff_speech_context",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=71,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    prior_speaker = state.players[0]
    next_speaker = state.players[1]
    long_speech = (
        "【竞选理由】我会整理票型。\n"
        "【警徽流】先验3号，再验5号。\n"
        + "这段前置位发言不应被后置位整段照抄。" * 24
    )
    state.public_facts.append(
        {
            "round_number": 1,
            "category": "claim",
            "text": f"第1轮警上发言：{prior_speaker.name}：{long_speech}",
            "schema_version": 3,
            "fact_id": "fact-sheriff-speech-context",
            "stage": "sheriff_speech",
            "actor": prior_speaker.name,
            "retention": "important",
            "source_opportunity_id": None,
            "details": {},
        }
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.sheriff_candidates = active_players[:3]
    round_state.sheriff_speech_order = active_players[:3]
    round_state.sheriff_speeches = [
        {"speaker": prior_speaker.name, "message": long_speech}
    ]
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )

    request = engine._build_player_action_request(
        player=next_speaker,
        action=ACTION_SHERIFF_SPEECH,
        options=[],
        result_key="say",
        round_state=round_state,
        phase="day",
    )

    public_facts = request.world_state["public_facts"]
    assert isinstance(public_facts, list)
    assert all("第1轮警上发言" not in str(line) for line in public_facts)
    election_context = request.world_state["sheriff_election"]
    assert isinstance(election_context, list)
    summary_line = next(
        str(line) for line in election_context if "前置位观点摘要" in str(line)
    )
    assert "\n" not in summary_line
    assert summary_line.endswith("…")
    assert len(summary_line.split("）：", 1)[1]) <= 180
    prompt, _schema = build_prompt(ACTION_SHERIFF_SPEECH, request.world_state)
    assert "不要复用其措辞、标题或段落格式" in prompt


def test_werewolf_self_explosion_prompt_renders_double_badge_context() -> None:
    world_state = {
        "round": 1,
        "name": "Alice",
        "role": "狼人",
        "remaining_players": "Alice、Bob、Cora",
        "rule_text": "你正在进行一局数字版狼人杀。",
        "options": "自爆、不自爆",
        "self_explosion_stage": "警上发言前",
        "sheriff": None,
        "sheriff_election_open": True,
        "sheriff_pre_election_bomb_count": 1,
        "rule_set_snapshot": {
            "sheriff_enabled": True,
            "sheriff_vote_weight": 1.5,
            "sheriff_badge_bomb_policy": "double",
            "werewolf_self_explosion_enabled": True,
        },
    }

    prompt, schema = build_prompt("werewolf_self_explosion", world_state)

    assert "行动：狼人自爆判断" in prompt
    assert "警上发言前" in prompt
    assert "双爆吞警徽" in prompt
    assert "第二次警长产生前自爆会导致警徽流失" in prompt
    assert schema["required"] == [
        "reasoning",
        "self_explode",
        "benefit_type",
        "expected_gain",
        "primary_risk",
    ]


def test_self_explosion_context_counts_chain_and_last_wolf_risk() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_self_explosion_context",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=69,
        rule_set=rule_set,
    )
    wolf = next(player.name for player in state.players if player.role == WEREWOLF)
    active_players = [
        wolf,
        *[player.name for player in state.players if player.role != WEREWOLF][:3],
    ]
    first = RoundState(number=1, players=active_players.copy(), werewolf_self_exploded="2号玩家")
    second = RoundState(number=2, players=active_players.copy(), werewolf_self_exploded="7号玩家")
    current = RoundState(number=3, players=active_players.copy())
    state.rounds = [first, second, current]
    engine = GameEngine(
        state=state,
        provider=FakeProvider([]),
        max_rounds=8,
        rule_set=rule_set,
    )
    cursor = PublicStageCursor(
        stage="debate",
        ordered_actors=tuple(active_players),
        completed_actors=tuple(active_players[:2]),
        current_actor=active_players[2],
        timing="before_actor",
    )

    context = engine._self_explosion_decision_context(
        actor=wolf,
        round_state=current,
        active_players=active_players,
        active_wolves=[wolf],
        cursor=cursor,
    )
    prompt, _schema = build_prompt(
        "werewolf_self_explosion",
        {
            **engine._world_state(state.player_by_name()[wolf], [], current),
            "options": "自爆、不自爆",
            "self_explosion_stage": "白天发言前",
            "self_explosion_decision_context": context.to_dict(),
        },
    )

    assert context.total_self_explosions == 2
    assert context.consecutive_self_explosion_rounds == 2
    assert context.active_wolves_before == 1
    assert context.actor_is_last_wolf is True
    assert context.completed_public_speakers == 2
    assert context.pending_public_speakers == 2
    assert context.explosion_would_end_game is True
    assert "已经连续 2 轮发生狼人自爆，默认选择不自爆" in prompt
    assert "你是场上最后一名狼人" in prompt
    assert "自爆会立即结算对局" in prompt


def test_werewolf_self_explosion_requests_active_wolves_concurrently() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_parallel_self_explosion",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=69,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    active_wolves = [player.name for player in state.players if player.role == "狼人"]
    exploding_wolf = active_wolves[1]
    provider = BarrierActionProvider(
        action_key="werewolf_self_explosion",
        result_key="self_explode",
        response_value_by_actor={
            wolf: "自爆" if wolf != active_wolves[0] else "不自爆" for wolf in active_wolves
        },
        expected_calls=len(active_wolves),
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    interrupted = engine._maybe_run_werewolf_self_explosion(
        round_state,
        round_log,
        active_players,
        PublicStageCursor(
            stage="debate",
            ordered_actors=tuple(active_players),
            timing="before_stage",
        ),
    )

    assert interrupted is True
    assert [
        actor for action, actor in provider.actions if action == "werewolf_self_explosion"
    ] == active_wolves
    assert round_state.werewolf_self_exploded == exploding_wolf
    assert round_log.werewolf_self_explosion is not None
    assert round_log.werewolf_self_explosion.decision_schema == "legacy"
    assert round_state.sheriff_election_resolution is not None
    assert round_state.sheriff_election_resolution.outcome == "postponed"
    assert (
        round_state.sheriff_election_resolution.reason_code == "first_pre_election_self_explosion"
    )
    assert round_log.werewolf_self_explosion.actor == exploding_wolf
    assert round_state.interruption is not None
    assert round_state.interruption.stage == "debate"
    assert round_state.interruption.timing == "before_stage"
    assert round_state.interruption.completed_actors == []
    assert round_state.interruption.pending_actors == [player.name for player in state.players]
    private_decision_events = [
        event
        for event in sink.events
        if event["action"] == "werewolf_self_explosion"
        and event["type"]
        in {
            "action_requested",
            "model_request_started",
            "model_response_delta",
            "model_thinking_delta",
            "model_thinking_tick",
            "model_response_received",
            "action_parsed",
        }
    ]
    assert private_decision_events == []

    engine._publish_self_explosion_update(round_state, active_players)

    public_updates = [
        event
        for event in sink.events
        if event["action"] == "werewolf_self_explosion" and event["type"] == "state_updated"
    ]
    assert public_updates
    assert public_updates[-1]["actor"] == exploding_wolf
    assert public_updates[-1]["payload"]["werewolf_self_exploded"] == exploding_wolf
    assert public_updates[-1]["payload"]["interruption"] == round_state.interruption.to_dict()
    assert [
        event["action"]
        for event in sink.events
        if event["type"] == "judge_cue"
        and event["action"] in {"werewolf_self_explosion", "self_explosion_skip"}
    ] == ["werewolf_self_explosion", "self_explosion_skip"]


def test_first_pre_sheriff_self_explosion_ends_day_without_losing_badge() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_first_self_explosion",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=70,
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    active_players = [player.name for player in state.players]
    exploding_wolf = next(player.name for player in state.players if player.role == "狼人")
    provider = SelfExplosionProvider(
        self_exploders=[exploding_wolf],
        candidates={active_players[0], active_players[1]},
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.werewolf_self_exploded == exploding_wolf
    assert round_state.day_ended_by_self_explosion is True
    assert round_state.sheriff_badge_lost is False
    assert state.sheriff_badge_lost is False
    assert state.sheriff_election_pending is True
    assert state.sheriff_pre_election_bomb_count == 1
    assert exploding_wolf not in active_players
    assert players_by_name[exploding_wolf].revealed_role is True
    assert round_state.votes == []
    assert round_log.summaries == []
    assert round_log.werewolf_self_explosion is not None


def test_second_pre_sheriff_self_explosion_loses_badge() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_second_self_explosion",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=71,
        rule_set=rule_set,
    )
    state.sheriff_pre_election_bomb_count = 1
    state.sheriff_election_pending = True
    active_players = [player.name for player in state.players]
    exploding_wolf = next(player.name for player in state.players if player.role == "狼人")
    provider = SelfExplosionProvider(
        self_exploders=[exploding_wolf], candidates={active_players[0]}
    )
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_badge_lost is True
    assert state.sheriff_badge_lost is True
    assert state.sheriff_election_pending is False
    assert round_state.sheriff_badge_lost_reason == "双爆吞警徽"
    assert round_state.sheriff_election_resolution is not None
    assert round_state.sheriff_election_resolution.outcome == "badge_lost"
    assert (
        round_state.sheriff_election_resolution.reason_code == "double_pre_election_self_explosion"
    )


def test_pending_sheriff_election_can_resume_after_first_self_explosion() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_resume_sheriff_after_bomb",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=72,
        rule_set=rule_set,
    )
    state.sheriff_pre_election_bomb_count = 1
    state.sheriff_election_pending = True
    active_players = [player.name for player in state.players]
    sheriff = active_players[0]
    second_candidate = active_players[1]
    provider = SelfExplosionProvider(
        self_exploders=[],
        candidates={sheriff, second_candidate},
        sheriff_vote_targets={
            name: sheriff for name in active_players if name not in {sheriff, second_candidate}
        },
    )
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_elected == sheriff
    assert state.sheriff == sheriff
    assert state.sheriff_election_pending is False


def test_first_night_pending_deaths_are_announced_after_self_explosion() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_self_explosion_pending_night",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=75,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    exploding_wolf = next(player.name for player in state.players if player.role == "狼人")
    night_target = next(player.name for player in state.players if player.role != "狼人")
    provider = FirstNightSelfExplosionProvider(
        remove_target=night_target,
        self_exploders=[exploding_wolf],
        candidates={active_players[0], active_players[1]},
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    state.rounds.append(round_state)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)
    engine._run_day_phase(round_state, round_log, active_players, pending_deaths)

    assert round_state.werewolf_self_exploded == exploding_wolf
    assert {death.player for death in round_state.day_deaths} == {exploding_wolf}
    assert {death.player for death in round_state.night_deaths} == {night_target}
    assert exploding_wolf not in active_players
    assert night_target not in active_players
    assert round_state.votes == []
    assert round_log.summaries == []


def test_werewolves_can_self_explode_after_sheriff_candidate_speech() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_self_explosion_after_sheriff_speech",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=57,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    candidates = active_players[:4]
    first_speaker = active_players[3]
    exploding_wolf = next(player.name for player in state.players if player.role == "狼人")
    provider = StageTriggeredSelfExplosionProvider(
        exploding_wolf=exploding_wolf,
        trigger_stage=f"{first_speaker} 警上发言后",
        candidates=set(candidates),
        sheriff_vote_targets={name: candidates[0] for name in active_players[4:]},
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        rng=random.Random(0),
    )

    interrupted = engine._run_sheriff_election_if_needed(round_state, round_log, active_players)

    assert interrupted is True
    assert round_state.werewolf_self_exploded == exploding_wolf
    assert [speech["speaker"] for speech in round_state.sheriff_speeches] == [first_speaker]
    assert round_state.sheriff_withdrawn == []
    assert round_state.sheriff_votes == {}
    assert exploding_wolf not in active_players


def test_werewolves_can_self_explode_after_day_debate_speech() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_self_explosion_after_debate_speech",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=76,
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    active_players = [player.name for player in state.players]
    sheriff = next(player.name for player in state.players if player.role != "狼人")
    state.sheriff = sheriff
    players_by_name[sheriff].is_sheriff = True
    sheriff_index = active_players.index(sheriff)
    speech_order = active_players[sheriff_index + 1 :] + active_players[:sheriff_index] + [sheriff]
    first_speaker = speech_order[0]
    exploding_wolf = next(player.name for player in state.players if player.role == "狼人")
    provider = StageTriggeredSelfExplosionProvider(
        exploding_wolf=exploding_wolf,
        trigger_stage=f"{first_speaker} 发言后",
        candidates=set(),
    )
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.werewolf_self_exploded == exploding_wolf
    assert [entry.speaker for entry in round_state.debate] == [first_speaker]
    assert round_state.votes == []
    assert round_log.summaries == []
    assert exploding_wolf not in active_players


def test_self_explosion_before_actor_records_pending_speakers_and_reaches_prompt() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_interruption_before_actor",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=20260714,
        rule_set=rule_set,
    )
    exploding_wolf = next(player.name for player in state.players if player.role == WEREWOLF)
    first_speaker = next(player.name for player in state.players if player.role != WEREWOLF)
    remaining = [
        player.name
        for player in state.players
        if player.name not in {first_speaker, exploding_wolf}
    ]
    speech_order = [first_speaker, exploding_wolf, *remaining]
    active_players = speech_order.copy()
    provider = StageTriggeredSelfExplosionProvider(
        exploding_wolf=exploding_wolf,
        trigger_stage=f"{exploding_wolf} 发言前",
        candidates=set(),
    )
    round_state = RoundState(number=3, players=active_players.copy())
    round_log = RoundLog(number=3)
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
    )

    interrupted = engine._run_debate_phase(round_state, round_log, active_players)

    assert interrupted is True
    assert round_state.interruption is not None
    assert round_state.interruption.stage == "debate"
    assert round_state.interruption.interrupted_by == "werewolf_self_explosion"
    assert round_state.interruption.actor == exploding_wolf
    assert round_state.interruption.timing == "before_actor"
    assert round_state.interruption.last_completed_speaker == first_speaker
    assert round_state.interruption.completed_actors == [first_speaker]
    assert round_state.interruption.pending_actors == speech_order[1:]
    interruption_fact = next(
        fact for fact in state.public_facts if fact["category"] == "interruption"
    )
    assert interruption_fact["retention"] == "critical"
    assert interruption_fact["details"] == round_state.interruption.to_dict()

    state.rounds.append(round_state)
    future_round = RoundState(number=4, players=active_players.copy())
    viewer = state.player_by_name()[remaining[0]]
    future_world_state = engine._world_state(viewer, [], future_round)
    interruption_lines = future_world_state["stage_interruptions"]
    assert isinstance(interruption_lines, list)
    assert any("尚未获得发言机会" in line for line in interruption_lines)
    assert any("不能将其视为主动沉默" in line for line in interruption_lines)
    future_prompt, _schema = build_prompt("debate", future_world_state)
    assert "公开流程中断记录" in future_prompt
    assert "尚未获得发言机会" in future_prompt
    assert "不能将其视为主动沉默" in future_prompt


def test_post_sheriff_self_explosion_ends_day_without_consuming_badge() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_post_sheriff_self_explosion",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=73,
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    active_players = [player.name for player in state.players]
    sheriff = next(player.name for player in state.players if player.role != "狼人")
    exploding_wolf = next(player.name for player in state.players if player.role == "狼人")
    state.sheriff = sheriff
    players_by_name[sheriff].is_sheriff = True
    provider = SelfExplosionProvider(self_exploders=[exploding_wolf], candidates=set())
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.werewolf_self_exploded == exploding_wolf
    assert state.sheriff == sheriff
    assert state.sheriff_badge_lost is False
    assert state.sheriff_pre_election_bomb_count == 0
    assert round_log.sheriff_badge is None


def test_wolf_sheriff_self_explosion_triggers_badge_handling() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_wolf_sheriff_self_explosion",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=74,
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    active_players = [player.name for player in state.players]
    wolf_sheriff = next(player.name for player in state.players if player.role == "狼人")
    badge_target = next(player.name for player in state.players if player.name != wolf_sheriff)
    state.sheriff = wolf_sheriff
    players_by_name[wolf_sheriff].is_sheriff = True
    provider = SelfExplosionProvider(
        self_exploders=[wolf_sheriff],
        candidates=set(),
        badge_choice=badge_target,
    )
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.werewolf_self_exploded == wolf_sheriff
    assert state.sheriff == badge_target
    assert round_state.sheriff_badge_target == badge_target
    assert round_log.sheriff_badge is not None


def test_sheriff_vote_prompt_includes_public_election_context() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_prompt_context",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=60,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.sheriff_candidates = [active_players[0], active_players[1]]
    round_state.sheriff_voters = [active_players[2]]
    round_state.sheriff_speeches = [{"speaker": active_players[0], "message": "我上警争警徽。"}]
    round_state.sheriff_withdrawn = [active_players[1]]
    round_state.sheriff_final_candidates = [active_players[0]]
    round_state.sheriff_pk_candidates = [active_players[0], active_players[3]]
    round_state.sheriff_pk_speeches = [{"speaker": active_players[3], "message": "我进入 PK。"}]
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )

    world_state = engine._world_state(
        state.player_by_name()[active_players[2]],
        [active_players[0]],
        round_state,
    )
    prompt, _schema = build_prompt("sheriff_vote", world_state)

    assert "警长竞选公开信息" in prompt
    assert f"上警名单：{active_players[0]}、{active_players[1]}" in prompt
    assert f"警下名单：{active_players[2]}" in prompt
    assert f"{active_players[0]}：我上警争警徽。" in prompt
    assert f"退水名单：{active_players[1]}" in prompt
    assert f"最终候选：{active_players[0]}" in prompt
    assert f"PK 候选：{active_players[0]}、{active_players[3]}" in prompt
    assert f"{active_players[3]}：我进入 PK。" in prompt
    assert "警长竞选资格" in prompt
    assert f"原始警下投票者：{active_players[2]}" in prompt
    assert "你是原始警下玩家，拥有本轮警长投票权" in prompt
    eligibility = world_state["public_action_eligibility"]
    assert isinstance(eligibility, dict)
    assert eligibility["actor_can_sheriff_vote"] is True
    assert eligibility["sheriff_vote_reason"] == "eligible_original_voter"


def test_empty_sheriff_voters_and_withdrawn_candidate_are_explicit_in_prompt() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_empty_sheriff_voters",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=61,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    withdrawn = active_players[0]
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.sheriff_candidates = active_players.copy()
    round_state.sheriff_voters = []
    round_state.sheriff_withdrawn = [withdrawn]
    round_state.sheriff_final_candidates = active_players[1:]
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )

    world_state = engine._world_state(
        state.player_by_name()[withdrawn],
        round_state.sheriff_final_candidates,
        round_state,
    )
    prompt, _schema = build_prompt("sheriff_vote", world_state)

    assert "警下名单：无" in prompt
    assert "原始警下投票者：无" in prompt
    assert "本轮没有警下投票者" in prompt
    assert "你已退水" in prompt
    eligibility = world_state["public_action_eligibility"]
    assert isinstance(eligibility, dict)
    assert eligibility["actor_can_sheriff_vote"] is False
    assert eligibility["sheriff_vote_reason"] == "withdrew_candidate_not_original_voter"


def test_invalid_eligibility_draft_is_buffered_and_only_valid_retry_is_public() -> None:
    class QualityRetryStreamProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.prompts: list[str] = []

        def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
            del model, temperature
            self.calls += 1
            self.prompts.append(prompt)
            speech = (
                "警下玩家请把票投给我。"
                if self.calls == 1
                else "本轮没有警下投票者，我只陈述自己的判断。"
            )
            return [
                '{"reasoning":"资格检查",',
                f'"say":"{speech}"',
                "}",
            ]

        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            return "".join(self.stream_json(model=model, prompt=prompt, temperature=temperature))

    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_buffered_quality_retry",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=62,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    speaker = state.players[0]
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.sheriff_candidates = active_players.copy()
    round_state.sheriff_voters = []
    round_state.sheriff_final_candidates = active_players.copy()
    provider = QualityRetryStreamProvider()
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    message, _log = engine._player_action(
        player=speaker,
        action=ACTION_SHERIFF_SPEECH,
        options=[],
        result_key="say",
        round_state=round_state,
        phase="day",
    )

    assert provider.calls == 2
    assert "没有警下投票者" in provider.prompts[1]
    assert message == "本轮没有警下投票者，我只陈述自己的判断。"
    public_blob = str(sink.events)
    assert "警下玩家请把票投给我" not in public_blob
    assert "本轮没有警下投票者，我只陈述自己的判断" in public_blob
    assert [event["type"] for event in sink.events].count("model_retry_scheduled") == 1
    assert [event["type"] for event in sink.events].count("action_parsed") == 1


def test_invalid_non_seer_investigation_plan_is_rewritten_before_publication() -> None:
    class InvestigationPlanRetryProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.prompts: list[str] = []

        def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
            del model, temperature
            self.calls += 1
            self.prompts.append(prompt)
            speech = (
                "我是村民。我的警徽流先验3号，再验5号。"
                if self.calls == 1
                else "我是村民；如果当选，我会整理票型、明确归票并谨慎移交警徽。"
            )
            return [json.dumps({"reasoning": "角色能力检查", "say": speech}, ensure_ascii=False)]

        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            return "".join(
                self.stream_json(model=model, prompt=prompt, temperature=temperature)
            )

    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_non_seer_investigation_plan_retry",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=72,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    speaker = next(player for player in state.players if player.role != SEER)
    candidates = [speaker.name, *[name for name in active_players if name != speaker.name][:2]]
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.sheriff_candidates = candidates
    round_state.sheriff_speech_order = candidates.copy()
    round_state.sheriff_voters = [name for name in active_players if name not in candidates]
    round_state.sheriff_final_candidates = candidates.copy()
    provider = InvestigationPlanRetryProvider()
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    message, action_log = engine._player_action(
        player=speaker,
        action=ACTION_SHERIFF_SPEECH,
        options=[],
        result_key="say",
        round_state=round_state,
        phase="day",
    )

    assert provider.calls == 2
    assert "只有预言家或明确公开跳预言家的玩家" in provider.prompts[1]
    assert message == "我是村民；如果当选，我会整理票型、明确归票并谨慎移交警徽。"
    assert "sheriff_speech_investigation_plan_without_seer_claim" in (
        action_log.speech_quality_initial_codes
    )
    public_blob = str(sink.events)
    assert "我的警徽流先验3号" not in public_blob
    assert "整理票型、明确归票并谨慎移交警徽" in public_blob
    assert [event["type"] for event in sink.events].count("model_retry_scheduled") == 1
    assert [event["type"] for event in sink.events].count("action_parsed") == 1


@pytest.mark.parametrize(
    "action",
    [ACTION_DEBATE, ACTION_SHERIFF_SPEECH, ACTION_SHERIFF_PK_SPEECH],
)
def test_public_speech_quality_retry_buffers_rejected_draft_for_every_stage(
    action: str,
) -> None:
    class SpeechQualityRetryProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.prompts: list[str] = []

        def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
            del model, temperature
            self.calls += 1
            self.prompts.append(prompt)
            speech = (
                "第一轮全票挂警徽定狼，所以我仍然保持这个判断。"
                if self.calls == 1
                else "3号玩家刚刚改票5号玩家，这个变化需要解释，我今天暂不跟票。"
            )
            return ['{"reasoning":"质量检查",', f'"say":"{speech}"', "}"]

        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            return "".join(
                self.stream_json(model=model, prompt=prompt, temperature=temperature)
            )

    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id=f"session_test_speech_quality_{action}",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=63,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    speaker = state.players[1]
    round_state = RoundState(number=1, players=active_players.copy())
    prior_message = "第一轮全票挂警徽定狼，所以先把目标放进狼坑。"
    if action == ACTION_DEBATE:
        round_state.speech_order = active_players.copy()
        round_state.debate = [DebateEntry(speaker=active_players[0], message=prior_message)]
    elif action == ACTION_SHERIFF_SPEECH:
        round_state.sheriff_candidates = active_players.copy()
        round_state.sheriff_speech_order = active_players.copy()
        round_state.sheriff_speeches = [
            {"speaker": active_players[0], "message": prior_message}
        ]
    else:
        round_state.sheriff_pk_candidates = active_players.copy()
        round_state.sheriff_pk_speeches = [
            {"speaker": active_players[0], "message": prior_message}
        ]
    provider = SpeechQualityRetryProvider()
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        speech_quality_retry_enabled=True,
    )

    message, action_log = engine._player_action(
        player=speaker,
        action=action,
        options=[],
        result_key="say",
        round_state=round_state,
        phase="day",
    )

    assert provider.calls == 2
    assert "本次发言质量任务" in provider.prompts[0]
    assert "不要复述已有长句" in provider.prompts[1]
    assert message == "3号玩家刚刚改票5号玩家，这个变化需要解释，我今天暂不跟票。"
    public_blob = str(sink.events)
    assert "所以我仍然保持这个判断" not in public_blob
    assert "3号玩家刚刚改票5号玩家" in public_blob
    assert [event["type"] for event in sink.events].count("action_parsed") == 1
    assert action_log.speech_quality_attempt_count == 2
    assert action_log.speech_quality_retry_exhausted is False
    assert "repeated_debate_phrase" in action_log.speech_quality_initial_codes
    assert action_log.speech_quality_report is not None
    assert action_log.speech_quality_report["requires_rewrite"] is False
    assert "所以我仍然保持这个判断" not in str(action_log.to_dict())


def test_public_speech_quality_retry_exhaustion_publishes_only_second_draft() -> None:
    class ExhaustedSpeechProvider:
        def __init__(self) -> None:
            self.calls = 0

        def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
            del model, prompt, temperature
            self.calls += 1
            speech = (
                "第一轮全票挂警徽定狼，所以我保持原判断。"
                if self.calls == 1
                else "第一轮全票挂警徽定狼，我还是不改判断。"
            )
            return ['{"reasoning":"质量检查",', f'"say":"{speech}"', "}"]

        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            return "".join(
                self.stream_json(model=model, prompt=prompt, temperature=temperature)
            )

    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_speech_quality_exhausted",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=64,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    speaker = state.players[1]
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.speech_order = active_players.copy()
    round_state.debate = [
        DebateEntry(
            speaker=active_players[0],
            message="第一轮全票挂警徽定狼，所以先把目标放进狼坑。",
        )
    ]
    provider = ExhaustedSpeechProvider()
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        speech_quality_retry_enabled=True,
    )

    message, action_log = engine._player_action(
        player=speaker,
        action=ACTION_DEBATE,
        options=[],
        result_key="say",
        round_state=round_state,
        phase="day",
    )

    assert provider.calls == 2
    assert message == "第一轮全票挂警徽定狼，我还是不改判断。"
    public_blob = str(sink.events)
    assert "所以我保持原判断" not in public_blob
    assert "我还是不改判断" in public_blob
    assert [event["type"] for event in sink.events].count("action_parsed") == 1
    assert all(
        event["type"] != "speech_quality_retry_exhausted" for event in sink.events
    )
    assert action_log.speech_quality_attempt_count == 2
    assert action_log.speech_quality_retry_exhausted is True
    assert action_log.speech_quality_report is not None
    assert action_log.speech_quality_report["requires_rewrite"] is True


def test_optional_action_timeout_uses_safe_abstain_and_records_execution() -> None:
    class TimeoutProvider:
        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            del model, prompt, temperature
            raise ModelDeadlineExceeded("test timeout")

    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_optional_timeout",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=65,
        rule_set=rule_set,
    )
    round_state = RoundState(
        number=1,
        players=[player.name for player in state.players],
    )
    engine = GameEngine(
        state=state,
        provider=TimeoutProvider(),
        max_rounds=8,
        rule_set=rule_set,
        action_budgets_enabled=True,
        fallback_seed=65,
    )

    choice, action_log = engine._player_action(
        player=state.players[0],
        action=ACTION_WITCH_POISON,
        options=[state.players[1].name, NO_WITCH_POISON],
        result_key="poison",
        round_state=round_state,
        phase="night",
    )

    assert choice == NO_WITCH_POISON
    assert action_log.execution_status == "fallback"
    assert action_log.fallback_choice == NO_WITCH_POISON
    assert action_log.fallback_reason == "timeout_optional_abstain"
    assert action_log.budget_ms == 12000


def test_required_timeout_choice_is_deterministic_and_order_independent() -> None:
    class TimeoutProvider:
        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            del model, prompt, temperature
            raise ModelDeadlineExceeded("test timeout")

    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_required_timeout",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=66,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    engine = GameEngine(
        state=state,
        provider=TimeoutProvider(),
        max_rounds=8,
        rule_set=rule_set,
        action_budgets_enabled=True,
        fallback_seed=66,
    )
    candidates = active_players[1:]

    first, first_log = engine._player_action(
        player=state.players[0],
        action="vote",
        options=candidates,
        result_key="vote",
        round_state=round_state,
        phase="day",
    )
    second, _second_log = engine._player_action(
        player=state.players[0],
        action="vote",
        options=list(reversed(candidates)),
        result_key="vote",
        round_state=round_state,
        phase="day",
    )

    assert first == second
    assert first in candidates
    assert first_log.fallback_reason == "timeout_deterministic_legal_choice"
    assert first_log.execution_status == "fallback"


def test_public_speech_timeout_uses_neutral_text_without_hidden_claims() -> None:
    class TimeoutProvider:
        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            del model, prompt, temperature
            raise ModelDeadlineExceeded("test timeout")

    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_speech_timeout",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=67,
        rule_set=rule_set,
    )
    round_state = RoundState(
        number=1,
        players=[player.name for player in state.players],
    )
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=TimeoutProvider(),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        action_budgets_enabled=True,
        speech_quality_retry_enabled=True,
        fallback_seed=67,
    )

    speech, action_log = engine._player_action(
        player=state.players[0],
        action=ACTION_DEBATE,
        options=[],
        result_key="say",
        round_state=round_state,
        phase="day",
    )

    assert speech == "本轮暂不追加判断，投票时我会给出明确选择。"
    assert action_log.fallback_reason == "timeout_neutral_public_speech"
    assert "查验" not in str(action_log.to_dict())
    assert "狼人" not in str(action_log.lm_log.result)
    assert "test timeout" not in str(sink.events)


def test_batch_deadline_falls_back_in_request_order_and_drops_late_events() -> None:
    class SlowFirstProvider:
        def __init__(self, slow_actor: str) -> None:
            self.slow_actor = slow_actor
            self.release = threading.Event()
            self.finished = threading.Event()

        def stream_json(
            self,
            *,
            model: str,
            prompt: str,
            temperature: float,
            call_options: object | None = None,
        ) -> Generator[str, None, None]:
            del model, temperature, call_options
            actor = _extract_actor_name(prompt)
            if actor == self.slow_actor:
                self.release.wait(timeout=1.0)
                yield json.dumps(
                    {"reasoning": "LATE_SENTINEL", "vote": "3号玩家"},
                    ensure_ascii=False,
                )
                self.finished.set()
                return
            yield json.dumps(
                {"reasoning": "快速合法选择", "vote": "3号玩家"},
                ensure_ascii=False,
            )

    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_batch_deadline",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=68,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    provider = SlowFirstProvider(active_players[0])
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        action_budgets_enabled=True,
        action_execution_budget=ActionExecutionBudgetV1(
            required_request_seconds=1.0,
            required_total_seconds=1.0,
            required_batch_seconds=0.05,
        ),
        fallback_seed=68,
    )
    requests = [
        engine._build_player_action_request(
            player=player,
            action="vote",
            options=active_players[2:],
            result_key="vote",
            round_state=round_state,
            phase="day",
        )
        for player in state.players[:2]
    ]

    results = engine._player_actions_batch(requests)

    assert not provider.finished.is_set()
    assert results[0][0] in active_players[2:]
    assert results[0][1].fallback_reason == "batch_deadline_deterministic_legal_choice"
    assert results[1][0] == active_players[2]
    assert [action_log.actor for _, action_log in results] == active_players[:2]
    parsed_actors = [
        event["actor"]
        for event in sink.events
        if event["type"] == "action_parsed" and event["action"] == "vote"
    ]
    assert parsed_actors == active_players[:2]
    assert "LATE_SENTINEL" not in str(sink.events)

    provider.release.set()
    assert provider.finished.wait(timeout=1.0)
    assert "LATE_SENTINEL" not in str(sink.events)
    assert [
        event["actor"]
        for event in sink.events
        if event["type"] == "action_parsed" and event["action"] == "vote"
    ] == active_players[:2]


def test_12_player_wolf_world_state_lists_all_living_teammates() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_12_player_wolf_context",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=42,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    engine = GameEngine(
        state=state,
        provider=NoInvestigateProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == "狼人")
    teammates = [
        player.name
        for player in state.players
        if player.role == "狼人" and player.name != wolf.name
    ]

    world_state = engine._world_state(wolf, [], round_state)

    assert world_state["werewolf_context"] == f"你的狼人队友是{'、'.join(teammates)}。"


def test_special_role_initialization_sets_ability_state() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_special_abilities",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=43,
        rule_set=rule_set,
    )
    players_by_role = {player.role: player for player in state.players}

    assert players_by_role["女巫"].witch_antidote_available is True
    assert players_by_role["女巫"].witch_poison_available is True
    assert players_by_role["猎人"].hunter_can_shoot is True
    assert players_by_role["白痴"].can_vote is True
    assert players_by_role["白痴"].revealed_role is False


def test_slaughter_side_wolves_win_when_all_gods_are_dead() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_slaughter_gods",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=44,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=NoInvestigateProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )
    wolf = next(player.name for player in state.players if player.role == "狼人")
    civilians = [player.name for player in state.players if player.role == "村民"]
    active_players = [wolf, *civilians]

    assert engine._get_winner(active_players) == "狼人阵营"


def test_slaughter_side_wolves_win_when_all_civilians_are_dead() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_slaughter_civilians",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=45,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=NoInvestigateProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )
    wolf = next(player.name for player in state.players if player.role == "狼人")
    gods = [
        player.name for player in state.players if player.role in {"预言家", "女巫", "猎人", "白痴"}
    ]
    active_players = [wolf, *gods]

    assert engine._get_winner(active_players) == "狼人阵营"


def test_slaughter_side_villagers_win_when_all_wolves_are_dead() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_slaughter_wolves",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=46,
        rule_set=rule_set,
    )
    engine = GameEngine(
        state=state,
        provider=NoInvestigateProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players if player.role != "狼人"]

    assert engine._get_winner(active_players) == "好人阵营"


def test_seer_investigation_records_alignment_not_exact_god_role() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_seer_alignment_result",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=47,
        rule_set=rule_set,
    )
    wolf = next(player for player in state.players if player.role == WEREWOLF)
    seer = next(player for player in state.players if player.role == SEER)
    hunter = next(player for player in state.players if player.role == HUNTER)
    active_players = [wolf.name, seer.name, hunter.name]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(
        state=state,
        provider=TargetedInvestigationProvider(
            investigate_target=hunter.name,
            remove_target=seer.name,
        ),
        max_rounds=8,
        rule_set=rule_set,
    )

    engine._run_night_phase(round_state, round_log, active_players)

    assert round_state.investigated == hunter.name
    assert seer.known_roles[hunter.name] == "好人阵营"
    assert f"第1轮：我查验了{hunter.name}，阵营是好人阵营。" in seer.observations
    assert HUNTER not in seer.known_roles.values()
    assert all(HUNTER not in observation for observation in seer.observations)


def test_night_phase_skips_investigate_when_seer_has_no_candidates() -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="session_test_no_investigate_candidates",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=43,
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    seer = next(player for player in state.players if player.role == SEER)
    active_players = [player.name for player in state.players]
    seer.known_roles = {
        name: players_by_name[name].role for name in active_players if name != seer.name
    }
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(
        state=state,
        provider=NoInvestigateProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.investigated is None
    assert round_log.investigate is None


def test_witch_can_save_self_on_first_night_and_cannot_poison_same_night() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_witch_self_save",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=47,
        rule_set=rule_set,
    )
    witch = next(player for player in state.players if player.role == "女巫")
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = WitchChoiceProvider(
        remove_target=witch.name,
        save_choice=witch.name,
        poison_choice="不使用毒药",
    )
    state.sheriff = next(player.name for player in state.players if player.name != witch.name)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.attacked == witch.name
    assert round_state.saved_by_witch == witch.name
    assert round_state.poisoned is None
    assert round_state.night_deaths == []
    assert round_state.eliminated is None
    assert witch.name in active_players
    assert witch.witch_antidote_available is False
    assert witch.witch_poison_available is True
    assert "witch_poison" not in provider.actions


def test_witch_poison_creates_night_death() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_witch_poison",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=48,
        rule_set=rule_set,
    )
    witch = next(player for player in state.players if player.role == "女巫")
    villager = next(player for player in state.players if player.role == "村民")
    target = next(player for player in state.players if player.role == "预言家")
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = WitchChoiceProvider(
        remove_target=target.name,
        save_choice="不使用解药",
        poison_choice=villager.name,
    )
    state.sheriff = next(
        player.name for player in state.players if player.name not in {target.name, villager.name}
    )
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.eliminated == target.name
    assert round_state.poisoned == villager.name
    assert [death.to_dict() for death in round_state.night_deaths] == [
        {"player": target.name, "cause": "werewolf_attack", "source": "狼人"},
        {"player": villager.name, "cause": "witch_poison", "source": witch.name},
    ]
    assert target.name not in active_players
    assert villager.name not in active_players
    assert witch.witch_poison_available is False


def test_hunter_shoots_after_werewolf_attack_death() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_hunter_shoot",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=49,
        rule_set=rule_set,
    )
    hunter = next(player for player in state.players if player.role == "猎人")
    wolf = next(player for player in state.players if player.role == "狼人")
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = HunterShotProvider(
        remove_target=hunter.name,
        save_choice="不使用解药",
        poison_choice="不使用毒药",
        shoot_choice=wolf.name,
    )
    state.sheriff = next(
        player.name for player in state.players if player.name not in {hunter.name, wolf.name}
    )
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.hunter_shot == wolf.name
    assert [death.cause for death in round_state.night_deaths] == [
        "werewolf_attack",
        "hunter_shot",
    ]
    assert hunter.name not in active_players
    assert wolf.name not in active_players


def test_hunter_cannot_shoot_after_witch_poison_death() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_hunter_poison_no_shot",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=50,
        rule_set=rule_set,
    )
    hunter = next(player for player in state.players if player.role == "猎人")
    seer = next(player for player in state.players if player.role == "预言家")
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = HunterShotProvider(
        remove_target=seer.name,
        save_choice="不使用解药",
        poison_choice=hunter.name,
        shoot_choice=seer.name,
    )
    state.sheriff = next(
        player.name for player in state.players if player.name not in {seer.name, hunter.name}
    )
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.poisoned == hunter.name
    assert round_state.hunter_shot is None
    assert "hunter_shoot" not in provider.actions
    assert hunter.name not in active_players


def test_idiot_reveals_and_survives_first_exile() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_idiot_reveal",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=51,
        rule_set=rule_set,
    )
    idiot = next(player for player in state.players if player.role == "白痴")
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(
        state=state,
        provider=NoInvestigateProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )

    engine._resolve_day_exile(idiot.name, round_state, round_log, active_players)

    assert round_state.idiot_revealed == idiot.name
    assert round_state.exiled is None
    assert round_state.day_deaths == []
    assert idiot.name in active_players
    assert idiot.can_vote is False
    assert idiot.revealed_role is True
    assert engine._refresh_winner(active_players) is False
    assert state.winner == ""


def test_revealed_idiot_is_exiled_if_voted_out_again() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_idiot_second_exile",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=52,
        rule_set=rule_set,
    )
    idiot = next(player for player in state.players if player.role == "白痴")
    idiot.can_vote = False
    idiot.revealed_role = True
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(
        state=state,
        provider=NoInvestigateProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )

    engine._resolve_day_exile(idiot.name, round_state, round_log, active_players)

    assert round_state.exiled == idiot.name
    assert [death.to_dict() for death in round_state.day_deaths] == [
        {"player": idiot.name, "cause": "vote_exile", "source": "投票"}
    ]
    assert idiot.name not in active_players


def test_revealed_idiot_does_not_vote() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_idiot_no_vote",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=53,
        rule_set=rule_set,
    )
    idiot = next(player for player in state.players if player.role == "白痴")
    idiot.can_vote = False
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )

    votes, _logs = engine._run_voting(round_state, active_players)

    assert idiot.name not in votes


def test_day_exile_vote_requests_eligible_voters_concurrently() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_parallel_day_vote",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=54,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    eligible_voters = active_players.copy()
    response_value_by_actor = {
        voter: next(name for name in active_players if name != voter) for voter in eligible_voters
    }
    provider = BarrierActionProvider(
        action_key="vote",
        result_key="vote",
        response_value_by_actor=response_value_by_actor,
        expected_calls=len(eligible_voters),
    )
    round_state = RoundState(number=1, players=active_players.copy())
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    votes, logs = engine._run_voting(round_state, active_players)

    assert [actor for action, actor in provider.actions if action == "vote"] == eligible_voters
    assert votes == response_value_by_actor
    assert [log.actor for log in logs] == eligible_voters
    assert list(round_state.vote_weights) == eligible_voters


def test_round_summaries_request_active_players_sequentially() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sequential_summaries",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=59,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players[:3]]
    sink = CapturingEventSink()
    provider = ScriptedChineseProvider()
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    engine._run_summaries(round_state, round_log, active_players)

    summary_events = [
        event
        for event in sink.events
        if event.get("action") == "summarize"
        and event["type"]
        in {
            "action_requested",
            "model_request_started",
            "model_thinking_tick",
            "model_response_delta",
            "model_response_received",
            "action_parsed",
        }
    ]
    assert summary_events == []
    assert list(round_state.private_summaries) == active_players
    assert round_state.summaries == {}
    assert round_state.public_summary == "第1轮；没有公开出局。"
    assert [log.actor for log in round_log.summaries] == active_players
    for name in active_players:
        assert state.player_by_name()[name].observations[-1] == (
            "第1轮总结：我会继续关注发言矛盾最大的玩家。"
        )


def test_small_rule_day_phase_uses_full_seat_order_without_bids() -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="session_test_ordered_speech",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=55,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(
        state=state,
        provider=NoBidOrderedSpeechProvider(),
        max_rounds=8,
        rule_set=rule_set,
    )

    engine._run_day_phase(round_state, round_log, active_players)

    assert [entry.speaker for entry in round_state.debate] == round_state.players
    assert round_state.speech_order == round_state.players
    assert round_state.bids == []
    assert round_log.bid == []


def test_12_player_first_day_elects_sheriff_and_uses_sheriff_speech_order() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_election",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=56,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    sheriff = active_players[0]
    second_candidate = active_players[1]
    provider = SheriffFlowProvider(
        candidates={sheriff, second_candidate},
        sheriff_vote_targets={
            name: sheriff for name in active_players if name not in {sheriff, second_candidate}
        },
        speech_order_choice="警左发言",
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    engine._run_day_phase(round_state, round_log, active_players)

    assert state.sheriff == sheriff
    assert state.player_by_name()[sheriff].is_sheriff is True
    assert round_state.sheriff == sheriff
    assert round_state.sheriff_candidates == [sheriff, second_candidate]
    assert set(round_state.sheriff_votes.values()) == {sheriff}
    assert round_state.speech_order[-1] == sheriff
    assert round_state.speech_order[:-1] == active_players[1:]
    assert round_log.sheriff_run
    assert round_log.sheriff_votes
    assert round_log.speech_order is not None
    election_event = next(
        event
        for event in sink.events
        if event["type"] == "state_updated" and event["payload"].get("sheriff_elected") == sheriff
    )
    direction_request = next(
        event
        for event in sink.events
        if event["type"] == "action_requested" and event["action"] == "speech_order"
    )
    assert election_event["actor"] == sheriff
    assert election_event["action"] == "sheriff_election_resolved"
    assert election_event["payload"]["narration_mode"] == "explicit_v1"
    assert election_event["payload"]["sheriff"] == sheriff
    assert election_event["payload"]["sheriff_candidates"] == [sheriff, second_candidate]
    assert election_event["payload"]["sheriff_voters"] == active_players[2:]
    assert election_event["payload"]["active_players"] == active_players
    assert election_event["payload"]["sheriff_election"]["outcome"] == "elected"
    assert election_event["payload"]["sheriff_election"]["reason_code"] == "first_vote_winner"
    assert sink.events.index(election_event) < sink.events.index(direction_request)


def test_sheriff_candidate_speeches_use_random_start_and_direction() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_random_sheriff_speeches",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=57,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    candidates = active_players[:4]
    provider = SheriffFlowProvider(
        candidates=set(candidates),
        sheriff_vote_targets={name: candidates[0] for name in active_players[4:]},
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        rng=random.Random(0),
    )

    engine._run_sheriff_election_if_needed(round_state, round_log, active_players)

    expected_speech_order = [
        active_players[3],
        active_players[2],
        active_players[1],
        active_players[0],
    ]
    assert round_state.sheriff_candidates == candidates
    assert round_state.sheriff_speech_order == expected_speech_order
    assert round_state.sheriff_speech_direction == "逆时针"
    assert [speech["speaker"] for speech in round_state.sheriff_speeches] == expected_speech_order
    assert [
        name for action, name in provider.actions if action == "sheriff_speech"
    ] == expected_speech_order


def test_sheriff_run_requests_all_players_concurrently() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_parallel_sheriff_run",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=31,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    provider = ConcurrentSheriffRunProvider(expected_calls=len(active_players))
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)

    engine._run_sheriff_election_if_needed(round_state, round_log, active_players)

    sheriff_cue = next(
        event
        for event in sink.events
        if event["type"] == "judge_cue" and event["action"] == "sheriff_raise_hands"
    )
    first_run_request = next(
        event
        for event in sink.events
        if event["type"] == "action_requested" and event["action"] == "sheriff_run"
    )
    assert sheriff_cue["payload"]["cue_id"] == "sheriff_raise_hands"
    assert sheriff_cue["payload"]["cue"] == "sheriff_raise_hands"
    assert sheriff_cue["payload"]["visible_text"] == "想要竞选警长的玩家请举手。"
    assert sheriff_cue["payload"]["static_asset_id"] == "sheriff_raise_hands"
    assert sink.events.index(sheriff_cue) < sink.events.index(first_run_request)
    assert [
        actor for action, actor in provider.actions if action == "sheriff_run"
    ] == active_players
    assert [
        event["actor"]
        for event in sink.events
        if event["type"] == "action_requested" and event["action"] == "sheriff_run"
    ] == active_players
    assert round_state.sheriff_candidates == []
    assert round_state.sheriff_voters == active_players


def test_sheriff_withdraw_requests_candidates_concurrently() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_parallel_sheriff_withdraw",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=34,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    candidates = active_players[:2]
    provider = BarrierSheriffProvider(
        action_key="sheriff_withdraw",
        result_key="withdraw",
        response_value_by_actor={name: "不退水" for name in candidates},
        expected_calls=len(candidates),
        candidates=set(candidates),
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_sheriff_election_if_needed(round_state, round_log, active_players)

    assert [
        actor for action, actor in provider.actions if action == "sheriff_withdraw"
    ] == candidates
    assert [log.actor for log in round_log.sheriff_withdraw] == candidates


def test_sheriff_vote_requests_off_sheriff_voters_concurrently() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_parallel_sheriff_vote",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=35,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    candidates = active_players[:2]
    voters = active_players[2:]
    provider = BarrierSheriffProvider(
        action_key="sheriff_vote",
        result_key="sheriff_vote",
        response_value_by_actor={name: candidates[0] for name in voters},
        expected_calls=len(voters),
        candidates=set(candidates),
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_sheriff_election_if_needed(round_state, round_log, active_players)

    assert [actor for action, actor in provider.actions if action == "sheriff_vote"] == voters
    assert round_state.sheriff_votes == {name: candidates[0] for name in voters}
    assert [log.actor for log in round_log.sheriff_votes] == voters


def test_sheriff_runoff_vote_requests_off_sheriff_voters_concurrently() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_parallel_sheriff_runoff_vote",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=36,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    candidates = active_players[:2]
    voters = active_players[2:]
    first_round_votes = {name: candidates[index % 2] for index, name in enumerate(voters)}
    provider = BarrierSheriffProvider(
        action_key="sheriff_runoff_vote",
        result_key="sheriff_vote",
        response_value_by_actor={name: candidates[0] for name in voters},
        expected_calls=len(voters),
        candidates=set(candidates),
        first_round_vote_targets=first_round_votes,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_sheriff_election_if_needed(round_state, round_log, active_players)

    assert [
        actor for action, actor in provider.actions if action == "sheriff_runoff_vote"
    ] == voters
    assert round_state.sheriff_runoff_votes == {name: candidates[0] for name in voters}
    assert [log.actor for log in round_log.sheriff_runoff_votes] == voters


def test_sheriff_run_stream_failure_falls_back_without_ordered_batch_deadlock() -> None:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(target=_run_sheriff_stream_fallback_batch, args=(result_queue,))

    process.start()
    process.join(timeout=5.0)
    if process.is_alive():
        process.terminate()
        process.join(timeout=1.0)
        pytest.fail("sheriff_run stream fallback batch did not finish")

    assert process.exitcode == 0
    try:
        result = result_queue.get(timeout=1.0)
    except queue.Empty:
        pytest.fail("sheriff_run stream fallback batch produced no result")
    assert "error" not in result
    active_players = result["active_players"]
    assert [
        actor for action, actor in result["actions"] if action == "stream_sheriff_run"
    ] == active_players
    assert sorted(
        actor for action, actor in result["actions"] if action == "complete_sheriff_run"
    ) == sorted(active_players)
    assert result["sheriff_candidates"] == []
    assert result["sheriff_voters"] == active_players


def test_sheriff_run_complete_json_retry_does_not_deadlock_ordered_batch() -> None:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(target=_run_sheriff_complete_retry_batch, args=(result_queue,))

    process.start()
    process.join(timeout=5.0)
    if process.is_alive():
        process.terminate()
        process.join(timeout=1.0)
        pytest.fail("sheriff_run complete_json retry batch did not finish")

    assert process.exitcode == 0
    try:
        result = result_queue.get(timeout=1.0)
    except queue.Empty:
        pytest.fail("sheriff_run complete_json retry batch produced no result")
    assert "error" not in result
    active_players = result["active_players"]
    first_attempts = [
        actor
        for action, actor, attempt in result["actions"]
        if action == "complete_sheriff_run" and attempt == 1
    ]
    second_attempts = [
        actor
        for action, actor, attempt in result["actions"]
        if action == "complete_sheriff_run" and attempt == 2
    ]
    assert first_attempts == active_players
    assert sorted(second_attempts) == sorted(active_players)
    assert result["sheriff_candidates"] == []
    assert result["sheriff_voters"] == active_players


def test_sheriff_run_model_event_failure_does_not_deadlock_ordered_batch() -> None:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(target=_run_sheriff_model_start_failure_batch, args=(result_queue,))

    process.start()
    process.join(timeout=5.0)
    if process.is_alive():
        process.terminate()
        process.join(timeout=1.0)
        pytest.fail("sheriff_run model event failure batch did not finish")

    assert process.exitcode == 0
    try:
        result = result_queue.get(timeout=1.0)
    except queue.Empty:
        pytest.fail("sheriff_run model event failure batch produced no result")
    assert result["error"] == "event sink failed before provider"
    assert result["provider_actions"] == result["active_players"][1:]


def test_batched_action_failure_checkpoints_successful_responses_before_raising() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_batch_failure_checkpoint_successes",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=38,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    fail_actor = active_players[2]
    provider = FailingSheriffRunProvider(fail_actor=fail_actor)
    checkpoint_manager = RecordingCheckpointManager()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        checkpoint_manager=checkpoint_manager,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)

    with pytest.raises(RuntimeError, match="batched model failure"):
        engine._run_sheriff_election_if_needed(round_state, round_log, active_players)

    successful_actors = [name for name in active_players if name != fail_actor]
    assert provider.actions == active_players
    assert [success["actor"] for success in checkpoint_manager.successes] == successful_actors
    assert {success["action"] for success in checkpoint_manager.successes} == {"sheriff_run"}
    assert all(success["prompt"] for success in checkpoint_manager.successes)
    assert [failure["actor"] for failure in checkpoint_manager.failures] == [fail_actor]
    assert checkpoint_manager.failures[0]["error"] == "batched model failure"


def test_batched_invalid_action_does_not_checkpoint_invalid_response() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_batch_invalid_checkpoint_successes",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=39,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    invalid_actor = active_players[2]
    provider = InvalidSheriffRunProvider(invalid_actor=invalid_actor)
    checkpoint_manager = RecordingCheckpointManager()
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        checkpoint_manager=checkpoint_manager,
        event_sink=sink,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)

    with pytest.raises(ValueError, match=f"{invalid_actor} returned invalid sheriff_run"):
        engine._run_sheriff_election_if_needed(round_state, round_log, active_players)

    assert provider.first_actions == active_players
    assert provider.attempts_by_actor == {
        actor: 3 if actor == invalid_actor else 1 for actor in active_players
    }
    assert [success["actor"] for success in checkpoint_manager.successes] == [
        actor for actor in active_players if actor != invalid_actor
    ]
    assert {success["action"] for success in checkpoint_manager.successes} == {"sheriff_run"}
    assert all(success["prompt"] for success in checkpoint_manager.successes)
    assert [failure["actor"] for failure in checkpoint_manager.failures] == [invalid_actor]
    assert "returned invalid sheriff_run" in str(checkpoint_manager.failures[0]["error"])
    decision_events = [
        event
        for event in sink.events
        if event["action"] == "sheriff_run"
        and event["type"] in {"model_response_received", "action_parsed"}
    ]
    assert [(event["actor"], event["type"]) for event in decision_events] == [
        (active_players[0], "model_response_received"),
        (active_players[0], "action_parsed"),
        (active_players[1], "model_response_received"),
        (active_players[1], "action_parsed"),
    ]


@pytest.mark.parametrize(
    "action",
    [ACTION_DEBATE, ACTION_SHERIFF_SPEECH, ACTION_SHERIFF_PK_SPEECH],
)
def test_required_public_speech_empty_response_uses_fallback_without_checkpoint(
    action: str,
) -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id=f"session_test_empty_{action}",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=40,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    speaker = state.players[0]
    round_state = RoundState(number=1, players=active_players.copy())
    checkpoint_manager = RecordingCheckpointManager()
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=FakeProvider([{"reasoning": "无发言", "say": ""}]),
        max_rounds=8,
        rule_set=rule_set,
        checkpoint_manager=checkpoint_manager,
        event_sink=sink,
    )

    message, action_log = engine._player_action(
        player=speaker,
        action=action,
        options=[],
        result_key="say",
        round_state=round_state,
        phase="day",
    )

    assert message == "本轮暂不追加判断，投票时我会给出明确选择。"
    assert action_log.execution_status == "fallback"
    assert action_log.fallback_reason == "required_public_speech_invalid"
    assert checkpoint_manager.successes == []
    assert checkpoint_manager.failures == []
    parsed_event = next(event for event in sink.events if event["type"] == "action_parsed")
    assert parsed_event["payload"]["result"]["say"] == message
    assert parsed_event["payload"]["fallback_reason"] == "required_public_speech_invalid"


def test_12_player_first_night_peace_is_announced_after_sheriff_election_before_debate() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_first_night_peace",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=66,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    witch = next(player.name for player in state.players if player.role == "女巫")
    sheriff = active_players[0]
    second_candidate = active_players[1]
    provider = FirstNightPeacefulSheriffProvider(
        protected_target=witch,
        candidates={sheriff, second_candidate},
        sheriff_vote_targets={
            name: sheriff for name in active_players if name not in {sheriff, second_candidate}
        },
    )
    sink = CapturingEventSink()
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)
    engine._run_day_phase(round_state, round_log, active_players, pending_deaths)

    assert pending_deaths == []
    assert round_state.night_deaths == []
    assert round_state.eliminated is None
    assert any("第1轮：夜晚无人出局。" in player.observations for player in state.players)
    night_update_index = next(
        index
        for index, event in enumerate(sink.events)
        if event["type"] == "state_updated"
        and event["phase"] == "night"
        and event["payload"]["night_deaths"] == []
    )
    first_debate_index = next(
        index
        for index, event in enumerate(sink.events)
        if event["type"] == "action_requested" and event["action"] == "debate"
    )
    dawn_index = next(
        index
        for index, event in enumerate(sink.events)
        if event["type"] == "judge_cue" and event["action"] == "dawn_peaceful"
    )
    assert night_update_index < dawn_index < first_debate_index


def test_sheriff_election_limits_speeches_to_candidates_and_votes_to_off_sheriff_players() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_rights",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=56,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    first_candidate = active_players[0]
    withdrawn_candidate = active_players[1]
    voter = active_players[2]
    provider = SheriffFlowProvider(
        candidates={first_candidate, withdrawn_candidate},
        withdraw={withdrawn_candidate},
        sheriff_vote_targets={name: first_candidate for name in active_players[2:]},
        speech_order_choice="警左发言",
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_candidates == [first_candidate, withdrawn_candidate]
    assert {entry["speaker"] for entry in round_state.sheriff_speeches} == {
        first_candidate,
        withdrawn_candidate,
    }
    assert set(round_state.sheriff_speech_order) == {first_candidate, withdrawn_candidate}
    assert round_state.sheriff_withdrawn == [withdrawn_candidate]
    assert round_state.sheriff_final_candidates == [first_candidate]
    assert round_state.sheriff_voters == active_players[2:]
    assert round_state.sheriff_votes == {}
    assert round_state.sheriff_elected == first_candidate
    assert state.sheriff == first_candidate
    assert ("sheriff_speech", voter) not in provider.actions
    assert ("sheriff_vote", first_candidate) not in provider.actions
    assert ("sheriff_vote", withdrawn_candidate) not in provider.actions
    assert any(entry.speaker == withdrawn_candidate for entry in round_state.debate)
    assert any(vote.actor == withdrawn_candidate for vote in round_log.votes[0])


def test_sheriff_election_runs_pk_and_runoff_when_first_vote_ties() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_pk",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=57,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    first_candidate = active_players[0]
    second_candidate = active_players[1]
    off_sheriff = active_players[2:]
    first_round_votes = {
        name: first_candidate if index % 2 == 0 else second_candidate
        for index, name in enumerate(off_sheriff)
    }
    runoff_votes = {name: first_candidate for name in off_sheriff}
    provider = SheriffFlowProvider(
        candidates={first_candidate, second_candidate},
        sheriff_vote_targets=first_round_votes,
        runoff_vote_targets=runoff_votes,
        speech_order_choice="警左发言",
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_pk_candidates == [first_candidate, second_candidate]
    assert [entry["speaker"] for entry in round_state.sheriff_pk_speeches] == [
        first_candidate,
        second_candidate,
    ]
    assert round_state.sheriff_runoff_votes == runoff_votes
    assert round_state.sheriff_elected == first_candidate
    assert state.sheriff == first_candidate
    assert round_state.sheriff_election_resolution is not None
    assert round_state.sheriff_election_resolution.reason_code == "runoff_vote_winner"
    assert [
        event["action"]
        for event in sink.events
        if event["type"] == "state_updated"
        and event["action"] in {"sheriff_pk_started", "sheriff_election_resolved"}
    ] == ["sheriff_pk_started", "sheriff_election_resolved"]
    assert [
        event["action"]
        for event in sink.events
        if event["type"] == "judge_cue"
        and event["action"]
        in {"sheriff_tie", "sheriff_pk_start", "sheriff_runoff_vote", "sheriff_result"}
    ] == ["sheriff_tie", "sheriff_pk_start", "sheriff_runoff_vote", "sheriff_result"]
    pk_facts = [fact for fact in state.public_facts if fact.get("stage") == "sheriff_pk_speech"]
    assert [fact["actor"] for fact in pk_facts] == [first_candidate, second_candidate]
    assert all(fact["retention"] == "critical" for fact in pk_facts)
    assert all(fact["fact_id"].startswith("r1:sheriff_pk_speech:") for fact in pk_facts)
    future_round = RoundState(number=4, players=active_players.copy())
    future_world_state = engine._world_state(
        state.player_by_name()[first_candidate],
        [],
        future_round,
    )
    self_history = future_world_state["public_self_history"]
    assert isinstance(self_history, list)
    assert any("第1轮警长PK发言" in line for line in self_history)
    future_prompt, _schema = build_prompt("debate", future_world_state)
    assert "你的公开发言历史" in future_prompt
    assert "第1轮警长PK发言" in future_prompt


def test_sheriff_badge_is_lost_and_all_players_are_off_sheriff_when_no_one_runs() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_no_candidates",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=61,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    provider = SheriffFlowProvider(
        candidates=set(),
        sheriff_vote_targets={},
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_candidates == []
    assert round_state.sheriff_voters == active_players
    assert round_state.sheriff_badge_lost is True
    assert state.sheriff is None
    assert round_state.sheriff_election_resolution is not None
    assert round_state.sheriff_election_resolution.reason_code == "no_candidates"
    resolution_events = [
        event for event in sink.events if event["action"] == "sheriff_election_resolved"
    ]
    assert len(resolution_events) == 1


def test_sheriff_badge_is_lost_when_no_candidates_remain_after_withdraw() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_all_withdraw",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=58,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    candidate = active_players[0]
    provider = SheriffFlowProvider(
        candidates={candidate},
        withdraw={candidate},
        sheriff_vote_targets={name: candidate for name in active_players[1:]},
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_final_candidates == []
    assert round_state.sheriff_badge_lost is True
    assert state.sheriff is None
    assert round_state.speech_order == active_players


def test_sheriff_badge_is_lost_when_all_players_run_and_multiple_candidates_remain() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_no_voters",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=59,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    provider = SheriffFlowProvider(
        candidates=set(active_players),
        sheriff_vote_targets={},
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_voters == []
    assert round_state.sheriff_badge_lost is True
    assert state.sheriff is None
    assert round_state.sheriff_election_resolution is not None
    assert round_state.sheriff_election_resolution.reason_code == "no_off_sheriff_voters"
    resolution_event = next(
        event for event in sink.events if event["action"] == "sheriff_election_resolved"
    )
    assert resolution_event["payload"]["sheriff_election"]["voters"] == []
    no_voters_cue = next(
        event
        for event in sink.events
        if event["type"] == "judge_cue" and event["action"] == "sheriff_no_voters"
    )
    assert no_voters_cue["payload"]["params"]["reason_code"] == "no_off_sheriff_voters"


def test_sheriff_vote_counts_as_one_and_half_votes() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_weight",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=57,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players[:4]]
    state.sheriff = active_players[0]
    engine = GameEngine(
        state=state, provider=ScriptedChineseProvider(), max_rounds=8, rule_set=rule_set
    )
    votes = {
        active_players[0]: active_players[1],
        active_players[2]: active_players[1],
        active_players[3]: active_players[2],
    }
    weights = {
        active_players[0]: 1.5,
        active_players[2]: 1.0,
        active_players[3]: 1.0,
    }

    assert engine._majority_vote(votes, active_players, weights) == active_players[1]


def test_majority_vote_requires_majority_of_active_vote_weight() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_active_vote_weight",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=59,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players[:4]]
    engine = GameEngine(
        state=state, provider=ScriptedChineseProvider(), max_rounds=8, rule_set=rule_set
    )
    votes = {active_players[0]: active_players[1]}
    weights = {name: 1.0 for name in active_players}

    assert engine._majority_vote(votes, active_players, weights) is None


def test_majority_vote_threshold_uses_eligible_voters_not_revealed_idiot() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_majority_eligible_voters",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=61,
        rule_set=rule_set,
    )
    idiot = next(player for player in state.players if player.role == "白痴")
    eligible_players = [player.name for player in state.players if player.name != idiot.name][:3]
    active_players = [*eligible_players, idiot.name]
    idiot.can_vote = False
    idiot.revealed_role = True
    engine = GameEngine(
        state=state, provider=ScriptedChineseProvider(), max_rounds=8, rule_set=rule_set
    )
    votes = {
        eligible_players[0]: eligible_players[2],
        eligible_players[1]: eligible_players[2],
    }
    weights = {name: 1.0 for name in eligible_players}

    assert engine._majority_vote(votes, active_players, weights) == eligible_players[2]


def test_dead_sheriff_can_transfer_badge() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_sheriff_badge",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=58,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    old_sheriff = active_players[0]
    new_sheriff = active_players[1]
    state.sheriff = old_sheriff
    state.player_by_name()[old_sheriff].is_sheriff = True
    provider = SheriffFlowProvider(
        candidates={old_sheriff},
        sheriff_vote_targets={name: old_sheriff for name in active_players if name != old_sheriff},
        badge_choice=new_sheriff,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    engine._remove_player(active_players, old_sheriff)
    round_state.day_deaths.append(DeathEvent(old_sheriff, "vote_exile", "投票"))
    engine._maybe_transfer_sheriff_badge(
        dead_player=old_sheriff,
        round_state=round_state,
        round_log=round_log,
        active_players=active_players,
        phase="vote",
    )

    assert state.sheriff == new_sheriff
    assert state.player_by_name()[old_sheriff].is_sheriff is False
    assert state.player_by_name()[new_sheriff].is_sheriff is True
    assert round_state.sheriff_badge_target == new_sheriff
    assert round_state.sheriff_badge_lost is False
    assert round_log.sheriff_badge is not None
    assert round_state.sheriff_badge_resolution is not None
    assert round_state.sheriff_badge_resolution.outcome == "transferred"
    badge_event = next(
        event for event in sink.events if event["action"] == "sheriff_badge_resolved"
    )
    assert badge_event["payload"]["sheriff"] == new_sheriff
    assert [
        event["action"]
        for event in sink.events
        if event["type"] == "judge_cue" and event["action"] in {"badge_owner_out", "badge_transfer"}
    ] == ["badge_owner_out", "badge_transfer"]


def test_living_sheriff_cannot_transfer_or_destroy_badge() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_living_sheriff_no_badge_transfer",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=58,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    old_sheriff = active_players[0]
    new_sheriff = active_players[1]
    state.sheriff = old_sheriff
    state.player_by_name()[old_sheriff].is_sheriff = True
    provider = SheriffFlowProvider(
        candidates={old_sheriff},
        sheriff_vote_targets={name: old_sheriff for name in active_players if name != old_sheriff},
        badge_choice=new_sheriff,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._maybe_transfer_sheriff_badge(
        dead_player=old_sheriff,
        round_state=round_state,
        round_log=round_log,
        active_players=active_players,
        phase="vote",
    )

    assert state.sheriff == old_sheriff
    assert state.player_by_name()[old_sheriff].is_sheriff is True
    assert state.player_by_name()[new_sheriff].is_sheriff is False
    assert round_state.sheriff_badge_target is None
    assert round_state.sheriff_badge_lost is False
    assert round_log.sheriff_badge is None


def test_hunter_shot_target_sheriff_transfers_badge() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_hunter_shot_sheriff_badge",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=62,
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    active_players = [player.name for player in state.players]
    hunter = next(player for player in state.players if player.role == "猎人")
    old_sheriff = next(player.name for player in state.players if player.name != hunter.name)
    new_sheriff = next(
        player.name for player in state.players if player.name not in {hunter.name, old_sheriff}
    )
    state.sheriff = old_sheriff
    players_by_name[old_sheriff].is_sheriff = True
    provider = HunterShotBadgeProvider(
        remove_target=hunter.name,
        save_choice="不使用解药",
        poison_choice="不使用毒药",
        shoot_choice=old_sheriff,
        badge_choice=new_sheriff,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._remove_player(active_players, hunter.name)
    engine._maybe_run_hunter_shot(
        dead_player=hunter.name,
        death_cause="vote_exile",
        round_state=round_state,
        round_log=round_log,
        active_players=active_players,
        phase="vote",
    )

    assert old_sheriff not in active_players
    assert state.sheriff == new_sheriff
    assert players_by_name[old_sheriff].is_sheriff is False
    assert players_by_name[new_sheriff].is_sheriff is True
    assert round_log.sheriff_badge is not None


def test_first_night_dead_elected_sheriff_transfers_badge_after_death_announcement() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_first_night_dead_sheriff_badge",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=60,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    players_by_name = state.player_by_name()
    dead_sheriff = next(name for name in active_players if players_by_name[name].role != "狼人")
    new_sheriff = next(
        name
        for name in active_players
        if name != dead_sheriff and players_by_name[name].role != "狼人"
    )
    provider = FirstNightSheriffDeathProvider(
        remove_target=dead_sheriff,
        candidates={dead_sheriff},
        badge_choice=new_sheriff,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    state.rounds.append(round_state)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)
    engine._run_day_phase(round_state, round_log, active_players, pending_deaths)

    assert round_state.sheriff_elected == dead_sheriff
    assert round_state.night_deaths[0].player == dead_sheriff
    assert dead_sheriff not in [player.name for player in state.players if player.is_sheriff]
    assert state.sheriff == new_sheriff
    assert players_by_name[new_sheriff].is_sheriff is True
    assert round_state.sheriff_badge_target == new_sheriff
    assert round_state.sheriff_badge_lost is False
    assert round_log.sheriff_badge is not None
    assert round_state.speech_order[-1] == new_sheriff
    new_sheriff_observations = players_by_name[new_sheriff].observations
    election_index = next(
        index
        for index, observation in enumerate(new_sheriff_observations)
        if f"警长竞选，{dead_sheriff}当选警长" in observation
    )
    night_death_index = next(
        index
        for index, observation in enumerate(new_sheriff_observations)
        if observation == f"第1轮：夜晚，{dead_sheriff}出局。"
    )
    badge_index = next(
        index
        for index, observation in enumerate(new_sheriff_observations)
        if observation == f"第1轮：{dead_sheriff}出局，将警徽移交给{new_sheriff}。"
    )
    assert election_index < night_death_index < badge_index


def test_werewolf_consensus_first_vote_sets_attacked() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_wolf_consensus_first_vote",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=501,
        rule_set=rule_set,
    )
    wolves = [player.name for player in state.players if player.role == "狼人"]
    target = next(player.name for player in state.players if player.role == "预言家")
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = WerewolfConsensusProvider(
        vote_rounds=[{wolf: target for wolf in wolves}],
        discussion_targets={wolf: target for wolf in wolves},
    )
    state.sheriff = next(player.name for player in state.players if player.name != target)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.attacked == target
    assert round_state.werewolf_vote_rounds == [
        {
            "round": 1,
            "candidates": [player.name for player in state.players if player.role != "狼人"],
            "votes": {wolf: target for wolf in wolves},
            "tally": {target: len(wolves)},
            "unanimous": True,
            "result": target,
        }
    ]
    assert len(round_state.werewolf_discussion) == len(wolves)
    assert len(round_log.werewolf_discussion) == len(wolves)
    assert len(round_log.werewolf_votes) == 1
    assert [log.actor for log in round_log.werewolf_votes[0]] == wolves
    assert round_log.eliminate is round_log.werewolf_votes[0][0]


def test_werewolf_consensus_revotes_until_unanimous() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_wolf_consensus_revoting",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=502,
        rule_set=rule_set,
    )
    wolves = [player.name for player in state.players if player.role == "狼人"]
    non_wolves = [player.name for player in state.players if player.role != "狼人"]
    first_target = non_wolves[0]
    second_target = non_wolves[1]
    final_target = first_target
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = WerewolfConsensusProvider(
        vote_rounds=[
            {
                wolves[0]: first_target,
                wolves[1]: second_target,
                wolves[2]: first_target,
                wolves[3]: second_target,
            },
            {wolf: final_target for wolf in wolves},
        ],
        discussion_targets={wolf: first_target for wolf in wolves},
    )
    state.sheriff = next(player.name for player in state.players if player.name != final_target)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.attacked == final_target
    assert [entry["round"] for entry in round_state.werewolf_vote_rounds] == [1, 2]
    assert round_state.werewolf_vote_rounds[0]["unanimous"] is False
    assert round_state.werewolf_vote_rounds[0]["result"] is None
    assert round_state.werewolf_vote_rounds[1]["unanimous"] is True
    assert round_state.werewolf_vote_rounds[1]["result"] == final_target
    assert round_state.werewolf_vote_rounds[1]["candidates"] == [first_target, second_target]
    assert len(round_log.werewolf_votes) == 2


def test_werewolf_consensus_can_converge_on_third_vote() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_wolf_consensus_third_vote",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=503,
        rule_set=rule_set,
    )
    wolves = [player.name for player in state.players if player.role == "狼人"]
    targets = [player.name for player in state.players if player.role != "狼人"][:3]
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = WerewolfConsensusProvider(
        vote_rounds=[
            {
                wolves[0]: targets[0],
                wolves[1]: targets[1],
                wolves[2]: targets[0],
                wolves[3]: targets[1],
            },
            {
                wolves[0]: targets[0],
                wolves[1]: targets[1],
                wolves[2]: targets[1],
                wolves[3]: targets[0],
            },
            {wolf: targets[1] for wolf in wolves},
        ],
        discussion_targets={wolf: targets[0] for wolf in wolves},
    )
    state.sheriff = next(player.name for player in state.players if player.name != targets[1])
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.attacked == targets[1]
    assert len(round_state.werewolf_vote_rounds) == 3
    assert round_state.werewolf_vote_rounds[2]["unanimous"] is True


def test_werewolf_consensus_errors_when_vote_round_limit_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_wolf_consensus_limit",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=504,
        rule_set=rule_set,
    )
    wolves = [player.name for player in state.players if player.role == "狼人"]
    non_wolves = [player.name for player in state.players if player.role != "狼人"]
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = WerewolfConsensusProvider(
        vote_rounds=[
            {wolves[0]: non_wolves[0], wolves[1]: non_wolves[1]},
            {wolves[0]: non_wolves[0], wolves[1]: non_wolves[1]},
        ],
        discussion_targets={wolf: non_wolves[0] for wolf in wolves},
    )
    monkeypatch.setattr("app.werewolf.engine.MAX_WEREWOLF_KILL_VOTE_ROUNDS", 2)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    with pytest.raises(RuntimeError, match="狼人夜晚投票未能达成一致"):
        engine._run_night_phase(round_state, round_log, active_players)


def test_guard_protects_consensus_werewolf_attack() -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_guard_consensus_attack",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=505,
        rule_set=rule_set,
    )
    wolves = [player.name for player in state.players if player.role == "狼人"]
    target = next(player.name for player in state.players if player.role == "村民")
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = WerewolfConsensusProvider(
        vote_rounds=[{wolf: target for wolf in wolves}],
        discussion_targets={wolf: target for wolf in wolves},
        protect_choice=target,
    )
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.attacked == target
    assert round_state.protected == target
    assert round_state.night_deaths == []
    assert target in active_players


def test_witch_can_save_consensus_werewolf_attack() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_witch_save_consensus_attack",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=506,
        rule_set=rule_set,
    )
    wolves = [player.name for player in state.players if player.role == "狼人"]
    witch = next(player for player in state.players if player.role == "女巫")
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = WerewolfConsensusProvider(
        vote_rounds=[{wolf: witch.name for wolf in wolves}],
        discussion_targets={wolf: witch.name for wolf in wolves},
        save_choice=witch.name,
    )
    state.sheriff = next(player.name for player in state.players if player.name != witch.name)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.attacked == witch.name
    assert round_state.saved_by_witch == witch.name
    assert round_state.night_deaths == []


def test_hunter_shoots_after_consensus_werewolf_attack_death() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_hunter_consensus_attack",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=507,
        rule_set=rule_set,
    )
    wolves = [player.name for player in state.players if player.role == "狼人"]
    hunter = next(player for player in state.players if player.role == "猎人")
    shot_target = wolves[0]
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    provider = WerewolfConsensusProvider(
        vote_rounds=[{wolf: hunter.name for wolf in wolves}],
        discussion_targets={wolf: hunter.name for wolf in wolves},
        shoot_choice=shot_target,
    )
    state.sheriff = next(
        player.name for player in state.players if player.name not in {hunter.name, shot_target}
    )
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)

    assert pending_deaths is None
    assert round_state.hunter_shot == shot_target
    assert [death.cause for death in round_state.night_deaths] == [
        "werewolf_attack",
        "hunter_shot",
    ]


def test_first_night_hunter_shot_is_announced_before_badge_and_debate() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_first_night_hunter_shot_full_announcement",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=67,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    hunter = next(player for player in state.players if player.role == "猎人")
    shot_sheriff = next(
        player.name
        for player in state.players
        if player.name != hunter.name and player.role != "狼人"
    )
    provider = FirstNightHunterShotBadgeProvider(
        remove_target=hunter.name,
        shoot_choice=shot_sheriff,
        candidates={shot_sheriff},
        sheriff_vote_targets={
            name: shot_sheriff for name in active_players if name != shot_sheriff
        },
        badge_choice=hunter.name,
    )
    sink = CapturingEventSink()
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    state.rounds.append(round_state)
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)
    engine._run_day_phase(round_state, round_log, active_players, pending_deaths)

    assert round_state.sheriff_elected == shot_sheriff
    assert [death.player for death in round_state.night_deaths] == [
        hunter.name,
        shot_sheriff,
    ]
    assert round_state.hunter_shot == shot_sheriff
    survivor = next(
        player for player in state.players if player.name not in {hunter.name, shot_sheriff}
    )
    full_death_message = f"第1轮：夜晚，{hunter.name}、{shot_sheriff}出局。"
    death_index = next(
        index
        for index, observation in enumerate(survivor.observations)
        if observation == full_death_message
    )
    badge_index = next(
        index
        for index, observation in enumerate(survivor.observations)
        if observation == f"第1轮：{shot_sheriff}出局，警徽被撕毁。"
    )
    assert death_index < badge_index
    assert round_state.sheriff_badge_target not in {hunter.name, shot_sheriff}
    assert state.sheriff not in {hunter.name, shot_sheriff}
    assert round_state.sheriff_badge_lost is True
    assert round_log.sheriff_badge is not None
    assert hunter.name not in round_log.sheriff_badge.options
    assert shot_sheriff not in round_log.sheriff_badge.options
    night_update_index = next(
        index
        for index, event in enumerate(sink.events)
        if event["type"] == "state_updated"
        and event["phase"] == "night"
        and event["payload"].get("night_deaths")
        == [
            {"player": hunter.name, "cause": "werewolf_attack", "source": "狼人"},
            {"player": shot_sheriff, "cause": "hunter_shot", "source": hunter.name},
        ]
    )
    first_debate_index = next(
        index
        for index, event in enumerate(sink.events)
        if event["type"] == "action_requested" and event["action"] == "debate"
    )
    assert night_update_index < first_debate_index


def test_first_night_badge_cannot_transfer_to_pending_dead_player() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_first_night_badge_excludes_pending_dead",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=61,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    players_by_name = state.player_by_name()
    dead_sheriff = next(name for name in active_players if players_by_name[name].role != "狼人")
    poisoned_player = next(
        name
        for name in active_players
        if name != dead_sheriff and players_by_name[name].role not in {"狼人", "女巫"}
    )
    provider = FirstNightPoisonBadgeProvider(
        remove_target=dead_sheriff,
        poison_choice=poisoned_player,
        candidates={dead_sheriff},
        badge_choice=poisoned_player,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    state.rounds.append(round_state)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._run_night_phase(round_state, round_log, active_players)
    engine._run_day_phase(round_state, round_log, active_players, pending_deaths)

    assert {death.player for death in round_state.night_deaths} >= {dead_sheriff, poisoned_player}
    assert round_state.sheriff_badge_target != poisoned_player
    assert state.sheriff != poisoned_player
    assert round_state.sheriff_badge_lost is True


def test_night_sheriff_badge_cannot_transfer_to_pending_night_death() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_night_badge_pending_death",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=63,
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    active_players = [player.name for player in state.players]
    old_sheriff = next(player.name for player in state.players if player.role != "猎人")
    poisoned_player = next(
        player.name
        for player in state.players
        if player.name != old_sheriff and player.role != "女巫"
    )
    state.sheriff = old_sheriff
    players_by_name[old_sheriff].is_sheriff = True
    provider = SheriffFlowProvider(
        candidates={old_sheriff},
        sheriff_vote_targets={name: old_sheriff for name in active_players if name != old_sheriff},
        badge_choice=poisoned_player,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.attacked = old_sheriff
    round_state.poisoned = poisoned_player
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._pending_night_deaths(round_state, active_players)
    engine._announce_night_deaths(pending_deaths, round_state, round_log, active_players)

    assert poisoned_player not in active_players
    assert round_state.sheriff_badge_target != poisoned_player
    assert state.sheriff != poisoned_player
    assert state.sheriff_badge_lost is True
    assert round_state.sheriff_badge_lost is True


def test_night_hunter_shot_sheriff_cannot_badge_pending_night_death() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_night_hunter_badge_pending_death",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=64,
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    active_players = [player.name for player in state.players]
    hunter = next(player for player in state.players if player.role == "猎人")
    old_sheriff = next(player.name for player in state.players if player.name != hunter.name)
    poisoned_player = next(
        player.name for player in state.players if player.name not in {hunter.name, old_sheriff}
    )
    state.sheriff = old_sheriff
    players_by_name[old_sheriff].is_sheriff = True
    provider = HunterShotBadgeProvider(
        remove_target=hunter.name,
        save_choice="不使用解药",
        poison_choice=poisoned_player,
        shoot_choice=old_sheriff,
        badge_choice=poisoned_player,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.attacked = hunter.name
    round_state.poisoned = poisoned_player
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._pending_night_deaths(round_state, active_players)
    engine._announce_night_deaths(pending_deaths, round_state, round_log, active_players)

    assert old_sheriff not in active_players
    assert poisoned_player not in active_players
    assert round_state.sheriff_badge_target != poisoned_player
    assert state.sheriff != poisoned_player
    assert state.sheriff_badge_lost is True
    assert round_state.sheriff_badge_lost is True


def test_night_hunter_cannot_shoot_pending_night_death() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_night_hunter_shot_pending_death",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=65,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    hunter = next(player for player in state.players if player.role == "猎人")
    poisoned_player = next(player.name for player in state.players if player.name != hunter.name)
    provider = HunterShotProvider(
        remove_target=hunter.name,
        save_choice="不使用解药",
        poison_choice=poisoned_player,
        shoot_choice=poisoned_player,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.attacked = hunter.name
    round_state.poisoned = poisoned_player
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    pending_deaths = engine._pending_night_deaths(round_state, active_players)
    engine._announce_night_deaths(pending_deaths, round_state, round_log, active_players)

    death_causes = [
        death.cause for death in round_state.night_deaths if death.player == poisoned_player
    ]
    assert death_causes == ["witch_poison"]
    assert round_state.hunter_shot != poisoned_player


class RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(
        self,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> object:
        self.events.append(
            {
                "type": event_type,
                "round": round_number,
                "phase": phase,
                "actor": actor,
                "action": action,
                "payload": payload or {},
            }
        )
        return None


def test_werewolf_consensus_live_events_publish_only_safe_vote_results() -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_wolf_consensus_event_privacy",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=508,
        rule_set=rule_set,
    )
    wolves = [player.name for player in state.players if player.role == "狼人"]
    target = next(player.name for player in state.players if player.role == "村民")
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    event_sink = RecordingEventSink()
    provider = WerewolfConsensusProvider(
        vote_rounds=[{wolf: target for wolf in wolves}],
        discussion_targets={wolf: target for wolf in wolves},
    )
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=event_sink,
    )

    engine._run_night_phase(round_state, round_log, active_players)

    wolf_start_event = next(
        event
        for event in event_sink.events
        if event["action"] == "remove" and event["type"] == "action_requested"
    )
    assert wolf_start_event == {
        "type": "action_requested",
        "round": 1,
        "phase": "night",
        "actor": None,
        "action": "remove",
        "payload": {},
    }
    wolf_cues = [
        event["action"]
        for event in event_sink.events
        if event["type"] == "judge_cue"
        and event["action"] in {"werewolves_wake", "werewolves_sleep"}
    ]
    assert wolf_cues == ["werewolves_wake", "werewolves_sleep"]
    private_decision_event_types = {
        "action_requested",
        "model_request_started",
        "model_response_delta",
        "model_thinking_delta",
        "model_thinking_tick",
        "model_response_received",
    }
    private_events = [
        event
        for event in event_sink.events
        if event["action"] in {"werewolf_discuss", "werewolf_kill_vote"}
        and event["type"] in private_decision_event_types
    ]
    assert private_events == []
    assert [
        event["actor"]
        for event in event_sink.events
        if event["action"] == "werewolf_kill_vote" and event["type"] == "action_parsed"
    ] == wolves
    public_target = f"{[player.name for player in state.players].index(target) + 1}号玩家"
    assert all(
        event["payload"]
        == {
            "choice": public_target,
            "result": {"target": public_target},
            "visible_result": {"target": public_target},
            "vote_round": 1,
        }
        for event in event_sink.events
        if event["action"] == "werewolf_kill_vote" and event["type"] == "action_parsed"
    )
    final_event = next(
        event
        for event in event_sink.events
        if event["action"] == "remove" and event["type"] == "action_parsed"
    )
    assert event_sink.events.index(wolf_start_event) < event_sink.events.index(final_event)
    wolf_wake = next(
        event
        for event in event_sink.events
        if event["type"] == "judge_cue" and event["action"] == "werewolves_wake"
    )
    wolf_sleep = next(
        event
        for event in event_sink.events
        if event["type"] == "judge_cue" and event["action"] == "werewolves_sleep"
    )
    assert (
        event_sink.events.index(wolf_wake)
        < event_sink.events.index(wolf_start_event)
        < event_sink.events.index(final_event)
        < event_sink.events.index(wolf_sleep)
    )
    assert final_event["actor"] is None
    assert final_event["payload"] == {
        "choice": public_target,
        "result": {"target": public_target},
        "visible_result": {"target": public_target},
        "vote_round": 1,
        "final_target": True,
    }
    assert not any(event["action"] == "werewolf_discuss" for event in event_sink.events)
    safe_wolf_events = [
        event
        for event in event_sink.events
        if event["action"] in {"werewolf_kill_vote", "remove"} and event["type"] == "action_parsed"
    ]
    assert "message" not in str(safe_wolf_events)
    assert "reasoning" not in str(safe_wolf_events)
    assert "raw_response" not in str(safe_wolf_events)
    assert [log.actor for log in round_log.werewolf_discussion] == wolves
    assert len(round_log.werewolf_votes) == 1
    assert [log.actor for log in round_log.werewolf_votes[0]] == wolves


def _read_db_outputs(
    store: DatabaseReplayStore,
    session_id: str,
) -> tuple[dict[str, object], list[object]]:
    replay = store.load_session(session_id)
    return _without_request_ids(replay["state"]), _without_request_ids(replay["logs"])


def _without_request_ids(value):
    if isinstance(value, dict):
        return {
            key: _without_request_ids(child) for key, child in value.items() if key != "request_id"
        }
    if isinstance(value, list):
        return [_without_request_ids(child) for child in value]
    return value


def _role_counts(players: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for player in players:
        role = str(player["role"])
        counts[role] = counts.get(role, 0) + 1
    return counts


def test_witch_poison_invalid_choice_falls_back_to_no_poison() -> None:
    class CapturingSink:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def publish(self, event_type: str, **kwargs: object) -> None:
            self.events.append({"type": event_type, **kwargs})

    sink = CapturingSink()
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="witch_poison_fallback",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=2026061501,
        rule_set=rule_set,
    )
    witch = next(player for player in state.players if player.role == WITCH)
    witch.witch_poison_available = True
    provider = FakeProvider(
        [
            {"reasoning": "想毒被刀目标", "poison": "10号玩家"},
            {"reasoning": "仍想毒被刀目标", "poison": "10号玩家"},
            {"reasoning": "继续毒被刀目标", "poison": "10号玩家"},
        ]
    )
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        rng=random.Random(1),
    )
    active_players = [witch.name, "6号玩家", "10号玩家", "12号玩家"]
    round_state = RoundState(number=5, players=active_players.copy(), attacked="10号玩家")
    round_log = RoundLog(number=5)

    engine._run_witch_phase(round_state, round_log, active_players)

    witch_cues = [event for event in sink.events if event["type"] == "judge_cue"]
    assert [event["action"] for event in witch_cues] == [
        "witch_wake",
        "witch_death",
        "witch_sleep",
    ]
    assert witch_cues[1]["payload"] == {
        "schema_version": 1,
        "cue_id": "witch_death",
        "cue": "witch_death",
        "visible_text": "今晚被狼人袭击的玩家是10号玩家。",
        "static_asset_id": "witch_death_seat_10",
        "params": {"target": "10号玩家"},
        "target": "10号玩家",
    }
    poison_request = next(
        event
        for event in sink.events
        if event["type"] == "action_requested" and event["action"] == ACTION_WITCH_POISON
    )
    assert (
        sink.events.index(witch_cues[0])
        < sink.events.index(witch_cues[1])
        < sink.events.index(poison_request)
        < sink.events.index(witch_cues[2])
    )
    assert round_state.poisoned is None
    assert round_log.witch_poison is not None
    assert round_log.witch_poison.choice == NO_WITCH_POISON
    assert round_log.witch_poison.invalid_value == "10号玩家"
    assert round_log.witch_poison.fallback_choice == NO_WITCH_POISON
    warning_event = next(
        event
        for event in sink.events
        if event["type"] == "action_quality_warning" and event["action"] == ACTION_WITCH_POISON
    )
    assert warning_event["payload"]["warnings"] == ["off_option_fallback"]
    assert warning_event["payload"]["invalid_value"] == "10号玩家"
    assert warning_event["payload"]["fallback_choice"] == NO_WITCH_POISON
    assert warning_event["payload"]["allowed_values"] == [
        "6号玩家",
        "12号玩家",
        NO_WITCH_POISON,
    ]
    parsed_event = next(
        event
        for event in sink.events
        if event["type"] == "action_parsed" and event["action"] == ACTION_WITCH_POISON
    )
    assert parsed_event["payload"]["choice"] == NO_WITCH_POISON
    assert parsed_event["payload"]["invalid_value"] == "10号玩家"
    assert parsed_event["payload"]["fallback_choice"] == NO_WITCH_POISON
    assert parsed_event["payload"]["fallback_reason"] == "optional_action_invalid"
    assert parsed_event["payload"]["attempt_count"] == 3


def test_hunter_invalid_shot_falls_back_to_no_shot() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="hunter_fallback",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=2026061502,
        rule_set=rule_set,
    )
    hunter = next(player for player in state.players if player.role == HUNTER)
    hunter.hunter_can_shoot = True
    provider = FakeProvider(
        [
            {"reasoning": "想带不存在玩家", "shoot": "99号玩家"},
            {"reasoning": "仍带不存在玩家", "shoot": "99号玩家"},
            {"reasoning": "继续带不存在玩家", "shoot": "99号玩家"},
        ]
    )
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    active_players = [hunter.name, "6号玩家", "12号玩家"]
    round_state = RoundState(number=5, players=active_players.copy())
    round_log = RoundLog(number=5)

    engine._maybe_run_hunter_shot(
        dead_player=hunter.name,
        death_cause="vote_exile",
        round_state=round_state,
        round_log=round_log,
        active_players=active_players,
        phase="day",
    )

    assert round_state.hunter_shot is None
    assert round_log.hunter_shoot is not None
    assert round_log.hunter_shoot.choice == NO_HUNTER_SHOT
    assert round_log.hunter_shoot.fallback_choice == NO_HUNTER_SHOT


def test_hunter_numeric_seat_alias_is_normalized_without_retry() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="hunter_numeric_alias",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=2026071401,
        rule_set=rule_set,
    )
    hunter = next(player for player in state.players if player.role == HUNTER)
    hunter.hunter_can_shoot = True
    candidates = [player for player in state.players if player is not hunter][:2]
    target = candidates[0]
    target_seat = state.players.index(target) + 1
    provider = FakeProvider(
        [{"reasoning": "直接返回座位数字", "shoot": target_seat}]
    )
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        rng=random.Random(1),
    )
    active_players = [hunter.name, *(player.name for player in candidates)]
    round_state = RoundState(number=5, players=active_players.copy())
    round_log = RoundLog(number=5)

    engine._maybe_run_hunter_shot(
        dead_player=hunter.name,
        death_cause="vote_exile",
        round_state=round_state,
        round_log=round_log,
        active_players=active_players,
        phase="day",
    )

    assert provider.calls == 1
    assert round_state.hunter_shot == target.name
    assert round_log.hunter_shoot is not None
    assert round_log.hunter_shoot.choice == target.name
    assert round_log.hunter_shoot.raw_choice == target_seat
    assert round_log.hunter_shoot.choice_normalization_kind == "seat_alias"


def test_secret_self_explosion_invalid_choice_falls_back_without_public_leak() -> None:
    sink = CapturingEventSink()
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="self_explosion_fallback_privacy",
        villager_model="deepseek-v4-flash",
        werewolf_model="deepseek-v4-flash",
        seed=2026061503,
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    wolf = next(player for player in state.players if player.role == WEREWOLF)
    provider = FakeProvider(
        [
            {"reasoning": "想选奇怪答案", "self_explode": "也许自爆"},
            {"reasoning": "继续选奇怪答案", "self_explode": "也许自爆"},
            {"reasoning": "仍然选奇怪答案", "self_explode": "也许自爆"},
        ]
    )
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        rng=random.Random(1),
    )
    round_state = RoundState(number=5, players=[player.name for player in state.players])

    choice, action_log = engine._player_action(
        player=players_by_name[wolf.name],
        action=ACTION_WEREWOLF_SELF_EXPLOSION,
        options=[WEREWOLF_SELF_EXPLODE, WEREWOLF_NO_SELF_EXPLODE],
        result_key="self_explode",
        round_state=round_state,
        phase="day",
    )

    assert choice == WEREWOLF_NO_SELF_EXPLODE
    assert action_log.choice == WEREWOLF_NO_SELF_EXPLODE
    assert action_log.invalid_value == "也许自爆"
    assert action_log.fallback_choice == WEREWOLF_NO_SELF_EXPLODE
    assert action_log.fallback_reason == "optional_action_invalid"
    leaking_events = [
        event
        for event in sink.events
        if event["type"] in {"action_quality_warning", "action_parsed"}
        and (
            event.get("actor") == wolf.name or event.get("action") == ACTION_WEREWOLF_SELF_EXPLOSION
        )
    ]
    assert leaking_events == []


def test_run_game_saves_in_progress_logs_when_required_action_fails(
    record_store: DatabaseReplayStore,
) -> None:
    provider = FakeProvider(
        [
            {"reasoning": "非法刀口", "target": "不存在玩家"},
            {"reasoning": "仍非法", "target": "不存在玩家"},
            {"reasoning": "继续非法", "target": "不存在玩家"},
        ]
    )

    with pytest.raises(GameRunError) as error:
        run_game(
            record_store=record_store,
            compiled_rule_set=legacy_official_compiled_rule_set("starter_6"),
            villager_model="deepseek-v4-flash",
            werewolf_model="deepseek-v4-flash",
            seed=2026061503,
            max_rounds=1,
            provider=provider,
            session_id="game_1200abcd",
        )

    assert error.value.session_id == "game_1200abcd"
    replay = record_store.load_session("game_1200abcd")
    logs = replay["logs"]

    assert logs
    assert logs[0]["number"] == 1


def test_run_game_does_not_write_legacy_game_json_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_store: DatabaseReplayStore,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = run_game(
        record_store=record_store,
        compiled_rule_set=legacy_official_compiled_rule_set(),
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    assert record_store.load_session(result.session_id)["status"] == "complete"
    assert list(tmp_path.rglob("game_complete.json")) == []
    assert list(tmp_path.rglob("game_partial.json")) == []
    assert list(tmp_path.rglob("game_logs.json")) == []
    assert list(tmp_path.rglob("resume_checkpoint.json")) == []
