# Werewolf Self-Explosion Double-Badge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add daytime werewolf self-explosion with direct night transition and double-explosion sheriff badge loss for the 12-player seer/witch/hunter/idiot rule set.

**Architecture:** Treat self-explosion as a single interrupt hook in `GameEngine`, enabled by rule metadata and surfaced through normal action logs, round state, checkpoints, API adapters, and replay UI. The hook can run at sheriff-election and formal day-speech boundaries; if a wolf explodes, the current day stops, pending first-night deaths are still settled, and the next round begins unless the game already ended. Sheriff badge loss is tracked at game level before a sheriff exists, with the second pre-sheriff explosion consuming the badge.

**Tech Stack:** Python dataclasses + pytest + existing model prompt system; React + TypeScript + Vitest + Testing Library; existing FastAPI replay/checkpoint structures.

---

## File Map

- Modify `apps/api/app/werewolf/rules.py`: add self-explosion action constant and rule-set metadata.
- Modify `apps/api/app/werewolf/prompts_zh.py`: add JSON schema, result label, and Chinese prompt for self-explosion decisions.
- Modify `apps/api/app/werewolf/models.py`: add game, round, and log fields for self-explosion and double-badge state.
- Modify `apps/api/app/werewolf/checkpoint.py`: persist and restore new state/log fields.
- Modify `apps/api/app/werewolf/engine.py`: add the interrupt hook, day-ending flow, double-badge accounting, and resumed sheriff election eligibility.
- Modify `apps/api/tests/test_werewolf_rules.py`: verify metadata and rule text.
- Modify `apps/api/tests/test_werewolf_runner.py`: cover prompt, hook, first bomb, second bomb, post-sheriff bomb, sheriff-wolf bomb, and first-night pending death interaction.
- Modify `apps/api/tests/test_werewolf_resume.py`: cover checkpoint round-trip for new fields.
- Modify `apps/web/src/features/games/types.ts`: add raw and normalized self-explosion fields.
- Modify `apps/web/src/features/games/api/adapters.ts`: normalize fields and create debug items for self-explosion.
- Modify `apps/web/src/features/games/api/adapters.test.ts`: cover new normalization and debug action ordering.
- Modify `apps/web/src/features/games/components/DayPhase.tsx`: show a day-ended-by-self-explosion notice.
- Modify `apps/web/src/features/games/components/DayPhase.test.tsx`: cover early day end display.
- Modify `apps/web/src/features/games/components/SheriffElectionPanel.tsx`: show badge loss reason for double-explosion.
- Modify `apps/web/src/features/games/components/SheriffElectionPanel.test.tsx`: cover first bomb and double-bomb messaging.

## Task 0: Create Implementation Worktree

**Files:**
- No code files changed.

- [ ] **Step 1: Confirm main workspace is clean**

Run:

```bash
git status --short
```

Expected: no output.

- [ ] **Step 2: Create a dedicated worktree**

Run:

```bash
git worktree add .worktrees/werewolf-self-explosion -b codex/werewolf-self-explosion
```

Expected: creates `.worktrees/werewolf-self-explosion` on branch `codex/werewolf-self-explosion`.

- [ ] **Step 3: Enter the worktree**

Run:

```bash
cd .worktrees/werewolf-self-explosion
git branch --show-current
```

Expected:

```text
codex/werewolf-self-explosion
```

## Task 1: Backend Rule Metadata And Prompt

**Files:**
- Modify `apps/api/app/werewolf/rules.py`
- Modify `apps/api/app/werewolf/prompts_zh.py`
- Test `apps/api/tests/test_werewolf_rules.py`
- Test `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing rule metadata tests**

In `apps/api/tests/test_werewolf_rules.py`, extend `test_12_player_rule_set_has_sheriff_flow_metadata` with:

```python
    assert rule.werewolf_self_explosion_enabled is True
    assert rule.sheriff_badge_bomb_policy == "double"
    assert "werewolf_self_explosion" in rule.day_actions
```

In `test_12_player_rule_text_describes_confirmed_table_rules`, add:

```python
    assert "狼人白天公开阶段可以自爆" in text
    assert "采用双爆吞警徽" in text
```

Add a new test:

```python
def test_small_rule_sets_do_not_enable_werewolf_self_explosion() -> None:
    for rule_id in ("classic_8", "starter_6", "social_8"):
        rule = get_rule_set(rule_id)

        assert rule.werewolf_self_explosion_enabled is False
        assert rule.sheriff_badge_bomb_policy == "none"
        assert "werewolf_self_explosion" not in rule.day_actions
```

- [ ] **Step 2: Write failing prompt test**

In `apps/api/tests/test_werewolf_runner.py`, add:

```python
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
```

- [ ] **Step 3: Run failing tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_rules.py::test_12_player_rule_set_has_sheriff_flow_metadata tests/test_werewolf_rules.py::test_12_player_rule_text_describes_confirmed_table_rules tests/test_werewolf_rules.py::test_small_rule_sets_do_not_enable_werewolf_self_explosion tests/test_werewolf_runner.py::test_werewolf_self_explosion_prompt_renders_double_badge_context -q
```

Expected: fail because the new rule fields/action and prompt action are not defined.

- [ ] **Step 4: Implement rule metadata**

In `apps/api/app/werewolf/rules.py`, add the action constant near the other day actions:

```python
ACTION_WEREWOLF_SELF_EXPLOSION = "werewolf_self_explosion"
```

Add fields to `RuleSet`:

```python
    werewolf_self_explosion_enabled: bool = False
    sheriff_badge_bomb_policy: str = "none"
```

Add `ACTION_WEREWOLF_SELF_EXPLOSION` to the 12-player `day_actions` after `ACTION_SHERIFF_RUNOFF_VOTE` and before `ACTION_SPEECH_ORDER`.

Set the 12-player rule fields:

```python
    werewolf_self_explosion_enabled=True,
    sheriff_badge_bomb_policy="double",
```

Add both fields to `rule_set_summary()` and `rule_set_snapshot()`:

```python
        "werewolf_self_explosion_enabled": rule_set.werewolf_self_explosion_enabled,
        "sheriff_badge_bomb_policy": rule_set.sheriff_badge_bomb_policy,
```

In `render_rule_text()`, inside `if rule_set.sheriff_enabled:`, append:

```python
        if rule_set.werewolf_self_explosion_enabled:
            lines.append(
                "狼人白天公开阶段可以自爆，自爆后该狼人公开出局并直接结束当天。"
                "本规则采用双爆吞警徽：警长产生前第一次自爆只中断竞选，第二次自爆才会导致警徽流失。"
            )
```

- [ ] **Step 5: Implement prompt metadata**

In `apps/api/app/werewolf/prompts_zh.py`, add to `SCHEMAS`:

```python
    "werewolf_self_explosion": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "self_explode": {"type": "string"},
        },
        "required": ["reasoning", "self_explode"],
    },
```

Add to `RESULT_FIELD_BY_ACTION`:

```python
    "werewolf_self_explosion": "self_explode",
```

Add to `FIELD_LABELS`:

```python
    "self_explode": "自爆选择",
```

Add to `_render_instruction()` before the role-specific night actions:

```python
    if action == "werewolf_self_explosion":
        stage = world_state.get("self_explosion_stage") or "白天公开阶段"
        sheriff = world_state.get("sheriff")
        bomb_count = int(world_state.get("sheriff_pre_election_bomb_count") or 0)
        badge_context = (
            "当前还没有警长，采用双爆吞警徽规则：第一次警长产生前自爆只会中断警长竞选，"
            "第二次警长产生前自爆会导致警徽流失。"
            if not sheriff
            else f"当前警长是{sheriff}，此时自爆不会吞警徽；若你是警长，则按死亡警长规则处理警徽。"
        )
        return (
            "行动：狼人自爆判断。\n"
            f"当前阶段：{stage}。\n"
            f"警长产生前自爆次数：{bomb_count}。\n"
            f"{badge_context}\n"
            "选择自爆会公开你是狼人、你立刻出局，并让当天直接结束进入夜晚。\n"
            f"候选选项：{options}。\n"
            "请以狼人阵营收益判断，输出字段 reasoning 和 self_explode。"
        )
```

- [ ] **Step 6: Verify tests pass**

Run the command from Step 3 again.

Expected: all listed tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add apps/api/app/werewolf/rules.py apps/api/app/werewolf/prompts_zh.py apps/api/tests/test_werewolf_rules.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: add self explosion rule metadata"
```

## Task 2: Backend State And Checkpoint Serialization

**Files:**
- Modify `apps/api/app/werewolf/models.py`
- Modify `apps/api/app/werewolf/checkpoint.py`
- Test `apps/api/tests/test_werewolf_resume.py`

- [ ] **Step 1: Write failing checkpoint round-trip test**

In `apps/api/tests/test_werewolf_resume.py`, add:

```python
def test_resume_checkpoint_preserves_self_explosion_state(tmp_path) -> None:
    from app.werewolf.checkpoint import game_state_from_dict, round_log_from_dict
    from app.werewolf.models import ActionLog, GameState, LmLog, Player, RoundLog, RoundState

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
    assert restored_round.sheriff_badge_lost_reason == "首爆中断警长竞选"
    assert restored_log.werewolf_self_explosion is not None
    assert restored_log.werewolf_self_explosion.choice == "自爆"
```

- [ ] **Step 2: Run failing test**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_resume.py::test_resume_checkpoint_preserves_self_explosion_state -q
```

Expected: fail because dataclass fields do not exist.

- [ ] **Step 3: Add dataclass fields**

In `apps/api/app/werewolf/models.py`, add to `RoundState`:

```python
    werewolf_self_exploded: str | None = None
    day_ended_by_self_explosion: bool = False
    sheriff_pre_election_bomb_count: int = 0
    sheriff_election_pending: bool = False
    sheriff_badge_lost_reason: str | None = None
```

Add these keys to `RoundState.to_dict()`:

```python
            "werewolf_self_exploded": self.werewolf_self_exploded,
            "day_ended_by_self_explosion": self.day_ended_by_self_explosion,
            "sheriff_pre_election_bomb_count": self.sheriff_pre_election_bomb_count,
            "sheriff_election_pending": self.sheriff_election_pending,
            "sheriff_badge_lost_reason": self.sheriff_badge_lost_reason,
```

Add to `RoundLog`:

```python
    werewolf_self_explosion: ActionLog | None = None
```

Add to `RoundLog.to_dict()`:

```python
            "werewolf_self_explosion": self.werewolf_self_explosion.to_dict() if self.werewolf_self_explosion else None,
```

Add to `GameState`:

```python
    sheriff_pre_election_bomb_count: int = 0
    sheriff_election_pending: bool = False
```

Add to `GameState.to_dict()`:

```python
            "sheriff_pre_election_bomb_count": self.sheriff_pre_election_bomb_count,
            "sheriff_election_pending": self.sheriff_election_pending,
```

- [ ] **Step 4: Restore fields from checkpoint**

In `apps/api/app/werewolf/checkpoint.py`, add to `game_state_from_dict()`:

```python
        sheriff_pre_election_bomb_count=int(data.get("sheriff_pre_election_bomb_count", 0)),
        sheriff_election_pending=bool(data.get("sheriff_election_pending", False)),
```

Add to `round_state_from_dict()`:

```python
        werewolf_self_exploded=data.get("werewolf_self_exploded"),
        day_ended_by_self_explosion=bool(data.get("day_ended_by_self_explosion", False)),
        sheriff_pre_election_bomb_count=int(data.get("sheriff_pre_election_bomb_count", 0)),
        sheriff_election_pending=bool(data.get("sheriff_election_pending", False)),
        sheriff_badge_lost_reason=data.get("sheriff_badge_lost_reason"),
```

Add to `round_log_from_dict()`:

```python
        werewolf_self_explosion=optional_action_log_from_dict(data.get("werewolf_self_explosion")),
```

- [ ] **Step 5: Verify test passes**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add apps/api/app/werewolf/models.py apps/api/app/werewolf/checkpoint.py apps/api/tests/test_werewolf_resume.py
git commit -m "feat: persist self explosion state"
```

## Task 3: Engine Self-Explosion Flow

**Files:**
- Modify `apps/api/app/werewolf/engine.py`
- Test `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Add scripted provider for self-explosion tests**

In `apps/api/tests/test_werewolf_runner.py`, after `SheriffFlowProvider`, add:

```python
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
```

Also add a first-night variant:

```python
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
```

- [ ] **Step 2: Write failing first-bomb test**

Add:

```python
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
```

- [ ] **Step 3: Write failing second-bomb and resumed-election tests**

Add:

```python
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
```

Add:

```python
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
```

- [ ] **Step 4: Write failing post-sheriff and wolf-sheriff tests**

Add:

```python
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
```

- [ ] **Step 5: Run failing engine tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py::test_first_pre_sheriff_self_explosion_ends_day_without_losing_badge tests/test_werewolf_runner.py::test_second_pre_sheriff_self_explosion_loses_badge tests/test_werewolf_runner.py::test_pending_sheriff_election_can_resume_after_first_self_explosion tests/test_werewolf_runner.py::test_first_night_pending_deaths_are_announced_after_self_explosion tests/test_werewolf_runner.py::test_post_sheriff_self_explosion_ends_day_without_consuming_badge tests/test_werewolf_runner.py::test_wolf_sheriff_self_explosion_triggers_badge_handling -q
```

Expected: fail because the engine hook does not exist.

- [ ] **Step 6: Implement engine constants and imports**

In `apps/api/app/werewolf/engine.py`, import `ACTION_WEREWOLF_SELF_EXPLOSION` from `rules.py`.

Add constants near `SHERIFF_BADGE_DESTROY`:

```python
WEREWOLF_SELF_EXPLODE = "自爆"
WEREWOLF_NO_SELF_EXPLODE = "不自爆"
SHERIFF_BADGE_LOST_DOUBLE_BOMB = "双爆吞警徽"
SHERIFF_BADGE_PENDING_FIRST_BOMB = "首爆中断警长竞选"
```

- [ ] **Step 7: Implement self-explosion hook**

Add methods to `GameEngine` before `_run_sheriff_election_if_needed`:

```python
    def _maybe_run_werewolf_self_explosion(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        stage: str,
    ) -> bool:
        if not self.rule_set.werewolf_self_explosion_enabled:
            return False
        if self.state.winner:
            return False

        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        for name in active_wolves:
            choice, action_log = self._player_action(
                player=players_by_name[name],
                action=ACTION_WEREWOLF_SELF_EXPLOSION,
                options=[WEREWOLF_SELF_EXPLODE, WEREWOLF_NO_SELF_EXPLODE],
                result_key="self_explode",
                round_state=round_state,
                phase="day",
                extra_world_state={"self_explosion_stage": stage},
            )
            if choice != WEREWOLF_SELF_EXPLODE:
                continue

            round_log.werewolf_self_explosion = action_log
            self._resolve_werewolf_self_explosion(
                wolf=name,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
            )
            return True
        return False

    def _resolve_werewolf_self_explosion(
        self,
        *,
        wolf: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        players_by_name = self.state.player_by_name()
        players_by_name[wolf].revealed_role = True
        round_state.werewolf_self_exploded = wolf
        round_state.day_ended_by_self_explosion = True
        round_state.day_deaths.append(DeathEvent(wolf, "werewolf_self_explosion", wolf))
        self._remove_player(active_players, wolf)
        self._announce(active_players, f"第{round_state.number}轮：{wolf}自爆为狼人，白天立即结束。")

        if self.state.sheriff == wolf:
            self._maybe_transfer_sheriff_badge(
                dead_player=wolf,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="day",
            )
            return

        if self.state.sheriff or self.state.sheriff_badge_lost:
            return

        self.state.sheriff_pre_election_bomb_count += 1
        round_state.sheriff_pre_election_bomb_count = self.state.sheriff_pre_election_bomb_count
        if (
            self.rule_set.sheriff_badge_bomb_policy == "double"
            and self.state.sheriff_pre_election_bomb_count >= 2
        ):
            round_state.sheriff_badge_lost_reason = SHERIFF_BADGE_LOST_DOUBLE_BOMB
            self.state.sheriff_election_pending = False
            round_state.sheriff_election_pending = False
            self._lose_sheriff_badge(round_state, active_players, SHERIFF_BADGE_LOST_DOUBLE_BOMB)
            return

        self.state.sheriff_election_pending = True
        round_state.sheriff_election_pending = True
        round_state.sheriff_badge_lost_reason = SHERIFF_BADGE_PENDING_FIRST_BOMB
```

`_player_action()` currently needs the new `extra_world_state` argument from the next step so the self-explosion stage can be included in the prompt.

- [ ] **Step 8: Add extra world-state support**

Update `_player_action()` signature in `engine.py` to:

```python
        extra_world_state: dict[str, object] | None = None,
```

After the existing `world_state = self._world_state(player, options, round_state)` line, merge:

```python
        if extra_world_state:
            world_state.update(extra_world_state)
```

In `_world_state()`, add:

```python
            "sheriff": self.state.sheriff,
            "sheriff_pre_election_bomb_count": self.state.sheriff_pre_election_bomb_count,
```

- [ ] **Step 9: Update sheriff election eligibility and interrupt points**

Change `_run_sheriff_election_if_needed()` to return `bool`: `True` means day was interrupted.

At the top, replace the current guard with:

```python
        round_state.sheriff = self.state.sheriff
        if not self._should_run_sheriff_election(round_state):
            return False
```

Add:

```python
    def _should_run_sheriff_election(self, round_state: RoundState) -> bool:
        return (
            self.rule_set.sheriff_enabled
            and not self.state.sheriff
            and not self.state.sheriff_badge_lost
            and (round_state.number == 1 or self.state.sheriff_election_pending)
        )
```

Inside `_run_sheriff_election_if_needed()`, before sheriff speeches, withdrawals, sheriff votes, PK speeches, and runoff votes, call:

```python
        if self._maybe_run_werewolf_self_explosion(round_state, round_log, active_players, "警上发言前"):
            return True
```

Use stage labels:

- `警上发言前`
- `退水前`
- `警下投票前`
- `PK 发言前`
- `二轮警下投票前`

When a sheriff is elected or badge is lost through ordinary election rules, clear pending state:

```python
        self.state.sheriff_election_pending = False
        round_state.sheriff_election_pending = False
```

Update `_lose_sheriff_badge()` so every badge-loss path exposes a reason:

```python
        round_state.sheriff_badge_lost_reason = reason
```

Return `False` at every non-interrupted exit.

- [ ] **Step 10: Update debate and day phase flow**

Change `_run_debate_phase()` to return `bool`. Before each speaker action, call:

```python
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                f"{speaker} 发言前",
            ):
                return True
```

Return `False` after all debate completes.

In `_run_day_phase()`, after sheriff election:

```python
        if self._run_sheriff_election_if_needed(round_state, round_log, active_players):
            self._finish_deferred_night_deaths_if_needed(
                pending_night_deaths,
                round_state,
                round_log,
                active_players,
            )
            self._publish_self_explosion_update(round_state, active_players)
            return
```

After pending night deaths are processed, replace:

```python
        self._run_debate_phase(round_state, round_log, active_players)
```

with:

```python
        if self._run_debate_phase(round_state, round_log, active_players):
            self._publish_self_explosion_update(round_state, active_players)
            return
```

Extract the existing pending-night-death block into this reusable helper:

```python
    def _finish_deferred_night_deaths_if_needed(
        self,
        pending_night_deaths: list[DeathEvent] | None,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        if pending_night_deaths is None:
            return

        pending_night_death_players = self._record_night_deaths(
            pending_night_deaths,
            round_state,
            active_players,
        )
        self._resolve_night_death_aftermath(
            pending_night_deaths,
            pending_night_death_players,
            round_state,
            round_log,
            active_players,
            transfer_sheriff_badge=False,
        )
        if round_state.night_deaths:
            eliminated_names = "、".join(death.player for death in round_state.night_deaths)
            self._announce(active_players, f"第{round_state.number}轮：夜晚，{eliminated_names}出局。")
        else:
            self._announce(active_players, f"第{round_state.number}轮：夜晚无人出局。")

        night_death_players = {death.player for death in round_state.night_deaths}
        for death in list(round_state.night_deaths):
            self._maybe_transfer_sheriff_badge(
                dead_player=death.player,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="night",
                excluded_badge_targets=night_death_players,
            )

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
        self.state.winner = self._get_winner(active_players)
```

Then replace the original inline `if pending_night_deaths is not None:` block in `_run_day_phase()` with:

```python
        self._finish_deferred_night_deaths_if_needed(
            pending_night_deaths,
            round_state,
            round_log,
            active_players,
        )
        if self.state.winner:
            return
```

Add:

```python
    def _publish_self_explosion_update(
        self,
        round_state: RoundState,
        active_players: list[str],
    ) -> None:
        self._publish_state_updated(
            round_state=round_state,
            phase="day",
            actor=round_state.werewolf_self_exploded,
            action=ACTION_WEREWOLF_SELF_EXPLOSION,
            payload={
                "werewolf_self_exploded": round_state.werewolf_self_exploded,
                "day_ended_by_self_explosion": round_state.day_ended_by_self_explosion,
                "day_deaths": [death.to_dict() for death in round_state.day_deaths],
                "sheriff_pre_election_bomb_count": round_state.sheriff_pre_election_bomb_count,
                "sheriff_election_pending": round_state.sheriff_election_pending,
                "sheriff_badge_lost": round_state.sheriff_badge_lost,
                "sheriff_badge_lost_reason": round_state.sheriff_badge_lost_reason,
                "active_players": active_players.copy(),
            },
        )
```

- [ ] **Step 11: Prevent duplicate pending deaths**

In `_record_night_deaths()`, skip deaths already recorded in `night_deaths` or `day_deaths`:

```python
        existing_dead_players = {
            death.player for death in [*round_state.night_deaths, *round_state.day_deaths]
        }
        recorded_night_deaths: set[str] = set()
        for death in deaths:
            if death.player in existing_dead_players:
                continue
            round_state.night_deaths.append(death)
            existing_dead_players.add(death.player)
            recorded_night_deaths.add(death.player)
            self._remove_player(active_players, death.player)

        round_state.eliminated = round_state.night_deaths[0].player if round_state.night_deaths else None
        return recorded_night_deaths
```

- [ ] **Step 12: Verify engine tests pass**

Run the command from Step 5 again.

Expected: all listed tests pass.

- [ ] **Step 13: Run focused backend regression tests**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_rules.py tests/test_werewolf_runner.py tests/test_werewolf_resume.py -q
```

Expected: all pass.

- [ ] **Step 14: Commit**

Run:

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: resolve werewolf self explosion flow"
```

## Task 4: Frontend Types, Adapter, And Debug Items

**Files:**
- Modify `apps/web/src/features/games/types.ts`
- Modify `apps/web/src/features/games/api/adapters.ts`
- Test `apps/web/src/features/games/api/adapters.test.ts`

- [ ] **Step 1: Write failing adapter test**

In `apps/web/src/features/games/api/adapters.test.ts`, add:

```ts
it("normalizes self explosion state and debug item", () => {
  const replay = normalizeGameReplay({
    ...baseResponse,
    state: {
      ...baseResponse.state,
      rounds: [
        {
          ...baseResponse.state.rounds[0],
          werewolf_self_exploded: "Bob",
          day_ended_by_self_explosion: true,
          sheriff_pre_election_bomb_count: 1,
          sheriff_election_pending: true,
          sheriff_badge_lost_reason: "首爆中断警长竞选",
          day_deaths: [{ player: "Bob", cause: "werewolf_self_explosion", source: "Bob" }],
        },
      ],
    },
    logs: [
      {
        ...baseResponse.logs[0],
        werewolf_self_explosion: {
          actor: "Bob",
          action: "werewolf_self_explosion",
          options: ["自爆", "不自爆"],
          choice: "自爆",
          lm_log: {
            prompt: "是否自爆？",
            raw_response: '{"self_explode":"自爆"}',
            result: { self_explode: "自爆" },
          },
        },
      },
    ],
  });

  const round = replay.rounds[0];
  expect(round.werewolf_self_exploded).toBe("Bob");
  expect(round.day_ended_by_self_explosion).toBe(true);
  expect(round.sheriff_pre_election_bomb_count).toBe(1);
  expect(round.sheriff_election_pending).toBe(true);
  expect(round.sheriff_badge_lost_reason).toBe("首爆中断警长竞选");
  expect(replay.debugItems).toContainEqual(
    expect.objectContaining({
      id: "round-1-day-werewolf-self-explosion",
      phase: "day",
      title: "狼人自爆",
      actor: "Bob",
      choice: "自爆",
    }),
  );
});
```

- [ ] **Step 2: Run failing frontend test**

Run:

```bash
pnpm --filter @werewolf-arena/web test -- adapters.test.ts
```

Expected: fail because fields and debug action are missing.

- [ ] **Step 3: Add TypeScript fields**

In `apps/web/src/features/games/types.ts`, add to `RawRoundLog`:

```ts
  werewolf_self_explosion?: RawActionLog | null;
```

Add to `RawRoundState`:

```ts
  werewolf_self_exploded?: string | null;
  day_ended_by_self_explosion?: boolean;
  sheriff_pre_election_bomb_count?: number;
  sheriff_election_pending?: boolean;
  sheriff_badge_lost_reason?: string | null;
```

Add those keys to the `Omit<RawRoundState, ...>` exclusion list, then add normalized fields to `GameRound`:

```ts
  werewolf_self_exploded: string | null;
  day_ended_by_self_explosion: boolean;
  sheriff_pre_election_bomb_count: number;
  sheriff_election_pending: boolean;
  sheriff_badge_lost_reason: string | null;
```

- [ ] **Step 4: Normalize fields and debug action**

In `apps/web/src/features/games/api/adapters.ts`, add to `ACTION_TITLES`:

```ts
  werewolf_self_explosion: "狼人自爆",
```

In `normalizeRound()`, add:

```ts
    werewolf_self_exploded: round.werewolf_self_exploded ?? null,
    day_ended_by_self_explosion: round.day_ended_by_self_explosion ?? false,
    sheriff_pre_election_bomb_count: round.sheriff_pre_election_bomb_count ?? 0,
    sheriff_election_pending: round.sheriff_election_pending ?? false,
    sheriff_badge_lost_reason: round.sheriff_badge_lost_reason ?? null,
```

In `debugItemsFromRound()`, after sheriff election debug actions and before `speech_order`, add:

```ts
  pushAction(
    items,
    round.number,
    "day",
    "day-werewolf-self-explosion",
    round.werewolf_self_explosion ?? null,
  );
```

- [ ] **Step 5: Verify frontend adapter test passes**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/api/adapters.ts apps/web/src/features/games/api/adapters.test.ts
git commit -m "feat: adapt self explosion replay data"
```

## Task 5: Frontend Self-Explosion Display

**Files:**
- Modify `apps/web/src/features/games/components/DayPhase.tsx`
- Modify `apps/web/src/features/games/components/DayPhase.test.tsx`
- Modify `apps/web/src/features/games/components/SheriffElectionPanel.tsx`
- Modify `apps/web/src/features/games/components/SheriffElectionPanel.test.tsx`

- [ ] **Step 1: Write failing DayPhase test**

In `apps/web/src/features/games/components/DayPhase.test.tsx`, add a round fixture field defaults matching `GameRound`, then add:

```tsx
it("shows when a werewolf self explosion ends the day early", () => {
  render(
    <DayPhase
      round={{
        ...baseRound,
        werewolf_self_exploded: "Bob",
        day_ended_by_self_explosion: true,
        sheriff_pre_election_bomb_count: 1,
        sheriff_election_pending: true,
        sheriff_badge_lost_reason: "首爆中断警长竞选",
        day_deaths: [{ player: "Bob", cause: "werewolf_self_explosion", source: "Bob" }],
      }}
      items={[]}
      selectedItem={null}
      onSelect={() => undefined}
    />,
  );

  expect(screen.getByText("Bob 自爆为狼人，白天提前结束")).toBeInTheDocument();
  expect(screen.getByText("首爆中断警长竞选，下一天继续竞选")).toBeInTheDocument();
});
```

- [ ] **Step 2: Write failing SheriffElectionPanel tests**

In `apps/web/src/features/games/components/SheriffElectionPanel.test.tsx`, add base defaults for new fields and add:

```tsx
it("shows double explosion badge loss reason", () => {
  render(
    <SheriffElectionPanel
      round={{
        ...baseRound,
        werewolf_self_exploded: "Bob",
        day_ended_by_self_explosion: true,
        sheriff_pre_election_bomb_count: 2,
        sheriff_badge_lost: true,
        sheriff_badge_lost_reason: "双爆吞警徽",
      }}
    />,
  );

  expect(screen.getByText("警徽状态：双爆吞警徽，警徽流失")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run failing component tests**

Run:

```bash
pnpm --filter @werewolf-arena/web test -- DayPhase.test.tsx SheriffElectionPanel.test.tsx
```

Expected: fail because the UI does not render the new text.

- [ ] **Step 4: Implement DayPhase notice**

In `DayPhase.tsx`, after `<SheriffElectionPanel items={items} round={round} />`, add:

```tsx
      <SelfExplosionNotice round={round} />
```

Add helper component before `SpecialDayResolution`:

```tsx
function SelfExplosionNotice({ round }: { round: GameRound }) {
  if (!round.day_ended_by_self_explosion || !round.werewolf_self_exploded) {
    return null;
  }

  return (
    <div className="mt-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
      <p className="font-medium">
        {round.werewolf_self_exploded} 自爆为狼人，白天提前结束
      </p>
      {round.sheriff_badge_lost_reason === "首爆中断警长竞选" ? (
        <p className="mt-1">首爆中断警长竞选，下一天继续竞选</p>
      ) : null}
      {round.sheriff_badge_lost_reason === "双爆吞警徽" ? (
        <p className="mt-1">双爆吞警徽，警徽流失</p>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 5: Implement SheriffElectionPanel badge reason**

In `BadgeStatus()`, update lost badge text:

```tsx
  const lostBadgeText =
    round.sheriff_badge_lost_reason === "双爆吞警徽"
      ? "警徽状态：双爆吞警徽，警徽流失"
      : round.sheriff_elected
        ? `${badgeTriggerText}警徽处理：撕毁警徽`
        : "警徽状态：警徽流失";
```

Ensure `hasSheriffDisplayData()` returns true when `round.werewolf_self_exploded` or `round.sheriff_badge_lost_reason` exists:

```tsx
    round.werewolf_self_exploded !== null ||
    round.sheriff_badge_lost_reason !== null ||
```

- [ ] **Step 6: Verify component tests pass**

Run the command from Step 3 again.

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add apps/web/src/features/games/components/DayPhase.tsx apps/web/src/features/games/components/DayPhase.test.tsx apps/web/src/features/games/components/SheriffElectionPanel.tsx apps/web/src/features/games/components/SheriffElectionPanel.test.tsx
git commit -m "feat: show self explosion replay state"
```

## Task 6: Full Verification

**Files:**
- No code files changed.

- [ ] **Step 1: Run backend test suite**

Run:

```bash
cd apps/api
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend test suite**

Run:

```bash
pnpm --filter @werewolf-arena/web test
```

Expected: all tests pass.

- [ ] **Step 3: Run web build**

Run:

```bash
pnpm --filter @werewolf-arena/web build
```

Expected: Vite/TypeScript build succeeds.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: clean worktree; recent commits correspond to the tasks above.
