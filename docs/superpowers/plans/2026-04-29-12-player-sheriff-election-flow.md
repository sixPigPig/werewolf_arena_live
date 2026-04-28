# 12 人预女猎白警长竞选流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 12 人预女猎白局升级为完整警长竞选流程：死讯公布前竞选、警上发言、退水、警下投票、平票 PK、警徽处理、警长定发言方向，并让前端清晰展示。

**Architecture:** 后端 `RuleSet` 和 `RoundState/RoundLog` 继续作为规则与回放数据源；`GameEngine` 增加警长竞选专属流程，竞选发言与正式白天发言分离。前端在 adapter 层兼容新增字段，并用独立 `SheriffElectionPanel` 展示警长竞选、警徽状态和发言方向。

**Tech Stack:** Python dataclasses + pytest + ruff；React + TypeScript + Vitest + Testing Library；现有 FastAPI/API 回放结构。

---

## File Map

- Modify `apps/api/app/werewolf/rules.py`: 新增警长动作常量，更新 12 人规则 `day_actions` 与规则文本。
- Modify `apps/api/app/werewolf/models.py`: 扩展 `RoundState`、`RoundLog` 序列化字段。
- Modify `apps/api/app/werewolf/prompts_zh.py`: 新增 `sheriff_speech`、`sheriff_withdraw`、`sheriff_pk_speech`、`sheriff_runoff_vote` schema、字段标签和中文指令。
- Modify `apps/api/app/werewolf/engine.py`: 重写首日警长竞选流程，拆分首夜 pending 死亡公布与警徽处理。
- Modify `apps/api/tests/test_werewolf_rules.py`: 覆盖规则动作和规则文本。
- Modify `apps/api/tests/test_werewolf_runner.py`: 覆盖警上/警下/退水/PK/首夜死亡警长警徽处理。
- Modify `apps/web/src/features/games/types.ts`: 新增警长竞选状态和日志字段类型。
- Modify `apps/web/src/features/games/api/adapters.ts`: 规范化新增字段，更新 debug 行动卡标题与顺序。
- Modify `apps/web/src/features/games/api/adapters.test.ts`: 覆盖新增字段和 debug 标题。
- Modify `apps/web/src/features/games/components/DayPhase.tsx`: 接入警长竞选展示区块。
- Create `apps/web/src/features/games/components/SheriffElectionPanel.tsx`: 展示警长竞选、警徽状态和发言方向。
- Create `apps/web/src/features/games/components/SheriffElectionPanel.test.tsx`: 覆盖警长竞选 UI。
- Modify `apps/web/src/features/games/components/DayPhase.test.tsx`: 覆盖新分区与旧数据兜底。
- Modify `apps/web/src/features/games/components/DebugPanel.tsx`: 增加新增解析字段中文标签。

## Task 0: 创建实现 worktree

**Files:**
- No code files changed.

- [ ] **Step 1: 确认主工作区干净**

Run:

```bash
git status --short
```

Expected: no output.

- [ ] **Step 2: 创建隔离 worktree**

Run:

```bash
git worktree add .worktrees/sheriff-election-flow -b codex/sheriff-election-flow
```

Expected: creates `.worktrees/sheriff-election-flow` on branch `codex/sheriff-election-flow`.

- [ ] **Step 3: 进入 worktree 并确认分支**

Run:

```bash
cd .worktrees/sheriff-election-flow
git branch --show-current
```

Expected:

```text
codex/sheriff-election-flow
```

## Task 1: 后端规则动作与提示词元数据

**Files:**
- Modify `apps/api/app/werewolf/rules.py`
- Modify `apps/api/app/werewolf/prompts_zh.py`
- Test `apps/api/tests/test_werewolf_rules.py`
- Test `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: 写规则动作失败测试**

Append these assertions inside `test_12_player_rule_set_has_sheriff_flow_metadata` in `apps/api/tests/test_werewolf_rules.py`:

```python
    assert rule.day_actions == (
        "sheriff_run",
        "sheriff_speech",
        "sheriff_withdraw",
        "sheriff_vote",
        "sheriff_pk_speech",
        "sheriff_runoff_vote",
        "speech_order",
        "debate",
        "vote",
        "hunter_shoot",
        "summarize",
    )
```

Replace the old `rule.day_actions` assertion in that test with the block above.

In `test_12_player_rule_text_describes_confirmed_table_rules`, replace the two sheriff text assertions:

```python
    assert "首日进行警长竞选和警长投票" in text
    assert "由警长决定发言顺序" in text
```

with:

```python
    assert "首日先上警、警上发言、退水，再由警下玩家投票选出警长" in text
    assert "平票时进入 PK 发言和二轮警下投票" in text
    assert "警长在正式白天发言前决定警左或警右" in text
```

- [ ] **Step 2: 写提示词失败测试**

In `apps/api/tests/test_werewolf_runner.py`, update `test_sheriff_prompt_actions_render_chinese_instructions` to build new prompts:

```python
    speech_prompt, speech_schema = build_prompt("sheriff_speech", world_state)
    withdraw_prompt, withdraw_schema = build_prompt("sheriff_withdraw", world_state)
    pk_prompt, pk_schema = build_prompt("sheriff_pk_speech", world_state)
    runoff_prompt, runoff_schema = build_prompt("sheriff_runoff_vote", world_state)
```

Add these assertions:

```python
    assert "警上竞选发言" in speech_prompt
    assert speech_schema["required"] == ["reasoning", "say"]
    assert "退水" in withdraw_prompt
    assert withdraw_schema["required"] == ["reasoning", "withdraw"]
    assert "PK 发言" in pk_prompt
    assert pk_schema["required"] == ["reasoning", "say"]
    assert "二轮警下投票" in runoff_prompt
    assert runoff_schema["required"] == ["reasoning", "sheriff_vote"]
```

- [ ] **Step 3: 运行失败测试**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_rules.py::test_12_player_rule_set_has_sheriff_flow_metadata tests/test_werewolf_rules.py::test_12_player_rule_text_describes_confirmed_table_rules tests/test_werewolf_runner.py::test_sheriff_prompt_actions_render_chinese_instructions -q
```

Expected: fails because new action constants and prompt schemas are not defined.

- [ ] **Step 4: 实现规则动作常量**

In `apps/api/app/werewolf/rules.py`, add constants after `ACTION_SHERIFF_RUN`:

```python
ACTION_SHERIFF_SPEECH = "sheriff_speech"
ACTION_SHERIFF_WITHDRAW = "sheriff_withdraw"
ACTION_SHERIFF_PK_SPEECH = "sheriff_pk_speech"
ACTION_SHERIFF_RUNOFF_VOTE = "sheriff_runoff_vote"
```

Update 12-player `day_actions`:

```python
    day_actions=(
        ACTION_SHERIFF_RUN,
        ACTION_SHERIFF_SPEECH,
        ACTION_SHERIFF_WITHDRAW,
        ACTION_SHERIFF_VOTE,
        ACTION_SHERIFF_PK_SPEECH,
        ACTION_SHERIFF_RUNOFF_VOTE,
        ACTION_SPEECH_ORDER,
        ACTION_DEBATE,
        ACTION_VOTE,
        ACTION_HUNTER_SHOOT,
        ACTION_SUMMARIZE,
    ),
```

Update `render_rule_text` sheriff paragraph to:

```python
        lines.append(
            "白天行动：首日先上警、警上发言、退水，再由警下玩家投票选出警长；"
            "平票时进入 PK 发言和二轮警下投票。"
        )
        lines.append(
            "警长在正式白天发言前决定警左或警右，所有玩家完成完整发言，随后投票放逐并进行总结。"
        )
        lines.append(
            f"警长投票计为 {rule_set.sheriff_vote_weight:g} 票，警长死亡时警徽可移交或撕毁。"
        )
```

- [ ] **Step 5: 实现提示词 schema 和指令**

In `apps/api/app/werewolf/prompts_zh.py`, add schemas:

```python
    "sheriff_speech": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "say": {"type": "string"}},
        "required": ["reasoning", "say"],
    },
    "sheriff_withdraw": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "withdraw": {"type": "string"}},
        "required": ["reasoning", "withdraw"],
    },
    "sheriff_pk_speech": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "say": {"type": "string"}},
        "required": ["reasoning", "say"],
    },
    "sheriff_runoff_vote": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "sheriff_vote": {"type": "string"}},
        "required": ["reasoning", "sheriff_vote"],
    },
```

Add to `RESULT_FIELD_BY_ACTION`:

```python
    "sheriff_speech": "say",
    "sheriff_withdraw": "withdraw",
    "sheriff_pk_speech": "say",
    "sheriff_runoff_vote": "sheriff_vote",
```

Add to `FIELD_LABELS`:

```python
    "withdraw": "退水选择",
```

Add branches in `_render_instruction`:

```python
    if action == "sheriff_speech":
        return (
            "行动：警上竞选发言。\n"
            "你已经上警，需要公开说明竞选警长的理由、警徽流思路和当前判断。\n"
            "发言必须是中文，简洁、有策略、像真实玩家。输出字段 reasoning 和 say。"
        )
    if action == "sheriff_withdraw":
        return (
            "行动：退水选择。\n"
            "你刚完成警上竞选发言，需要决定是否退水。退水后不再是警长候选，也不会获得警长投票权。\n"
            f"候选选项：{options}。\n"
            "输出字段 reasoning 和 withdraw。"
        )
    if action == "sheriff_pk_speech":
        return (
            "行动：警长竞选 PK 发言。\n"
            "首轮警下投票出现最高票平票，你作为 PK 候选需要再次发言争取警下二轮票。\n"
            "发言必须是中文，简洁、有策略、像真实玩家。输出字段 reasoning 和 say。"
        )
    if action == "sheriff_runoff_vote":
        return (
            "行动：二轮警下投票。\n"
            "你是警下玩家，只能从 PK 候选中选择一名玩家投票。\n"
            f"候选人：{options}。\n"
            "输出字段 reasoning 和 sheriff_vote。"
        )
```

- [ ] **Step 6: 运行测试确认通过**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_rules.py::test_12_player_rule_set_has_sheriff_flow_metadata tests/test_werewolf_rules.py::test_12_player_rule_text_describes_confirmed_table_rules tests/test_werewolf_runner.py::test_sheriff_prompt_actions_render_chinese_instructions -q
```

Expected: all selected tests pass.

- [ ] **Step 7: 提交**

Run:

```bash
git add apps/api/app/werewolf/rules.py apps/api/app/werewolf/prompts_zh.py apps/api/tests/test_werewolf_rules.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: add sheriff election prompt actions"
```

Expected: commit succeeds.

## Task 2: 后端回合状态和日志序列化

**Files:**
- Modify `apps/api/app/werewolf/models.py`
- Test `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: 写失败测试**

In `apps/api/tests/test_werewolf_runner.py`, replace `test_sheriff_state_serializes_to_game_and_round_payloads` with:

```python
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
    assert round_payload["sheriff_candidates"] == [state.players[0].name, state.players[1].name]
    assert round_payload["sheriff_speeches"] == [
        {"speaker": state.players[0].name, "message": "我上警争警徽。"}
    ]
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
```

Add a new log serialization test:

```python
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
    log.sheriff_pk_speech.append(action)
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
    assert payload["sheriff_pk_speech"][0]["action"] == "sheriff_speech"
    assert payload["sheriff_runoff_votes"][0]["choice"] == "Alice"
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_sheriff_state_serializes_to_game_and_round_payloads tests/test_werewolf_runner.py::test_sheriff_action_logs_serialize_new_election_steps -q
```

Expected: fails because new dataclass fields do not exist.

- [ ] **Step 3: 扩展 `RoundState`**

In `apps/api/app/werewolf/models.py`, add fields after `sheriff_candidates`:

```python
    sheriff_speeches: list[dict[str, str]] = field(default_factory=list)
    sheriff_withdrawn: list[str] = field(default_factory=list)
    sheriff_final_candidates: list[str] = field(default_factory=list)
    sheriff_voters: list[str] = field(default_factory=list)
    sheriff_pk_candidates: list[str] = field(default_factory=list)
    sheriff_pk_speeches: list[dict[str, str]] = field(default_factory=list)
    sheriff_runoff_votes: dict[str, str] = field(default_factory=dict)
    sheriff_elected: str | None = None
```

Add these keys in `RoundState.to_dict()` after `sheriff_candidates`:

```python
            "sheriff_speeches": self.sheriff_speeches,
            "sheriff_withdrawn": self.sheriff_withdrawn,
            "sheriff_final_candidates": self.sheriff_final_candidates,
            "sheriff_voters": self.sheriff_voters,
            "sheriff_pk_candidates": self.sheriff_pk_candidates,
            "sheriff_pk_speeches": self.sheriff_pk_speeches,
            "sheriff_runoff_votes": self.sheriff_runoff_votes,
            "sheriff_elected": self.sheriff_elected,
```

- [ ] **Step 4: 扩展 `RoundLog`**

In `apps/api/app/werewolf/models.py`, add fields after `sheriff_run`:

```python
    sheriff_speech: list[ActionLog] = field(default_factory=list)
    sheriff_withdraw: list[ActionLog] = field(default_factory=list)
    sheriff_pk_speech: list[ActionLog] = field(default_factory=list)
    sheriff_runoff_votes: list[ActionLog] = field(default_factory=list)
```

Add these keys in `RoundLog.to_dict()` after `sheriff_run`:

```python
            "sheriff_speech": [log.to_dict() for log in self.sheriff_speech],
            "sheriff_withdraw": [log.to_dict() for log in self.sheriff_withdraw],
            "sheriff_pk_speech": [log.to_dict() for log in self.sheriff_pk_speech],
            "sheriff_runoff_votes": [log.to_dict() for log in self.sheriff_runoff_votes],
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_sheriff_state_serializes_to_game_and_round_payloads tests/test_werewolf_runner.py::test_sheriff_action_logs_serialize_new_election_steps -q
```

Expected: both tests pass.

- [ ] **Step 6: 提交**

Run:

```bash
git add apps/api/app/werewolf/models.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: serialize sheriff election state"
```

Expected: commit succeeds.

## Task 3: 警长竞选主流程

**Files:**
- Modify `apps/api/app/werewolf/engine.py`
- Modify `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: 添加可脚本化警长流程 provider**

In `apps/api/tests/test_werewolf_runner.py`, replace `SheriffFlowProvider` with this version:

```python
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
        if '"sheriff_vote"' in prompt and "二轮警下投票" in prompt:
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
            choice = options[0] if options else "1"
            return json.dumps({"reasoning": "测试放逐票。", "vote": choice}, ensure_ascii=False)
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)
```

- [ ] **Step 2: 写警上/警下权限失败测试**

Add this test in `apps/api/tests/test_werewolf_runner.py`:

```python
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
    assert [entry["speaker"] for entry in round_state.sheriff_speeches] == [
        first_candidate,
        withdrawn_candidate,
    ]
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
```

- [ ] **Step 3: 写 PK 和二轮失败测试**

Add this test:

```python
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
```

- [ ] **Step 4: 写警徽流失失败测试**

Add these tests:

```python
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
```

- [ ] **Step 5: 运行失败测试**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_sheriff_election_limits_speeches_to_candidates_and_votes_to_off_sheriff_players tests/test_werewolf_runner.py::test_sheriff_election_runs_pk_and_runoff_when_first_vote_ties tests/test_werewolf_runner.py::test_sheriff_badge_is_lost_when_no_candidates_remain_after_withdraw tests/test_werewolf_runner.py::test_sheriff_badge_is_lost_when_all_players_run_and_multiple_candidates_remain -q
```

Expected: tests fail because the current engine does not run sheriff speeches, withdraw, voter restrictions, PK, or badge loss in these cases.

- [ ] **Step 6: 导入新动作常量**

In `apps/api/app/werewolf/engine.py`, extend the import from `app.werewolf.rules`:

```python
    ACTION_SHERIFF_PK_SPEECH,
    ACTION_SHERIFF_RUNOFF_VOTE,
    ACTION_SHERIFF_SPEECH,
    ACTION_SHERIFF_WITHDRAW,
```

Add constants near existing sheriff constants:

```python
SHERIFF_WITHDRAW = "退水"
SHERIFF_STAY = "不退水"
```

- [ ] **Step 7: 增加选举 tally helper**

Replace `_plurality_winner` with:

```python
    def _plurality_winner(self, votes: dict[str, str]) -> str | None:
        winners = self._plurality_winners(votes)
        return winners[0] if len(winners) == 1 else None

    def _plurality_winners(self, votes: dict[str, str]) -> list[str]:
        if not votes:
            return []
        tally = Counter(votes.values())
        top_count = max(tally.values())
        return [name for name, count in tally.items() if count == top_count]
```

- [ ] **Step 8: 重写 `_run_sheriff_election_if_needed`**

Replace the body of `_run_sheriff_election_if_needed` after the guard with:

```python
        players_by_name = self.state.player_by_name()
        candidates: list[str] = []
        voters: list[str] = []
        for name in active_players:
            run_choice, action_log = self._player_action(
                player=players_by_name[name],
                action=ACTION_SHERIFF_RUN,
                options=[SHERIFF_RUN, SHERIFF_SKIP],
                result_key="run",
                round_state=round_state,
                phase="day",
            )
            round_log.sheriff_run.append(action_log)
            if run_choice == SHERIFF_RUN:
                candidates.append(name)
            else:
                voters.append(name)

        round_state.sheriff_candidates = candidates
        round_state.sheriff_voters = voters
        if not candidates:
            self._lose_sheriff_badge(round_state, active_players, "无人上警")
            return

        withdrawn: list[str] = []
        for candidate in candidates:
            message, speech_log = self._player_action(
                player=players_by_name[candidate],
                action=ACTION_SHERIFF_SPEECH,
                options=[],
                result_key="say",
                round_state=round_state,
                phase="day",
            )
            if not isinstance(message, str) or not message:
                raise ValueError(f"{candidate} did not return a valid sheriff speech.")
            entry = {"speaker": candidate, "message": message}
            round_state.sheriff_speeches.append(entry)
            round_log.sheriff_speech.append(speech_log)

            withdraw_choice, withdraw_log = self._player_action(
                player=players_by_name[candidate],
                action=ACTION_SHERIFF_WITHDRAW,
                options=[SHERIFF_WITHDRAW, SHERIFF_STAY],
                result_key="withdraw",
                round_state=round_state,
                phase="day",
            )
            round_log.sheriff_withdraw.append(withdraw_log)
            if withdraw_choice == SHERIFF_WITHDRAW:
                withdrawn.append(candidate)

        round_state.sheriff_withdrawn = withdrawn
        final_candidates = [name for name in candidates if name not in withdrawn]
        round_state.sheriff_final_candidates = final_candidates

        if not final_candidates:
            self._lose_sheriff_badge(round_state, active_players, "所有警上玩家退水")
            return
        if len(final_candidates) == 1:
            self._elect_sheriff(final_candidates[0], round_state, active_players)
            return
        if not voters:
            self._lose_sheriff_badge(round_state, active_players, "没有警下玩家拥有警长投票权")
            return

        for voter in voters:
            vote, action_log = self._player_action(
                player=players_by_name[voter],
                action=ACTION_SHERIFF_VOTE,
                options=final_candidates,
                result_key="sheriff_vote",
                round_state=round_state,
                phase="day",
            )
            round_log.sheriff_votes.append(action_log)
            if isinstance(vote, str) and vote in final_candidates:
                round_state.sheriff_votes[voter] = vote

        sheriff = self._plurality_winner(round_state.sheriff_votes)
        if sheriff is not None:
            self._elect_sheriff(sheriff, round_state, active_players)
            return

        pk_candidates = [
            name for name in final_candidates if name in self._plurality_winners(round_state.sheriff_votes)
        ]
        round_state.sheriff_pk_candidates = pk_candidates
        for candidate in pk_candidates:
            message, action_log = self._player_action(
                player=players_by_name[candidate],
                action=ACTION_SHERIFF_PK_SPEECH,
                options=[],
                result_key="say",
                round_state=round_state,
                phase="day",
            )
            if not isinstance(message, str) or not message:
                raise ValueError(f"{candidate} did not return a valid sheriff PK speech.")
            round_state.sheriff_pk_speeches.append({"speaker": candidate, "message": message})
            round_log.sheriff_pk_speech.append(action_log)

        for voter in voters:
            vote, action_log = self._player_action(
                player=players_by_name[voter],
                action=ACTION_SHERIFF_RUNOFF_VOTE,
                options=pk_candidates,
                result_key="sheriff_vote",
                round_state=round_state,
                phase="day",
            )
            round_log.sheriff_runoff_votes.append(action_log)
            if isinstance(vote, str) and vote in pk_candidates:
                round_state.sheriff_runoff_votes[voter] = vote

        runoff_winner = self._plurality_winner(round_state.sheriff_runoff_votes)
        if runoff_winner is not None:
            self._elect_sheriff(runoff_winner, round_state, active_players)
            return

        self._lose_sheriff_badge(round_state, active_players, "二轮警下投票仍然平票")
```

- [ ] **Step 9: 添加警长当选和流失 helper**

Add below `_run_sheriff_election_if_needed`:

```python
    def _elect_sheriff(
        self,
        sheriff: str,
        round_state: RoundState,
        active_players: list[str],
    ) -> None:
        self._set_sheriff(sheriff)
        round_state.sheriff = sheriff
        round_state.sheriff_elected = sheriff
        round_state.sheriff_badge_lost = False
        self._announce(
            active_players,
            f"第{round_state.number}轮：警长竞选，{sheriff}当选警长，投票计为{self.rule_set.sheriff_vote_weight:g}票。",
        )

    def _lose_sheriff_badge(
        self,
        round_state: RoundState,
        active_players: list[str],
        reason: str,
    ) -> None:
        self._set_sheriff(None)
        self.state.sheriff_badge_lost = True
        round_state.sheriff = None
        round_state.sheriff_badge_lost = True
        self._announce(active_players, f"第{round_state.number}轮：{reason}，警徽流失。")
```

- [ ] **Step 10: 运行测试确认通过**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_sheriff_election_limits_speeches_to_candidates_and_votes_to_off_sheriff_players tests/test_werewolf_runner.py::test_sheriff_election_runs_pk_and_runoff_when_first_vote_ties tests/test_werewolf_runner.py::test_sheriff_badge_is_lost_when_no_candidates_remain_after_withdraw tests/test_werewolf_runner.py::test_sheriff_badge_is_lost_when_all_players_run_and_multiple_candidates_remain -q
```

Expected: selected tests pass.

- [ ] **Step 11: 提交**

Run:

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: implement sheriff election flow"
```

Expected: commit succeeds.

## Task 4: 首夜 pending 死亡和警徽处理

**Files:**
- Modify `apps/api/app/werewolf/engine.py`
- Modify `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: 写首夜死亡警长移交失败测试**

Add this test:

```python
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
    new_sheriff = next(name for name in active_players if name != dead_sheriff and players_by_name[name].role != "狼人")
    provider = FirstNightSheriffDeathProvider(
        remove_target=dead_sheriff,
        candidates={dead_sheriff},
        badge_choice=new_sheriff,
    )
    engine = GameEngine(state=state, provider=provider, max_rounds=1, rule_set=rule_set)

    logs = engine.run()
    round_state = state.rounds[0]

    assert round_state.sheriff_elected == dead_sheriff
    assert round_state.night_deaths[0].player == dead_sheriff
    assert dead_sheriff not in [player.name for player in state.players if player.is_sheriff]
    assert state.sheriff == new_sheriff
    assert players_by_name[new_sheriff].is_sheriff is True
    assert round_state.sheriff_badge_target == new_sheriff
    assert round_state.sheriff_badge_lost is False
    assert logs[0].sheriff_badge is not None
```

Add provider:

```python
class FirstNightSheriffDeathProvider(SheriffFlowProvider):
    def __init__(self, *, remove_target: str, candidates: set[str], badge_choice: str) -> None:
        super().__init__(
            candidates=candidates,
            sheriff_vote_targets={},
            badge_choice=badge_choice,
        )
        self.remove_target = remove_target

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
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
```

- [ ] **Step 2: 写 pending 死亡不能接警徽失败测试**

Add this test:

```python
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
        name for name in active_players
        if name != dead_sheriff and players_by_name[name].role not in {"狼人", "女巫"}
    )
    provider = FirstNightPoisonBadgeProvider(
        remove_target=dead_sheriff,
        poison_choice=poisoned_player,
        candidates={dead_sheriff},
        badge_choice=poisoned_player,
    )
    engine = GameEngine(state=state, provider=provider, max_rounds=1, rule_set=rule_set)

    engine.run()
    round_state = state.rounds[0]

    assert {death.player for death in round_state.night_deaths} >= {dead_sheriff, poisoned_player}
    assert round_state.sheriff_badge_target != poisoned_player
    assert state.sheriff != poisoned_player
    assert round_state.sheriff_badge_lost is True
```

Add provider:

```python
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
```

- [ ] **Step 3: 运行失败测试**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_first_night_dead_elected_sheriff_transfers_badge_after_death_announcement tests/test_werewolf_runner.py::test_first_night_badge_cannot_transfer_to_pending_dead_player -q
```

Expected: fails because night deaths are currently removed before sheriff election.

- [ ] **Step 4: 拆分夜晚死亡计算与公布**

In `apps/api/app/werewolf/engine.py`, replace `_resolve_night_deaths` with helpers:

```python
    def _pending_night_deaths(self, round_state: RoundState, active_players: list[str]) -> list[DeathEvent]:
        deaths: list[DeathEvent] = []
        if (
            round_state.attacked
            and round_state.attacked != round_state.protected
            and round_state.attacked != round_state.saved_by_witch
        ):
            deaths.append(DeathEvent(round_state.attacked, "werewolf_attack", "狼人"))

        witch_name = self._active_player_for_role(WITCH, active_players)
        if round_state.poisoned:
            deaths.append(DeathEvent(round_state.poisoned, "witch_poison", witch_name or None))

        seen: set[str] = set()
        unique_deaths: list[DeathEvent] = []
        for death in deaths:
            if death.player not in seen:
                seen.add(death.player)
                unique_deaths.append(death)
        return unique_deaths

    def _announce_night_deaths(
        self,
        deaths: list[DeathEvent],
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        pending_night_deaths = {death.player for death in deaths}
        for death in deaths:
            round_state.night_deaths.append(death)
            self._remove_player(active_players, death.player)
            self._maybe_run_hunter_shot(
                dead_player=death.player,
                death_cause=death.cause,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="night",
                excluded_shot_targets=pending_night_deaths,
                excluded_badge_targets=pending_night_deaths,
            )
            self._maybe_transfer_sheriff_badge(
                dead_player=death.player,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="night",
                excluded_badge_targets=pending_night_deaths,
            )
        round_state.eliminated = round_state.night_deaths[0].player if round_state.night_deaths else None
```

- [ ] **Step 5: 让首日警长局延迟公布死亡**

In `_run_night_phase`, replace:

```python
        self._resolve_night_deaths(round_state, round_log, active_players)
```

with:

```python
        pending_deaths = self._pending_night_deaths(round_state, active_players)
        should_defer_deaths = (
            self.rule_set.sheriff_enabled and round_state.number == 1 and not self.state.sheriff
        )
        if not should_defer_deaths:
            self._announce_night_deaths(pending_deaths, round_state, round_log, active_players)
```

Then return `pending_deaths` from `_run_night_phase`:

```python
    def _run_night_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> list[DeathEvent]:
```

End `_run_night_phase` with:

```python
        return pending_deaths
```

In `run`, replace:

```python
            self._run_night_phase(round_state, round_log, active_players)
```

with:

```python
            pending_deaths = self._run_night_phase(round_state, round_log, active_players)
```

Before winner check after night, only check winner immediately when no death deferral occurred:

```python
            if round_state.night_deaths:
                self.state.winner = self._get_winner(active_players)
                if self.state.winner:
                    round_state.success = True
                    break
```

In `_run_day_phase`, add parameter:

```python
        pending_night_deaths: list[DeathEvent] | None = None,
```

After `_run_sheriff_election_if_needed(...)`, add:

```python
        if pending_night_deaths:
            self._announce_night_deaths(pending_night_deaths, round_state, round_log, active_players)
            if round_state.night_deaths:
                eliminated_names = "、".join(death.player for death in round_state.night_deaths)
                self._announce(active_players, f"第{round_state.number}轮：夜晚，{eliminated_names}出局。")
                self._publish_state_updated(
                    round_state=round_state,
                    phase="night",
                    payload={
                        "attacked": round_state.attacked,
                        "eliminated": round_state.eliminated,
                        "protected": round_state.protected,
                        "investigated": round_state.investigated,
                        "saved_by_witch": round_state.saved_by_witch,
                        "poisoned": round_state.poisoned,
                        "night_deaths": [death.to_dict() for death in round_state.night_deaths],
                        "active_players": active_players.copy(),
                    },
                )
```

In `run`, pass pending deaths:

```python
            self._run_day_phase(round_state, round_log, active_players, pending_deaths)
```

- [ ] **Step 6: 确保死亡后无警长时跳过发言方向**

In `_speech_order`, keep existing guard:

```python
            and self.state.sheriff
            and self.state.sheriff in active_players
```

Add assertion in `test_first_night_dead_elected_sheriff_transfers_badge_after_death_announcement`:

```python
    assert round_state.speech_order[-1] == new_sheriff
```

- [ ] **Step 7: 运行测试确认通过**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_first_night_dead_elected_sheriff_transfers_badge_after_death_announcement tests/test_werewolf_runner.py::test_first_night_badge_cannot_transfer_to_pending_dead_player -q
```

Expected: both tests pass.

- [ ] **Step 8: 运行后端警长相关测试**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py -q
```

Expected: all runner tests pass.

- [ ] **Step 9: 提交**

Run:

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: defer first night deaths until sheriff election"
```

Expected: commit succeeds.

## Task 5: 前端类型与 adapter

**Files:**
- Modify `apps/web/src/features/games/types.ts`
- Modify `apps/web/src/features/games/api/adapters.ts`
- Modify `apps/web/src/features/games/api/adapters.test.ts`
- Modify `apps/web/src/features/games/components/DebugPanel.tsx`

- [ ] **Step 1: 写 adapter 失败测试**

In `apps/web/src/features/games/api/adapters.test.ts`, add:

```ts
it("normalizes full sheriff election fields", () => {
  const replay = normalizeGameReplay({
    ...rawReplay,
    state: {
      ...rawReplay.state,
      rounds: [
        {
          ...rawReplay.state.rounds[0],
          sheriff_candidates: ["Alice", "Bob"],
          sheriff_speeches: [{ speaker: "Alice", message: "我上警。" }],
          sheriff_withdrawn: ["Bob"],
          sheriff_final_candidates: ["Alice"],
          sheriff_voters: ["Cora", "Dan"],
          sheriff_votes: { Cora: "Alice", Dan: "Alice" },
          sheriff_pk_candidates: [],
          sheriff_pk_speeches: [],
          sheriff_runoff_votes: {},
          sheriff_elected: "Alice",
          sheriff_badge_lost: false,
        },
      ],
    },
  });

  const round = replay.rounds[0];
  expect(round.sheriff_candidates).toEqual(["Alice", "Bob"]);
  expect(round.sheriff_speeches).toEqual([{ speaker: "Alice", message: "我上警。" }]);
  expect(round.sheriff_withdrawn).toEqual(["Bob"]);
  expect(round.sheriff_final_candidates).toEqual(["Alice"]);
  expect(round.sheriff_voters).toEqual(["Cora", "Dan"]);
  expect(round.sheriff_votes).toEqual({ Cora: "Alice", Dan: "Alice" });
  expect(round.sheriff_elected).toBe("Alice");
});
```

Update the existing "creates debug items for sheriff actions" test to include `sheriff_speech`, `sheriff_withdraw`, `sheriff_pk_speech`, and `sheriff_runoff_votes`, and expect titles:

```ts
[
  "上警选择",
  "警上发言",
  "退水选择",
  "警下投票",
  "PK 发言",
  "警下二轮投票",
  "发言方向",
  "警徽处理",
]
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/api/adapters.test.ts
```

Expected: fails because types and adapter fields are missing.

- [ ] **Step 3: 更新类型**

In `apps/web/src/features/games/types.ts`, add:

```ts
export type SpeechEntry = {
  speaker: string;
  message: string;
};
```

In `RawRoundLog`, add optional fields:

```ts
  sheriff_speech?: RawActionLog[];
  sheriff_withdraw?: RawActionLog[];
  sheriff_pk_speech?: RawActionLog[];
  sheriff_runoff_votes?: RawActionLog[];
```

In `RawRoundState`, add optional fields:

```ts
  sheriff_speeches?: SpeechEntry[];
  sheriff_withdrawn?: string[];
  sheriff_final_candidates?: string[];
  sheriff_voters?: string[];
  sheriff_pk_candidates?: string[];
  sheriff_pk_speeches?: SpeechEntry[];
  sheriff_runoff_votes?: Record<string, string>;
  sheriff_elected?: string | null;
```

Add these names to the `GameRound` omit list:

```ts
  | "sheriff_speeches"
  | "sheriff_withdrawn"
  | "sheriff_final_candidates"
  | "sheriff_voters"
  | "sheriff_pk_candidates"
  | "sheriff_pk_speeches"
  | "sheriff_runoff_votes"
  | "sheriff_elected"
```

Add normalized fields to `GameRound`:

```ts
  sheriff_speeches: SpeechEntry[];
  sheriff_withdrawn: string[];
  sheriff_final_candidates: string[];
  sheriff_voters: string[];
  sheriff_pk_candidates: string[];
  sheriff_pk_speeches: SpeechEntry[];
  sheriff_runoff_votes: Record<string, string>;
  sheriff_elected: string | null;
```

- [ ] **Step 4: 更新 adapter normalize 和 debug 标题**

In `apps/web/src/features/games/api/adapters.ts`, update `ACTION_TITLES`:

```ts
  sheriff_run: "上警选择",
  sheriff_speech: "警上发言",
  sheriff_withdraw: "退水选择",
  sheriff_vote: "警下投票",
  sheriff_pk_speech: "PK 发言",
  sheriff_runoff_vote: "警下二轮投票",
  speech_order: "发言方向",
  sheriff_badge: "警徽处理",
```

In `normalizeRound`, add fields:

```ts
    sheriff_speeches: round.sheriff_speeches ?? [],
    sheriff_withdrawn: round.sheriff_withdrawn ?? [],
    sheriff_final_candidates: round.sheriff_final_candidates ?? [],
    sheriff_voters: round.sheriff_voters ?? [],
    sheriff_pk_candidates: round.sheriff_pk_candidates ?? [],
    sheriff_pk_speeches: round.sheriff_pk_speeches ?? [],
    sheriff_runoff_votes: round.sheriff_runoff_votes ?? {},
    sheriff_elected: round.sheriff_elected ?? null,
```

In `debugItemsFromRound`, insert after `sheriff_run`:

```ts
  (round.sheriff_speech ?? []).forEach((action, index) => {
    pushAction(items, round.number, "day", `day-sheriff-speech-${index}`, action);
  });
  (round.sheriff_withdraw ?? []).forEach((action, index) => {
    pushAction(items, round.number, "day", `day-sheriff-withdraw-${index}`, action);
  });
```

Insert after `sheriff_votes`:

```ts
  (round.sheriff_pk_speech ?? []).forEach((action, index) => {
    pushAction(items, round.number, "day", `day-sheriff-pk-speech-${index}`, action);
  });
  (round.sheriff_runoff_votes ?? []).forEach((action, index) => {
    pushAction(items, round.number, "day", `day-sheriff-runoff-vote-${index}`, action);
  });
```

- [ ] **Step 5: 更新 DebugPanel 字段标签**

In `apps/web/src/features/games/components/DebugPanel.tsx`, extend `PARSED_FIELD_LABELS`:

```ts
  run: "上警选择",
  withdraw: "退水选择",
  sheriff_vote: "警长投票对象",
  speech_order: "发言方向",
  badge: "警徽处理",
```

- [ ] **Step 6: 运行测试确认通过**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/api/adapters.test.ts
```

Expected: adapters tests pass.

- [ ] **Step 7: 提交**

Run:

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/api/adapters.ts apps/web/src/features/games/api/adapters.test.ts apps/web/src/features/games/components/DebugPanel.tsx
git commit -m "feat: normalize sheriff election replay fields"
```

Expected: commit succeeds.

## Task 6: 前端警长竞选展示

**Files:**
- Create `apps/web/src/features/games/components/SheriffElectionPanel.tsx`
- Create `apps/web/src/features/games/components/SheriffElectionPanel.test.tsx`
- Modify `apps/web/src/features/games/components/DayPhase.tsx`
- Modify `apps/web/src/features/games/components/DayPhase.test.tsx`

- [ ] **Step 1: 写 `SheriffElectionPanel` 失败测试**

Create `apps/web/src/features/games/components/SheriffElectionPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GameRound } from "../types";
import { SheriffElectionPanel } from "./SheriffElectionPanel";

const round = {
  number: 1,
  players: ["Alice", "Bob", "Cora", "Dan"],
  attacked: null,
  eliminated: null,
  protected: null,
  investigated: null,
  exiled: null,
  saved_by_witch: null,
  poisoned: null,
  hunter_shot: null,
  idiot_revealed: null,
  night_deaths: [],
  day_deaths: [],
  debate: [],
  bids: [],
  bidGroups: [],
  votes: [],
  voteTally: [],
  voteCount: 0,
  voteMajorityThreshold: null,
  sheriff: "Alice",
  sheriff_candidates: ["Alice", "Bob"],
  sheriff_speeches: [
    { speaker: "Alice", message: "我上警争警徽。" },
    { speaker: "Bob", message: "我也上警。" },
  ],
  sheriff_withdrawn: ["Bob"],
  sheriff_final_candidates: ["Alice"],
  sheriff_voters: ["Cora", "Dan"],
  sheriff_votes: { Cora: "Alice", Dan: "Alice" },
  sheriff_pk_candidates: [],
  sheriff_pk_speeches: [],
  sheriff_runoff_votes: {},
  sheriff_elected: "Alice",
  speech_order: ["Cora", "Dan", "Bob", "Alice"],
  speech_order_choice: "警左发言",
  vote_weights: {},
  sheriff_badge_target: null,
  sheriff_badge_lost: false,
  summaries: {},
  success: true,
} satisfies GameRound;

describe("SheriffElectionPanel", () => {
  it("renders sheriff election groups, speeches, withdrawals, votes, and result", () => {
    render(<SheriffElectionPanel round={round} />);

    expect(screen.getByText("警长竞选")).toBeInTheDocument();
    expect(screen.getByText("上警：Alice、Bob")).toBeInTheDocument();
    expect(screen.getByText("警下：Cora、Dan")).toBeInTheDocument();
    expect(screen.getByText("Alice：我上警争警徽。")).toBeInTheDocument();
    expect(screen.getByText("退水：Bob")).toBeInTheDocument();
    expect(screen.getByText("最终候选：Alice")).toBeInTheDocument();
    expect(screen.getByText("Cora -> Alice")).toBeInTheDocument();
    expect(screen.getByText("Dan -> Alice")).toBeInTheDocument();
    expect(screen.getByText("Alice 当选警长")).toBeInTheDocument();
    expect(screen.getByText("发言方向：警左发言")).toBeInTheDocument();
    expect(screen.getByText("Cora -> Dan -> Bob -> Alice")).toBeInTheDocument();
  });

  it("renders badge lost and runoff details", () => {
    render(
      <SheriffElectionPanel
        round={{
          ...round,
          sheriff: null,
          sheriff_final_candidates: ["Alice", "Bob"],
          sheriff_pk_candidates: ["Alice", "Bob"],
          sheriff_pk_speeches: [{ speaker: "Bob", message: "PK 拉票。" }],
          sheriff_runoff_votes: { Cora: "Alice", Dan: "Bob" },
          sheriff_elected: null,
          sheriff_badge_lost: true,
          speech_order_choice: null,
        }}
      />,
    );

    expect(screen.getByText("PK 候选：Alice、Bob")).toBeInTheDocument();
    expect(screen.getByText("Bob：PK 拉票。")).toBeInTheDocument();
    expect(screen.getByText("二轮投票")).toBeInTheDocument();
    expect(screen.getByText("警徽流失")).toBeInTheDocument();
    expect(screen.getByText("无警长，按座次顺序发言")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/SheriffElectionPanel.test.tsx
```

Expected: fails because component does not exist.

- [ ] **Step 3: 创建 `SheriffElectionPanel`**

Create `apps/web/src/features/games/components/SheriffElectionPanel.tsx`:

```tsx
import type { GameRound, SpeechEntry } from "../types";

type SheriffElectionPanelProps = {
  round: GameRound;
};

export function SheriffElectionPanel({ round }: SheriffElectionPanelProps) {
  const hasElection =
    round.sheriff_candidates.length > 0 ||
    round.sheriff_voters.length > 0 ||
    round.sheriff_speeches.length > 0 ||
    round.sheriff_badge_lost ||
    Boolean(round.sheriff_elected);

  if (!hasElection) {
    return null;
  }

  return (
    <>
      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          警长竞选
        </h4>
        <div className="mt-2 space-y-2 text-sm text-slate-700">
          <p>上警：{formatList(round.sheriff_candidates)}</p>
          <p>警下：{formatList(round.sheriff_voters)}</p>
          <SpeechList speeches={round.sheriff_speeches} />
          <p>退水：{formatList(round.sheriff_withdrawn)}</p>
          <p>最终候选：{formatList(round.sheriff_final_candidates)}</p>
          <VoteList title="警下投票" votes={round.sheriff_votes} />
          {round.sheriff_pk_candidates.length > 0 ? (
            <>
              <p>PK 候选：{formatList(round.sheriff_pk_candidates)}</p>
              <SpeechList speeches={round.sheriff_pk_speeches} />
              <VoteList title="二轮投票" votes={round.sheriff_runoff_votes} />
            </>
          ) : null}
          <p className="font-medium text-slate-950">
            {round.sheriff_elected
              ? `${round.sheriff_elected} 当选警长`
              : round.sheriff_badge_lost
                ? "警徽流失"
                : "未产生警长"}
          </p>
        </div>
      </section>

      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          警徽状态
        </h4>
        <div className="mt-2 space-y-1 text-sm text-slate-700">
          <p>当前警长：{round.sheriff ?? "无"}</p>
          {round.sheriff_badge_target ? (
            <p>警徽移交：{round.sheriff_badge_target}</p>
          ) : null}
          {round.sheriff_badge_lost ? <p>警徽流失</p> : null}
        </div>
      </section>

      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          发言方向
        </h4>
        <div className="mt-2 space-y-1 text-sm text-slate-700">
          <p>
            {round.speech_order_choice
              ? `发言方向：${round.speech_order_choice}`
              : "无警长，按座次顺序发言"}
          </p>
          {round.speech_order.length > 0 ? (
            <p>{round.speech_order.join(" -> ")}</p>
          ) : null}
        </div>
      </section>
    </>
  );
}

function SpeechList({ speeches }: { speeches: SpeechEntry[] }) {
  if (speeches.length === 0) {
    return null;
  }

  return (
    <div className="space-y-1">
      {speeches.map((speech, index) => (
        <p
          className="break-words rounded border border-slate-200 bg-slate-50 px-3 py-2"
          key={`${speech.speaker}-${index}`}
        >
          {speech.speaker}：{speech.message}
        </p>
      ))}
    </div>
  );
}

function VoteList({
  title,
  votes,
}: {
  title: string;
  votes: Record<string, string>;
}) {
  const entries = Object.entries(votes);
  if (entries.length === 0) {
    return null;
  }

  return (
    <div>
      <p className="font-medium text-slate-950">{title}</p>
      <div className="mt-1 space-y-1">
        {entries.map(([voter, target]) => (
          <p key={voter}>
            {voter} -&gt; {target}
          </p>
        ))}
      </div>
    </div>
  );
}

function formatList(items: string[]) {
  return items.length > 0 ? items.join("、") : "无";
}
```

- [ ] **Step 4: 接入 `DayPhase`**

In `apps/web/src/features/games/components/DayPhase.tsx`, import:

```tsx
import { SheriffElectionPanel } from "./SheriffElectionPanel";
```

Replace the existing speech-order section:

```tsx
      {round.speech_order.length > 0 ? (
        <section className="mt-4">
          <h4 className="text-xs font-semibold uppercase text-slate-500">
            发言顺序
          </h4>
          <p className="mt-2 text-sm text-slate-700">
            {round.speech_order.join(" -> ")}
          </p>
        </section>
      ) : null}
```

with:

```tsx
      <SheriffElectionPanel round={round} />
```

Change the heading for formal debate:

```tsx
          白天发言
```

Change the heading for vote:

```tsx
          放逐投票
```

- [ ] **Step 5: 更新 `DayPhase.test.tsx` baseRound**

Add these fields to `baseRound`:

```ts
  sheriff_speeches: [],
  sheriff_withdrawn: [],
  sheriff_final_candidates: [],
  sheriff_voters: [],
  sheriff_pk_candidates: [],
  sheriff_pk_speeches: [],
  sheriff_runoff_votes: {},
  sheriff_elected: null,
```

Update "hides bidding for ordered speech rounds and shows speech order" to expect `白天发言` and not rely on the old standalone `发言顺序` heading:

```ts
    expect(screen.getByText("白天发言")).toBeInTheDocument();
```

Add a new test:

```tsx
  it("renders sheriff election panel inside day phase", () => {
    render(
      <DayPhase
        round={{
          ...baseRound,
          hunter_shot: null,
          idiot_revealed: null,
          day_deaths: [],
          sheriff_candidates: ["Alice"],
          sheriff_speeches: [{ speaker: "Alice", message: "我上警。" }],
          sheriff_final_candidates: ["Alice"],
          sheriff_voters: ["Bob"],
          sheriff_elected: "Alice",
          sheriff: "Alice",
          speech_order_choice: "警左发言",
          speech_order: ["Bob", "Alice"],
        }}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("警长竞选")).toBeInTheDocument();
    expect(screen.getByText("Alice 当选警长")).toBeInTheDocument();
    expect(screen.getByText("Bob -> Alice")).toBeInTheDocument();
  });
```

- [ ] **Step 6: 运行组件测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/SheriffElectionPanel.test.tsx src/features/games/components/DayPhase.test.tsx
```

Expected: component tests pass.

- [ ] **Step 7: 提交**

Run:

```bash
git add apps/web/src/features/games/components/SheriffElectionPanel.tsx apps/web/src/features/games/components/SheriffElectionPanel.test.tsx apps/web/src/features/games/components/DayPhase.tsx apps/web/src/features/games/components/DayPhase.test.tsx
git commit -m "feat: display sheriff election timeline"
```

Expected: commit succeeds.

## Task 7: 全量验证和收尾

**Files:**
- Modify only files needed to fix failures found by verification.

- [ ] **Step 1: 运行后端测试**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: 运行后端 lint**

Run:

```bash
cd apps/api
.venv/bin/python -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 3: 运行前端测试**

Run:

```bash
pnpm --dir apps/web test -- --run
```

Expected: all Vitest suites pass.

- [ ] **Step 4: 运行前端 build**

Run:

```bash
pnpm --dir apps/web build
```

Expected: build completes successfully.

- [ ] **Step 5: 运行前端 lint 并记录结果**

Run:

```bash
pnpm --dir apps/web lint
```

Expected: the new or touched sheriff-election files have no lint errors. If lint still reports the known pre-existing errors in `useGameRunEvents.ts`, `useLiveDirector.ts`, or `LiveGamePage.tsx`, do not change those files in this task; record them in the final status.

- [ ] **Step 6: 检查 diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: only intended files are modified.

- [ ] **Step 7: 修复验证发现的本任务相关问题**

If a command fails in a file touched by this implementation, fix that file and rerun the failing command. Use a focused commit:

```bash
git add <fixed-files>
git commit -m "fix: stabilize sheriff election flow"
```

Expected: verification commands from Steps 1-5 pass or only show the pre-existing frontend lint issues listed in Step 5.

## Self-Review Checklist

- Spec coverage:
  - 警上/警下权限由 Task 3 覆盖。
  - 退水不返还警长投票权由 Task 3 覆盖。
  - 平票 PK 与二轮投票由 Task 3 覆盖。
  - 首夜死讯公布前竞选和死亡警长警徽处理由 Task 4 覆盖。
  - 前端结构化展示和 debug 标题由 Task 5、Task 6 覆盖。
- Placeholder scan: This plan contains no unresolved placeholder sections.
- Type consistency:
  - Backend state fields use `sheriff_speeches`, `sheriff_withdrawn`, `sheriff_final_candidates`, `sheriff_voters`, `sheriff_pk_candidates`, `sheriff_pk_speeches`, `sheriff_runoff_votes`, `sheriff_elected`.
  - Frontend fields use the same snake_case names to match API payloads.
  - Log fields use `sheriff_speech`, `sheriff_withdraw`, `sheriff_pk_speech`, `sheriff_runoff_votes`.
