# Official Rule Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an official-rule-preset game platform so users can launch狼人杀 runs with `classic_8`, `starter_6`, or `social_8`, and see the selected rule in live and replay views.

**Architecture:** Add a backend `RuleSet` registry as the source of truth. Thread a selected `RuleSet` through game initialization, engine night actions, prompt rendering, live run metadata, events, and saved replay state. The frontend fetches official rule summaries, sends `rule_set_id` when launching runs, and renders a compact rule summary on create/live/replay screens.

**Tech Stack:** FastAPI, dataclasses, pytest, React, TanStack Query, TypeScript, Vitest, Testing Library.

---

## File Structure

- Create `apps/api/app/werewolf/rules.py`: official rule definitions, validation, lookup, snapshot serialization, and Chinese rule text rendering.
- Create `apps/api/tests/test_werewolf_rules.py`: backend tests for registry behavior and validation.
- Modify `apps/api/app/werewolf/models.py`: store `rule_set` on `GameState`.
- Modify `apps/api/app/werewolf/engine.py`: initialize players from `RuleSet`, run night actions based on rule config, and pass dynamic rule text to prompts.
- Modify `apps/api/app/werewolf/runner.py`: accept `rule_set_id`, resolve the rule, and pass it into `initialize_game_state()` and `GameEngine`.
- Modify `apps/api/app/werewolf/prompts_zh.py`: render `world_state["rule_text"]` instead of a fixed role composition.
- Modify `apps/api/app/werewolf/live.py`: store and emit rule metadata for live runs.
- Modify `apps/api/app/api/routes/games.py`: expose `GET /api/v1/games/rule-sets`, accept `rule_set_id` in run creation, and pass rule metadata to background runs.
- Modify `apps/api/app/werewolf/replay.py`: include `rule_set` in session summaries.
- Modify existing backend tests in `apps/api/tests/test_werewolf_runner.py`, `apps/api/tests/test_werewolf_lm.py`, and `apps/api/tests/test_games_api.py`.
- Create `apps/web/src/features/games/api/listRuleSets.ts`: fetch official rule summaries.
- Create `apps/web/src/features/games/components/RuleSetSummary.tsx`: reusable rule summary display.
- Modify `apps/web/src/features/games/types.ts`: add `RuleSetSummary` and optional rule fields on run/replay/session types.
- Modify `apps/web/src/features/games/components/CreateGameRunForm.tsx`: render official rule selection and submit `rule_set_id`.
- Modify `apps/web/src/pages/LiveGamePage.tsx` and `apps/web/src/pages/GameDetailPage.tsx`: display selected rule summary.
- Modify frontend tests in `apps/web/src/features/games/api/liveRunApi.test.ts`, `apps/web/src/pages/GamesPage.test.tsx`, `apps/web/src/pages/LiveGamePage.test.tsx`, and `apps/web/src/pages/GameDetailPage.test.tsx`.

---

### Task 1: Backend Official Rule Registry

**Files:**
- Create: `apps/api/app/werewolf/rules.py`
- Test: `apps/api/tests/test_werewolf_rules.py`

- [ ] **Step 1: Write failing tests for the official registry**

Create `apps/api/tests/test_werewolf_rules.py`:

```python
import pytest

from app.werewolf.rules import (
    CLASSIC_8,
    DEFAULT_RULE_SET_ID,
    OFFICIAL_RULE_SETS,
    RuleConfigurationError,
    get_rule_set,
    list_rule_set_summaries,
    render_rule_text,
    rule_set_snapshot,
    validate_rule_sets,
)


def test_official_rule_registry_contains_mvp_rules() -> None:
    assert DEFAULT_RULE_SET_ID == "classic_8"
    assert [rule.id for rule in OFFICIAL_RULE_SETS] == [
        "classic_8",
        "starter_6",
        "social_8",
    ]


def test_rule_role_counts_match_player_count() -> None:
    validate_rule_sets(OFFICIAL_RULE_SETS)

    for rule in OFFICIAL_RULE_SETS:
        assert sum(role.count for role in rule.roles) == rule.player_count


def test_get_rule_set_returns_classic_rule() -> None:
    rule = get_rule_set("classic_8")

    assert rule == CLASSIC_8
    assert rule.name == "经典 8 人局"
    assert rule.player_count == 8
    assert [role.role for role in rule.roles] == ["狼人", "预言家", "医生", "村民"]


def test_get_rule_set_rejects_unknown_id() -> None:
    with pytest.raises(KeyError, match="unknown_rule"):
        get_rule_set("unknown_rule")


def test_rule_set_snapshot_is_json_safe() -> None:
    snapshot = rule_set_snapshot(get_rule_set("starter_6"))

    assert snapshot == {
        "id": "starter_6",
        "version": "2026.04",
        "name": "新手 6 人快局",
        "description": "更短的官方入门局，适合快速观察模型策略。",
        "player_count": 6,
        "roles": [
            {"role": "狼人", "count": 1, "team": "werewolves", "model_group": "werewolf"},
            {"role": "预言家", "count": 1, "team": "villagers", "model_group": "villager"},
            {"role": "医生", "count": 1, "team": "villagers", "model_group": "villager"},
            {"role": "村民", "count": 3, "team": "villagers", "model_group": "villager"},
        ],
        "night_actions": ["remove", "protect", "investigate"],
        "day_actions": ["bid", "debate", "vote", "summarize"],
        "win_condition": "wolves_gte_others",
        "reveal_policy": "hidden",
        "complexity": "入门",
        "estimated_duration": "短",
    }


def test_rule_summaries_are_frontend_friendly() -> None:
    summaries = list_rule_set_summaries()

    assert summaries[0]["id"] == "classic_8"
    assert summaries[0]["role_summary"] == "2 狼人 / 1 预言家 / 1 医生 / 4 村民"
    assert summaries[1]["player_count"] == 6
    assert summaries[2]["night_actions"] == ["remove"]


def test_render_rule_text_matches_rule_actions() -> None:
    classic_text = render_rule_text(get_rule_set("classic_8"))
    social_text = render_rule_text(get_rule_set("social_8"))

    assert "共 8 名玩家：2 名狼人、1 名预言家、1 名医生、4 名村民。" in classic_text
    assert "医生保护一名玩家" in classic_text
    assert "预言家查验一名玩家身份" in classic_text
    assert "共 8 名玩家：2 名狼人、6 名村民。" in social_text
    assert "医生保护" not in social_text
    assert "预言家查验" not in social_text


def test_validate_rule_sets_rejects_duplicate_ids() -> None:
    duplicate = (get_rule_set("classic_8"), get_rule_set("classic_8"))

    with pytest.raises(RuleConfigurationError, match="Duplicate rule_set id"):
        validate_rule_sets(duplicate)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_rules.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.werewolf.rules'`.

- [ ] **Step 3: Implement `rules.py`**

Create `apps/api/app/werewolf/rules.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.werewolf.config import DOCTOR, SEER, VILLAGER, WEREWOLF

TEAM_VILLAGERS = "villagers"
TEAM_WEREWOLVES = "werewolves"
MODEL_GROUP_VILLAGER = "villager"
MODEL_GROUP_WEREWOLF = "werewolf"

ACTION_REMOVE = "remove"
ACTION_PROTECT = "protect"
ACTION_INVESTIGATE = "investigate"
ACTION_BID = "bid"
ACTION_DEBATE = "debate"
ACTION_VOTE = "vote"
ACTION_SUMMARIZE = "summarize"

WIN_CONDITION_WOLVES_GTE_OTHERS = "wolves_gte_others"
REVEAL_POLICY_HIDDEN = "hidden"
DEFAULT_RULE_SET_ID = "classic_8"


class RuleConfigurationError(ValueError):
    """Raised when official rule definitions are internally inconsistent."""


@dataclass(frozen=True)
class RoleSpec:
    role: str
    count: int
    team: str
    model_group: str


@dataclass(frozen=True)
class RuleSet:
    id: str
    version: str
    name: str
    description: str
    player_count: int
    roles: tuple[RoleSpec, ...]
    night_actions: tuple[str, ...]
    day_actions: tuple[str, ...]
    win_condition: str
    reveal_policy: str
    complexity: str
    estimated_duration: str

    def role_team(self, role: str) -> str:
        return next((spec.team for spec in self.roles if spec.role == role), TEAM_VILLAGERS)


CLASSIC_8 = RuleSet(
    id="classic_8",
    version="2026.04",
    name="经典 8 人局",
    description="保留当前默认玩法，适合作为模型对局基准。",
    player_count=8,
    roles=(
        RoleSpec(WEREWOLF, 2, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF),
        RoleSpec(SEER, 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
        RoleSpec(DOCTOR, 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
        RoleSpec(VILLAGER, 4, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
    ),
    night_actions=(ACTION_REMOVE, ACTION_PROTECT, ACTION_INVESTIGATE),
    day_actions=(ACTION_BID, ACTION_DEBATE, ACTION_VOTE, ACTION_SUMMARIZE),
    win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="标准",
    estimated_duration="中",
)

STARTER_6 = RuleSet(
    id="starter_6",
    version="2026.04",
    name="新手 6 人快局",
    description="更短的官方入门局，适合快速观察模型策略。",
    player_count=6,
    roles=(
        RoleSpec(WEREWOLF, 1, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF),
        RoleSpec(SEER, 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
        RoleSpec(DOCTOR, 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
        RoleSpec(VILLAGER, 3, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
    ),
    night_actions=(ACTION_REMOVE, ACTION_PROTECT, ACTION_INVESTIGATE),
    day_actions=(ACTION_BID, ACTION_DEBATE, ACTION_VOTE, ACTION_SUMMARIZE),
    win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="入门",
    estimated_duration="短",
)

SOCIAL_8 = RuleSet(
    id="social_8",
    version="2026.04",
    name="无神职心理局",
    description="只有狼人和村民，重点观察发言、欺骗和投票推理。",
    player_count=8,
    roles=(
        RoleSpec(WEREWOLF, 2, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF),
        RoleSpec(VILLAGER, 6, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
    ),
    night_actions=(ACTION_REMOVE,),
    day_actions=(ACTION_BID, ACTION_DEBATE, ACTION_VOTE, ACTION_SUMMARIZE),
    win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="心理",
    estimated_duration="中",
)

OFFICIAL_RULE_SETS = (CLASSIC_8, STARTER_6, SOCIAL_8)
_RULES_BY_ID = {rule.id: rule for rule in OFFICIAL_RULE_SETS}


def get_rule_set(rule_set_id: str = DEFAULT_RULE_SET_ID) -> RuleSet:
    return _RULES_BY_ID[rule_set_id]


def list_rule_set_summaries() -> list[dict[str, Any]]:
    return [rule_set_summary(rule) for rule in OFFICIAL_RULE_SETS]


def rule_set_summary(rule: RuleSet) -> dict[str, Any]:
    summary = rule_set_snapshot(rule)
    summary["role_summary"] = role_summary(rule)
    return summary


def rule_set_snapshot(rule: RuleSet) -> dict[str, Any]:
    payload = asdict(rule)
    payload["roles"] = [asdict(role) for role in rule.roles]
    payload["night_actions"] = list(rule.night_actions)
    payload["day_actions"] = list(rule.day_actions)
    return payload


def role_summary(rule: RuleSet) -> str:
    return " / ".join(f"{role.count} {role.role}" for role in rule.roles)


def render_rule_text(rule: RuleSet) -> str:
    night_parts: list[str] = []
    if ACTION_REMOVE in rule.night_actions:
        night_parts.append("狼人选择一名玩家出局")
    if ACTION_PROTECT in rule.night_actions:
        night_parts.append("医生保护一名玩家")
    if ACTION_INVESTIGATE in rule.night_actions:
        night_parts.append("预言家查验一名玩家身份")

    night_text = "；".join(night_parts)
    if ACTION_PROTECT in rule.night_actions:
        night_text += "。如果狼人目标被医生保护，则无人出局"

    return (
        "你正在进行一局数字版狼人杀。\n\n"
        "游戏规则：\n"
        f"- 共 {rule.player_count} 名玩家：{_role_count_text(rule)}。\n"
        "- 每轮包含夜晚和白天两个阶段。\n"
        f"- 夜晚：{night_text}。\n"
        "- 白天：所有存活玩家讨论，并投票放逐一名玩家。\n"
        "- 胜利条件：好人阵营放逐全部狼人即获胜；"
        "狼人数量大于或等于其他存活玩家数量时狼人获胜。\n"
    )


def validate_rule_sets(rule_sets: tuple[RuleSet, ...]) -> None:
    seen: set[str] = set()
    for rule in rule_sets:
        if rule.id in seen:
            raise RuleConfigurationError(f"Duplicate rule_set id: {rule.id}")
        seen.add(rule.id)

        if sum(role.count for role in rule.roles) != rule.player_count:
            raise RuleConfigurationError(f"Role counts do not match player count: {rule.id}")
        if rule.player_count <= 0:
            raise RuleConfigurationError(f"Rule must have at least one player: {rule.id}")
        if not any(role.team == TEAM_WEREWOLVES for role in rule.roles):
            raise RuleConfigurationError(f"Rule must include werewolves: {rule.id}")


def _role_count_text(rule: RuleSet) -> str:
    return "、".join(f"{role.count} 名{role.role}" for role in rule.roles)


validate_rule_sets(OFFICIAL_RULE_SETS)
```

- [ ] **Step 4: Run registry tests**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_rules.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit registry**

Run:

```bash
git add apps/api/app/werewolf/rules.py apps/api/tests/test_werewolf_rules.py
git commit -m "feat: add official rule registry"
```

---

### Task 2: Backend Engine Uses Rule Sets

**Files:**
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/runner.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Add failing runner tests for rule selection**

Append these tests to `apps/api/tests/test_werewolf_runner.py`:

```python
def test_run_game_uses_starter_6_rule_set(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
        rule_set_id="starter_6",
    )

    state = json.loads((result.log_directory / "game_complete.json").read_text())

    assert state["rule_set"]["id"] == "starter_6"
    assert state["rule_set"]["name"] == "新手 6 人快局"
    assert len(state["players"]) == 6
    assert _role_counts(state["players"]) == {
        "狼人": 1,
        "预言家": 1,
        "医生": 1,
        "村民": 3,
    }


def test_run_game_uses_social_8_rule_set_without_divine_actions(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
        rule_set_id="social_8",
    )

    state = json.loads((result.log_directory / "game_complete.json").read_text())
    logs = json.loads((result.log_directory / "game_logs.json").read_text())

    assert state["rule_set"]["id"] == "social_8"
    assert len(state["players"]) == 8
    assert _role_counts(state["players"]) == {"狼人": 2, "村民": 6}
    assert logs[0]["protect"] is None
    assert logs[0]["investigate"] is None


def test_run_game_defaults_to_classic_8_rule_set(tmp_path) -> None:
    result = run_game(
        logs_dir=tmp_path,
        seed=7,
        max_rounds=8,
        provider=ScriptedChineseProvider(),
    )

    state = json.loads((result.log_directory / "game_complete.json").read_text())

    assert state["rule_set"]["id"] == "classic_8"
    assert len(state["players"]) == 8


def _role_counts(players: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for player in players:
        role = str(player["role"])
        counts[role] = counts.get(role, 0) + 1
    return counts
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_runner.py::test_run_game_uses_starter_6_rule_set tests/test_werewolf_runner.py::test_run_game_uses_social_8_rule_set_without_divine_actions tests/test_werewolf_runner.py::test_run_game_defaults_to_classic_8_rule_set -v
```

Expected: FAIL because `run_game()` does not accept `rule_set_id` and `GameState` does not serialize `rule_set`.

- [ ] **Step 3: Store rule snapshots on game state**

Modify `apps/api/app/werewolf/models.py`:

```python
@dataclass
class GameState:
    session_id: str
    players: list[Player]
    rule_set: dict[str, Any] = field(default_factory=dict)
    rounds: list[RoundState] = field(default_factory=list)
    winner: str = ""
    error_message: str = ""

    def player_by_name(self) -> dict[str, Player]:
        return {player.name: player for player in self.players}

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "rule_set": self.rule_set,
            "players": [player.to_dict() for player in self.players],
            "rounds": [round_state.to_dict() for round_state in self.rounds],
            "winner": self.winner,
            "error_message": self.error_message,
        }
```

- [ ] **Step 4: Update engine initialization and night-action gating**

Modify imports in `apps/api/app/werewolf/engine.py`:

```python
from app.werewolf.rules import (
    ACTION_INVESTIGATE,
    ACTION_PROTECT,
    ACTION_REMOVE,
    MODEL_GROUP_WEREWOLF,
    TEAM_WEREWOLVES,
    RuleSet,
    render_rule_text,
    rule_set_snapshot,
)
```

Replace `initialize_game_state()` with:

```python
def initialize_game_state(
    *,
    session_id: str,
    villager_model: str,
    werewolf_model: str,
    seed: int | None,
    rule_set: RuleSet,
) -> GameState:
    player_names = choose_player_names(seed, player_count=rule_set.player_count)
    players: list[Player] = []
    next_name_index = 0

    for role_spec in rule_set.roles:
        model = werewolf_model if role_spec.model_group == MODEL_GROUP_WEREWOLF else villager_model
        for _index in range(role_spec.count):
            players.append(Player(player_names[next_name_index], role_spec.role, model))
            next_name_index += 1

    current_players = [player.name for player in players]
    werewolf_names = [player.name for player in players if rule_set.role_team(player.role) == TEAM_WEREWOLVES]

    for player in players:
        other_wolf = None
        if rule_set.role_team(player.role) == TEAM_WEREWOLVES:
            other_wolf = next((name for name in werewolf_names if name != player.name), None)
        player.gamestate = GameView(
            round_number=1,
            current_players=current_players.copy(),
            other_wolf=other_wolf,
        )

    return GameState(
        session_id=session_id,
        players=players,
        rule_set=rule_set_snapshot(rule_set),
    )
```

In `GameEngine.__init__()`, add `rule_set`:

```python
        rule_set: RuleSet,
```

and store it:

```python
        self.rule_set = rule_set
```

In `_run_night_phase()`, replace role checks with rule-action checks:

```python
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        non_wolves = [
            name for name in active_players if not self._is_werewolf(players_by_name[name])
        ]

        if ACTION_REMOVE in self.rule_set.night_actions and active_wolves and non_wolves:
            wolf = players_by_name[active_wolves[0]]
            eliminated, round_log.eliminate = self._player_action(
                player=wolf,
                action="remove",
                options=non_wolves,
                result_key="remove",
                round_state=round_state,
                phase="night",
            )
            round_state.eliminated = eliminated

        if ACTION_PROTECT in self.rule_set.night_actions and self._is_role_active(DOCTOR, active_players):
            doctor = players_by_name[self._active_player_for_role(DOCTOR, active_players)]
            protected, round_log.protect = self._player_action(
                player=doctor,
                action="protect",
                options=active_players,
                result_key="protect",
                round_state=round_state,
                phase="night",
            )
            round_state.protected = protected

        if ACTION_INVESTIGATE in self.rule_set.night_actions and self._is_role_active(SEER, active_players):
            seer = players_by_name[self._active_player_for_role(SEER, active_players)]
            investigate_options = [
                name
                for name in active_players
                if name != seer.name and name not in seer.known_roles
            ]
            investigated, round_log.investigate = self._player_action(
                player=seer,
                action="investigate",
                options=investigate_options,
                result_key="investigate",
                round_state=round_state,
                phase="night",
            )
            round_state.investigated = investigated
            if investigated:
                role = players_by_name[investigated].role
                seer.known_roles[investigated] = role
                seer.add_observation(f"第{round_state.number}轮：我查验了{investigated}，身份是{role}。")
```

In `_world_state()`, replace fixed counts with dynamic rule text:

```python
            "rule_text": render_rule_text(self.rule_set),
            "werewolf_context": self._werewolf_context(player, active_players),
```

Remove `"num_players": 8` and `"num_villagers": 4` from `_world_state()`.

Add helper to `GameEngine`:

```python
    def _is_werewolf(self, player: Player) -> bool:
        return self.rule_set.role_team(player.role) == TEAM_WEREWOLVES
```

Replace `_get_winner()` with:

```python
    def _get_winner(self, active_players: list[str]) -> str:
        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        active_villagers = [name for name in active_players if name not in active_wolves]

        if not active_wolves:
            return WINNER_VILLAGERS
        if len(active_wolves) >= len(active_villagers):
            return WINNER_WEREWOLVES
        return ""
```

- [ ] **Step 5: Update runner to resolve rule sets**

Modify `apps/api/app/werewolf/runner.py` imports:

```python
from app.werewolf.rules import DEFAULT_RULE_SET_ID, get_rule_set
```

Add parameter to `run_game()`:

```python
    rule_set_id: str = DEFAULT_RULE_SET_ID,
```

Resolve before initialization:

```python
    rule_set = get_rule_set(rule_set_id)
    state = initialize_game_state(
        session_id=session_id,
        villager_model=villager_model,
        werewolf_model=werewolf_model,
        seed=seed,
        rule_set=rule_set,
    )
```

Pass into engine:

```python
        engine = GameEngine(
            state=state,
            provider=provider or DeepSeekProvider(),
            max_rounds=max_rounds,
            rule_set=rule_set,
            event_sink=event_sink or NullEventSink(),
        )
```

- [ ] **Step 6: Run runner tests**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_runner.py -v
```

Expected: FAIL only in prompt-related assertions because `prompts_zh.py` still expects fixed `num_players` keys.

- [ ] **Step 7: Commit engine wiring after prompt task passes**

Do not commit yet if Step 6 still fails. This task commits after Task 3 also passes:

```bash
git add apps/api/app/werewolf/models.py apps/api/app/werewolf/engine.py apps/api/app/werewolf/runner.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: initialize games from rule presets"
```

---

### Task 3: Dynamic Prompt Rule Text

**Files:**
- Modify: `apps/api/app/werewolf/prompts_zh.py`
- Modify: `apps/api/tests/test_werewolf_lm.py`
- Test: `apps/api/tests/test_werewolf_lm.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Update prompt tests for dynamic rule text**

Modify `test_chinese_prompt_contains_rules_role_and_json_instruction()` in `apps/api/tests/test_werewolf_lm.py` so the world state includes `rule_text`:

```python
def test_chinese_prompt_contains_rules_role_and_json_instruction() -> None:
    prompt, schema = build_prompt(
        "vote",
        {
            "name": "阿宁",
            "role": "村民",
            "round": 2,
            "observations": ["第1轮：昨晚无人出局。"],
            "remaining_players": "阿宁、老周、小白",
            "debate": ["老周：我怀疑小白。"],
            "bidding_rationale": "我需要说明自己的判断。",
            "personality": "",
            "rule_text": "你正在进行一局数字版狼人杀。\n\n游戏规则：\n- 共 6 名玩家：1 名狼人、1 名预言家、1 名医生、3 名村民。",
            "werewolf_context": "",
            "debate_turns_left": 2,
            "options": "老周、小白",
        },
    )

    assert "狼人杀" in prompt
    assert "共 6 名玩家：1 名狼人、1 名预言家、1 名医生、3 名村民" in prompt
    assert "你是阿宁，身份是村民" in prompt
    assert "请只输出合法 JSON" in prompt
    assert '"vote"' in prompt
    assert "字段含义：reasoning=推理，vote=投票对象" in prompt
    assert schema["required"] == ["reasoning", "vote"]
```

In `test_generate_action_retries_until_allowed_value()` and `test_generate_action_accepts_numeric_value_for_string_allowed_values()`, replace `num_players` and `num_villagers` keys with:

```python
            "rule_text": "你正在进行一局数字版狼人杀。",
```

- [ ] **Step 2: Run prompt tests to verify they fail**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_lm.py::test_chinese_prompt_contains_rules_role_and_json_instruction -v
```

Expected: FAIL with `KeyError: 'num_players'`.

- [ ] **Step 3: Update prompt rendering**

Modify `apps/api/app/werewolf/prompts_zh.py`.

Replace `GAME_RULES` with a fallback:

```python
DEFAULT_GAME_RULES = """你正在进行一局数字版狼人杀。

游戏规则：
- 共 8 名玩家：2 名狼人、1 名预言家、1 名医生、4 名村民。
- 每轮包含夜晚和白天两个阶段。
- 夜晚：狼人选择一名玩家出局；预言家查验一名玩家身份；医生保护一名玩家。如果狼人目标被医生保护，则无人出局。
- 白天：所有存活玩家讨论，并投票放逐一名玩家。
- 胜利条件：好人阵营放逐全部狼人即获胜；狼人数量大于或等于其他存活玩家数量时狼人获胜。
"""
```

Replace `_render_base()` with:

```python
def _render_base(world_state: dict[str, Any]) -> str:
    rules_text = str(world_state.get("rule_text") or DEFAULT_GAME_RULES)
    personality = world_state.get("personality") or "无"
    werewolf_context = world_state.get("werewolf_context") or ""
    return (
        f"{rules_text}\n"
        "当前状态：\n"
        f"- 现在是第 {world_state['round']} 轮。\n"
        f"- 你是{world_state['name']}，身份是{world_state['role']}。{werewolf_context}\n"
        f"- 你的性格设定：{personality}\n"
        f"- 当前存活玩家：{world_state['remaining_players']}"
    )
```

- [ ] **Step 4: Run prompt and runner tests**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_lm.py tests/test_werewolf_runner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit prompt and engine wiring**

Run:

```bash
git add apps/api/app/werewolf/prompts_zh.py apps/api/tests/test_werewolf_lm.py apps/api/app/werewolf/models.py apps/api/app/werewolf/engine.py apps/api/app/werewolf/runner.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: render prompts from selected rule"
```

---

### Task 4: API, Live Run Metadata, and Replay Summaries

**Files:**
- Modify: `apps/api/app/werewolf/live.py`
- Modify: `apps/api/app/api/routes/games.py`
- Modify: `apps/api/app/werewolf/replay.py`
- Test: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: Add failing API tests**

Add these tests to `apps/api/tests/test_games_api.py`:

```python
def test_list_rule_sets_returns_official_rules() -> None:
    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 200
    payload = response.json()
    assert [rule["id"] for rule in payload["rule_sets"]] == [
        "classic_8",
        "starter_6",
        "social_8",
    ]
    assert payload["rule_sets"][0]["role_summary"] == "2 狼人 / 1 预言家 / 1 医生 / 4 村民"


def test_create_game_run_accepts_rule_set_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "starter_6", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["rule_set"]["id"] == "starter_6"
    assert captured[0]["rule_set_id"] == "starter_6"


def test_create_game_run_rejects_unknown_rule_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "missing_rule", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown rule set: missing_rule"


def test_list_games_includes_rule_set_summary(tmp_path: Path) -> None:
    session_id = "session_20260424_050950_66ea9f38"
    state = sample_state(session_id)
    state["rule_set"] = {
        "id": "social_8",
        "version": "2026.04",
        "name": "无神职心理局",
        "player_count": 8,
        "roles": [{"role": "狼人", "count": 2}, {"role": "村民", "count": 6}],
    }
    write_json(tmp_path / session_id / "game_complete.json", state)
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["sessions"][0]["rule_set"]["id"] == "social_8"
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
cd apps/api && uv run pytest tests/test_games_api.py::test_list_rule_sets_returns_official_rules tests/test_games_api.py::test_create_game_run_accepts_rule_set_id tests/test_games_api.py::test_create_game_run_rejects_unknown_rule_set tests/test_games_api.py::test_list_games_includes_rule_set_summary -v
```

Expected: FAIL because the route and live metadata do not exist.

- [ ] **Step 3: Update live run metadata**

Modify `apps/api/app/werewolf/live.py`.

Add fields to `LiveGameRun`:

```python
    rule_set_id: str
    rule_set: dict[str, Any]
```

In `to_summary()`, include:

```python
            "rule_set_id": self.rule_set_id,
            "rule_set": self.rule_set,
```

Change `LiveRunRegistry.create_run()` signature:

```python
        rule_set_id: str,
        rule_set: dict[str, Any],
```

Pass those into `LiveGameRun`:

```python
                rule_set_id=rule_set_id,
                rule_set=rule_set,
```

Add to `run_created` payload:

```python
                    "rule_set_id": rule_set_id,
                    "rule_set": rule_set,
```

Update existing direct registry calls in `apps/api/tests/test_games_api.py`, including `test_game_run_events_replays_existing_events()`, so they pass rule metadata:

```python
    run = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={
            "id": "classic_8",
            "version": "2026.04",
            "name": "经典 8 人局",
            "player_count": 8,
            "roles": [],
        },
    )
```

- [ ] **Step 4: Update games API routes**

Modify imports in `apps/api/app/api/routes/games.py`:

```python
from app.werewolf.rules import DEFAULT_RULE_SET_ID, get_rule_set, list_rule_set_summaries, rule_set_snapshot
```

Add field to `CreateGameRunRequest`:

```python
    rule_set_id: str = DEFAULT_RULE_SET_ID
```

Add route before `@router.get("/{session_id}")`:

```python
@router.get("/rule-sets")
def list_rule_sets() -> dict:
    return {"rule_sets": list_rule_set_summaries()}
```

At the start of `create_game_run()`:

```python
    try:
        rule_set = get_rule_set(request.rule_set_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown rule set: {request.rule_set_id}",
        ) from exc
    rule_snapshot = rule_set_snapshot(rule_set)
```

Pass rule metadata to `registry.create_run()`:

```python
        rule_set_id=rule_set.id,
        rule_set=rule_snapshot,
```

Pass `rule_set_id` to background thread kwargs:

```python
            "rule_set_id": rule_set.id,
```

Add parameter to `_run_game_in_background()`:

```python
    rule_set_id: str,
```

Pass to `run_game()`:

```python
            rule_set_id=rule_set_id,
```

- [ ] **Step 5: Include rule_set in replay session summaries**

Modify `apps/api/app/werewolf/replay.py` inside `list_sessions()` session payload:

```python
                    "rule_set": state.get("rule_set"),
```

- [ ] **Step 6: Run API tests**

Run:

```bash
cd apps/api && uv run pytest tests/test_games_api.py -v
```

Expected: PASS.

- [ ] **Step 7: Run all backend tests**

Run:

```bash
cd apps/api && uv run pytest -v
```

Expected: PASS.

- [ ] **Step 8: Commit API metadata**

Run:

```bash
git add apps/api/app/werewolf/live.py apps/api/app/api/routes/games.py apps/api/app/werewolf/replay.py apps/api/tests/test_games_api.py
git commit -m "feat: expose selected rule metadata"
```

---

### Task 5: Frontend Rule Types, API Client, and Create Form

**Files:**
- Create: `apps/web/src/features/games/api/listRuleSets.ts`
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Test: `apps/web/src/features/games/api/liveRunApi.test.ts`
- Test: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Add frontend types and API test expectations**

Modify `apps/web/src/features/games/types.ts`:

```ts
export type RoleSpecSummary = {
  role: string;
  count: number;
  team?: string;
  model_group?: string;
};

export type RuleSetSummary = {
  id: string;
  version: string;
  name: string;
  description?: string;
  player_count: number;
  roles: RoleSpecSummary[];
  night_actions?: string[];
  day_actions?: string[];
  win_condition?: string;
  reveal_policy?: string;
  complexity?: string;
  estimated_duration?: string;
  role_summary?: string;
};

export type RuleSetsResponse = {
  rule_sets: RuleSetSummary[];
};
```

Add optional `rule_set?: RuleSetSummary | null;` to `GameSessionSummary`, `RawGameState`, and `GameRun`.

Add `rule_set_id?: string;` to `CreateGameRunRequest`.

Modify `apps/web/src/features/games/api/liveRunApi.test.ts` create-run mock to include:

```ts
          rule_set_id: "starter_6",
          rule_set: {
            id: "starter_6",
            version: "2026.04",
            name: "新手 6 人快局",
            player_count: 6,
            roles: [],
          },
```

Change create call and expected body:

```ts
    const run = await createGameRun({
      rule_set_id: "starter_6",
      seed: 21,
      max_rounds: 8,
    });
```

```ts
        body: JSON.stringify({
          rule_set_id: "starter_6",
          seed: 21,
          max_rounds: 8,
        }),
```

- [ ] **Step 2: Add rule list API client**

Create `apps/web/src/features/games/api/listRuleSets.ts`:

```ts
import { apiFetch } from "../../../api/client";
import type { RuleSetsResponse } from "../types";

export function listRuleSets(): Promise<RuleSetsResponse> {
  return apiFetch<RuleSetsResponse>("/api/v1/games/rule-sets");
}
```

- [ ] **Step 3: Run API client tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/api/liveRunApi.test.ts
```

Expected: PASS.

- [ ] **Step 4: Update create form tests to mock rule-set fetch**

In `apps/web/src/pages/GamesPage.test.tsx`, add helper near the top:

```ts
function ruleSetsResponse() {
  return {
    rule_sets: [
      {
        id: "classic_8",
        version: "2026.04",
        name: "经典 8 人局",
        description: "保留当前默认玩法，适合作为模型对局基准。",
        player_count: 8,
        roles: [
          { role: "狼人", count: 2 },
          { role: "预言家", count: 1 },
          { role: "医生", count: 1 },
          { role: "村民", count: 4 },
        ],
        role_summary: "2 狼人 / 1 预言家 / 1 医生 / 4 村民",
        complexity: "标准",
        estimated_duration: "中",
      },
      {
        id: "starter_6",
        version: "2026.04",
        name: "新手 6 人快局",
        description: "更短的官方入门局，适合快速观察模型策略。",
        player_count: 6,
        roles: [
          { role: "狼人", count: 1 },
          { role: "预言家", count: 1 },
          { role: "医生", count: 1 },
          { role: "村民", count: 3 },
        ],
        role_summary: "1 狼人 / 1 预言家 / 1 医生 / 3 村民",
        complexity: "入门",
        estimated_duration: "短",
      },
    ],
  };
}
```

For each `fetch` mock in the file, return `ruleSetsResponse()` when the URL ends with `/api/v1/games/rule-sets`.

Add a test:

```ts
  it("renders official rule presets and submits the selected rule", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_1234abcd",
              session_id: "session_20260424_120000_ab12cd34",
              rule_set_id: "starter_6",
              rule_set: ruleSetsResponse().rule_sets[1],
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              seed: null,
              max_rounds: 8,
              status: "queued",
              created_at: "2026-04-24T12:00:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games" element={<GamesPage />} />
        <Route path="/games/live/:runId" element={<p>实时观战 run_1234abcd</p>} />
      </Routes>,
      "/games",
    );

    await userEvent.click(await screen.findByRole("radio", { name: /新手 6 人快局/ }));
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({
        body: JSON.stringify({
          rule_set_id: "starter_6",
          seed: null,
          max_rounds: 8,
        }),
        method: "POST",
      }),
    );
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });
```

- [ ] **Step 5: Run page test to verify it fails before UI update**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL because no rule radios are rendered.

- [ ] **Step 6: Update create form UI**

Modify `apps/web/src/features/games/components/CreateGameRunForm.tsx`.

Replace the TanStack Query import with:

```ts
import { useMutation, useQuery } from "@tanstack/react-query";
import { listRuleSets } from "../api/listRuleSets";
```

Add state and query:

```ts
  const [selectedRuleSetId, setSelectedRuleSetId] = useState("classic_8");
  const {
    data: ruleSetsData,
    isError: isRuleSetsError,
    isPending: isRuleSetsPending,
  } = useQuery({
    queryKey: ["rule-sets"],
    queryFn: listRuleSets,
  });
  const ruleSets = ruleSetsData?.rule_sets ?? [];
```

In submit payload:

```ts
        mutation.mutate({
          rule_set_id: selectedRuleSetId,
          seed: seed ? Number(seed) : null,
          max_rounds: parsedMaxRounds,
        });
```

Before the existing seed/max-round controls, render:

```tsx
      <fieldset className="mb-4">
        <legend className="text-sm font-semibold text-slate-950">官方规则</legend>
        {isRuleSetsPending ? (
          <p className="mt-2 text-sm text-slate-600">正在读取官方规则...</p>
        ) : isRuleSetsError ? (
          <p className="mt-2 text-sm text-red-700">无法读取官方规则</p>
        ) : (
          <div className="mt-2 grid gap-2 md:grid-cols-3">
            {ruleSets.map((rule) => (
              <label
                className={`cursor-pointer rounded-md border p-3 text-sm ${
                  selectedRuleSetId === rule.id
                    ? "border-slate-950 bg-slate-50"
                    : "border-slate-200 bg-white"
                }`}
                key={rule.id}
              >
                <input
                  checked={selectedRuleSetId === rule.id}
                  className="sr-only"
                  name="rule_set_id"
                  onChange={() => setSelectedRuleSetId(rule.id)}
                  type="radio"
                />
                <span className="block font-semibold text-slate-950">
                  {rule.name}
                </span>
                <span className="mt-1 block text-xs text-slate-600">
                  {rule.player_count} 人 · {rule.complexity ?? "标准"} · {rule.estimated_duration ?? "中"}
                </span>
                <span className="mt-2 block text-xs text-slate-700">
                  {rule.role_summary ??
                    rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ")}
                </span>
              </label>
            ))}
          </div>
        )}
      </fieldset>
```

Disable submit when rules are unavailable:

```tsx
          disabled={mutation.isPending || isRuleSetsPending || isRuleSetsError}
```

- [ ] **Step 7: Run frontend form tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx src/features/games/api/liveRunApi.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit frontend rule picker**

Run:

```bash
git add apps/web/src/features/games/api/listRuleSets.ts apps/web/src/features/games/types.ts apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/features/games/api/liveRunApi.test.ts apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat: select official rule presets"
```

---

### Task 6: Frontend Rule Summaries on Live and Replay Pages

**Files:**
- Create: `apps/web/src/features/games/components/RuleSetSummary.tsx`
- Modify: `apps/web/src/features/games/api/adapters.ts`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/GameDetailPage.tsx`
- Test: `apps/web/src/pages/LiveGamePage.test.tsx`
- Test: `apps/web/src/pages/GameDetailPage.test.tsx`

- [ ] **Step 1: Add reusable rule summary component**

Create `apps/web/src/features/games/components/RuleSetSummary.tsx`:

```tsx
import type { RuleSetSummary as RuleSetSummaryType } from "../types";

type RuleSetSummaryProps = {
  ruleSet?: RuleSetSummaryType | null;
};

const FALLBACK_RULE: RuleSetSummaryType = {
  id: "classic_8",
  version: "legacy",
  name: "经典 8 人局",
  player_count: 8,
  roles: [
    { role: "狼人", count: 2 },
    { role: "预言家", count: 1 },
    { role: "医生", count: 1 },
    { role: "村民", count: 4 },
  ],
  role_summary: "2 狼人 / 1 预言家 / 1 医生 / 4 村民",
};

export function RuleSetSummary({ ruleSet }: RuleSetSummaryProps) {
  const rule = ruleSet ?? FALLBACK_RULE;
  const roleSummary =
    rule.role_summary ??
    rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");

  return (
    <section className="rounded-md border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-sm font-semibold text-slate-950">{rule.name}</h2>
        <span className="text-xs text-slate-500">v{rule.version}</span>
        <span className="text-xs text-slate-500">{rule.player_count} 人</span>
      </div>
      <p className="mt-1 text-sm text-slate-700">{roleSummary}</p>
    </section>
  );
}
```

- [ ] **Step 2: Update replay adapter to keep rule metadata**

Modify `normalizeGameReplay()` in `apps/web/src/features/games/api/adapters.ts`:

```ts
    ruleSet: response.state.rule_set ?? null,
```

Add `ruleSet?: RuleSetSummary | null;` to `GameReplay` in `types.ts`.

- [ ] **Step 3: Add tests for rendering rule summaries**

In `apps/web/src/pages/LiveGamePage.test.tsx`, add `rule_set_id` and `rule_set` to run responses:

```ts
            rule_set_id: "starter_6",
            rule_set: {
              id: "starter_6",
              version: "2026.04",
              name: "新手 6 人快局",
              player_count: 6,
              roles: [
                { role: "狼人", count: 1 },
                { role: "预言家", count: 1 },
                { role: "医生", count: 1 },
                { role: "村民", count: 3 },
              ],
              role_summary: "1 狼人 / 1 预言家 / 1 医生 / 3 村民",
            },
```

In the first live page test, assert:

```ts
    expect(await screen.findByText("新手 6 人快局")).toBeInTheDocument();
    expect(screen.getByText("1 狼人 / 1 预言家 / 1 医生 / 3 村民")).toBeInTheDocument();
```

In `apps/web/src/pages/GameDetailPage.test.tsx`, add `rule_set` to `detailResponse.state`:

```ts
    rule_set: {
      id: "social_8",
      version: "2026.04",
      name: "无神职心理局",
      player_count: 8,
      roles: [
        { role: "狼人", count: 2 },
        { role: "村民", count: 6 },
      ],
      role_summary: "2 狼人 / 6 村民",
    },
```

In replay detail test, assert:

```ts
    expect(await screen.findByText("无神职心理局")).toBeInTheDocument();
    expect(screen.getByText("2 狼人 / 6 村民")).toBeInTheDocument();
```

- [ ] **Step 4: Run tests to verify they fail before page updates**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx src/pages/GameDetailPage.test.tsx
```

Expected: FAIL because the pages do not render the new summary component.

- [ ] **Step 5: Render summaries on live page**

Modify imports in `apps/web/src/pages/LiveGamePage.tsx`:

```ts
import { RuleSetSummary } from "../features/games/components/RuleSetSummary";
```

Render below the status strip:

```tsx
      <div className="mt-4">
        <RuleSetSummary ruleSet={run.rule_set} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)_22rem]">
```

- [ ] **Step 6: Render summaries on replay page**

Modify imports in `apps/web/src/pages/GameDetailPage.tsx`:

```ts
import { RuleSetSummary } from "../features/games/components/RuleSetSummary";
```

Wrap `GameLayout` with a main layout:

```tsx
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <div className="mb-4">
        <RuleSetSummary ruleSet={data.ruleSet} />
      </div>
      <GameLayout
        debug={<DebugPanel item={visibleSelectedItem} />}
        players={<PlayerPanel game={data} />}
        timeline={
          <RoundTimeline
            debugItems={data.debugItems}
            onSelect={(item) =>
              setSelection({ itemId: item.id, sessionId: data.sessionId })
            }
            rounds={data.rounds}
            selectedItem={visibleSelectedItem}
          />
        }
      />
    </main>
  );
```

- [ ] **Step 7: Run rule summary page tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx src/pages/GameDetailPage.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Commit frontend summaries**

Run:

```bash
git add apps/web/src/features/games/components/RuleSetSummary.tsx apps/web/src/features/games/api/adapters.ts apps/web/src/features/games/types.ts apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/GameDetailPage.tsx apps/web/src/pages/LiveGamePage.test.tsx apps/web/src/pages/GameDetailPage.test.tsx
git commit -m "feat: show rule presets in live and replay"
```

---

### Task 7: Full Verification

**Files:**
- Verify: all files changed in previous tasks.

- [ ] **Step 1: Run all backend tests**

Run:

```bash
cd apps/api && uv run pytest -v
```

Expected: PASS.

- [ ] **Step 2: Run all frontend tests**

Run:

```bash
pnpm --dir apps/web test -- --run
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS with Vite build output and no TypeScript errors.

- [ ] **Step 4: Review final diff**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: `git status --short` shows no uncommitted changes from this implementation. Existing unrelated user changes may remain if they were present before execution; do not revert them.
