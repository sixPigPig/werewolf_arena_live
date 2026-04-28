# Rule Options Speech And Sheriff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the existing rule options so small-player games use normal ordered speeches without bidding, while the 12-player seer-witch-hunter-idiot game uses a sheriff election, sheriff-directed speech order, and sheriff vote weight.

**Architecture:** The backend `RuleSet` becomes the source of truth for speech and sheriff policy. The engine reads those policies to choose either seat-order speeches or a sheriff flow, and frontend components render the rule differences as tags and replay fields instead of assuming every game has bid rounds.

**Tech Stack:** Python dataclasses and pytest in `apps/api`; React, TypeScript, TanStack Query, Testing Library, and Vitest in `apps/web`.

---

## Scope

Implement these behavior changes:

- Rename the small-game protection role from `医生` to `守卫` while keeping the existing `protect` action.
- Remove `bid` from all active rule flows.
- Make 6-player and 8-player games use one full ordered speech round.
- Make the 12-player rule set explicitly sheriff-enabled.
- Add first-day sheriff election for the 12-player rule set.
- Let the sheriff choose `警左发言` or `警右发言`; the sheriff speaks last.
- Give the sheriff a 1.5 vote weight in exile voting.
- Let a dead sheriff pass the badge to a living player or tear it up.
- Update API payloads, replay normalization, rule cards, and day-phase UI.

Keep these policies explicit:

- Sheriff election tie: no sheriff is elected.
- Exile vote tie or no weighted majority: no player is exiled.
- If no sheriff exists, a sheriff-enabled game falls back to seat-order speeches.
- Legacy replay payloads with `bids` remain readable.

## File Structure

- Modify `apps/api/app/werewolf/config.py`: rename the displayed protection role to `守卫` while preserving `DOCTOR` as the engine constant.
- Modify `apps/api/app/werewolf/rules.py`: add speech/sheriff metadata, remove active `bid` flows, update rule names/descriptions/tags, and expose metadata in summaries/snapshots.
- Modify `apps/api/app/werewolf/models.py`: serialize sheriff state, speech order, weighted votes, and sheriff action logs.
- Modify `apps/api/app/werewolf/prompts_zh.py`: add prompt schemas and instructions for sheriff election, sheriff vote, speech-order choice, and badge transfer.
- Modify `apps/api/app/werewolf/engine.py`: replace bid-selected debate with rule-driven ordered speeches, add sheriff election/order/vote-weight/badge-transfer helpers.
- Modify `apps/api/tests/test_werewolf_rules.py`: assert new rule metadata, role terminology, and rule text.
- Modify `apps/api/tests/test_werewolf_runner.py`: assert ordered speeches, no bid calls, sheriff election, weighted voting, and badge transfer.
- Modify `apps/web/src/features/games/types.ts`: add sheriff and speech metadata to API/replay types.
- Modify `apps/web/src/features/games/api/adapters.ts`: normalize new replay fields, weighted vote tallies, and sheriff debug items while preserving legacy bid support.
- Modify `apps/web/src/features/games/api/adapters.test.ts`: cover new normalized replay fields and action titles.
- Modify `apps/web/src/features/games/components/CreateGameRunForm.tsx`: group rule cards and show rule tags.
- Modify `apps/web/src/features/games/components/RuleSetSummary.tsx`: show tags in detail/replay summaries.
- Modify `apps/web/src/features/games/components/DayPhase.tsx`: hide bid UI for new rounds, show speech order and weighted vote resolution.
- Modify `apps/web/src/features/games/components/VoteTable.tsx`: display 1.5 sheriff vote weights.
- Modify `apps/web/src/features/games/components/DayPhase.test.tsx`: verify speech order, hidden bid section, and weighted votes.
- Modify `apps/web/src/pages/GamesPage.test.tsx`: verify redesigned rule cards and submitted rule selection.

---

### Task 1: Rule Metadata And Guard Terminology

**Files:**
- Modify: `apps/api/app/werewolf/config.py`
- Modify: `apps/api/app/werewolf/rules.py`
- Test: `apps/api/tests/test_werewolf_rules.py`

- [ ] **Step 1: Write failing rule metadata tests**

Add assertions to `test_rule_set_snapshot_is_json_safe` so `starter_6` expects the guard role and speech policy:

```python
assert snapshot["roles"][2]["role"] == "守卫"
assert snapshot["day_actions"] == ["debate", "vote", "summarize"]
assert snapshot["sheriff_enabled"] is False
assert snapshot["sheriff_vote_weight"] == 1.0
assert snapshot["speech_policy"] == "sequential"
assert snapshot["speech_rounds"] == 1
assert snapshot["rule_tags"] == ["无警长", "顺序发言", "新手"]
```

Add a 12-player policy test:

```python
def test_12_player_rule_set_has_sheriff_flow_metadata() -> None:
    rule = get_rule_set("classic_12_seer_witch_hunter_idiot")

    assert rule.sheriff_enabled is True
    assert rule.sheriff_vote_weight == 1.5
    assert rule.speech_policy == "sheriff_directed"
    assert rule.speech_rounds == 1
    assert rule.day_actions == (
        "sheriff_run",
        "sheriff_vote",
        "speech_order",
        "debate",
        "vote",
        "hunter_shoot",
        "summarize",
    )
    assert rule.rule_tags == ("有警长", "警徽 1.5 票", "屠边", "预女猎白")
```

Update `test_rule_summaries_are_frontend_friendly`:

```python
assert summaries[0]["role_summary"] == "2 狼人 / 1 预言家 / 1 守卫 / 4 村民"
assert summaries[0]["rule_tags"] == ["无警长", "顺序发言", "标准"]
assert summaries[3]["sheriff_enabled"] is True
assert summaries[3]["rule_tags"] == ["有警长", "警徽 1.5 票", "屠边", "预女猎白"]
```

- [ ] **Step 2: Run the focused rule tests and confirm failure**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_rules.py -q
```

Expected: failures mention missing `sheriff_enabled`, `speech_policy`, `rule_tags`, and old `医生` text.

- [ ] **Step 3: Implement rule metadata and guard terminology**

In `apps/api/app/werewolf/config.py`, preserve existing imports while changing display terminology:

```python
GUARD = "守卫"
DOCTOR = GUARD
```

In `apps/api/app/werewolf/rules.py`, add constants:

```python
ACTION_SHERIFF_RUN = "sheriff_run"
ACTION_SHERIFF_VOTE = "sheriff_vote"
ACTION_SPEECH_ORDER = "speech_order"
ACTION_SHERIFF_BADGE = "sheriff_badge"

SPEECH_POLICY_SEQUENTIAL = "sequential"
SPEECH_POLICY_SHERIFF_DIRECTED = "sheriff_directed"
```

Extend `RuleSet` with defaulted metadata fields:

```python
    sheriff_enabled: bool = False
    sheriff_vote_weight: float = 1.0
    speech_policy: str = SPEECH_POLICY_SEQUENTIAL
    speech_rounds: int = 1
    rule_tags: tuple[str, ...] = ()
```

Update the three small-player rule sets:

```python
day_actions=(ACTION_DEBATE, ACTION_VOTE, ACTION_SUMMARIZE),
speech_policy=SPEECH_POLICY_SEQUENTIAL,
speech_rounds=1,
rule_tags=("无警长", "顺序发言", "新手"),
```

Use these exact role summaries by changing the protection role to `守卫`:

```python
RoleSpec("守卫", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD)
```

Update `CLASSIC_12_SEER_WITCH_HUNTER_IDIOT`:

```python
day_actions=(
    ACTION_SHERIFF_RUN,
    ACTION_SHERIFF_VOTE,
    ACTION_SPEECH_ORDER,
    ACTION_DEBATE,
    ACTION_VOTE,
    ACTION_HUNTER_SHOOT,
    ACTION_SUMMARIZE,
),
sheriff_enabled=True,
sheriff_vote_weight=1.5,
speech_policy=SPEECH_POLICY_SHERIFF_DIRECTED,
speech_rounds=1,
rule_tags=("有警长", "警徽 1.5 票", "屠边", "预女猎白"),
```

Include the new metadata in `rule_set_summary()` and `rule_set_snapshot()`:

```python
"sheriff_enabled": rule_set.sheriff_enabled,
"sheriff_vote_weight": rule_set.sheriff_vote_weight,
"speech_policy": rule_set.speech_policy,
"speech_rounds": rule_set.speech_rounds,
"rule_tags": list(rule_set.rule_tags),
```

Update `render_rule_text()` day text:

```python
if rule_set.sheriff_enabled:
    lines.append("白天行动：首日警长竞选、警长指定发言方向、全员发言、投票与总结。")
    lines.append("警长规则：警长拥有 1.5 票，死亡时可移交警徽或撕毁警徽。")
else:
    lines.append("白天行动：按座位顺序全员发言一轮，随后投票与总结。")
```

Update night action text:

```python
ACTION_PROTECT: "守卫保护一名玩家",
```

- [ ] **Step 4: Run the focused rule tests and confirm pass**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_rules.py -q
```

Expected: all tests in `test_werewolf_rules.py` pass.

- [ ] **Step 5: Commit rule metadata**

Run:

```bash
git add apps/api/app/werewolf/config.py apps/api/app/werewolf/rules.py apps/api/tests/test_werewolf_rules.py
git commit -m "feat: add rule speech and sheriff metadata"
```

---

### Task 2: Model And Prompt Support For Sheriff Flow

**Files:**
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/prompts_zh.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing serialization and prompt tests**

Add this test to `apps/api/tests/test_werewolf_runner.py`:

```python
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
```

Add prompt smoke checks:

```python
from app.werewolf.prompts_zh import build_prompt


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
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_sheriff_state_serializes_to_game_and_round_payloads tests/test_werewolf_runner.py::test_sheriff_prompt_actions_render_chinese_instructions -q
```

Expected: failures mention missing dataclass fields and unsupported prompt actions.

- [ ] **Step 3: Add sheriff state fields**

In `Player`, add:

```python
    is_sheriff: bool = False
```

Include it in `Player.to_dict()`:

```python
"is_sheriff": self.is_sheriff,
```

In `RoundState`, add:

```python
    sheriff: str | None = None
    sheriff_candidates: list[str] = field(default_factory=list)
    sheriff_votes: dict[str, str] = field(default_factory=dict)
    speech_order: list[str] = field(default_factory=list)
    speech_order_choice: str | None = None
    vote_weights: dict[str, float] = field(default_factory=dict)
    sheriff_badge_target: str | None = None
    sheriff_badge_lost: bool = False
```

Include each field in `RoundState.to_dict()`.

In `RoundLog`, add:

```python
    sheriff_run: list[ActionLog] = field(default_factory=list)
    sheriff_votes: list[ActionLog] = field(default_factory=list)
    speech_order: ActionLog | None = None
    sheriff_badge: ActionLog | None = None
```

Include each field in `RoundLog.to_dict()`.

In `GameState`, add:

```python
    sheriff: str | None = None
    sheriff_badge_lost: bool = False
```

Include both fields in `GameState.to_dict()`.

- [ ] **Step 4: Add prompt schemas and instructions**

In `SCHEMAS`, add:

```python
"sheriff_run": {
    "type": "object",
    "properties": {"reasoning": {"type": "string"}, "run": {"type": "string"}},
    "required": ["reasoning", "run"],
},
"sheriff_vote": {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "sheriff_vote": {"type": "string"},
    },
    "required": ["reasoning", "sheriff_vote"],
},
"speech_order": {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "speech_order": {"type": "string"},
    },
    "required": ["reasoning", "speech_order"],
},
"sheriff_badge": {
    "type": "object",
    "properties": {"reasoning": {"type": "string"}, "badge": {"type": "string"}},
    "required": ["reasoning", "badge"],
},
```

In `RESULT_FIELD_BY_ACTION`, add:

```python
"sheriff_run": "run",
"sheriff_vote": "sheriff_vote",
"speech_order": "speech_order",
"sheriff_badge": "badge",
```

In `FIELD_LABELS`, add:

```python
"run": "是否上警",
"sheriff_vote": "警长投票对象",
"speech_order": "发言方向",
"badge": "警徽去向",
```

In `_render_instruction()`, add branches:

```python
if action == "sheriff_run":
    return (
        "行动：警长竞选报名。\n"
        "你需要选择是否参与警长竞选。上警表示你愿意公开争取警徽，不上警表示留在警下观察。\n"
        f"候选项：{options}。\n"
        f"请以{role}的目标思考，输出字段 reasoning 和 run。"
    )
if action == "sheriff_vote":
    return (
        "行动：警长投票。\n"
        "你需要从警长候选人中选择一名玩家。警长将拥有 1.5 票并决定白天发言方向。\n"
        f"候选人：{options}。\n"
        "输出字段 reasoning 和 sheriff_vote。"
    )
if action == "speech_order":
    return (
        "行动：警长决定发言方向。\n"
        "你是当前警长，需要决定今天从警左还是警右开始发言，警长最后归票发言。\n"
        f"候选项：{options}。\n"
        "输出字段 reasoning 和 speech_order。"
    )
if action == "sheriff_badge":
    return (
        "行动：移交警徽。\n"
        "你是死亡的警长，需要选择把警徽交给一名仍然存活的玩家，或撕毁警徽。\n"
        f"候选项：{options}。\n"
        "输出字段 reasoning 和 badge。"
    )
```

- [ ] **Step 5: Run focused tests and confirm pass**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_sheriff_state_serializes_to_game_and_round_payloads tests/test_werewolf_runner.py::test_sheriff_prompt_actions_render_chinese_instructions -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit model and prompt support**

Run:

```bash
git add apps/api/app/werewolf/models.py apps/api/app/werewolf/prompts_zh.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: add sheriff state and prompts"
```

---

### Task 3: Ordered Speeches Without Bidding

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Add a provider that fails on bid calls**

Add to `apps/api/tests/test_werewolf_runner.py`:

```python
class NoBidOrderedSpeechProvider(ScriptedChineseProvider):
    def __init__(self) -> None:
        self.debate_actors: list[str] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        if '"bid"' in prompt:
            raise AssertionError("Bid should not be requested in ordered speech flow.")
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)
```

- [ ] **Step 2: Write failing ordered speech test**

Add:

```python
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
```

- [ ] **Step 3: Run the ordered speech test and confirm failure**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_small_rule_day_phase_uses_full_seat_order_without_bids -q
```

Expected: failure from `NoBidOrderedSpeechProvider` because `_run_day_phase()` still requests `bid`.

- [ ] **Step 4: Replace bid-selected debate with ordered debate**

In `apps/api/app/werewolf/engine.py`, import speech constants:

```python
    ACTION_DEBATE,
    ACTION_SPEECH_ORDER,
    SPEECH_POLICY_SHERIFF_DIRECTED,
```

Replace the bid loop in `_run_day_phase()` with:

```python
self._run_sheriff_election_if_needed(round_state, round_log, active_players)
self._run_debate_phase(round_state, round_log, active_players)
```

Add:

```python
def _run_debate_phase(
    self,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
) -> None:
    speech_order = self._speech_order(round_state, round_log, active_players)
    round_state.speech_order = speech_order.copy()

    for speaker in speech_order:
        if speaker not in active_players:
            continue
        player = self.state.player_by_name()[speaker]
        message, action_log = self._player_action(
            player=player,
            action=ACTION_DEBATE,
            options=[],
            result_key="say",
            round_state=round_state,
            phase="day",
        )
        if not isinstance(message, str) or not message:
            raise ValueError(f"{speaker} did not return a valid debate message.")

        entry = DebateEntry(speaker=speaker, message=message)
        round_state.debate.append(entry)
        round_log.debate.append(action_log)
        self._record_public_debate(active_players, entry)
        self._publish_state_updated(
            round_state=round_state,
            phase="day",
            actor=speaker,
            action=ACTION_DEBATE,
            payload={
                "debate_entry": entry.to_dict(),
                "debate": [debate_entry.to_dict() for debate_entry in round_state.debate],
                "speech_order": round_state.speech_order.copy(),
            },
        )
```

Add the default speech order helper:

```python
def _speech_order(
    self,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
) -> list[str]:
    if (
        self.rule_set.speech_policy == SPEECH_POLICY_SHERIFF_DIRECTED
        and self.state.sheriff
        and self.state.sheriff in active_players
    ):
        return self._sheriff_directed_speech_order(round_state, round_log, active_players)
    return active_players.copy()
```

Add a stub used by Task 4:

```python
def _run_sheriff_election_if_needed(
    self,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
) -> None:
    round_state.sheriff = self.state.sheriff
```

Add a sheriff-order fallback used by Task 4:

```python
def _sheriff_directed_speech_order(
    self,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
) -> list[str]:
    del round_state, round_log
    return active_players.copy()
```

Leave `_get_next_speaker()` in place until frontend legacy bid tests are adjusted; no new code should call it.

- [ ] **Step 5: Run the ordered speech test and confirm pass**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_small_rule_day_phase_uses_full_seat_order_without_bids -q
```

Expected: test passes and no bid prompt is requested.

- [ ] **Step 6: Run runner smoke tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_run_game_with_deepseek_models_writes_complete_chinese_logs tests/test_werewolf_runner.py::test_run_game_uses_starter_6_rule_set tests/test_werewolf_runner.py::test_run_game_defaults_to_classic_8_rule_set -q
```

Expected: selected runner tests pass after updating assertions from `医生` to `守卫`.

- [ ] **Step 7: Commit ordered speech flow**

Run:

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: replace bid debate with ordered speeches"
```

---

### Task 4: Sheriff Election, Speech Direction, Weighted Vote, And Badge Transfer

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Add a scripted sheriff provider**

Add:

```python
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
        del model, temperature
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
            return json.dumps(
                {"reasoning": "把警徽交给更可信的人。", "badge": self.badge_choice},
                ensure_ascii=False,
            )
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)
```

Add:

```python
def _extract_actor_name(prompt: str) -> str:
    marker = "- 你是"
    if marker not in prompt:
        return ""
    return prompt.split(marker, 1)[1].split("，", 1)[0]
```

- [ ] **Step 2: Write failing sheriff election and order test**

Add:

```python
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
```

- [ ] **Step 3: Write failing weighted vote helper test**

Add:

```python
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
```

- [ ] **Step 4: Write failing badge transfer test**

Add:

```python
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
```

- [ ] **Step 5: Run sheriff tests and confirm failure**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_12_player_first_day_elects_sheriff_and_uses_sheriff_speech_order tests/test_werewolf_runner.py::test_sheriff_vote_counts_as_one_and_half_votes tests/test_werewolf_runner.py::test_dead_sheriff_can_transfer_badge -q
```

Expected: failures mention stubbed sheriff order, missing weighted vote signature, and missing badge helper.

- [ ] **Step 6: Implement sheriff election**

In `engine.py`, import:

```python
    ACTION_SHERIFF_BADGE,
    ACTION_SHERIFF_RUN,
    ACTION_SHERIFF_VOTE,
```

Add constants near the existing action option constants:

```python
SHERIFF_RUN = "上警"
SHERIFF_SKIP = "不上警"
SPEECH_FROM_LEFT = "警左发言"
SPEECH_FROM_RIGHT = "警右发言"
SHERIFF_BADGE_DESTROY = "撕毁警徽"
```

Replace `_run_sheriff_election_if_needed()` with:

```python
def _run_sheriff_election_if_needed(
    self,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
) -> None:
    if not self.rule_set.sheriff_enabled or round_state.number != 1 or self.state.sheriff:
        round_state.sheriff = self.state.sheriff
        return

    players_by_name = self.state.player_by_name()
    candidates: list[str] = []
    for name in active_players:
        choice, action_log = self._player_action(
            player=players_by_name[name],
            action=ACTION_SHERIFF_RUN,
            options=[SHERIFF_RUN, SHERIFF_SKIP],
            result_key="run",
            round_state=round_state,
            phase="day",
        )
        round_log.sheriff_run.append(action_log)
        if choice == SHERIFF_RUN:
            candidates.append(name)

    round_state.sheriff_candidates = candidates
    if not candidates:
        self._announce(active_players, f"第{round_state.number}轮：无人上警，本局暂时没有警长。")
        return

    votes: dict[str, str] = {}
    for voter in active_players:
        vote, action_log = self._player_action(
            player=players_by_name[voter],
            action=ACTION_SHERIFF_VOTE,
            options=candidates,
            result_key="sheriff_vote",
            round_state=round_state,
            phase="day",
        )
        if isinstance(vote, str) and vote in candidates:
            votes[voter] = vote
        round_log.sheriff_votes.append(action_log)

    round_state.sheriff_votes = votes
    sheriff = self._plurality_winner(votes)
    if not sheriff:
        self._announce(active_players, f"第{round_state.number}轮：警长投票平票，本局暂时没有警长。")
        return

    self._set_sheriff(sheriff)
    round_state.sheriff = sheriff
    self._announce(active_players, f"第{round_state.number}轮：{sheriff} 当选警长，拥有 1.5 票。")
```

Add helpers:

```python
def _plurality_winner(self, votes: dict[str, str]) -> str | None:
    if not votes:
        return None
    tally = Counter(votes.values())
    top_count = max(tally.values())
    winners = [name for name, count in tally.items() if count == top_count]
    return winners[0] if len(winners) == 1 else None


def _set_sheriff(self, sheriff: str | None) -> None:
    players_by_name = self.state.player_by_name()
    for player in players_by_name.values():
        player.is_sheriff = player.name == sheriff
    self.state.sheriff = sheriff
    if sheriff:
        self.state.sheriff_badge_lost = False
```

- [ ] **Step 7: Implement sheriff-directed speech order**

Replace `_sheriff_directed_speech_order()`:

```python
def _sheriff_directed_speech_order(
    self,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
) -> list[str]:
    sheriff = self.state.sheriff
    if not sheriff or sheriff not in active_players:
        return active_players.copy()

    choice, action_log = self._player_action(
        player=self.state.player_by_name()[sheriff],
        action=ACTION_SPEECH_ORDER,
        options=[SPEECH_FROM_LEFT, SPEECH_FROM_RIGHT],
        result_key="speech_order",
        round_state=round_state,
        phase="day",
    )
    round_log.speech_order = action_log
    round_state.speech_order_choice = str(choice) if choice else SPEECH_FROM_LEFT

    sheriff_index = active_players.index(sheriff)
    if choice == SPEECH_FROM_RIGHT:
        before_sheriff = list(reversed(active_players[:sheriff_index]))
        after_sheriff = list(reversed(active_players[sheriff_index + 1 :]))
        return before_sheriff + after_sheriff + [sheriff]
    return active_players[sheriff_index + 1 :] + active_players[:sheriff_index] + [sheriff]
```

- [ ] **Step 8: Implement weighted exile voting**

Change `_run_voting()` after setting `votes[voter]`:

```python
round_state.vote_weights[voter] = self._vote_weight(voter)
```

Add:

```python
def _vote_weight(self, voter: str) -> float:
    if self.rule_set.sheriff_enabled and voter == self.state.sheriff:
        return self.rule_set.sheriff_vote_weight
    return 1.0
```

Change `_majority_vote()` signature and body:

```python
def _majority_vote(
    self,
    votes: dict[str, str],
    active_players: list[str],
    vote_weights: dict[str, float],
) -> str | None:
    if not votes:
        return None

    tally: Counter[str] = Counter()
    for voter, target in votes.items():
        tally[target] += vote_weights.get(voter, 1.0)

    target, weight = sorted(tally.items(), key=lambda item: (-item[1], item[0]))[0]
    tied_targets = [name for name, count in tally.items() if count == weight]
    if len(tied_targets) > 1:
        return None

    total_weight = sum(vote_weights.get(voter, 1.0) for voter in votes)
    if weight > total_weight / 2:
        return target
    return None
```

Update the call in `_run_day_phase()`:

```python
exiled = self._majority_vote(votes, active_players, round_state.vote_weights)
```

- [ ] **Step 9: Implement badge transfer**

Call `_maybe_transfer_sheriff_badge()` after any sheriff removal. In `_resolve_night_deaths()`, after `_maybe_run_hunter_shot(...)`, add:

```python
self._maybe_transfer_sheriff_badge(
    dead_player=death.player,
    round_state=round_state,
    round_log=round_log,
    active_players=active_players,
    phase="night",
)
```

In `_resolve_day_exile()`, after `_maybe_run_hunter_shot(...)`, add the same call with `phase="vote"` and `dead_player=exiled`.

Add:

```python
def _maybe_transfer_sheriff_badge(
    self,
    *,
    dead_player: str,
    round_state: RoundState,
    round_log: RoundLog,
    active_players: list[str],
    phase: str,
) -> None:
    if not self.rule_set.sheriff_enabled or dead_player != self.state.sheriff:
        return
    if self.state.sheriff_badge_lost:
        return

    old_sheriff = self.state.player_by_name()[dead_player]
    if not active_players:
        self._set_sheriff(None)
        self.state.sheriff_badge_lost = True
        round_state.sheriff_badge_lost = True
        return

    options = active_players.copy() + [SHERIFF_BADGE_DESTROY]
    choice, action_log = self._player_action(
        player=old_sheriff,
        action=ACTION_SHERIFF_BADGE,
        options=options,
        result_key="badge",
        round_state=round_state,
        phase=phase,
    )
    round_log.sheriff_badge = action_log

    if choice in active_players:
        self._set_sheriff(str(choice))
        round_state.sheriff_badge_target = str(choice)
        round_state.sheriff = str(choice)
        self._announce(active_players, f"{dead_player} 将警徽移交给 {choice}。")
        return

    self._set_sheriff(None)
    self.state.sheriff_badge_lost = True
    round_state.sheriff_badge_lost = True
    round_state.sheriff = None
    self._announce(active_players, f"{dead_player} 撕毁警徽，本局不再有警长。")
```

- [ ] **Step 10: Run sheriff tests and confirm pass**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_12_player_first_day_elects_sheriff_and_uses_sheriff_speech_order tests/test_werewolf_runner.py::test_sheriff_vote_counts_as_one_and_half_votes tests/test_werewolf_runner.py::test_dead_sheriff_can_transfer_badge -q
```

Expected: all three tests pass.

- [ ] **Step 11: Run backend rule and runner suites**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_rules.py tests/test_werewolf_runner.py -q
```

Expected: all selected backend tests pass.

- [ ] **Step 12: Commit sheriff engine flow**

Run:

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: add sheriff election and weighted voting"
```

---

### Task 5: Frontend Types And Replay Normalization

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/api/adapters.ts`
- Test: `apps/web/src/features/games/api/adapters.test.ts`

- [ ] **Step 1: Write failing adapter tests for sheriff replay fields**

Add:

```ts
it("normalizes sheriff speech order and weighted votes", () => {
  const replay = normalizeGameReplay({
    ...rawReplay,
    state: {
      ...rawReplay.state,
      sheriff: "Alice",
      sheriff_badge_lost: false,
      rounds: [
        {
          ...rawReplay.state.rounds[0],
          players: ["Alice", "Bob", "Cora"],
          sheriff: "Alice",
          sheriff_candidates: ["Alice", "Bob"],
          sheriff_votes: { Cora: "Alice" },
          speech_order: ["Bob", "Cora", "Alice"],
          speech_order_choice: "警左发言",
          votes: [{ Alice: "Bob", Cora: "Bob" }],
          vote_weights: { Alice: 1.5, Cora: 1 },
          sheriff_badge_target: null,
          sheriff_badge_lost: false,
        },
      ],
    },
  });

  expect(replay.sheriff).toBe("Alice");
  expect(replay.rounds[0].speech_order).toEqual(["Bob", "Cora", "Alice"]);
  expect(replay.rounds[0].votes).toEqual([
    { voter: "Alice", target: "Bob", weight: 1.5 },
    { voter: "Cora", target: "Bob", weight: 1 },
  ]);
  expect(replay.rounds[0].voteTally).toEqual([{ target: "Bob", count: 2.5 }]);
  expect(replay.rounds[0].voteCount).toBe(2.5);
  expect(replay.rounds[0].voteMajorityThreshold).toBe(1.75);
});
```

Add a debug item test:

```ts
it("creates debug items for sheriff actions", () => {
  const replay = normalizeGameReplay({
    ...rawReplay,
    logs: [
      {
        ...rawReplay.logs[0],
        number: 1,
        sheriff_run: [
          {
            actor: "Alice",
            action: "sheriff_run",
            options: ["上警", "不上警"],
            choice: "上警",
            lm_log: { prompt: "警长竞选", raw_response: "{}", result: {} },
          },
        ],
        sheriff_votes: [
          {
            actor: "Bob",
            action: "sheriff_vote",
            options: ["Alice"],
            choice: "Alice",
            lm_log: { prompt: "警长投票", raw_response: "{}", result: {} },
          },
        ],
        speech_order: {
          actor: "Alice",
          action: "speech_order",
          options: ["警左发言", "警右发言"],
          choice: "警左发言",
          lm_log: { prompt: "发言方向", raw_response: "{}", result: {} },
        },
        sheriff_badge: null,
      },
    ],
  });

  expect(replay.debugItems.map(({ title }) => title)).toContain("警长竞选");
  expect(replay.debugItems.map(({ title }) => title)).toContain("警长投票");
  expect(replay.debugItems.map(({ title }) => title)).toContain("发言方向");
});
```

- [ ] **Step 2: Run adapter tests and confirm failure**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/api/adapters.test.ts
```

Expected: TypeScript or assertion failures mention missing sheriff fields and titles.

- [ ] **Step 3: Extend frontend types**

In `RuleSetSummary`, add:

```ts
sheriff_enabled?: boolean;
sheriff_vote_weight?: number;
speech_policy?: "sequential" | "sheriff_directed" | string;
speech_rounds?: number;
rule_tags?: string[];
```

In `RawRoundLog`, add optional fields:

```ts
sheriff_run?: RawActionLog[];
sheriff_votes?: RawActionLog[];
speech_order?: RawActionLog | null;
sheriff_badge?: RawActionLog | null;
```

In `RawPlayer`, add:

```ts
is_sheriff?: boolean;
```

In `RawRoundState`, add optional fields:

```ts
sheriff?: string | null;
sheriff_candidates?: string[];
sheriff_votes?: Record<string, string>;
speech_order?: string[];
speech_order_choice?: string | null;
vote_weights?: Record<string, number>;
sheriff_badge_target?: string | null;
sheriff_badge_lost?: boolean;
```

In `RawGameState`, add:

```ts
sheriff?: string | null;
sheriff_badge_lost?: boolean;
```

Change `VoteEntry`:

```ts
export type VoteEntry = {
  voter: string;
  target: string;
  weight: number;
};
```

Add these fields to `GameRound`:

```ts
sheriff: string | null;
sheriff_candidates: string[];
sheriff_votes: Record<string, string>;
speech_order: string[];
speech_order_choice: string | null;
vote_weights: Record<string, number>;
sheriff_badge_target: string | null;
sheriff_badge_lost: boolean;
```

Add these fields to `GameReplay`:

```ts
sheriff: string | null;
sheriffBadgeLost: boolean;
```

- [ ] **Step 4: Normalize sheriff fields and weighted votes**

In `ACTION_TITLES`, add:

```ts
sheriff_run: "警长竞选",
sheriff_vote: "警长投票",
speech_order: "发言方向",
sheriff_badge: "警徽移交",
```

In `normalizeGameReplay()`, add:

```ts
sheriff: response.state.sheriff ?? null,
sheriffBadgeLost: response.state.sheriff_badge_lost ?? false,
```

In `normalizeRound()`, replace vote normalization:

```ts
const voteWeights = round.vote_weights ?? {};
const votes = round.votes.flatMap((entry) =>
  Object.entries(entry).map(([voter, target]) => ({
    voter,
    target,
    weight: voteWeights[voter] ?? 1,
  })),
);
const totalVoteWeight = votes.reduce((sum, vote) => sum + vote.weight, 0);
```

Return the new fields:

```ts
sheriff: round.sheriff ?? null,
sheriff_candidates: round.sheriff_candidates ?? [],
sheriff_votes: round.sheriff_votes ?? {},
speech_order: round.speech_order ?? [],
speech_order_choice: round.speech_order_choice ?? null,
vote_weights: voteWeights,
sheriff_badge_target: round.sheriff_badge_target ?? null,
sheriff_badge_lost: round.sheriff_badge_lost ?? false,
votes,
voteTally: tallyVotes(votes),
voteCount: totalVoteWeight,
voteMajorityThreshold: totalVoteWeight > 0 ? totalVoteWeight / 2 : null,
```

Replace `tallyVotes()`:

```ts
function tallyVotes(votes: VoteEntry[]) {
  const counts = new Map<string, number>();
  votes.forEach((vote) => {
    counts.set(vote.target, (counts.get(vote.target) ?? 0) + vote.weight);
  });

  return Array.from(counts.entries())
    .map(([target, count]) => ({ target, count }))
    .sort((a, b) => b.count - a.count || a.target.localeCompare(b.target));
}
```

In `debugItemsFromRound()`, add sheriff actions before debate:

```ts
(round.sheriff_run ?? []).forEach((action, index) => {
  pushAction(items, round.number, "day", `day-sheriff-run-${index}`, action);
});
(round.sheriff_votes ?? []).forEach((action, index) => {
  pushAction(items, round.number, "day", `day-sheriff-vote-${index}`, action);
});
pushAction(items, round.number, "day", "day-speech-order", round.speech_order ?? null);
pushAction(items, round.number, "day", "day-sheriff-badge", round.sheriff_badge ?? null);
```

- [ ] **Step 5: Run adapter tests and confirm pass**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/api/adapters.test.ts
```

Expected: adapter tests pass.

- [ ] **Step 6: Commit frontend type and adapter changes**

Run:

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/api/adapters.ts apps/web/src/features/games/api/adapters.test.ts
git commit -m "feat: normalize sheriff replay data"
```

---

### Task 6: Frontend Rule Cards And Day Replay UI

**Files:**
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Modify: `apps/web/src/features/games/components/RuleSetSummary.tsx`
- Modify: `apps/web/src/features/games/components/DayPhase.tsx`
- Modify: `apps/web/src/features/games/components/VoteTable.tsx`
- Test: `apps/web/src/features/games/components/DayPhase.test.tsx`
- Test: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Write failing DayPhase UI tests**

Update `baseRound` in `DayPhase.test.tsx` with the new required fields:

```ts
sheriff: null,
sheriff_candidates: [],
sheriff_votes: {},
speech_order: [],
speech_order_choice: null,
vote_weights: {},
sheriff_badge_target: null,
sheriff_badge_lost: false,
```

Add:

```ts
it("hides bidding for ordered speech rounds and shows speech order", () => {
  render(
    <DayPhase
      round={{
        ...baseRound,
        speech_order: ["Alice", "Bob"],
        debate: [
          { speaker: "Alice", message: "先听我说。" },
          { speaker: "Bob", message: "我反驳。" },
        ],
      }}
      items={[]}
      selectedItem={null}
      onSelect={vi.fn()}
    />,
  );

  expect(screen.queryByText("竞价")).not.toBeInTheDocument();
  expect(screen.getByText("发言顺序")).toBeInTheDocument();
  expect(screen.getByText("Alice -> Bob")).toBeInTheDocument();
});

it("shows sheriff vote weight in vote table", () => {
  render(
    <DayPhase
      round={{
        ...baseRound,
        votes: [{ voter: "Alice", target: "Bob", weight: 1.5 }],
        voteTally: [{ target: "Bob", count: 1.5 }],
        voteCount: 1.5,
        voteMajorityThreshold: 0.75,
      }}
      items={[]}
      selectedItem={null}
      onSelect={vi.fn()}
    />,
  );

  expect(screen.getByText("Bob：1.5票")).toBeInTheDocument();
  expect(screen.getByText("Alice（1.5票）")).toBeInTheDocument();
});
```

- [ ] **Step 2: Write failing rule card tests**

In `GamesPage.test.tsx`, extend `ruleSetsResponse()` with `rule_tags` and sheriff metadata for both rules:

```ts
rule_tags: ["无警长", "顺序发言", "标准"],
sheriff_enabled: false,
speech_policy: "sequential",
speech_rounds: 1,
```

For the 12-player fixture used in existing rule selection tests, include:

```ts
rule_tags: ["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
sheriff_enabled: true,
sheriff_vote_weight: 1.5,
speech_policy: "sheriff_directed",
speech_rounds: 1,
```

Add assertions:

```ts
expect(await screen.findByText("快速少人局")).toBeInTheDocument();
expect(screen.getByText("无警长")).toBeInTheDocument();
expect(screen.getByText("顺序发言")).toBeInTheDocument();
```

- [ ] **Step 3: Run frontend focused tests and confirm failure**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/DayPhase.test.tsx src/pages/GamesPage.test.tsx
```

Expected: tests fail because UI does not render tags, still shows bid section, and does not display vote weights.

- [ ] **Step 4: Update VoteTable for weighted votes**

In `VoteTable.tsx`, render counts with a helper:

```ts
function formatVoteCount(count: number) {
  return Number.isInteger(count) ? `${count}` : count.toFixed(1);
}
```

Use it in tally:

```tsx
{entry.target}：{formatVoteCount(entry.count)}票
```

Change voter cell:

```tsx
{vote.weight === 1 ? vote.voter : `${vote.voter}（${formatVoteCount(vote.weight)}票）`}
```

- [ ] **Step 5: Update DayPhase for speech order and legacy bids**

Render bid rounds only when there is legacy bid data:

```tsx
{round.bidGroups.length > 0 || round.bids.length > 0 ? (
  <section className="mt-3">
    <h4 className="text-xs font-semibold uppercase text-slate-500">
      历史竞价
    </h4>
    <div className="mt-2">
      <BidRounds round={round} />
    </div>
  </section>
) : null}
```

Add a speech order block before debate:

```tsx
{round.speech_order.length > 0 ? (
  <section className="mt-3">
    <h4 className="text-xs font-semibold uppercase text-slate-500">
      发言顺序
    </h4>
    <p className="mt-2 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
      {round.speech_order.join(" -> ")}
    </p>
  </section>
) : null}
```

In `VoteResolution`, render weighted threshold:

```tsx
多数门槛 {formatVoteCount(round.voteMajorityThreshold)}/{formatVoteCount(round.voteCount)}
```

Import or define `formatVoteCount` in a shared local helper inside `DayPhase.tsx`.

- [ ] **Step 6: Update rule card grouping and tags**

In `CreateGameRunForm.tsx`, derive groups:

```ts
const quickRules = ruleSets.filter((rule) => !rule.sheriff_enabled);
const sheriffRules = ruleSets.filter((rule) => rule.sheriff_enabled);
```

Render each group with headings:

```tsx
<RuleGroup
  title="快速少人局"
  rules={quickRules}
  selectedRuleSetId={selectedRuleSetId}
  onSelect={setSelectedRuleSetId}
/>
<RuleGroup
  title="标准警长局"
  rules={sheriffRules}
  selectedRuleSetId={selectedRuleSetId}
  onSelect={setSelectedRuleSetId}
/>
```

Add a local `RuleGroup` function that reuses the current label markup and renders tags:

```tsx
{rule.rule_tags && rule.rule_tags.length > 0 ? (
  <span className="mt-3 flex flex-wrap gap-1.5">
    {rule.rule_tags.map((tag) => (
      <span
        className="rounded border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-600"
        key={tag}
      >
        {tag}
      </span>
    ))}
  </span>
) : null}
```

Use existing card dimensions and `rounded-md`; do not introduce a landing-page layout.

- [ ] **Step 7: Update RuleSetSummary tags**

In `RuleSetSummary.tsx`, update fallback role summary to `守卫` and render tags:

```tsx
{rule.rule_tags && rule.rule_tags.length > 0 ? (
  <div className="mt-2 flex flex-wrap gap-1.5">
    {rule.rule_tags.map((tag) => (
      <span
        className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-600"
        key={tag}
      >
        {tag}
      </span>
    ))}
  </div>
) : null}
```

- [ ] **Step 8: Run frontend focused tests and confirm pass**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/DayPhase.test.tsx src/pages/GamesPage.test.tsx
```

Expected: focused frontend tests pass.

- [ ] **Step 9: Commit frontend UI updates**

Run:

```bash
git add apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/features/games/components/RuleSetSummary.tsx apps/web/src/features/games/components/DayPhase.tsx apps/web/src/features/games/components/VoteTable.tsx apps/web/src/features/games/components/DayPhase.test.tsx apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat: show redesigned rule options and sheriff replay"
```

---

### Task 7: Full Verification And Cleanup

**Files:**
- Modify: `apps/api/app/werewolf/config.py`
- Modify: `apps/api/app/werewolf/rules.py`
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/prompts_zh.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/tests/test_werewolf_rules.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/api/adapters.ts`
- Modify: `apps/web/src/features/games/api/adapters.test.ts`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Modify: `apps/web/src/features/games/components/RuleSetSummary.tsx`
- Modify: `apps/web/src/features/games/components/DayPhase.tsx`
- Modify: `apps/web/src/features/games/components/VoteTable.tsx`
- Modify: `apps/web/src/features/games/components/DayPhase.test.tsx`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Run full backend tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest -q
```

Expected: all backend tests pass.

- [ ] **Step 2: Run full frontend tests**

Run:

```bash
pnpm --dir apps/web test -- --run
```

Expected: all frontend tests pass.

- [ ] **Step 3: Run frontend build**

Run:

```bash
pnpm --dir apps/web build
```

Expected: build passes.

- [ ] **Step 4: Run API lint**

Run:

```bash
cd apps/api
.venv/bin/python -m ruff check .
```

Expected: lint passes.

- [ ] **Step 5: Check frontend lint status**

Run:

```bash
pnpm --dir apps/web lint
```

Expected: any failures in `useGameRunEvents.ts`, `useLiveDirector.ts`, or `LiveGamePage.tsx` should be treated as pre-existing unless touched by this work. New failures in files touched by this plan must be fixed before completion.

- [ ] **Step 6: Inspect git diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: changed files match this plan; no unrelated files are modified.

- [ ] **Step 7: Commit verification fixes if any were needed**

If Task 7 required code changes in the scoped files, run:

```bash
git add apps/api/app/werewolf/config.py apps/api/app/werewolf/rules.py apps/api/app/werewolf/models.py apps/api/app/werewolf/prompts_zh.py apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_rules.py apps/api/tests/test_werewolf_runner.py apps/web/src/features/games/types.ts apps/web/src/features/games/api/adapters.ts apps/web/src/features/games/api/adapters.test.ts apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/features/games/components/RuleSetSummary.tsx apps/web/src/features/games/components/DayPhase.tsx apps/web/src/features/games/components/VoteTable.tsx apps/web/src/features/games/components/DayPhase.test.tsx apps/web/src/pages/GamesPage.test.tsx
git commit -m "fix: polish sheriff rule flow"
```

---

## Implementation Notes

- Keep `ACTION_BID` defined for legacy replay labels and old logs, but remove it from official rule-set `day_actions` and stop calling it from the engine.
- Keep `RoundState.bids` and `RoundLog.bid` for backward compatibility; new games should leave them empty.
- Keep the engine constant name `DOCTOR` as an alias to `守卫` so current imports do not need a broad rename.
- Do not add PK rounds in this iteration; ties resolve to no sheriff or no exile according to the scope section.
- Do not change the default rule-set id; `classic_8` remains the default, but its display role becomes `守卫`.

## Self-Review

- Spec coverage: rule metadata, small-game ordered speeches, 12-player sheriff election, speech direction, weighted voting, badge transfer, frontend tags, replay UI, and tests are covered by Tasks 1-7.
- Placeholder scan: no implementation step depends on an undefined field or action; tie policies and legacy bid behavior are explicit.
- Type consistency: backend fields use snake_case payload names; frontend types preserve those raw names and expose camelCase only for `GameReplay.sheriffBadgeLost`, matching existing adapter style.
