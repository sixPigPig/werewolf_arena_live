import json

import pytest

from app.werewolf.config import SEER
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.live import NullEventSink
from app.werewolf.models import RoundLog, RoundState
from app.werewolf.prompts_zh import build_prompt
from app.werewolf.rules import get_rule_set
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
        if '"run"' in prompt:
            return json.dumps({"reasoning": "测试中默认参与警长竞选。", "run": choice}, ensure_ascii=False)
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


class SheriffFlowProvider(ScriptedChineseProvider):
    def __init__(
        self,
        *,
        candidates: set[str],
        sheriff_vote_target: str,
        speech_order_choice: str = "警左发言",
        badge_choice: str = "撕毁警徽",
    ) -> None:
        self.candidates = candidates
        self.sheriff_vote_target = sheriff_vote_target
        self.speech_order_choice = speech_order_choice
        self.badge_choice = badge_choice
        self.actions: list[str] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        name = _extract_actor_name(prompt)
        if '"run"' in prompt:
            self.actions.append("sheriff_run")
            choice = "上警" if name in self.candidates else "不上警"
            return json.dumps({"reasoning": "根据身份争取警徽。", "run": choice}, ensure_ascii=False)
        if '"sheriff_vote"' in prompt:
            self.actions.append("sheriff_vote")
            return json.dumps(
                {"reasoning": "选择最适合带队的人。", "sheriff_vote": self.sheriff_vote_target},
                ensure_ascii=False,
            )
        if '"speech_order"' in prompt:
            self.actions.append("speech_order")
            return json.dumps(
                {"reasoning": "让关键位置最后归票。", "speech_order": self.speech_order_choice},
                ensure_ascii=False,
            )
        if '"badge"' in prompt:
            self.actions.append("sheriff_badge")
            options = _extract_options(prompt)
            choice = self.badge_choice if self.badge_choice in options else "撕毁警徽"
            return json.dumps(
                {"reasoning": "把警徽交给更可信的人。", "badge": choice},
                ensure_ascii=False,
            )
        if '"vote"' in prompt:
            options = _extract_options(prompt)
            living_players = _extract_living_players(prompt)
            if name in living_players:
                choice = living_players[(living_players.index(name) + 1) % len(living_players)]
                if choice not in options:
                    choice = options[0] if options else "1"
            else:
                choice = options[0] if options else "1"
            return json.dumps({"reasoning": "测试中分散放逐票。", "vote": choice}, ensure_ascii=False)
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


class WitchChoiceProvider:
    def __init__(self, *, remove_target: str, save_choice: str, poison_choice: str) -> None:
        self.remove_target = remove_target
        self.save_choice = save_choice
        self.poison_choice = poison_choice
        self.actions: list[str] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
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
        return json.dumps({"reasoning": "默认选择。", "bid": "0"}, ensure_ascii=False)


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
    assert {player["role"] for player in state["players"]} == {"狼人", "预言家", "守卫", "村民"}
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


class MutatingWorldStateSink:
    def publish(self, event_type: str, **kwargs: object) -> None:
        if event_type != "model_request_started":
            return

        payload = kwargs.get("payload")
        if not isinstance(payload, dict):
            return

        world_state = payload.get("world_state")
        if isinstance(world_state, dict):
            world_state["options"] = "__mutated_by_sink__"
            world_state["remaining_players"] = "__mutated_by_sink__"


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

    engine._run_night_phase(round_state, round_log, active_players)

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
        session_id="session_20260424_120000_ab12cd34",
    )
    with_sink = run_game(
        logs_dir=tmp_path / "with_sink",
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="session_20260424_120000_ab12cd34",
        event_sink=CapturingEventSink(),
    )

    assert _read_json_outputs(with_sink.log_directory) == _read_json_outputs(baseline.log_directory)


def test_model_request_world_state_event_payload_is_isolated_from_gameplay(tmp_path) -> None:
    baseline = run_game(
        logs_dir=tmp_path / "baseline",
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="session_20260424_120000_ab12cd34",
    )
    with_mutating_sink = run_game(
        logs_dir=tmp_path / "with_mutating_sink",
        seed=21,
        max_rounds=4,
        provider=ScriptedChineseProvider(),
        session_id="session_20260424_120000_ab12cd34",
        event_sink=MutatingWorldStateSink(),
    )

    assert _read_json_outputs(with_mutating_sink.log_directory) == _read_json_outputs(
        baseline.log_directory
    )


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


def test_sheriff_state_serializes_to_game_and_round_payloads() -> None:
    state = initialize_game_state(
        session_id="session_test_sheriff_payload",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=54,
        rule_set=get_rule_set("classic_12_seer_witch_hunter_idiot"),
    )
    state.sheriff = state.players[0].name
    state.players[0].is_sheriff = True
    round_state = RoundState(number=1, players=[player.name for player in state.players])
    round_state.sheriff = state.sheriff
    round_state.sheriff_candidates = [state.players[0].name, state.players[1].name]
    round_state.sheriff_votes = {state.players[2].name: state.players[0].name}
    round_state.speech_order = [player.name for player in state.players]
    round_state.vote_weights = {state.players[0].name: 1.5}
    state.rounds.append(round_state)

    payload = state.to_dict()

    assert payload["sheriff"] == state.players[0].name
    assert payload["players"][0]["is_sheriff"] is True
    assert payload["rounds"][0]["sheriff"] == state.players[0].name
    assert payload["rounds"][0]["sheriff_candidates"] == [
        state.players[0].name,
        state.players[1].name,
    ]
    assert payload["rounds"][0]["sheriff_votes"] == {
        state.players[2].name: state.players[0].name
    }
    assert payload["rounds"][0]["speech_order"] == [player.name for player in state.players]
    assert payload["rounds"][0]["vote_weights"] == {state.players[0].name: 1.5}


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
    vote_prompt, vote_schema = build_prompt("sheriff_vote", world_state)
    order_prompt, order_schema = build_prompt("speech_order", world_state)
    badge_prompt, badge_schema = build_prompt("sheriff_badge", world_state)

    assert "警长竞选" in run_prompt
    assert run_schema["required"] == ["reasoning", "run"]
    assert "警长投票" in vote_prompt
    assert vote_schema["required"] == ["reasoning", "sheriff_vote"]
    assert "发言方向" in order_prompt
    assert order_schema["required"] == ["reasoning", "speech_order"]
    assert "移交警徽" in badge_prompt
    assert badge_schema["required"] == ["reasoning", "badge"]


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

    engine._run_night_phase(round_state, round_log, active_players)

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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_night_phase(round_state, round_log, active_players)

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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_night_phase(round_state, round_log, active_players)

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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_night_phase(round_state, round_log, active_players)

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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._run_night_phase(round_state, round_log, active_players)

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
        sheriff_vote_target=sheriff,
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
        sheriff_vote_target=old_sheriff,
        badge_choice=new_sheriff,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._remove_player(active_players, old_sheriff)
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
        sheriff_vote_target=old_sheriff,
        badge_choice=poisoned_player,
    )
    round_state = RoundState(number=1, players=active_players.copy())
    round_state.attacked = old_sheriff
    round_state.poisoned = poisoned_player
    round_log = RoundLog(number=1)
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)

    engine._resolve_night_deaths(round_state, round_log, active_players)

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

    engine._resolve_night_deaths(round_state, round_log, active_players)

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

    engine._resolve_night_deaths(round_state, round_log, active_players)

    death_causes = [
        death.cause for death in round_state.night_deaths if death.player == poisoned_player
    ]
    assert death_causes == ["witch_poison"]
    assert round_state.hunter_shot != poisoned_player


def _read_json_outputs(log_directory) -> tuple[dict[str, object], list[object]]:
    complete = json.loads((log_directory / "game_complete.json").read_text())
    logs = json.loads((log_directory / "game_logs.json").read_text())
    return complete, logs


def _role_counts(players: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for player in players:
        role = str(player["role"])
        counts[role] = counts.get(role, 0) + 1
    return counts
