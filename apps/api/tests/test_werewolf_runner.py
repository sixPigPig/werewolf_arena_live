import json
import multiprocessing
import queue
import random
import threading
from types import SimpleNamespace

import pytest

from app.werewolf.config import HUNTER, SEER, WEREWOLF
from app.werewolf.checkpoint import player_from_dict, round_log_from_dict, round_state_from_dict
from app.werewolf.engine import GameEngine, MaxRoundsExceeded, initialize_game_state
from app.werewolf.live import NullEventSink
from app.werewolf.models import DeathEvent, RoundLog, RoundState
from app.werewolf.player_configs import PlayerConfig
from app.werewolf.player_profile_prompts import compose_player_profile_prompt
from app.werewolf.prompts_zh import build_prompt
from app.werewolf.rules import MODEL_GROUP_WEREWOLF, get_rule_set
from app.werewolf.runner import GameRunError, run_game


class ScriptedChineseProvider:
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        options = _extract_options(prompt)
        choice = options[0] if options else "1"
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
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {"reasoning": "狼人私密沟通。", "target": choice, "message": f"建议袭击{choice}。"},
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps({"reasoning": "狼人统一刀口。", "target": choice}, ensure_ascii=False)
        if '"remove"' in prompt:
            return json.dumps({"reasoning": "他对狼人阵营威胁最大。", "remove": choice}, ensure_ascii=False)
        if '"protect"' in prompt:
            return json.dumps({"reasoning": "他可能是关键好人。", "protect": choice}, ensure_ascii=False)
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
                {"reasoning": "我需要记录本轮线索。", "summary": "我会继续关注发言矛盾最大的玩家。"},
                ensure_ascii=False,
            )
        if '"self_explode"' in prompt:
            return json.dumps(
                {"reasoning": "测试中默认不自爆。", "self_explode": "不自爆"},
                ensure_ascii=False,
            )
        if '"run"' in prompt:
            return json.dumps({"reasoning": "测试中默认参与警长竞选。", "run": choice}, ensure_ascii=False)
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
            return ['{"reasoning":"公开发言",', '"say":"我', '不是', '狼"}']
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
            return json.dumps({"reasoning": "根据身份争取警徽。", "run": choice}, ensure_ascii=False)
        if '"withdraw"' in prompt:
            self.actions.append(("sheriff_withdraw", name))
            choice = "退水" if name in self.withdraw else "不退水"
            return json.dumps({"reasoning": "根据警上形势决定是否退水。", "withdraw": choice}, ensure_ascii=False)
        if '"say"' in prompt and "警上竞选发言" in prompt:
            self.actions.append(("sheriff_speech", name))
            return json.dumps({"reasoning": "争取警徽。", "say": f"{name} 警上发言。"}, ensure_ascii=False)
        if '"say"' in prompt and "PK 发言" in prompt:
            self.actions.append(("sheriff_pk_speech", name))
            return json.dumps({"reasoning": "争取二轮票。", "say": f"{name} PK 发言。"}, ensure_ascii=False)
        if '"sheriff_vote"' in prompt and "行动：二轮警下投票" in prompt:
            self.actions.append(("sheriff_runoff_vote", name))
            choice = self.runoff_vote_targets[name]
            return json.dumps({"reasoning": "二轮选择。", "sheriff_vote": choice}, ensure_ascii=False)
        if '"sheriff_vote"' in prompt:
            self.actions.append(("sheriff_vote", name))
            choice = self.sheriff_vote_targets[name]
            return json.dumps({"reasoning": "选择最适合带队的人。", "sheriff_vote": choice}, ensure_ascii=False)
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
        del model, temperature
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
        del model, temperature
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            self.actions.append(("stream_sheriff_run", name))
            raise RuntimeError("stream failed before first chunk")
        return [self.complete_json(model=model, prompt=prompt, temperature=temperature)]

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
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
        del model, temperature
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
            return json.dumps({"reasoning": "测试自爆判断。", "self_explode": choice}, ensure_ascii=False)
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
                    return json.dumps({"reasoning": "测试分散投票。", "vote": choice}, ensure_ascii=False)
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
    assert serialized["werewolf_discussion"] == payload["werewolf_discussion"]
    assert serialized["werewolf_votes"] == payload["werewolf_votes"]


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
    assert round_state.werewolf_vote_rounds[0]["votes"] == {
        wolf: target for wolf in active_wolves
    }
    assert [log.actor for log in round_log.werewolf_votes[0]] == active_wolves


def _extract_options(prompt: str) -> list[str]:
    marker = next((candidate for candidate in ("候选人：", "候选选项：") if candidate in prompt), "")
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


def test_run_game_with_deepseek_models_writes_complete_chinese_logs(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    assert result.winner in {"好人阵营", "狼人阵营"}
    assert result.session_id.startswith("game_")
    assert result.log_directory.exists()
    assert (result.log_directory / "game_complete.json").exists()
    assert (result.log_directory / "game_logs.json").exists()

    state = json.loads((result.log_directory / "game_complete.json").read_text())
    logs = json.loads((result.log_directory / "game_logs.json").read_text())

    assert state["winner"] == result.winner
    assert len(state["players"]) == 8
    assert state["error_message"] == ""
    assert {player["role"] for player in state["players"]} == {"狼人", "预言家", "守卫", "村民"}
    assert any("第" in observation for player in state["players"] for observation in player["observations"])
    assert logs[0]["debate"]
    assert logs[0]["summaries"]
    assert "狼人杀" in logs[0]["debate"][0]["lm_log"]["prompt"]
    assert "我认为" in state["rounds"][0]["debate"][0]["message"]


def test_run_game_defaults_to_minimax_when_only_minimax_key_is_configured(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_MODEL=deepseek-v4-flash\n"
        "MINIMAX_API_KEY=minimax-key\n"
        "MINIMAX_MODEL=MiniMax-M2.7\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    result = run_game(
        logs_dir=tmp_path / "logs",
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    state = json.loads((result.log_directory / "game_complete.json").read_text())

    assert {player["model"] for player in state["players"]} == {"MiniMax-M2.7"}


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


def test_run_game_accepts_custom_session_id(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
        event_sink=NullEventSink(),
    )

    assert result.session_id == "game_1200abcd"
    assert result.log_directory == tmp_path / "game_1200abcd"


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


def test_run_game_publishes_streaming_model_events(tmp_path) -> None:
    sink = CapturingEventSink()

    with pytest.raises(GameRunError, match="Maximum rounds exceeded"):
        run_game(
            logs_dir=tmp_path,
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
    response_event = next(event for event in sink.events if event["type"] == "model_response_received")
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


def test_run_game_event_sink_does_not_change_final_logs(tmp_path) -> None:
    baseline = run_game(
        logs_dir=tmp_path / "baseline",
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
    )
    with_sink = run_game(
        logs_dir=tmp_path / "with_sink",
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
        event_sink=CapturingEventSink(),
    )

    assert _read_json_outputs(with_sink.log_directory) == _read_json_outputs(baseline.log_directory)


def test_live_model_events_do_not_publish_internal_model_payloads(tmp_path) -> None:
    sink = CapturingEventSink()
    run_game(
        logs_dir=tmp_path,
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="game_1200abcd",
        event_sink=sink,
    )

    model_events = [
        event
        for event in sink.events
        if event["type"]
        in {"model_request_started", "model_response_received", "action_parsed"}
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


def test_run_game_uses_starter_6_rule_set(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=31,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
        rule_set_id="starter_6",
    )

    state = json.loads((result.log_directory / "game_complete.json").read_text())

    assert state["rule_set"]["id"] == "starter_6"
    assert state["rule_set"]["name"] == "新手 6 人快局"
    assert len(state["players"]) == 6
    assert _role_counts(state["players"]) == {"狼人": 1, "预言家": 1, "守卫": 1, "村民": 3}


def test_run_game_uses_social_8_rule_set_without_divine_actions(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=37,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
        rule_set_id="social_8",
    )

    state = json.loads((result.log_directory / "game_complete.json").read_text())
    logs = json.loads((result.log_directory / "game_logs.json").read_text())

    assert len(state["players"]) == 8
    assert _role_counts(state["players"]) == {"狼人": 2, "村民": 6}
    assert logs[0]["protect"] is None
    assert logs[0]["investigate"] is None


def test_run_game_defaults_to_classic_8_rule_set(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=41,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    state = json.loads((result.log_directory / "game_complete.json").read_text())

    assert state["rule_set"]["id"] == "classic_8"
    assert len(state["players"]) == 8


def test_run_game_uses_12_player_seer_witch_hunter_idiot_rule_set(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=54,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
        rule_set_id="classic_12_seer_witch_hunter_idiot",
    )

    state = json.loads((result.log_directory / "game_complete.json").read_text())
    logs = json.loads((result.log_directory / "game_logs.json").read_text())

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
    rule_order = [
        role_spec.role
        for role_spec in rule_set.roles
        for _ in range(role_spec.count)
    ]
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
    round_state.sheriff_speeches = [
        {"speaker": state.players[0].name, "message": "我上警争警徽。"}
    ]
    round_state.sheriff_speech_order = [state.players[1].name, state.players[0].name]
    round_state.sheriff_speech_direction = "逆时针"
    round_state.sheriff_withdrawn = [state.players[1].name]
    round_state.sheriff_final_candidates = [state.players[0].name]
    round_state.sheriff_voters = [state.players[2].name]
    round_state.sheriff_votes = {state.players[2].name: state.players[0].name}
    round_state.sheriff_pk_candidates = [state.players[0].name, state.players[3].name]
    round_state.sheriff_pk_speeches = [
        {"speaker": state.players[3].name, "message": "我进入 PK。"}
    ]
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
    assert round_payload["sheriff_runoff_votes"] == {
        state.players[2].name: state.players[3].name
    }
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
        "sheriff_pre_election_bomb_count": 1,
    }

    prompt, schema = build_prompt("werewolf_self_explosion", world_state)

    assert "行动：狼人自爆判断" in prompt
    assert "警上发言前" in prompt
    assert "双爆吞警徽" in prompt
    assert "第二次警长产生前自爆会导致警徽流失" in prompt
    assert schema["required"] == ["reasoning", "self_explode"]


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
            wolf: "自爆" if wolf != active_wolves[0] else "不自爆"
            for wolf in active_wolves
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
        "并发自爆测试",
    )

    assert interrupted is True
    assert [
        actor for action, actor in provider.actions if action == "werewolf_self_explosion"
    ] == active_wolves
    assert round_state.werewolf_self_exploded == exploding_wolf
    assert round_log.werewolf_self_explosion is not None
    assert round_log.werewolf_self_explosion.actor == exploding_wolf
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
        if event["action"] == "werewolf_self_explosion"
        and event["type"] == "state_updated"
    ]
    assert public_updates
    assert public_updates[-1]["actor"] == exploding_wolf
    assert public_updates[-1]["payload"]["werewolf_self_exploded"] == exploding_wolf


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
    provider = SelfExplosionProvider(self_exploders=[exploding_wolf], candidates={active_players[0]})
    round_state = RoundState(number=2, players=active_players.copy())
    round_log = RoundLog(number=2)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_badge_lost is True
    assert state.sheriff_badge_lost is True
    assert state.sheriff_election_pending is False
    assert round_state.sheriff_badge_lost_reason == "双爆吞警徽"


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
    round_state.sheriff_speeches = [
        {"speaker": active_players[0], "message": "我上警争警徽。"}
    ]
    round_state.sheriff_withdrawn = [active_players[1]]
    round_state.sheriff_final_candidates = [active_players[0]]
    round_state.sheriff_pk_candidates = [active_players[0], active_players[3]]
    round_state.sheriff_pk_speeches = [
        {"speaker": active_players[3], "message": "我进入 PK。"}
    ]
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
    teammates = [player.name for player in state.players if player.role == "狼人" and player.name != wolf.name]

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
    gods = [player.name for player in state.players if player.role in {"预言家", "女巫", "猎人", "白痴"}]
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
        voter: next(name for name in active_players if name != voter)
        for voter in eligible_voters
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


def test_round_summaries_request_active_players_concurrently() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_parallel_summaries",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=59,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    provider = BarrierActionProvider(
        action_key="summarize",
        result_key="summary",
        response_value_by_actor={
            name: f"{name} 的并发总结"
            for name in active_players
        },
        expected_calls=len(active_players),
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_summaries(round_state, round_log, active_players)

    assert [
        actor for action, actor in provider.actions if action == "summarize"
    ] == active_players
    assert list(round_state.summaries) == active_players
    assert [log.actor for log in round_log.summaries] == active_players
    for name in active_players:
        assert state.player_by_name()[name].observations[-1] == (
            f"第1轮总结：{name} 的并发总结"
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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

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

    assert [
        actor for action, actor in provider.actions if action == "sheriff_vote"
    ] == voters
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
    first_round_votes = {
        name: candidates[index % 2]
        for index, name in enumerate(voters)
    }
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
    assert night_update_index < first_debate_index


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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_pk_candidates == [first_candidate, second_candidate]
    assert [entry["speaker"] for entry in round_state.sheriff_pk_speeches] == [
        first_candidate,
        second_candidate,
    ]
    assert round_state.sheriff_runoff_votes == runoff_votes
    assert round_state.sheriff_elected == first_candidate
    assert state.sheriff == first_candidate


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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_candidates == []
    assert round_state.sheriff_voters == active_players
    assert round_state.sheriff_badge_lost is True
    assert state.sheriff is None


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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_day_phase(round_state, round_log, active_players)

    assert round_state.sheriff_voters == []
    assert round_state.sheriff_badge_lost is True
    assert state.sheriff is None


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
    engine = GameEngine(state=state, provider=ScriptedChineseProvider(), max_rounds=8, rule_set=rule_set)
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
    engine = GameEngine(state=state, provider=ScriptedChineseProvider(), max_rounds=8, rule_set=rule_set)
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
    engine = GameEngine(state=state, provider=ScriptedChineseProvider(), max_rounds=8, rule_set=rule_set)
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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

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
        player.name
        for player in state.players
        if player.name not in {hunter.name, old_sheriff}
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
        name for name in active_players if name != dead_sheriff and players_by_name[name].role != "狼人"
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
            "candidates": [
                player.name for player in state.players if player.role != "狼人"
            ],
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
            {wolves[0]: targets[0], wolves[1]: targets[1], wolves[2]: targets[0], wolves[3]: targets[1]},
            {wolves[0]: targets[0], wolves[1]: targets[1], wolves[2]: targets[1], wolves[3]: targets[0]},
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
        and event["payload"]["night_deaths"]
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
        player.name
        for player in state.players
        if player.name not in {hunter.name, old_sheriff}
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


def test_werewolf_consensus_live_events_do_not_publish_wolf_actor() -> None:
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

    secret_actions = {"werewolf_discuss", "werewolf_kill_vote"}
    secret_decision_event_types = {
        "action_requested",
        "model_request_started",
        "model_response_delta",
        "model_thinking_delta",
        "model_thinking_tick",
        "model_response_received",
        "action_parsed",
    }
    secret_events = [
        event
        for event in event_sink.events
        if event["action"] in secret_actions and event["type"] in secret_decision_event_types
    ]
    assert secret_events == []
    assert [log.actor for log in round_log.werewolf_discussion] == wolves
    assert len(round_log.werewolf_votes) == 1
    assert [log.actor for log in round_log.werewolf_votes[0]] == wolves


def _read_json_outputs(log_directory) -> tuple[dict[str, object], list[object]]:
    complete = json.loads((log_directory / "game_complete.json").read_text())
    logs = json.loads((log_directory / "game_logs.json").read_text())
    return _without_request_ids(complete), _without_request_ids(logs)


def _without_request_ids(value):
    if isinstance(value, dict):
        return {
            key: _without_request_ids(child)
            for key, child in value.items()
            if key != "request_id"
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
