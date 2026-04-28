# 12 人预女猎白规则 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个可创建、可直播、可复盘的 12 人预女猎白官方规则局，并保持现有 6/8 人规则局兼容。

**Architecture:** 后端继续以 `RuleSet` 作为规则注册入口，但扩展角色分类、屠边胜利条件、特殊角色能力状态和死亡事件列表。引擎把“夜晚行动”和“死亡触发能力”拆成可测试的小函数，避免把女巫、猎人、白痴逻辑硬塞进单个 `eliminated` 字段。前端只消费后端日志中的结构化字段，旧日志缺字段时使用兼容默认值。

**Tech Stack:** Python dataclasses + FastAPI + pytest；React + TypeScript + TanStack Query + Vitest。

---

## 已确认局规

- 配置：4 狼人 / 1 预言家 / 1 女巫 / 1 猎人 / 1 白痴 / 4 村民。
- 胜利条件：屠边。狼人全灭则好人胜；神职全灭或平民全灭则狼人胜。
- 女巫：首夜可自救；解药、毒药各一次；同一夜只能救或毒二选一。
- 猎人：被狼人击杀或白天放逐可开枪；被女巫毒死不能开枪。
- 白痴：首次被白天投票放逐时翻牌免死，之后不能投票，但仍存活、可发言、可被夜晚击杀；若已翻牌后再次被放逐，则正常出局。

## 文件结构

- 修改 `apps/api/app/werewolf/config.py`：新增 `WITCH`、`HUNTER`、`IDIOT` 角色常量。
- 修改 `apps/api/app/werewolf/rules.py`：新增 12 人规则、角色分类、女巫/猎人行动常量、屠边胜利条件和规则文本。
- 修改 `apps/api/app/werewolf/models.py`：新增死亡事件模型、玩家能力状态、回合中的女巫/猎人/白痴字段；保留旧字段兼容旧前端与旧复盘。
- 修改 `apps/api/app/werewolf/prompts_zh.py`：新增 `witch_save`、`witch_poison`、`hunter_shoot` JSON schema 和中文指令。
- 修改 `apps/api/app/werewolf/engine.py`：实现 4 狼队友视角、女巫救毒、猎人开枪、白痴翻牌、屠边胜利条件、投票权过滤和多死亡结算。
- 修改 `apps/api/tests/test_werewolf_rules.py`：覆盖新规则注册、快照、规则文本和屠边配置。
- 修改 `apps/api/tests/test_werewolf_runner.py`：覆盖核心玩法结算。
- 修改 `apps/api/tests/test_werewolf_lm.py`：覆盖新 prompt schema。
- 修改 `apps/api/tests/test_games_api.py`：覆盖规则列表 API 返回新规则。
- 修改 `apps/web/src/features/games/types.ts`：扩展原始回合、规范化回合、行动日志类型。
- 修改 `apps/web/src/features/games/api/adapters.ts`：兼容新死亡事件和新行动标题。
- 修改 `apps/web/src/features/games/components/CreateGameRunForm.tsx`：无需新增接口，确认规则卡片能展示 12 人局。
- 修改 `apps/web/src/features/games/components/NightPhase.tsx`：展示解药、毒药和夜晚死亡列表。
- 修改 `apps/web/src/features/games/components/DayPhase.tsx`：展示白痴翻牌和猎人开枪结果。
- 修改 `apps/web/src/features/games/components/PlayerPanel.tsx` 与 `apps/web/src/features/games/components/LivePlayerPanel.tsx`：补女巫、猎人、白痴样式。
- 修改 `apps/web/src/features/games/api/adapters.test.ts`，创建 `apps/web/src/features/games/components/NightPhase.test.tsx` 和 `apps/web/src/features/games/components/DayPhase.test.tsx`。

## 数据模型约定

后端新增死亡事件，旧字段继续保留：

```python
@dataclass
class DeathEvent:
    player: str
    cause: str
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"player": self.player, "cause": self.cause, "source": self.source}
```

`RoundState` 新增字段：

```python
night_deaths: list[DeathEvent] = field(default_factory=list)
day_deaths: list[DeathEvent] = field(default_factory=list)
saved_by_witch: str | None = None
poisoned: str | None = None
hunter_shot: str | None = None
idiot_revealed: str | None = None
```

兼容策略：

- `round.eliminated` 继续表示第一个夜晚出局玩家；如果夜晚无人出局则为 `None`。
- `round.exiled` 继续表示白天实际出局玩家；白痴翻牌免死时 `exiled=None`，`idiot_revealed=<玩家名>`。
- 新 UI 优先读 `night_deaths` / `day_deaths`；旧日志没有这些字段时回退到 `eliminated` / `exiled`。

玩家新增能力状态：

```python
can_vote: bool = True
revealed_role: bool = False
witch_antidote_available: bool = False
witch_poison_available: bool = False
hunter_can_shoot: bool = False
```

初始化规则：

- 女巫：`witch_antidote_available=True`，`witch_poison_available=True`。
- 猎人：`hunter_can_shoot=True`。
- 白痴：初始 `can_vote=True`，`revealed_role=False`。
- 其他角色：默认能力状态为 `False`，`can_vote=True`。

## Task 1: 扩展规则注册表

**Files:**
- Modify: `apps/api/app/werewolf/config.py`
- Modify: `apps/api/app/werewolf/rules.py`
- Test: `apps/api/tests/test_werewolf_rules.py`
- Test: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_werewolf_rules.py` 增加：

```python
def test_official_rule_registry_contains_12_player_seer_witch_hunter_idiot() -> None:
    rule = get_rule_set("classic_12_seer_witch_hunter_idiot")

    assert rule.name == "12 人预女猎白局"
    assert rule.player_count == 12
    assert rule.win_condition == "slaughter_side"
    assert [role.role for role in rule.roles] == ["狼人", "预言家", "女巫", "猎人", "白痴", "村民"]
    assert [role.count for role in rule.roles] == [4, 1, 1, 1, 1, 4]
```

在同文件增加：

```python
def test_12_player_rule_text_describes_confirmed_table_rules() -> None:
    text = render_rule_text(get_rule_set("classic_12_seer_witch_hunter_idiot"))

    assert "共 12 名玩家：4 名狼人、1 名预言家、1 名女巫、1 名猎人、1 名白痴、4 名村民。" in text
    assert "女巫拥有一瓶解药和一瓶毒药" in text
    assert "猎人死亡时可以开枪" in text
    assert "白痴首次被放逐时翻牌免死" in text
    assert "神职全灭或平民全灭时狼人获胜" in text
```

在 `apps/api/tests/test_games_api.py` 的规则列表测试中补断言：

```python
assert any(rule["id"] == "classic_12_seer_witch_hunter_idiot" for rule in payload["rule_sets"])
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_rules.py tests/test_games_api.py -q
```

Expected: FAIL，原因是新规则 ID、角色常量、胜利条件尚不存在。

- [ ] **Step 3: 实现规则常量和注册表**

在 `config.py` 增加：

```python
WITCH = "女巫"
HUNTER = "猎人"
IDIOT = "白痴"
```

在 `rules.py` 增加常量：

```python
ACTION_WITCH_SAVE = "witch_save"
ACTION_WITCH_POISON = "witch_poison"
ACTION_HUNTER_SHOOT = "hunter_shoot"

WIN_CONDITION_SLAUGHTER_SIDE = "slaughter_side"

ROLE_CATEGORY_WEREWOLF = "werewolf"
ROLE_CATEGORY_GOD = "god"
ROLE_CATEGORY_CIVILIAN = "civilian"
```

把 `RoleSpec` 扩展为：

```python
@dataclass(frozen=True)
class RoleSpec:
    role: str
    count: int
    team: str
    model_group: str
    category: str = ROLE_CATEGORY_CIVILIAN
```

现有规则中：

- 狼人设置 `ROLE_CATEGORY_WEREWOLF`。
- 预言家和医生设置 `ROLE_CATEGORY_GOD`。
- 村民设置 `ROLE_CATEGORY_CIVILIAN`。

新增规则：

```python
CLASSIC_12_SEER_WITCH_HUNTER_IDIOT = RuleSet(
    id="classic_12_seer_witch_hunter_idiot",
    version=RULE_SET_VERSION,
    name="12 人预女猎白局",
    description="4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。",
    player_count=12,
    roles=(
        RoleSpec("狼人", 4, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF, ROLE_CATEGORY_WEREWOLF),
        RoleSpec("预言家", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("女巫", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("猎人", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("白痴", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("村民", 4, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_CIVILIAN),
    ),
    night_actions=(ACTION_REMOVE, ACTION_INVESTIGATE, ACTION_WITCH_SAVE, ACTION_WITCH_POISON),
    day_actions=(ACTION_BID, ACTION_DEBATE, ACTION_VOTE, ACTION_HUNTER_SHOOT, ACTION_SUMMARIZE),
    win_condition=WIN_CONDITION_SLAUGHTER_SIDE,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="进阶",
    estimated_duration="长",
)
```

把它加入 `OFFICIAL_RULE_SETS` 的末尾，保留现有默认 `classic_8` 不变。

`rule_set_snapshot()` 的 role 项增加 `category`，前端类型用可选字段兼容旧数据。

`render_rule_text()` 对 `WIN_CONDITION_SLAUGHTER_SIDE` 输出屠边说明，并把新行动翻译为女巫、猎人、白痴规则。

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_rules.py tests/test_games_api.py -q
```

Expected: PASS。

## Task 2: 扩展状态模型和 4 狼队友视角

**Files:**
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_werewolf_runner.py` 增加：

```python
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
```

再增加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_12_player_initialization_sets_role_counts_and_wolf_teammates tests/test_werewolf_runner.py::test_special_role_initialization_sets_ability_state -q
```

Expected: FAIL，原因是 `wolf_teammates` 和特殊能力字段尚不存在。

- [ ] **Step 3: 实现模型字段**

在 `GameView` 增加：

```python
wolf_teammates: list[str] = field(default_factory=list)
```

`to_dict()` 继续输出旧字段 `other_wolf`，并新增：

```python
"wolf_teammates": self.wolf_teammates,
```

在 `Player` 增加：

```python
can_vote: bool = True
revealed_role: bool = False
witch_antidote_available: bool = False
witch_poison_available: bool = False
hunter_can_shoot: bool = False
```

`Player.to_dict()` 增加同名字段。

新增 `DeathEvent` dataclass，并在 `RoundState` 增加计划前文列出的字段。`RoundState.to_dict()` 输出：

```python
"night_deaths": [death.to_dict() for death in self.night_deaths],
"day_deaths": [death.to_dict() for death in self.day_deaths],
"saved_by_witch": self.saved_by_witch,
"poisoned": self.poisoned,
"hunter_shot": self.hunter_shot,
"idiot_revealed": self.idiot_revealed,
```

- [ ] **Step 4: 初始化能力状态和狼队友列表**

在 `initialize_game_state()` 创建玩家后，根据角色设置：

```python
if player.role == WITCH:
    player.witch_antidote_available = True
    player.witch_poison_available = True
elif player.role == HUNTER:
    player.hunter_can_shoot = True
```

狼队友视角改为：

```python
wolf_teammates = [wolf.name for wolf in werewolves if wolf.name != player.name]
other_wolf = wolf_teammates[0] if wolf_teammates else None
```

创建 `GameView` 时同时传入 `other_wolf=other_wolf` 和 `wolf_teammates=wolf_teammates`。

- [ ] **Step 5: 运行测试确认通过**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_12_player_initialization_sets_role_counts_and_wolf_teammates tests/test_werewolf_runner.py::test_special_role_initialization_sets_ability_state -q
```

Expected: PASS。

## Task 3: 扩展 Prompt schema

**Files:**
- Modify: `apps/api/app/werewolf/prompts_zh.py`
- Test: `apps/api/tests/test_werewolf_lm.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_werewolf_lm.py` 增加：

```python
def test_build_prompt_supports_witch_save_action() -> None:
    prompt, schema = build_prompt(
        "witch_save",
        {
            "name": "Alice",
            "role": "女巫",
            "round": 1,
            "observations": [],
            "remaining_players": "Alice、Bob",
            "debate": [],
            "bidding_rationale": "",
            "personality": "",
            "rule_text": "你正在进行一局数字版狼人杀。",
            "werewolf_context": "",
            "debate_turns_left": 0,
            "options": "Alice、不使用解药",
        },
    )

    assert schema["required"] == ["reasoning", "save"]
    assert "女巫夜晚解药" in prompt
    assert "输出字段 reasoning 和 save" in prompt
```

同文件增加 `witch_poison` 和 `hunter_shoot` 测试：

```python
def test_build_prompt_supports_witch_poison_action() -> None:
    prompt, schema = build_prompt(
        "witch_poison",
        {
            "name": "Alice",
            "role": "女巫",
            "round": 1,
            "observations": [],
            "remaining_players": "Alice、Bob、Carol",
            "debate": [],
            "bidding_rationale": "",
            "personality": "",
            "rule_text": "你正在进行一局数字版狼人杀。",
            "werewolf_context": "",
            "debate_turns_left": 0,
            "options": "Bob、Carol、不使用毒药",
        },
    )

    assert schema["required"] == ["reasoning", "poison"]
    assert "女巫夜晚毒药" in prompt
    assert "输出字段 reasoning 和 poison" in prompt


def test_build_prompt_supports_hunter_shoot_action() -> None:
    prompt, schema = build_prompt(
        "hunter_shoot",
        {
            "name": "Alice",
            "role": "猎人",
            "round": 1,
            "observations": [],
            "remaining_players": "Bob、Carol",
            "debate": [],
            "bidding_rationale": "",
            "personality": "",
            "rule_text": "你正在进行一局数字版狼人杀。",
            "werewolf_context": "",
            "debate_turns_left": 0,
            "options": "Bob、Carol、不发动技能",
        },
    )

    assert schema["required"] == ["reasoning", "shoot"]
    assert "猎人死亡开枪" in prompt
    assert "输出字段 reasoning 和 shoot" in prompt
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_lm.py -q
```

Expected: FAIL，原因是 prompt 不支持新 action。

- [ ] **Step 3: 实现 schema 和指令**

在 `SCHEMAS` 增加：

```python
"witch_save": {
    "type": "object",
    "properties": {"reasoning": {"type": "string"}, "save": {"type": "string"}},
    "required": ["reasoning", "save"],
},
"witch_poison": {
    "type": "object",
    "properties": {"reasoning": {"type": "string"}, "poison": {"type": "string"}},
    "required": ["reasoning", "poison"],
},
"hunter_shoot": {
    "type": "object",
    "properties": {"reasoning": {"type": "string"}, "shoot": {"type": "string"}},
    "required": ["reasoning", "shoot"],
},
```

同步扩展 `RESULT_FIELD_BY_ACTION` 和 `FIELD_LABELS`。

在 `_render_instruction()` 增加：

```python
if action == "witch_save":
    return (
        "行动：女巫夜晚解药。\n"
        f"候选人：{options}。\n"
        "你知道今晚被狼人袭击的玩家，可以选择使用解药救人，或选择不使用解药。"
        "本规则允许首夜自救，但同一夜使用解药后不能再使用毒药。输出字段 reasoning 和 save。"
    )
if action == "witch_poison":
    return (
        "行动：女巫夜晚毒药。\n"
        f"候选人：{options}。\n"
        "你可以选择一名玩家使用毒药，或选择不使用毒药。"
        "被毒死的猎人不能开枪。输出字段 reasoning 和 poison。"
    )
if action == "hunter_shoot":
    return (
        "行动：猎人死亡开枪。\n"
        f"候选人：{options}。\n"
        "你可以选择一名存活玩家带走，或选择不发动技能。"
        "结合发言、投票和阵营目标做判断。输出字段 reasoning 和 shoot。"
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_lm.py -q
```

Expected: PASS。

## Task 4: 实现屠边胜利条件

**Files:**
- Modify: `apps/api/app/werewolf/rules.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_werewolf_runner.py` 增加：

```python
def test_slaughter_side_wolves_win_when_all_gods_are_dead() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="session_test_slaughter_gods",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=44,
        rule_set=rule_set,
    )
    engine = GameEngine(state=state, provider=NoInvestigateProvider(), max_rounds=8, rule_set=rule_set)
    active_players = [player.name for player in state.players if player.role in {"狼人", "村民"}]

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
    engine = GameEngine(state=state, provider=NoInvestigateProvider(), max_rounds=8, rule_set=rule_set)
    active_players = [player.name for player in state.players if player.role != "村民"]

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
    engine = GameEngine(state=state, provider=NoInvestigateProvider(), max_rounds=8, rule_set=rule_set)
    active_players = [player.name for player in state.players if player.role != "狼人"]

    assert engine._get_winner(active_players) == "好人阵营"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_slaughter_side_wolves_win_when_all_gods_are_dead tests/test_werewolf_runner.py::test_slaughter_side_wolves_win_when_all_civilians_are_dead tests/test_werewolf_runner.py::test_slaughter_side_villagers_win_when_all_wolves_are_dead -q
```

Expected: 至少前两个 FAIL，因为当前胜利条件只按狼人与其他存活人数比较。

- [ ] **Step 3: 实现角色分类 helper 和屠边判断**

在 `rules.py` 增加：

```python
def role_category(rule_set: RuleSet, role: str) -> str:
    return next(role_spec.category for role_spec in rule_set.roles if role_spec.role == role)
```

在 `engine.py` 的 `_get_winner()` 中：

```python
if self.rule_set.win_condition == WIN_CONDITION_SLAUGHTER_SIDE:
    active_gods = [
        name
        for name in active_players
        if role_category(self.rule_set, players_by_name[name].role) == ROLE_CATEGORY_GOD
    ]
    active_civilians = [
        name
        for name in active_players
        if role_category(self.rule_set, players_by_name[name].role) == ROLE_CATEGORY_CIVILIAN
    ]
    if not active_wolves:
        return WINNER_VILLAGERS
    if not active_gods or not active_civilians:
        return WINNER_WEREWOLVES
    return ""
```

保留现有 `wolves_gte_others` 逻辑给 6/8 人旧规则使用。

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_slaughter_side_wolves_win_when_all_gods_are_dead tests/test_werewolf_runner.py::test_slaughter_side_wolves_win_when_all_civilians_are_dead tests/test_werewolf_runner.py::test_slaughter_side_villagers_win_when_all_wolves_are_dead -q
```

Expected: PASS。

## Task 5: 实现女巫夜晚救毒和多死亡结算

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/models.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: 写测试用 provider**

在 `apps/api/tests/test_werewolf_runner.py` 增加：

```python
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
            return json.dumps({"reasoning": "选择夜晚袭击目标。", "remove": self.remove_target}, ensure_ascii=False)
        if '"investigate"' in prompt:
            self.actions.append("investigate")
            choice = _extract_options(prompt)[0]
            return json.dumps({"reasoning": "查验可疑玩家。", "investigate": choice}, ensure_ascii=False)
        if '"save"' in prompt:
            self.actions.append("witch_save")
            return json.dumps({"reasoning": "根据局势决定是否救人。", "save": self.save_choice}, ensure_ascii=False)
        if '"poison"' in prompt:
            self.actions.append("witch_poison")
            return json.dumps({"reasoning": "根据局势决定是否毒人。", "poison": self.poison_choice}, ensure_ascii=False)
        if '"shoot"' in prompt:
            self.actions.append("hunter_shoot")
            return json.dumps({"reasoning": "不发动技能。", "shoot": "不发动技能"}, ensure_ascii=False)
        return json.dumps({"reasoning": "默认选择。", "bid": "0"}, ensure_ascii=False)
```

这里复用测试文件已有的 `_extract_options(prompt)` helper。

- [ ] **Step 2: 写失败测试**

首夜自救测试：

```python
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
```

女巫毒人测试：

```python
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
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_witch_can_save_self_on_first_night_and_cannot_poison_same_night tests/test_werewolf_runner.py::test_witch_poison_creates_night_death -q
```

Expected: FAIL，原因是女巫行动和死亡事件尚未实现。

- [ ] **Step 4: 实现女巫行动**

在 `engine.py` 增加常量：

```python
NO_WITCH_SAVE = "不使用解药"
NO_WITCH_POISON = "不使用毒药"
NO_HUNTER_SHOT = "不发动技能"
```

复用 `engine.py` 现有的 `_active_player_for_role(self, role: str, active_players: list[str]) -> str`，女巫、猎人、白痴都通过同一套角色查找逻辑定位当前存活玩家。

新增 `_run_witch_phase()`：

```python
def _run_witch_phase(self, round_state: RoundState, round_log: RoundLog, active_players: list[str]) -> None:
    players_by_name = self.state.player_by_name()
    witch_name = self._active_player_for_role(WITCH, active_players)
    if not witch_name:
        return
    witch = players_by_name[witch_name]

    used_antidote = False
    if round_state.attacked and witch.witch_antidote_available:
        save_choice, round_log.witch_save = self._player_action(
            player=witch,
            action=ACTION_WITCH_SAVE,
            options=[round_state.attacked, NO_WITCH_SAVE],
            result_key="save",
            round_state=round_state,
            phase="night",
        )
        if save_choice == round_state.attacked:
            round_state.saved_by_witch = round_state.attacked
            witch.witch_antidote_available = False
            used_antidote = True

    if used_antidote or not witch.witch_poison_available:
        return

    poison_options = [
        name
        for name in active_players
        if name != witch.name and name != round_state.attacked
    ] + [NO_WITCH_POISON]
    if poison_options == [NO_WITCH_POISON]:
        return
    poison_choice, round_log.witch_poison = self._player_action(
        player=witch,
        action=ACTION_WITCH_POISON,
        options=poison_options,
        result_key="poison",
        round_state=round_state,
        phase="night",
    )
    if poison_choice and poison_choice != NO_WITCH_POISON:
        round_state.poisoned = str(poison_choice)
        witch.witch_poison_available = False
```

`RoundLog` 增加 `witch_save`、`witch_poison` 字段和 `to_dict()` 输出。

在 `_run_night_phase()` 中，顺序改为：

1. 狼人袭击。
2. 医生保护；仅当规则包含 `ACTION_PROTECT` 时运行，用于保持现有 6/8 人局兼容。
3. 预言家查验。
4. 女巫救毒；仅当规则包含 `ACTION_WITCH_SAVE` 或 `ACTION_WITCH_POISON` 时运行。
5. 统一调用 `_resolve_night_deaths()`。

新增 `_resolve_night_deaths()`，按规则把狼刀和毒药写入 `night_deaths`，并移除玩家：

```python
if (
    round_state.attacked
    and round_state.attacked != round_state.protected
    and round_state.attacked != round_state.saved_by_witch
):
    deaths.append(DeathEvent(round_state.attacked, "werewolf_attack", "狼人"))
if round_state.poisoned:
    deaths.append(DeathEvent(round_state.poisoned, "witch_poison", witch_name))
```

同名玩家只移除一次；`round_state.eliminated` 设为 `night_deaths[0].player` 或 `None`。

- [ ] **Step 5: 运行测试确认通过**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_witch_can_save_self_on_first_night_and_cannot_poison_same_night tests/test_werewolf_runner.py::test_witch_poison_creates_night_death -q
```

Expected: PASS。

## Task 6: 实现猎人死亡开枪

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/models.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_werewolf_runner.py` 增加：

```python
class HunterShotProvider(WitchChoiceProvider):
    def __init__(self, *, remove_target: str, save_choice: str, poison_choice: str, shoot_choice: str) -> None:
        super().__init__(remove_target=remove_target, save_choice=save_choice, poison_choice=poison_choice)
        self.shoot_choice = shoot_choice

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"shoot"' in prompt:
            self.actions.append("hunter_shoot")
            return json.dumps({"reasoning": "猎人带走最可疑玩家。", "shoot": self.shoot_choice}, ensure_ascii=False)
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)
```

测试狼人击杀猎人后可开枪：

```python
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
    assert [death.cause for death in round_state.night_deaths] == ["werewolf_attack", "hunter_shot"]
    assert hunter.name not in active_players
    assert wolf.name not in active_players
```

测试女巫毒死猎人不能开枪：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_hunter_shoots_after_werewolf_attack_death tests/test_werewolf_runner.py::test_hunter_cannot_shoot_after_witch_poison_death -q
```

Expected: FAIL，原因是猎人开枪流程尚不存在。

- [ ] **Step 3: 实现死亡触发能力**

新增 helper：

```python
def _maybe_run_hunter_shot(
    self,
    *,
    dead_player: str,
    death_cause: str,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
    phase: str,
) -> None:
    players_by_name = self.state.player_by_name()
    hunter = players_by_name[dead_player]
    if hunter.role != HUNTER or not hunter.hunter_can_shoot:
        return
    if death_cause == "witch_poison":
        return
    options = [name for name in active_players if name != hunter.name] + [NO_HUNTER_SHOT]
    if options == [NO_HUNTER_SHOT]:
        return
    shot, action_log = self._player_action(
        player=hunter,
        action=ACTION_HUNTER_SHOOT,
        options=options,
        result_key="shoot",
        round_state=round_state,
        phase=phase,
    )
    round_log.hunter_shoot = action_log
    hunter.hunter_can_shoot = False
    if shot and shot != NO_HUNTER_SHOT:
        round_state.hunter_shot = str(shot)
        self._remove_player(active_players, str(shot))
        death = DeathEvent(str(shot), "hunter_shot", hunter.name)
        if phase == "night":
            round_state.night_deaths.append(death)
        else:
            round_state.day_deaths.append(death)
```

在夜晚死亡结算中，先移除死亡者，再对每个死亡者调用 `_maybe_run_hunter_shot()`；毒死猎人时传入 `death_cause="witch_poison"`。

`RoundLog` 增加 `hunter_shoot` 字段和 `to_dict()` 输出。

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_hunter_shoots_after_werewolf_attack_death tests/test_werewolf_runner.py::test_hunter_cannot_shoot_after_witch_poison_death -q
```

Expected: PASS。

## Task 7: 实现白痴翻牌和投票权过滤

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/models.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: 写失败测试**

新增白痴首次被放逐免死测试：

```python
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
    engine = GameEngine(state=state, provider=NoInvestigateProvider(), max_rounds=8, rule_set=rule_set)

    engine._resolve_day_exile(idiot.name, round_state, round_log, active_players)

    assert round_state.idiot_revealed == idiot.name
    assert round_state.exiled is None
    assert round_state.day_deaths == []
    assert idiot.name in active_players
    assert idiot.can_vote is False
    assert idiot.revealed_role is True
```

新增已翻牌白痴再次被放逐正常出局：

```python
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
    engine = GameEngine(state=state, provider=NoInvestigateProvider(), max_rounds=8, rule_set=rule_set)

    engine._resolve_day_exile(idiot.name, round_state, round_log, active_players)

    assert round_state.exiled == idiot.name
    assert [death.to_dict() for death in round_state.day_deaths] == [
        {"player": idiot.name, "cause": "vote_exile", "source": "投票"}
    ]
    assert idiot.name not in active_players
```

新增不能投票测试：

```python
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
    engine = GameEngine(state=state, provider=ScriptedChineseProvider(), max_rounds=8, rule_set=rule_set)

    votes, _logs = engine._run_voting(round_state, active_players)

    assert idiot.name not in votes
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_idiot_reveals_and_survives_first_exile tests/test_werewolf_runner.py::test_revealed_idiot_is_exiled_if_voted_out_again tests/test_werewolf_runner.py::test_revealed_idiot_does_not_vote -q
```

Expected: FAIL，原因是 `_resolve_day_exile()` 和投票权过滤尚不存在。

- [ ] **Step 3: 实现放逐结算 helper**

把 `_run_day_phase()` 中直接移除 `exiled` 的逻辑替换成：

```python
if exiled:
    self._resolve_day_exile(exiled, round_state, round_log, active_players)
else:
    self._announce(active_players, f"第{round_state.number}轮：白天投票未形成多数，无人被放逐。")
```

新增 helper：

```python
def _resolve_day_exile(
    self,
    exiled: str,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
) -> None:
    player = self.state.player_by_name()[exiled]
    if player.role == IDIOT and not player.revealed_role:
        player.revealed_role = True
        player.can_vote = False
        round_state.idiot_revealed = exiled
        self._announce(active_players, f"第{round_state.number}轮：白天投票，{exiled}翻开白痴身份，免于出局但失去投票权。")
        return

    round_state.exiled = exiled
    self._remove_player(active_players, exiled)
    round_state.day_deaths.append(DeathEvent(exiled, "vote_exile", "投票"))
    self._announce(active_players, f"第{round_state.number}轮：白天投票，{exiled}被放逐。")
    self._maybe_run_hunter_shot(
        dead_player=exiled,
        death_cause="vote_exile",
        round_state=round_state,
        round_log=round_log,
        active_players=active_players,
        phase="vote",
    )
```

- [ ] **Step 4: 实现投票权过滤**

新增：

```python
def _eligible_voters(self, active_players: list[str]) -> list[str]:
    players_by_name = self.state.player_by_name()
    return [name for name in active_players if players_by_name[name].can_vote]
```

`_run_voting()` 遍历 `_eligible_voters(active_players)`，投票候选人仍为所有其他存活玩家：

```python
for voter in self._eligible_voters(active_players):
    options=[name for name in active_players if name != voter]
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_idiot_reveals_and_survives_first_exile tests/test_werewolf_runner.py::test_revealed_idiot_is_exiled_if_voted_out_again tests/test_werewolf_runner.py::test_revealed_idiot_does_not_vote -q
```

Expected: PASS。

## Task 8: 跑通 12 人局日志和 API

**Files:**
- Modify: `apps/api/app/werewolf/runner.py`
- Modify: `apps/api/app/api/routes/games.py`
- Test: `apps/api/tests/test_werewolf_runner.py`
- Test: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: 写集成测试**

在 `apps/api/tests/test_werewolf_runner.py` 增加：

```python
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
```

- [ ] **Step 2: 运行集成测试确认失败或暴露 provider 缺口**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_run_game_uses_12_player_seer_witch_hunter_idiot_rule_set -q
```

Expected: 若 `ScriptedChineseProvider` 尚不支持新 action，则 FAIL 在模型响应字段；若前面任务已补，则 PASS。

- [ ] **Step 3: 补测试 provider 新 action**

在 `ScriptedChineseProvider.complete_json()` 中增加：

```python
if '"save"' in prompt:
    return json.dumps({"reasoning": "测试中默认不使用解药。", "save": "不使用解药"}, ensure_ascii=False)
if '"poison"' in prompt:
    return json.dumps({"reasoning": "测试中默认不使用毒药。", "poison": "不使用毒药"}, ensure_ascii=False)
if '"shoot"' in prompt:
    return json.dumps({"reasoning": "测试中默认不开枪。", "shoot": "不发动技能"}, ensure_ascii=False)
```

- [ ] **Step 4: 运行后端规则和 runner 测试**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_rules.py tests/test_werewolf_lm.py tests/test_werewolf_runner.py tests/test_games_api.py -q
```

Expected: PASS。

## Task 9: 前端类型和适配层

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/api/adapters.ts`
- Test: `apps/web/src/features/games/api/adapters.test.ts`

- [ ] **Step 1: 写失败测试**

在 `adapters.test.ts` 增加一个包含新字段的 replay fixture，断言 normalize 后保留死亡事件和新 debug action：

```typescript
it("normalizes witch hunter idiot round fields", () => {
  const replay = normalizeGameReplay({
    session_id: "session_20260428_120000_abcd1234",
    status: "complete",
    state: {
      session_id: "session_20260428_120000_abcd1234",
      winner: "好人阵营",
      error_message: "",
      rule_set: {
        id: "classic_12_seer_witch_hunter_idiot",
        version: "2026.04",
        name: "12 人预女猎白局",
        player_count: 12,
        roles: [],
      },
      players: [],
      rounds: [
        {
          number: 1,
          players: ["Alice", "Bob"],
          attacked: "Alice",
          eliminated: null,
          protected: null,
          investigated: "Bob",
          exiled: null,
          saved_by_witch: "Alice",
          poisoned: null,
          hunter_shot: null,
          idiot_revealed: "Bob",
          night_deaths: [],
          day_deaths: [],
          debate: [],
          bids: [],
          votes: [],
          summaries: {},
          success: true,
        },
      ],
    },
    logs: [
      {
        number: 1,
        eliminate: null,
        protect: null,
        investigate: null,
        witch_save: {
          actor: "Witch",
          action: "witch_save",
          options: ["Alice", "不使用解药"],
          choice: "Alice",
          lm_log: { prompt: "", raw_response: "", result: { save: "Alice" } },
        },
        witch_poison: null,
        hunter_shoot: null,
        bid: [],
        debate: [],
        votes: [],
        summaries: [],
      },
    ],
  });

  expect(replay.rounds[0].saved_by_witch).toBe("Alice");
  expect(replay.rounds[0].idiot_revealed).toBe("Bob");
  expect(replay.debugItems[0]).toMatchObject({
    title: "女巫解药",
    action: "witch_save",
    choice: "Alice",
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- adapters.test.ts
```

Expected: FAIL，原因是 TS 类型和 action adapter 不认识新字段。

- [ ] **Step 3: 扩展类型**

在 `types.ts` 增加：

```typescript
export type DeathEvent = {
  player: string;
  cause: string;
  source?: string | null;
};
```

`RoleSpecSummary` 增加：

```typescript
category?: string;
```

`RawRoundLog` 增加：

```typescript
witch_save?: RawActionLog | null;
witch_poison?: RawActionLog | null;
hunter_shoot?: RawActionLog | null;
```

`RawRoundState` 增加：

```typescript
night_deaths?: DeathEvent[];
day_deaths?: DeathEvent[];
saved_by_witch?: string | null;
poisoned?: string | null;
hunter_shot?: string | null;
idiot_revealed?: string | null;
```

`GameRound` 保留这些字段并在 normalize 时给默认值。

- [ ] **Step 4: 扩展 adapter**

`ACTION_TITLES` 增加：

```typescript
witch_save: "女巫解药",
witch_poison: "女巫毒药",
hunter_shoot: "猎人开枪",
```

`debugItemsFromRound()` 在夜晚 action 中追加：

```typescript
pushAction(items, round.number, "night", "night-witch-save", round.witch_save ?? null);
pushAction(items, round.number, "night", "night-witch-poison", round.witch_poison ?? null);
pushAction(items, round.number, "night", "night-hunter-shoot", round.hunter_shoot ?? null);
```

`normalizeRound()` 为新字段提供默认值：

```typescript
night_deaths: round.night_deaths ?? (eliminated ? [{ player: eliminated, cause: "legacy_night_elimination", source: null }] : []),
day_deaths: round.day_deaths ?? (round.exiled ? [{ player: round.exiled, cause: "legacy_vote_exile", source: null }] : []),
saved_by_witch: round.saved_by_witch ?? null,
poisoned: round.poisoned ?? null,
hunter_shot: round.hunter_shot ?? null,
idiot_revealed: round.idiot_revealed ?? null,
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```bash
pnpm --dir apps/web test -- adapters.test.ts
```

Expected: PASS。

## Task 10: 前端展示预女猎白结算

**Files:**
- Modify: `apps/web/src/features/games/components/NightPhase.tsx`
- Modify: `apps/web/src/features/games/components/DayPhase.tsx`
- Modify: `apps/web/src/features/games/components/PlayerPanel.tsx`
- Modify: `apps/web/src/features/games/components/LivePlayerPanel.tsx`
- Create: `apps/web/src/features/games/components/NightPhase.test.tsx`
- Create: `apps/web/src/features/games/components/DayPhase.test.tsx`

- [ ] **Step 1: 写夜晚展示失败测试**

创建 `NightPhase.test.tsx`：

```typescript
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NightPhase } from "./NightPhase";
import type { GameRound } from "../types";

const baseRound: GameRound = {
  number: 1,
  players: ["Alice", "Bob"],
  attacked: "Alice",
  eliminated: null,
  protected: null,
  investigated: "Bob",
  exiled: null,
  saved_by_witch: "Alice",
  poisoned: "Bob",
  hunter_shot: null,
  idiot_revealed: null,
  night_deaths: [{ player: "Bob", cause: "witch_poison", source: "Witch" }],
  day_deaths: [],
  debate: [],
  bids: [],
  bidGroups: [],
  votes: [],
  voteTally: [],
  voteCount: 0,
  voteMajorityThreshold: null,
  summaries: {},
  success: true,
};

describe("NightPhase", () => {
  it("renders witch save, poison, and night death fields", () => {
    render(
      <NightPhase
        round={baseRound}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("解药")).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("毒药")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("夜晚死亡")).toBeInTheDocument();
    expect(screen.getByText("Bob 出局")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 写白天展示失败测试**

创建 `DayPhase.test.tsx`：

```typescript
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DayPhase } from "./DayPhase";
import type { GameRound } from "../types";

const baseRound: GameRound = {
  number: 1,
  players: ["Alice", "Bob"],
  attacked: null,
  eliminated: null,
  protected: null,
  investigated: null,
  exiled: null,
  saved_by_witch: null,
  poisoned: null,
  hunter_shot: "Alice",
  idiot_revealed: "Bob",
  night_deaths: [],
  day_deaths: [{ player: "Alice", cause: "hunter_shot", source: "Hunter" }],
  debate: [],
  bids: [],
  bidGroups: [],
  votes: [],
  voteTally: [],
  voteCount: 0,
  voteMajorityThreshold: null,
  summaries: {},
  success: true,
};

describe("DayPhase", () => {
  it("renders idiot reveal and hunter shot fields", () => {
    render(
      <DayPhase
        round={baseRound}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Bob 翻牌免死，失去投票权")).toBeInTheDocument();
    expect(screen.getByText("猎人带走 Alice")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web test -- NightPhase.test.tsx DayPhase.test.tsx
```

Expected: FAIL，原因是组件尚未展示新字段。

- [ ] **Step 4: 夜晚展示字段**

`NightPhase.tsx` 的信息区从固定四列扩展为响应式列表，新增：

- 解药：`round.saved_by_witch ?? "未使用"`
- 毒药：`round.poisoned ?? "未使用"`
- 夜晚死亡：`round.night_deaths.map((death) => death.player).join("、") || "无"`

结果文本改为：

```typescript
const resultText =
  round.night_deaths.length > 0
    ? `${round.night_deaths.map((death) => death.player).join("、")} 出局`
    : round.saved_by_witch
      ? `${round.saved_by_witch} 被女巫救下，平安夜`
      : "平安夜";
```

- [ ] **Step 5: 白天展示字段**

`DayPhase.tsx` 在投票结果附近增加：

- 白痴翻牌：有 `round.idiot_revealed` 时显示 `<名字> 翻牌免死，失去投票权`。
- 猎人开枪：有 `round.hunter_shot` 时显示 `猎人带走 <名字>`。
- 白天死亡：读取 `round.day_deaths`，没有则沿用 `round.exiled`。

- [ ] **Step 6: 角色样式**

在 `PlayerPanel.tsx` 与 `LivePlayerPanel.tsx` 的 `ROLE_STYLES` 增加：

```typescript
女巫: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-800",
猎人: "border-orange-200 bg-orange-50 text-orange-800",
白痴: "border-cyan-200 bg-cyan-50 text-cyan-800",
```

保持现有预言家、狼人、村民样式不变。

- [ ] **Step 7: 运行前端测试**

Run:

```bash
pnpm --dir apps/web test
```

Expected: PASS。

## Task 11: 全量验证

**Files:**
- No production file edits in this task

- [ ] **Step 1: 后端全量测试**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest -q
```

Expected: PASS。

- [ ] **Step 2: 前端全量测试**

Run:

```bash
pnpm --dir apps/web test
```

Expected: PASS。

- [ ] **Step 3: 手动发起一局 12 人预女猎白**

启动后端：

```bash
cd apps/api && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动前端：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 pnpm --dir apps/web dev --host 127.0.0.1 --port 5173
```

浏览器检查：

- 打开 `http://127.0.0.1:5173/games`。
- 创建页显示“12 人预女猎白局”。
- 发起该规则局后，直播页能看到 12 名玩家。
- 女巫、猎人、白痴角色样式正常。
- 复盘页夜晚区域能显示解药、毒药、夜晚死亡。
- 白天区域能显示白痴翻牌或猎人开枪事件。

## 自查清单

- 规则配置覆盖已确认局规。
- 旧 `classic_8`、`starter_6`、`social_8` 默认行为不改。
- `eliminated` 和 `exiled` 保留兼容语义。
- 新增死亡事件列表覆盖多死亡场景。
- 女巫同夜救毒互斥。
- 猎人被毒死不能开枪。
- 白痴翻牌后不能投票。
- 12 人 4 狼队友视角不再只暴露一个队友。
- 前端旧日志缺新字段时不崩溃。
