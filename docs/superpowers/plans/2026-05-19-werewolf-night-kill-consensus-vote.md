# Werewolf Night Kill Consensus Vote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-wolf night kill selection with private wolf discussion plus repeated unanimous wolf voting.

**Architecture:** Keep the existing night death pipeline intact by changing only how `round_state.attacked` is produced. Add backend model/log fields for wolf discussion and vote rounds, add two secret model actions, and route all multi-wolf night kills through a focused consensus helper. Frontend replay normalization and debug views read the new fields while legacy `attacked`, `night_deaths`, and `eliminate` remain compatible.

**Tech Stack:** Python dataclasses and pytest in `apps/api`; React/TypeScript, Vitest, and existing replay adapters in `apps/web`.

---

## File Structure

- Modify `apps/api/app/werewolf/rules.py`: add action constants for `werewolf_discuss` and `werewolf_kill_vote`.
- Modify `apps/api/app/werewolf/models.py`: serialize `RoundState.werewolf_discussion`, `RoundState.werewolf_vote_rounds`, `RoundLog.werewolf_discussion`, and `RoundLog.werewolf_votes`.
- Modify `apps/api/app/werewolf/prompts_zh.py`: add schemas, result fields, field labels, and Chinese instructions for the two new actions.
- Modify `apps/api/app/werewolf/streaming.py`: mark the new actions as secret night actions with generic waiting text.
- Modify `apps/api/app/werewolf/engine.py`: add the consensus helper, use it from `_run_night_phase()`, and mask public live actors for secret wolf actions.
- Modify `apps/api/tests/test_werewolf_lm.py`: cover prompt schemas and instructions.
- Modify `apps/api/tests/test_werewolf_runner.py`: cover consensus voting, repeated revotes, protection/witch/hunter compatibility, serialization, and the protection threshold.
- Modify `apps/web/src/features/games/types.ts`: add replay types for discussion and vote rounds.
- Modify `apps/web/src/features/games/api/adapters.ts`: normalize new round fields and expose debug items for wolf discussion/votes.
- Modify `apps/web/src/features/games/api/adapters.test.ts`: cover replay normalization and debug items.
- Modify `apps/web/src/features/games/liveLabels.ts`: add labels for the new actions.
- Modify `apps/web/src/features/games/liveGodView.ts`: do not expose wolf discussion/vote action lines from public events.
- Modify `apps/web/src/features/games/liveGodView.test.ts`: lock the no-leak behavior.

---

### Task 1: Backend Action Surface And Serialization

**Files:**
- Modify: `apps/api/app/werewolf/rules.py`
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/prompts_zh.py`
- Modify: `apps/api/app/werewolf/streaming.py`
- Test: `apps/api/tests/test_werewolf_lm.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing prompt tests**

Append these tests to `apps/api/tests/test_werewolf_lm.py`:

```python
def test_build_prompt_supports_werewolf_discuss_action() -> None:
    prompt, schema = build_prompt(
        "werewolf_discuss",
        _world_state_for_special_action("狼人", "Alice、Bob"),
    )

    assert schema["required"] == ["reasoning", "target", "message"]
    assert "狼人夜晚私密沟通" in prompt
    assert "输出字段 reasoning、target 和 message" in prompt


def test_build_prompt_supports_werewolf_kill_vote_action() -> None:
    prompt, schema = build_prompt(
        "werewolf_kill_vote",
        {
            **_world_state_for_special_action("狼人", "Alice、Bob"),
            "werewolf_discussion": ["Wolf A 建议袭击 Alice。"],
            "werewolf_previous_vote_round": "第1轮票型：Wolf A -> Alice；Wolf B -> Bob。",
            "werewolf_kill_vote_round": 2,
        },
    )

    assert schema["required"] == ["reasoning", "target"]
    assert "狼人夜晚狼刀投票" in prompt
    assert "当前是第 2 轮狼刀投票" in prompt
    assert "输出字段 reasoning 和 target" in prompt
```

- [ ] **Step 2: Write failing model serialization tests**

Append these tests to `apps/api/tests/test_werewolf_runner.py`:

```python
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
```

- [ ] **Step 3: Run the failing tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_build_prompt_supports_werewolf_discuss_action \
  tests/test_werewolf_lm.py::test_build_prompt_supports_werewolf_kill_vote_action \
  tests/test_werewolf_runner.py::test_round_state_serializes_werewolf_consensus_fields \
  tests/test_werewolf_runner.py::test_round_log_serializes_werewolf_consensus_logs \
  -q
```

Expected: FAIL because the new actions and fields do not exist.

- [ ] **Step 4: Add backend constants and dataclass fields**

In `apps/api/app/werewolf/rules.py`, add constants next to `ACTION_REMOVE`:

```python
ACTION_WEREWOLF_DISCUSS = "werewolf_discuss"
ACTION_WEREWOLF_KILL_VOTE = "werewolf_kill_vote"
```

In `apps/api/app/werewolf/models.py`, add fields to `RoundState` after `night_deaths`:

```python
    werewolf_discussion: list[dict[str, Any]] = field(default_factory=list)
    werewolf_vote_rounds: list[dict[str, Any]] = field(default_factory=list)
```

Add the fields to `RoundState.to_dict()` after `night_deaths`:

```python
            "werewolf_discussion": self.werewolf_discussion,
            "werewolf_vote_rounds": self.werewolf_vote_rounds,
```

Add fields to `RoundLog` after `hunter_shoot`:

```python
    werewolf_discussion: list[ActionLog] = field(default_factory=list)
    werewolf_votes: list[list[ActionLog]] = field(default_factory=list)
```

Add the fields to `RoundLog.to_dict()` after `hunter_shoot`:

```python
            "werewolf_discussion": [log.to_dict() for log in self.werewolf_discussion],
            "werewolf_votes": [
                [log.to_dict() for log in vote_logs] for vote_logs in self.werewolf_votes
            ],
```

- [ ] **Step 5: Add prompt schemas and instructions**

In `apps/api/app/werewolf/prompts_zh.py`, add schemas after `"remove"`:

```python
    "werewolf_discuss": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "target": {"type": "string"},
            "message": {"type": "string"},
        },
        "required": ["reasoning", "target", "message"],
    },
    "werewolf_kill_vote": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "target": {"type": "string"}},
        "required": ["reasoning", "target"],
    },
```

Add result fields:

```python
    "werewolf_discuss": "target",
    "werewolf_kill_vote": "target",
```

Add field label:

```python
    "target": "目标",
    "message": "私密沟通",
```

Add instruction branches before the existing `if action == "remove"` branch:

```python
    if action == "werewolf_discuss":
        discussion = world_state.get("werewolf_discussion") or []
        previous_vote = world_state.get("werewolf_previous_vote_round") or "暂无。"
        vote_round = int(world_state.get("werewolf_kill_vote_round") or 1)
        discussion_text = "\n".join(f"- {line}" for line in discussion) if discussion else "暂无。"
        return (
            "行动：狼人夜晚私密沟通。\n"
            f"当前是第 {vote_round} 轮狼刀投票前的沟通。\n"
            f"候选人：{options}。\n"
            f"已有狼人沟通：\n{discussion_text}\n"
            f"上一轮票型：{previous_vote}\n"
            "你必须从候选人中建议一名袭击目标，并用 message 给队友简短说明理由。"
            "这是仅狼人队友可见的信息。避免伤害性措辞，用游戏术语表达。"
            "输出字段 reasoning、target 和 message。"
        )
    if action == "werewolf_kill_vote":
        discussion = world_state.get("werewolf_discussion") or []
        previous_vote = world_state.get("werewolf_previous_vote_round") or "暂无。"
        vote_round = int(world_state.get("werewolf_kill_vote_round") or 1)
        discussion_text = "\n".join(f"- {line}" for line in discussion) if discussion else "暂无。"
        return (
            "行动：狼人夜晚狼刀投票。\n"
            f"当前是第 {vote_round} 轮狼刀投票。\n"
            f"候选人：{options}。\n"
            f"狼人沟通记录：\n{discussion_text}\n"
            f"上一轮票型：{previous_vote}\n"
            "你必须从候选人中选择一名袭击目标。狼刀只有在所有存活狼人投向同一目标时才成立。"
            "请尽量与队友形成一致刀口。输出字段 reasoning 和 target。"
        )
```

- [ ] **Step 6: Add streaming wait text for new secret actions**

In `apps/api/app/werewolf/streaming.py`, add the two action names to the night secret set in `waiting_message_for_action()`:

```python
        "werewolf_discuss",
        "werewolf_kill_vote",
```

- [ ] **Step 7: Run tests for this task**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_build_prompt_supports_werewolf_discuss_action \
  tests/test_werewolf_lm.py::test_build_prompt_supports_werewolf_kill_vote_action \
  tests/test_werewolf_runner.py::test_round_state_serializes_werewolf_consensus_fields \
  tests/test_werewolf_runner.py::test_round_log_serializes_werewolf_consensus_logs \
  -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add \
  apps/api/app/werewolf/rules.py \
  apps/api/app/werewolf/models.py \
  apps/api/app/werewolf/prompts_zh.py \
  apps/api/app/werewolf/streaming.py \
  apps/api/tests/test_werewolf_lm.py \
  apps/api/tests/test_werewolf_runner.py
git commit -m "feat: add werewolf consensus action surface"
```

---

### Task 2: Consensus Vote Engine

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Add a scripted provider for consensus tests**

Add this helper class near the other provider classes in `apps/api/tests/test_werewolf_runner.py`:

```python
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
        del model, temperature
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
```

- [ ] **Step 2: Write failing tests for first-round unanimity and repeated revote**

Append these tests to `apps/api/tests/test_werewolf_runner.py`:

```python
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
        protect_choice=target,
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
```

- [ ] **Step 3: Run the failing tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_werewolf_consensus_first_vote_sets_attacked \
  tests/test_werewolf_runner.py::test_werewolf_consensus_revotes_until_unanimous \
  -q
```

Expected: FAIL because `_run_night_phase()` still uses only `active_wolves[0]`.

- [ ] **Step 4: Import constants and add the protection threshold**

In `apps/api/app/werewolf/engine.py`, extend the rules import:

```python
    ACTION_WEREWOLF_DISCUSS,
    ACTION_WEREWOLF_KILL_VOTE,
```

Add this constant near the existing module constants:

```python
MAX_WEREWOLF_KILL_VOTE_ROUNDS = 8
```

- [ ] **Step 5: Replace the single-wolf representative call in `_run_night_phase()`**

Replace the current `if ACTION_REMOVE ...` block in `_run_night_phase()` with:

```python
        if ACTION_REMOVE in self.rule_set.night_actions:
            round_state.attacked = self._run_werewolf_kill_consensus(
                round_state,
                round_log,
                active_players,
                active_wolves,
                non_wolves,
            )
```

- [ ] **Step 6: Add consensus helper methods**

Add these methods to `GameEngine` before `_run_witch_phase()`:

```python
    def _run_werewolf_kill_consensus(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        active_wolves: list[str],
        non_wolves: list[str],
    ) -> str | None:
        if not active_wolves or not non_wolves:
            return None

        players_by_name = self.state.player_by_name()
        candidates = non_wolves.copy()
        previous_vote_round: dict[str, object] | None = None

        for vote_round in range(1, MAX_WEREWOLF_KILL_VOTE_ROUNDS + 1):
            if len(active_wolves) > 1:
                self._run_werewolf_discussion_round(
                    round_state=round_state,
                    round_log=round_log,
                    active_wolves=active_wolves,
                    candidates=candidates,
                    vote_round=vote_round,
                    previous_vote_round=previous_vote_round,
                )

            votes: dict[str, str] = {}
            vote_logs: list[ActionLog] = []
            discussion_context = self._werewolf_discussion_context(round_state)
            previous_vote_context = self._werewolf_vote_round_context(previous_vote_round)
            for wolf_name in active_wolves:
                wolf = players_by_name[wolf_name]
                target, action_log = self._player_action(
                    player=wolf,
                    action=ACTION_WEREWOLF_KILL_VOTE,
                    options=candidates,
                    result_key="target",
                    round_state=round_state,
                    phase="night",
                    extra_world_state={
                        "werewolf_discussion": discussion_context,
                        "werewolf_previous_vote_round": previous_vote_context,
                        "werewolf_kill_vote_round": vote_round,
                    },
                )
                votes[wolf_name] = str(target)
                vote_logs.append(action_log)

            round_log.werewolf_votes.append(vote_logs)
            vote_record = self._record_werewolf_vote_round(vote_round, candidates, votes)
            round_state.werewolf_vote_rounds.append(vote_record)
            previous_vote_round = vote_record
            if vote_record["unanimous"]:
                round_log.eliminate = vote_logs[0] if vote_logs else None
                return str(vote_record["result"])

            candidates = list(dict.fromkeys(votes.values()))

        raise RuntimeError("狼人夜晚投票未能达成一致")

    def _run_werewolf_discussion_round(
        self,
        *,
        round_state: RoundState,
        round_log: RoundLog,
        active_wolves: list[str],
        candidates: list[str],
        vote_round: int,
        previous_vote_round: dict[str, object] | None,
    ) -> None:
        players_by_name = self.state.player_by_name()
        previous_vote_context = self._werewolf_vote_round_context(previous_vote_round)
        for wolf_name in active_wolves:
            discussion_context = self._werewolf_discussion_context(round_state)
            wolf = players_by_name[wolf_name]
            target, action_log = self._player_action(
                player=wolf,
                action=ACTION_WEREWOLF_DISCUSS,
                options=candidates,
                result_key="target",
                round_state=round_state,
                phase="night",
                extra_world_state={
                    "werewolf_discussion": discussion_context,
                    "werewolf_previous_vote_round": previous_vote_context,
                    "werewolf_kill_vote_round": vote_round,
                },
            )
            message = ""
            if action_log.lm_log.result:
                message = str(action_log.lm_log.result.get("message") or "")
            round_state.werewolf_discussion.append(
                {
                    "round": vote_round,
                    "speaker": wolf.name,
                    "target": str(target),
                    "message": message,
                }
            )
            round_log.werewolf_discussion.append(action_log)

    def _record_werewolf_vote_round(
        self,
        vote_round: int,
        candidates: list[str],
        votes: dict[str, str],
    ) -> dict[str, object]:
        tally: dict[str, int] = {}
        for target in votes.values():
            tally[target] = tally.get(target, 0) + 1
        voted_targets = list(dict.fromkeys(votes.values()))
        unanimous = len(voted_targets) == 1
        return {
            "round": vote_round,
            "candidates": candidates.copy(),
            "votes": votes.copy(),
            "tally": tally,
            "unanimous": unanimous,
            "result": voted_targets[0] if unanimous else None,
        }

    def _werewolf_discussion_context(self, round_state: RoundState) -> list[str]:
        return [
            (
                f"第{entry.get('round')}轮沟通，{entry.get('speaker')}建议"
                f"{entry.get('target')}：{entry.get('message')}"
            )
            for entry in round_state.werewolf_discussion
        ]

    def _werewolf_vote_round_context(
        self,
        vote_round: dict[str, object] | None,
    ) -> str:
        if not vote_round:
            return "暂无。"
        votes = vote_round.get("votes")
        if not isinstance(votes, dict):
            return "暂无。"
        vote_text = "；".join(f"{wolf} -> {target}" for wolf, target in votes.items())
        return f"第{vote_round.get('round')}轮票型：{vote_text}。"
```

- [ ] **Step 7: Run tests for this task**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_werewolf_consensus_first_vote_sets_attacked \
  tests/test_werewolf_runner.py::test_werewolf_consensus_revotes_until_unanimous \
  -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: run night kill by wolf consensus vote"
```

---

### Task 3: Consensus Edge Cases And Existing Night Compatibility

**Files:**
- Modify: `apps/api/tests/test_werewolf_runner.py`
- Modify: `apps/api/app/werewolf/engine.py`

- [ ] **Step 1: Update the shared scripted provider for new wolf vote prompts**

In `ScriptedChineseProvider.complete_json()` in `apps/api/tests/test_werewolf_runner.py`, add these branches before the existing `if '"remove"' in prompt:` branch:

```python
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {"reasoning": "狼人私密沟通。", "target": choice, "message": f"建议袭击{choice}。"},
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps({"reasoning": "狼人统一刀口。", "target": choice}, ensure_ascii=False)
```

- [ ] **Step 2: Add helper branches to custom night providers**

For custom providers that currently return a target from an `if '"remove"' in prompt:` branch, add a matching `if '"target"' in prompt:` branch before it. Use this pattern, replacing `self.remove_target` with the provider's existing night target attribute:

```python
        if '"message"' in prompt and '"target"' in prompt:
            return json.dumps(
                {
                    "reasoning": "测试狼人夜晚沟通。",
                    "target": self.remove_target,
                    "message": f"建议袭击{self.remove_target}。",
                },
                ensure_ascii=False,
            )
        if '"target"' in prompt:
            return json.dumps(
                {"reasoning": "测试狼人投票。", "target": self.remove_target},
                ensure_ascii=False,
            )
```

Apply the same pattern to providers using `self.target`, `self.protected_target`, or a local configured night target. Keep the old `'"remove"'` branches so older tests and logs remain readable.

- [ ] **Step 3: Write failing tests for threshold and third-round convergence**

Append these tests to `apps/api/tests/test_werewolf_runner.py`:

```python
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


def test_werewolf_consensus_errors_when_vote_round_limit_is_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
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
```

- [ ] **Step 4: Write compatibility tests for guard, witch, and hunter**

Append these tests to `apps/api/tests/test_werewolf_runner.py`:

```python
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
```

- [ ] **Step 5: Run edge and compatibility tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_werewolf_consensus_can_converge_on_third_vote \
  tests/test_werewolf_runner.py::test_werewolf_consensus_errors_when_vote_round_limit_is_exceeded \
  tests/test_werewolf_runner.py::test_guard_protects_consensus_werewolf_attack \
  tests/test_werewolf_runner.py::test_witch_can_save_consensus_werewolf_attack \
  tests/test_werewolf_runner.py::test_hunter_shoots_after_consensus_werewolf_attack_death \
  -q
```

Expected: PASS after provider updates and helper behavior are in place.

- [ ] **Step 6: Run existing night-action tests likely touched by provider changes**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_witch_can_save_self_on_first_night_and_cannot_poison_same_night \
  tests/test_werewolf_runner.py::test_witch_poison_creates_night_death \
  tests/test_werewolf_runner.py::test_hunter_shoots_after_werewolf_attack_death \
  tests/test_werewolf_runner.py::test_hunter_cannot_shoot_after_witch_poison_death \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "test: cover wolf consensus night resolution"
```

---

### Task 4: Secret Live Event Privacy

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`
- Modify: `apps/web/src/features/games/liveLabels.ts`
- Modify: `apps/web/src/features/games/liveGodView.ts`
- Modify: `apps/web/src/features/games/liveGodView.test.ts`

- [ ] **Step 1: Write backend privacy test**

Append this test to `apps/api/tests/test_werewolf_runner.py`:

```python
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

    secret_events = [
        event
        for event in event_sink.events
        if event["action"] in {"werewolf_discuss", "werewolf_kill_vote"}
    ]
    assert secret_events
    assert {event["actor"] for event in secret_events} == {None}
    assert all("choice" not in event["payload"] for event in secret_events)
    assert all("options" not in event["payload"] for event in secret_events)
    assert all("result_key" not in event["payload"] for event in secret_events)
```

- [ ] **Step 2: Implement backend actor masking for secret wolf actions**

In `apps/api/app/werewolf/engine.py`, add helper methods near `_publish_state_updated()`:

```python
    def _public_actor_for_action(self, phase: str, action: str, actor: str) -> str | None:
        if phase == "night" and action in {
            ACTION_WEREWOLF_DISCUSS,
            ACTION_WEREWOLF_KILL_VOTE,
        }:
            return None
        return actor

    def _public_payload_for_action_parsed(
        self,
        phase: str,
        action: str,
        action_log: ActionLog,
        visible_result: object,
        options: list[str],
    ) -> dict[str, object]:
        if phase == "night" and action in {
            ACTION_WEREWOLF_DISCUSS,
            ACTION_WEREWOLF_KILL_VOTE,
        }:
            return {
                "message": "狼人正在秘密协商狼刀",
                "options": [],
            }
        return {
            "choice": action_log.choice,
            "result": visible_result,
            "visible_result": visible_result,
            "options": options.copy(),
        }

    def _public_payload_for_action_requested(
        self,
        phase: str,
        action: str,
        options: list[str],
        result_key: str,
    ) -> dict[str, object]:
        if phase == "night" and action in {
            ACTION_WEREWOLF_DISCUSS,
            ACTION_WEREWOLF_KILL_VOTE,
        }:
            return {"message": "狼人正在秘密协商狼刀"}
        return {"options": options.copy(), "result_key": result_key}
```

In `_player_action()`, compute the public actor after `world_state`:

```python
        public_actor = self._public_actor_for_action(phase, action, player.name)
```

Use `public_actor` in the three `_publish()` calls and in `event_context`:

```python
            actor=public_actor,
```

Replace the `action_requested` payload with:

```python
            payload=self._public_payload_for_action_requested(
                phase,
                action,
                options,
                result_key,
            ),
```

Replace the `action_parsed` payload with:

```python
            payload=self._public_payload_for_action_parsed(
                phase,
                action,
                action_log,
                visible_result,
                options,
            ),
```

Keep `ActionLog.actor` as the real player name so replay logs remain complete.

- [ ] **Step 3: Add frontend labels for new actions**

In `apps/web/src/features/games/liveLabels.ts`, add labels to `ACTION_LABELS`:

```ts
  werewolf_discuss: "夜晚沟通",
  werewolf_kill_vote: "狼刀投票",
```

- [ ] **Step 4: Write frontend no-leak test**

Append this test to `apps/web/src/features/games/liveGodView.test.ts`:

```ts
  it("does not expose secret wolf consensus actions from public live events", () => {
    const events = [
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "1号 狼人", role: "werewolf", model: "deepseek-chat" },
            { name: "2号 狼人", role: "werewolf", model: "deepseek-chat" },
            { name: "3号 平民", role: "villager", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: null,
        action: "werewolf_discuss",
        payload: { message: "狼人正在秘密协商狼刀" },
      }),
      event({
        id: 3,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: null,
        action: "werewolf_kill_vote",
        payload: { message: "狼人正在秘密协商狼刀" },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "暗夜古堡");

    expect(state.nightActions).toEqual([]);
  });
```

- [ ] **Step 5: Make live god view ignore new secret action lines**

In `apps/web/src/features/games/liveGodView.ts`, add this guard after `const payload = payloadForEvent(event);` in `collectActionLine()`:

```ts
  if (
    event.phase === "night" &&
    (event.action === "werewolf_discuss" ||
      event.action === "werewolf_kill_vote")
  ) {
    return;
  }
```

- [ ] **Step 6: Run privacy tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_werewolf_consensus_live_events_do_not_publish_wolf_actor \
  -q
pnpm --dir apps/web test -- liveGodView.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  apps/api/app/werewolf/engine.py \
  apps/api/tests/test_werewolf_runner.py \
  apps/web/src/features/games/liveLabels.ts \
  apps/web/src/features/games/liveGodView.ts \
  apps/web/src/features/games/liveGodView.test.ts
git commit -m "fix: keep wolf consensus actions secret in live view"
```

---

### Task 5: Frontend Replay Types And Debug Items

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/api/adapters.ts`
- Modify: `apps/web/src/features/games/api/adapters.test.ts`

- [ ] **Step 1: Write failing adapter test**

Append this test to `apps/web/src/features/games/api/adapters.test.ts`:

```ts
  it("normalizes werewolf consensus fields and debug actions", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      state: {
        ...rawReplay.state,
        rounds: [
          {
            ...rawReplay.state.rounds[0],
            werewolf_discussion: [
              {
                round: 1,
                speaker: "张三",
                target: "李四",
                message: "建议袭击李四。",
              },
            ],
            werewolf_vote_rounds: [
              {
                round: 1,
                candidates: ["李四"],
                votes: { 张三: "李四" },
                tally: { 李四: 1 },
                unanimous: true,
                result: "李四",
              },
            ],
          },
        ],
      },
      logs: [
        {
          ...rawReplay.logs[0],
          werewolf_discussion: [
            {
              actor: "张三",
              action: "werewolf_discuss",
              options: ["李四"],
              choice: "李四",
              lm_log: {
                prompt: "狼人夜晚私密沟通",
                raw_response: '{"target":"李四","message":"建议袭击李四。"}',
                result: { target: "李四", message: "建议袭击李四。" },
              },
            },
          ],
          werewolf_votes: [
            [
              {
                actor: "张三",
                action: "werewolf_kill_vote",
                options: ["李四"],
                choice: "李四",
                lm_log: {
                  prompt: "狼人夜晚狼刀投票",
                  raw_response: '{"target":"李四"}',
                  result: { target: "李四" },
                },
              },
            ],
          ],
        },
      ],
    });

    expect(replay.rounds[0].werewolf_discussion).toEqual([
      {
        round: 1,
        speaker: "张三",
        target: "李四",
        message: "建议袭击李四。",
      },
    ]);
    expect(replay.rounds[0].werewolf_vote_rounds[0]).toMatchObject({
      round: 1,
      unanimous: true,
      result: "李四",
    });
    expect(replay.debugItems).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "round-1-night-werewolf-discussion-0",
          title: "狼人夜聊",
          action: "werewolf_discuss",
        }),
        expect.objectContaining({
          id: "round-1-night-werewolf-vote-0-0",
          title: "狼刀投票",
          action: "werewolf_kill_vote",
        }),
      ]),
    );
  });
```

- [ ] **Step 2: Add TypeScript types**

In `apps/web/src/features/games/types.ts`, add these types after `DeathEvent`:

```ts
export type WerewolfDiscussionEntry = {
  round: number;
  speaker: string;
  target: string;
  message: string;
};

export type WerewolfVoteRound = {
  round: number;
  candidates: string[];
  votes: Record<string, string>;
  tally: Record<string, number>;
  unanimous: boolean;
  result: string | null;
};
```

Add optional fields to `RawRoundLog`:

```ts
  werewolf_discussion?: RawActionLog[];
  werewolf_votes?: RawActionLog[][];
```

Add optional fields to `RawRoundState`:

```ts
  werewolf_discussion?: WerewolfDiscussionEntry[];
  werewolf_vote_rounds?: WerewolfVoteRound[];
```

Add both field names to the `Omit<RawRoundState, ...>` list in `GameRound`:

```ts
  | "werewolf_discussion"
  | "werewolf_vote_rounds"
```

Add normalized fields to `GameRound`:

```ts
  werewolf_discussion: WerewolfDiscussionEntry[];
  werewolf_vote_rounds: WerewolfVoteRound[];
```

- [ ] **Step 3: Normalize new fields**

In `apps/web/src/features/games/api/adapters.ts`, return default arrays from `normalizeRound()`:

```ts
    werewolf_discussion: round.werewolf_discussion ?? [],
    werewolf_vote_rounds: round.werewolf_vote_rounds ?? [],
```

Add action titles:

```ts
  werewolf_discuss: "狼人夜聊",
  werewolf_kill_vote: "狼刀投票",
```

Add debug extraction after existing `night-eliminate` push:

```ts
  (round.werewolf_discussion ?? []).forEach((action, index) => {
    pushAction(
      items,
      round.number,
      "night",
      `night-werewolf-discussion-${index}`,
      action,
    );
  });
  (round.werewolf_votes ?? []).forEach((voteRound, roundIndex) => {
    voteRound.forEach((action, actionIndex) => {
      pushAction(
        items,
        round.number,
        "night",
        `night-werewolf-vote-${roundIndex}-${actionIndex}`,
        action,
      );
    });
  });
```

- [ ] **Step 4: Run adapter tests**

Run:

```bash
pnpm --dir apps/web test -- adapters.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  apps/web/src/features/games/types.ts \
  apps/web/src/features/games/api/adapters.ts \
  apps/web/src/features/games/api/adapters.test.ts
git commit -m "feat: show wolf consensus data in replay debug"
```

---

### Task 6: Full Verification

**Files:**
- Verify: `apps/api/app/werewolf/*`
- Verify: `apps/web/src/features/games/*`

- [ ] **Step 1: Run focused backend suite**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py \
  tests/test_werewolf_runner.py \
  tests/test_werewolf_resume.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run focused frontend suite**

Run:

```bash
pnpm --dir apps/web test -- adapters.test.ts liveGodView.test.ts
```

Expected: PASS.

- [ ] **Step 3: Run broader API regression tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_rules.py \
  tests/test_werewolf_lm.py \
  tests/test_werewolf_runner.py \
  tests/test_games_api.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Run frontend type/build check**

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS.

- [ ] **Step 5: Inspect working tree**

Run:

```bash
git status --short
```

Expected: only intentional changes remain. If the pre-existing files `apps/web/src/features/games/components/VirtualPlayerCardGrid.tsx`, `apps/web/src/features/games/components/VirtualPlayerLibrary.test.tsx`, and `apps/web/src/styles/index.css` are still modified, leave them untouched because they predate this plan.

- [ ] **Step 6: Commit final verification note if any fix was required**

If Step 1-4 required additional code fixes, commit those fixes:

```bash
git add apps/api apps/web
git commit -m "fix: stabilize wolf consensus regressions"
```

If Step 1-4 passed without further code changes, do not create an empty commit.
