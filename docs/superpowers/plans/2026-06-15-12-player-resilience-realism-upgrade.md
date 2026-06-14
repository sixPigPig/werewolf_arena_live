# 12 Player Resilience Realism Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep 12 player seer-witch-hunter-idiot games from aborting on recoverable invalid model actions, preserve useful failure logs, and extend realism monitoring for newly observed machine-like behavior.

**Architecture:** Add invalid-action feedback at the LM boundary, then let the engine apply explicit fail-soft defaults only for optional actions. Persist action metadata through replay/checkpoint paths, extend evaluator/action-quality checks, and surface retry/fallback progress in live/debug UI without leaking private summaries.

**Tech Stack:** Python dataclasses, pytest, existing Werewolf engine/checkpoint/replay serialization, React/TypeScript, Vitest.

---

## File Structure

- Modify `apps/api/app/werewolf/lm.py`: add invalid-attempt metadata and feedback prompts for allowed-value retries.
- Modify `apps/api/app/werewolf/models.py`: extend `ActionLog` and `LmLog` serialization with invalid/fallback metadata.
- Modify `apps/api/app/werewolf/checkpoint.py`: load new action/log metadata for resume compatibility.
- Modify `apps/api/app/werewolf/engine.py`: apply fail-soft defaults for optional actions, publish fallback warnings, keep current run logs available on failure, and add progress metadata.
- Modify `apps/api/app/werewolf/runner.py`: save engine in-progress logs when `engine.run()` raises.
- Modify `apps/api/app/werewolf/prompts_zh.py`: strengthen witch poison and self-explosion instructions.
- Modify `apps/api/app/werewolf/action_quality.py`: add text checks for term contradiction, self-reference-as-group, and chain self-explosion warnings.
- Modify `apps/api/app/werewolf/evaluator.py`: flag partial replay aborts, empty partial logs, off-option retry failures, chain self-explosion, term contradictions, and self-reference issues.
- Modify `apps/web/src/features/games/types.ts`: add debug metadata fields for action logs.
- Modify `apps/web/src/features/games/api/adapters.ts`: normalize fallback/invalid metadata into debug items.
- Modify `apps/web/src/features/games/liveDirector.ts`: render safe retry/fallback status events.
- Modify `apps/web/src/features/games/liveDebugTrace.ts`: attach action quality warnings and fallback metadata to traces.
- Tests in `apps/api/tests/test_werewolf_lm.py`, `apps/api/tests/test_werewolf_runner.py`, `apps/api/tests/test_werewolf_resume.py`, `apps/api/tests/test_werewolf_evaluator.py`, `apps/api/tests/test_werewolf_action_quality.py`, `apps/web/src/features/games/liveDirector.test.ts`, `apps/web/src/features/games/liveDebugTrace.test.ts`, and `apps/web/src/features/games/api/adapters.test.ts`.

---

### Task 1: Invalid Action Feedback At LM Boundary

**Files:**
- Modify: `apps/api/app/werewolf/lm.py`
- Test: `apps/api/tests/test_werewolf_lm.py`

- [ ] **Step 1: Write failing LM retry feedback tests**

Append to `apps/api/tests/test_werewolf_lm.py`:

```python
def test_generate_action_retries_with_invalid_allowed_value_feedback() -> None:
    class CapturingProvider:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                '{"reasoning":"想毒10","poison":"10号玩家"}',
                '{"reasoning":"改毒12","poison":"12号玩家"}',
            ]

        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            del model, temperature
            self.prompts.append(prompt)
            return self.responses[len(self.prompts) - 1]

    provider = CapturingProvider()

    value, lm_log = generate_action(
        provider=provider,
        action="witch_poison",
        world_state={
            **_world_state_for_special_action("女巫", ""),
            "options": ["6号玩家", "12号玩家", "不使用毒药"],
        },
        model="deepseek-v4-flash",
        allowed_values=["6号玩家", "12号玩家", "不使用毒药"],
        result_key="poison",
        retries=2,
    )

    assert value == "12号玩家"
    assert len(provider.prompts) == 2
    assert "上次输出的 poison 为“10号玩家”" in provider.prompts[1]
    assert "6号玩家、12号玩家、不使用毒药" in provider.prompts[1]
    assert lm_log.invalid_attempts == [
        {
            "value": "10号玩家",
            "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
            "result_key": "poison",
        }
    ]


def test_generate_action_returns_invalid_attempts_after_exhausting_retries() -> None:
    provider = FakeProvider(
        [
            {"reasoning": "想毒10", "poison": "10号玩家"},
            {"reasoning": "仍毒10", "poison": "10号玩家"},
        ]
    )

    value, lm_log = generate_action(
        provider=provider,
        action="witch_poison",
        world_state={
            **_world_state_for_special_action("女巫", ""),
            "options": ["6号玩家", "12号玩家", "不使用毒药"],
        },
        model="deepseek-v4-flash",
        allowed_values=["6号玩家", "12号玩家", "不使用毒药"],
        result_key="poison",
        retries=2,
    )

    assert value is None
    assert lm_log.result == {"reasoning": "仍毒10", "poison": "10号玩家"}
    assert lm_log.invalid_attempts == [
        {
            "value": "10号玩家",
            "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
            "result_key": "poison",
        },
        {
            "value": "10号玩家",
            "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
            "result_key": "poison",
        },
    ]
    assert "retry" in lm_log.raw_response
```

- [ ] **Step 2: Run failing LM tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_generate_action_retries_with_invalid_allowed_value_feedback \
  tests/test_werewolf_lm.py::test_generate_action_returns_invalid_attempts_after_exhausting_retries \
  -q
```

Expected: FAIL because `LmLog.invalid_attempts` and invalid feedback prompts do not exist.

- [ ] **Step 3: Extend `LmLog` and add invalid feedback helpers**

In `apps/api/app/werewolf/lm.py`, update imports:

```python
from dataclasses import dataclass, field
```

Change `LmLog`:

```python
@dataclass
class LmLog:
    prompt: str
    raw_response: str
    result: dict[str, Any] | None
    request_id: str | None = None
    invalid_attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = {
            "prompt": self.prompt,
            "raw_response": self.raw_response,
            "result": self.result,
        }
        if self.request_id is not None:
            value["request_id"] = self.request_id
        if self.invalid_attempts:
            value["invalid_attempts"] = self.invalid_attempts
        return value
```

Add helpers near `_normalize_allowed_value()`:

```python
def _invalid_attempt(
    *,
    value: Any,
    allowed_values: list[Any],
    result_key: str | None,
) -> dict[str, Any]:
    return {
        "value": value,
        "allowed_values": allowed_values.copy(),
        "result_key": result_key or "result",
    }


def _prompt_with_invalid_feedback(
    base_prompt: str,
    invalid_attempt: dict[str, Any],
) -> str:
    allowed_values = "、".join(str(item) for item in invalid_attempt["allowed_values"])
    result_key = str(invalid_attempt["result_key"])
    value = str(invalid_attempt["value"])
    return (
        f"{base_prompt}\n\n"
        "上次输出无效，请修正。\n"
        f"上次输出的 {result_key} 为“{value}”，但该值不在合法候选中。\n"
        f"本次必须从以下候选中选择 {result_key}：{allowed_values}。\n"
        "如果你原本最怀疑的人不在候选中，请在剩余候选中重新排序，或选择合法的放弃/不使用选项。\n"
        "只输出合法 JSON。"
    )
```

- [ ] **Step 4: Use feedback prompt in `generate_action()`**

Change the body of `generate_action()` so each retry can use feedback:

```python
    base_prompt, _schema = build_prompt(action, world_state)
    raw_responses: list[str] = []
    invalid_attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    current_prompt = base_prompt

    for attempt in range(retries):
        if invalid_attempts:
            current_prompt = _prompt_with_invalid_feedback(base_prompt, invalid_attempts[-1])
        raw_response = provider.complete_json(
            model=model,
            prompt=current_prompt,
            temperature=min(1.0, 0.4 + attempt * 0.2),
        )
```

After normalizing value:

```python
        if allowed_values is None or normalized_value in allowed_values:
            return normalized_value, LmLog(
                prompt=current_prompt,
                raw_response=raw_response,
                result=result,
                invalid_attempts=invalid_attempts.copy(),
            )
        invalid_attempts.append(
            _invalid_attempt(
                value=normalized_value,
                allowed_values=allowed_values,
                result_key=result_key,
            )
        )
```

Change the exhausted return:

```python
    return None, LmLog(
        prompt=current_prompt,
        raw_response="\n--- retry ---\n".join(raw_responses),
        result=last_result,
        invalid_attempts=invalid_attempts.copy(),
    )
```

- [ ] **Step 5: Use feedback prompt in `generate_action_with_events()`**

Apply the same pattern to `generate_action_with_events()`:

```python
    base_prompt, _schema = build_prompt(action, world_state)
    raw_responses: list[str] = []
    invalid_attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    last_request_id: str | None = None
    current_prompt = base_prompt
```

At each attempt:

```python
        if invalid_attempts:
            current_prompt = _prompt_with_invalid_feedback(base_prompt, invalid_attempts[-1])
```

Use `current_prompt` in `_complete_json_with_optional_stream()` and return it in `LmLog`. When invalid:

```python
        invalid_attempts.append(
            _invalid_attempt(
                value=normalized_value,
                allowed_values=allowed_values,
                result_key=result_key,
            )
        )
        _publish_model_event(
            event_sink,
            "model_retry_scheduled",
            context=context,
            payload={
                "request_id": request_id,
                "model": model,
                "attempt": attempt + 2,
                "invalid_value": normalized_value,
                "allowed_values": allowed_values.copy(),
                "result_key": result_key,
                "message": "模型选择不在候选项中，正在带反馈重试。",
            },
        )
```

- [ ] **Step 6: Run LM tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_generate_action_retries_with_invalid_allowed_value_feedback \
  tests/test_werewolf_lm.py::test_generate_action_returns_invalid_attempts_after_exhausting_retries \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/lm.py apps/api/tests/test_werewolf_lm.py
git commit -m "feat: retry invalid actions with feedback"
```

---

### Task 2: Persist Invalid And Fallback Action Metadata

**Files:**
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/checkpoint.py`
- Test: `apps/api/tests/test_werewolf_resume.py`

- [ ] **Step 1: Write failing serialization tests**

Append to `apps/api/tests/test_werewolf_resume.py`:

```python
def test_action_log_serializes_invalid_and_fallback_metadata() -> None:
    action_log = ActionLog(
        actor="1号玩家",
        action="witch_poison",
        options=["6号玩家", "12号玩家", "不使用毒药"],
        choice="不使用毒药",
        lm_log=LmLog(
            prompt="prompt",
            raw_response='{"poison":"10号玩家"}',
            result={"poison": "10号玩家"},
            invalid_attempts=[
                {
                    "value": "10号玩家",
                    "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
                    "result_key": "poison",
                }
            ],
        ),
        invalid_value="10号玩家",
        fallback_choice="不使用毒药",
        fallback_reason="optional_action_invalid",
        attempt_count=3,
    )

    payload = action_log.to_dict()

    assert payload["invalid_value"] == "10号玩家"
    assert payload["fallback_choice"] == "不使用毒药"
    assert payload["fallback_reason"] == "optional_action_invalid"
    assert payload["attempt_count"] == 3
    assert payload["lm_log"]["invalid_attempts"][0]["value"] == "10号玩家"


def test_action_log_from_dict_defaults_invalid_and_fallback_metadata() -> None:
    action_log = action_log_from_dict(
        {
            "actor": "1号玩家",
            "action": "witch_poison",
            "options": ["不使用毒药"],
            "choice": "不使用毒药",
            "lm_log": {
                "prompt": "prompt",
                "raw_response": "{}",
                "result": {"poison": "不使用毒药"},
            },
        }
    )

    assert action_log.invalid_value is None
    assert action_log.fallback_choice is None
    assert action_log.fallback_reason is None
    assert action_log.attempt_count == 1
    assert action_log.lm_log.invalid_attempts == []
```

- [ ] **Step 2: Run failing serialization tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_resume.py::test_action_log_serializes_invalid_and_fallback_metadata \
  tests/test_werewolf_resume.py::test_action_log_from_dict_defaults_invalid_and_fallback_metadata \
  -q
```

Expected: FAIL because metadata fields are not defined.

- [ ] **Step 3: Extend `ActionLog`**

In `apps/api/app/werewolf/models.py`, change `ActionLog`:

```python
@dataclass
class ActionLog:
    actor: str
    action: str
    options: list[str]
    choice: str | None
    lm_log: LmLog
    invalid_value: object | None = None
    fallback_choice: object | None = None
    fallback_reason: str | None = None
    attempt_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "action": self.action,
            "options": self.options,
            "choice": self.choice,
            "lm_log": self.lm_log.to_dict(),
            "invalid_value": self.invalid_value,
            "fallback_choice": self.fallback_choice,
            "fallback_reason": self.fallback_reason,
            "attempt_count": self.attempt_count,
        }
```

- [ ] **Step 4: Load metadata in checkpoints**

In `apps/api/app/werewolf/checkpoint.py`, update `action_log_from_dict()`:

```python
    return ActionLog(
        actor=str(data.get("actor") or ""),
        action=str(data.get("action") or ""),
        options=[str(item) for item in data.get("options", [])],
        choice=data.get("choice"),
        lm_log=LmLog(
            prompt=str(lm_log_data.get("prompt") or ""),
            raw_response=str(lm_log_data.get("raw_response") or ""),
            result=lm_log_data.get("result", lm_log_data.get("parsed")),
            request_id=lm_log_data.get("request_id"),
            invalid_attempts=copy.deepcopy(lm_log_data.get("invalid_attempts", [])),
        ),
        invalid_value=data.get("invalid_value"),
        fallback_choice=data.get("fallback_choice"),
        fallback_reason=data.get("fallback_reason"),
        attempt_count=int(data.get("attempt_count") or 1),
    )
```

- [ ] **Step 5: Run serialization tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_resume.py::test_action_log_serializes_invalid_and_fallback_metadata \
  tests/test_werewolf_resume.py::test_action_log_from_dict_defaults_invalid_and_fallback_metadata \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/models.py apps/api/app/werewolf/checkpoint.py apps/api/tests/test_werewolf_resume.py
git commit -m "feat: persist invalid action metadata"
```

---

### Task 3: Fail-Soft Optional Actions

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing engine fail-soft tests**

Append to `apps/api/tests/test_werewolf_runner.py`:

```python
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
    players = state.player_by_name()
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

    assert round_state.poisoned is None
    assert round_log.witch_poison is not None
    assert round_log.witch_poison.choice == NO_WITCH_POISON
    assert round_log.witch_poison.invalid_value == "10号玩家"
    assert round_log.witch_poison.fallback_choice == NO_WITCH_POISON
    assert any(event["type"] == "action_quality_warning" for event in sink.events)


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
```

- [ ] **Step 2: Run failing fail-soft tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_witch_poison_invalid_choice_falls_back_to_no_poison \
  tests/test_werewolf_runner.py::test_hunter_invalid_shot_falls_back_to_no_shot \
  -q
```

Expected: FAIL because invalid optional actions still raise.

- [ ] **Step 3: Add optional fallback mapping and metadata helpers**

In `apps/api/app/werewolf/engine.py`, add near constants:

```python
OPTIONAL_ACTION_FALLBACKS = {
    ACTION_WITCH_SAVE: NO_WITCH_SAVE,
    ACTION_WITCH_POISON: NO_WITCH_POISON,
    ACTION_HUNTER_SHOOT: NO_HUNTER_SHOT,
    ACTION_WEREWOLF_SELF_EXPLOSION: WEREWOLF_NO_SELF_EXPLODE,
    ACTION_SHERIFF_WITHDRAW: SHERIFF_STAY,
}
```

Add helpers near `_invalid_player_action_error()`:

```python
    def _optional_fallback_choice(self, request: PlayerActionRequest) -> object | None:
        fallback = OPTIONAL_ACTION_FALLBACKS.get(request.action)
        if fallback is not None and fallback in request.options:
            return fallback
        return None

    def _invalid_value_from_result(self, result: PlayerActionResult) -> object | None:
        if result.value is not None:
            return result.value
        if result.lm_log.invalid_attempts:
            return result.lm_log.invalid_attempts[-1].get("value")
        return None

    def _publish_optional_fallback_warning(
        self,
        *,
        request: PlayerActionRequest,
        invalid_value: object | None,
        fallback_choice: object,
    ) -> None:
        self._publish(
            "action_quality_warning",
            round_number=request.round_state.number,
            phase=request.phase,
            actor=request.player.name,
            action=request.action,
            payload={
                "warnings": ["off_option_fallback"],
                "invalid_value": invalid_value,
                "fallback_choice": fallback_choice,
                "allowed_values": request.options.copy(),
            },
        )
```

- [ ] **Step 4: Apply fallback in `_finalize_player_action_result()`**

In `_finalize_player_action_result()`, after creating `action_log`, replace invalid handling with:

```python
        invalid_error = self._invalid_player_action_error(result)
        if invalid_error is not None:
            fallback_choice = self._optional_fallback_choice(request)
            if fallback_choice is None:
                raise invalid_error
            invalid_value = self._invalid_value_from_result(result)
            value = fallback_choice
            action_log.choice = str(fallback_choice)
            action_log.invalid_value = invalid_value
            action_log.fallback_choice = fallback_choice
            action_log.fallback_reason = "optional_action_invalid"
            action_log.attempt_count = max(1, len(lm_log.invalid_attempts))
            self._publish_optional_fallback_warning(
                request=request,
                invalid_value=invalid_value,
                fallback_choice=fallback_choice,
            )
```

Keep the existing `model_response_received` and `action_parsed` publish after this block so the fallback choice is visible in debug flow.

- [ ] **Step 5: Let batch finalization handle invalid optional actions**

Remove the `invalid_errors = {...}` precheck block in `_player_actions_batch()`. Invalid required actions still raise when `_finalize_player_action_result()` is called for that result. Optional actions can now fallback there.

- [ ] **Step 6: Run fail-soft tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_witch_poison_invalid_choice_falls_back_to_no_poison \
  tests/test_werewolf_runner.py::test_hunter_invalid_shot_falls_back_to_no_shot \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "fix: fail soft for invalid optional actions"
```

---

### Task 4: Preserve Partial Logs On Failure

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/runner.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing partial log preservation test**

Append to `apps/api/tests/test_werewolf_runner.py`:

```python
def test_run_game_saves_in_progress_logs_when_required_action_fails(tmp_path) -> None:
    provider = FakeProvider(
        [
            {"reasoning": "非法刀口", "target": "不存在玩家"},
            {"reasoning": "仍非法", "target": "不存在玩家"},
            {"reasoning": "继续非法", "target": "不存在玩家"},
        ]
    )

    with pytest.raises(GameRunError):
        run_game(
            villager_model="deepseek-v4-flash",
            werewolf_model="deepseek-v4-flash",
            seed=2026061503,
            logs_dir=tmp_path,
            max_rounds=1,
            provider=provider,
            session_id="required_action_failure",
            rule_set_id="starter_6",
        )

    log_path = tmp_path / "required_action_failure" / "game_logs.json"
    logs = json.loads(log_path.read_text(encoding="utf-8"))

    assert logs
    assert logs[0]["number"] == 1
```

- [ ] **Step 2: Run failing partial log test**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_run_game_saves_in_progress_logs_when_required_action_fails \
  -q
```

Expected: FAIL because `run_game()` saves the local empty `logs` variable when `engine.run()` raises before returning.

- [ ] **Step 3: Keep engine logs accessible during run**

In `GameEngine.__init__()`, add:

```python
        self.logs: list[RoundLog] = []
```

In `GameEngine.run()`, replace local initialization:

```python
        logs: list[RoundLog] = []
```

with:

```python
        logs: list[RoundLog] = []
        self.logs = logs
```

Because `round_log` is appended before round actions, `self.logs` will include the in-progress round if an exception occurs.

- [ ] **Step 4: Use engine logs when runner catches errors**

In `apps/api/app/werewolf/runner.py`, initialize `engine = None` before the `try` block and update exception handling:

```python
    engine = None
    try:
        engine = GameEngine(
            state=state,
            provider=provider or create_model_provider(),
            max_rounds=max_rounds,
            rule_set=rule_set,
            event_sink=event_sink or NullEventSink(),
            rng=engine_rng,
            checkpoint_manager=checkpoint_manager,
        )
        logs = engine.run()
    except Exception as exc:
        if engine is not None:
            logs = engine.logs
        state.error_message = str(exc)
        save_game(state, logs, log_directory)
        raise GameRunError(str(exc), log_directory) from exc
```

Apply the same pattern in `resume_game()`:

```python
    engine = None
    try:
        engine = GameEngine(
            state=state,
            provider=replay_provider,
            max_rounds=max_rounds,
            rule_set=rule_set,
            event_sink=event_sink or NullEventSink(),
            rng=rng,
            starting_active_players=active_players,
            checkpoint_manager=checkpoint_manager,
        )
        logs_after_resume = engine.run()
    except Exception as exc:
        if engine is not None:
            logs_after_resume = engine.logs
        state.error_message = str(exc)
        save_game(state, logs_before_round + logs_after_resume, log_directory)
        raise GameRunError(str(exc), log_directory) from exc
```

- [ ] **Step 5: Run partial log test**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_run_game_saves_in_progress_logs_when_required_action_fails \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/engine.py apps/api/app/werewolf/runner.py apps/api/tests/test_werewolf_runner.py
git commit -m "fix: preserve partial logs on game failure"
```

---

### Task 5: Prompt And Quality Checks For New Realism Issues

**Files:**
- Modify: `apps/api/app/werewolf/prompts_zh.py`
- Modify: `apps/api/app/werewolf/action_quality.py`
- Test: `apps/api/tests/test_werewolf_lm.py`
- Test: `apps/api/tests/test_werewolf_action_quality.py`

- [ ] **Step 1: Write failing prompt and quality tests**

Append to `apps/api/tests/test_werewolf_lm.py`:

```python
def test_witch_poison_prompt_explains_attacked_target_exclusion() -> None:
    prompt, _schema = build_prompt(
        "witch_poison",
        {
            **_world_state_for_special_action("女巫", ""),
            "options": ["6号玩家", "11号玩家", "12号玩家", "不使用毒药"],
            "attacked": "10号玩家",
        },
    )

    assert "今晚被狼人袭击的目标是10号玩家" in prompt
    assert "10号玩家不在毒药候选中" in prompt
    assert "poison 必须完全等于候选人中的一个值" in prompt


def test_werewolf_self_explosion_prompt_mentions_chain_cost() -> None:
    prompt, _schema = build_prompt(
        "werewolf_self_explosion",
        {
            **_world_state_for_special_action("狼人", ""),
            "public_facts": [
                "第1轮：2号玩家自爆为狼人，白天立即结束。",
                "第2轮：7号玩家自爆为狼人，白天立即结束。",
            ],
        },
    )

    assert "已有狼人自爆" in prompt
    assert "收益不明确时选择不自爆" in prompt
```

Append to `apps/api/tests/test_werewolf_action_quality.py`:

```python
def test_action_quality_flags_role_term_contradiction_and_self_reference() -> None:
    assert "role_term_contradiction" in action_quality_warnings(
        action="debate",
        text="3号预言家查杀5号好人，所以5号可信。",
    )
    assert "self_reference_as_group" in action_quality_warnings(
        action="debate",
        text="我10号是村民，后置位10、11、12都需要解释身份。",
        actor="10号玩家",
    )
```

- [ ] **Step 2: Run failing prompt and quality tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_witch_poison_prompt_explains_attacked_target_exclusion \
  tests/test_werewolf_lm.py::test_werewolf_self_explosion_prompt_mentions_chain_cost \
  tests/test_werewolf_action_quality.py::test_action_quality_flags_role_term_contradiction_and_self_reference \
  -q
```

Expected: FAIL because prompt text and quality checks are not present.

- [ ] **Step 3: Update action quality helper signature**

In `apps/api/app/werewolf/action_quality.py`, change the signature:

```python
def action_quality_warnings(
    *,
    action: str,
    text: str,
    actor: str | None = None,
    endgame: bool = False,
) -> list[str]:
```

Add checks before return:

```python
    if ("查杀" in normalized and "好人" in normalized) or (
        "金水" in normalized and "狼人" in normalized
    ):
        warnings.append("role_term_contradiction")

    if actor:
        actor_number = actor.replace("玩家", "")
        group_patterns = [
            f"{actor_number}、",
            f"、{actor_number}",
            f"{actor_number}和",
        ]
        if any(pattern in normalized for pattern in group_patterns) and (
            "后置位" in normalized or "他们" in normalized or "范围" in normalized
        ):
            warnings.append("self_reference_as_group")
```

Update engine calls to pass `actor=actor`.

- [ ] **Step 4: Strengthen witch poison prompt**

In `apps/api/app/werewolf/prompts_zh.py`, update the `witch_poison` branch:

```python
    if action == "witch_poison":
        attacked = str(world_state.get("attacked") or "")
        attacked_note = (
            f"今晚被狼人袭击的目标是{attacked}；{attacked}不在毒药候选中，不能同时作为毒药目标。"
            if attacked
            else ""
        )
        return (
            "行动：女巫夜晚毒药。\n"
            f"候选人：{options}。\n"
            f"{attacked_note}"
            "你可以选择一名候选玩家使用毒药，或选择不使用毒药。"
            "如果你最怀疑的人不在候选中，请在剩余候选中重新排序，或选择不使用毒药。"
            "如果不使用毒药，必须说明保留毒药仍有收益，不能只说信息不足。"
            "poison 必须完全等于候选人中的一个值。"
            "结合公开事实、票型和警徽流判断。被毒死的猎人不能开枪。"
            "输出字段 reasoning 和 poison。"
        )
```

- [ ] **Step 5: Strengthen self-explosion prompt**

In the `werewolf_self_explosion` branch, include:

```python
        return (
            "行动：狼人自爆判断。\n"
            f"候选人：{options}。\n"
            "已有狼人自爆时，继续自爆必须能带来明确收益，例如吞警徽、阻止关键查验、保护最后隐狼或直接创造胜势。"
            "收益不明确时选择不自爆，保留白天发言空间。"
            "输出字段 reasoning 和 self_explode。"
        )
```

- [ ] **Step 6: Run prompt and quality tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py::test_witch_poison_prompt_explains_attacked_target_exclusion \
  tests/test_werewolf_lm.py::test_werewolf_self_explosion_prompt_mentions_chain_cost \
  tests/test_werewolf_action_quality.py::test_action_quality_flags_role_term_contradiction_and_self_reference \
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/prompts_zh.py apps/api/app/werewolf/action_quality.py apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_lm.py apps/api/tests/test_werewolf_action_quality.py
git commit -m "feat: flag new realism quality issues"
```

---

### Task 6: Evaluator Coverage For Partial Failures And Realism Smells

**Files:**
- Modify: `apps/api/app/werewolf/evaluator.py`
- Test: `apps/api/tests/test_werewolf_evaluator.py`

- [ ] **Step 1: Write failing evaluator tests**

Append to `apps/api/tests/test_werewolf_evaluator.py`:

```python
def test_evaluator_flags_invalid_abort_empty_logs_and_chain_self_explosion(tmp_path) -> None:
    replay = {
        "session_id": "partial_eval",
        "error_message": "1号玩家 returned invalid witch_poison: None",
        "players": [],
        "rounds": [
            {"number": 1, "werewolf_self_exploded": "2号玩家", "debate": [], "summaries": {}},
            {"number": 2, "werewolf_self_exploded": "7号玩家", "debate": [], "summaries": {}},
            {"number": 3, "werewolf_self_exploded": "8号玩家", "debate": [], "summaries": {}},
        ],
    }
    replay_path = tmp_path / "game_partial.json"
    logs_path = tmp_path / "game_logs.json"
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    logs_path.write_text("[]", encoding="utf-8")

    report = evaluate_replay(replay_path)

    assert "invalid_action_abort" in report.issue_codes
    assert "empty_partial_logs" in report.issue_codes
    assert "chain_self_explosion_overuse" in report.issue_codes


def test_evaluator_flags_term_contradiction_and_self_reference(tmp_path) -> None:
    replay = {
        "session_id": "text_eval",
        "winner": "",
        "players": [],
        "rounds": [
            {
                "number": 3,
                "summaries": {},
                "sheriff_speeches": [],
                "debate": [
                    {"speaker": "1号玩家", "message": "3号预言家查杀5号好人。"},
                    {"speaker": "10号玩家", "message": "我10号是村民，后置位10、11、12都可疑。"},
                ],
            }
        ],
    }
    path = tmp_path / "game_complete.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    report = evaluate_replay(path)

    assert "role_term_contradiction" in report.issue_codes
    assert "self_reference_as_group" in report.issue_codes
```

- [ ] **Step 2: Run failing evaluator tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_evaluator.py::test_evaluator_flags_invalid_abort_empty_logs_and_chain_self_explosion \
  tests/test_werewolf_evaluator.py::test_evaluator_flags_term_contradiction_and_self_reference \
  -q
```

Expected: FAIL because evaluator does not flag these issues.

- [ ] **Step 3: Add partial failure checks**

In `apps/api/app/werewolf/evaluator.py`, add constants:

```python
INVALID_ACTION_MARKERS = ("returned invalid", "invalid witch_poison", "invalid hunter_shoot")
```

At the start of `evaluate_replay()` after loading data:

```python
    error_message = str(data.get("error_message") or "")
    if any(marker in error_message for marker in INVALID_ACTION_MARKERS):
        issues.append(
            ReplayEvaluationIssue(
                code="invalid_action_abort",
                round_number=0,
                detail=error_message,
            )
        )
    logs_path = path.with_name("game_logs.json")
    if error_message and logs_path.exists():
        try:
            logs_data = json.loads(logs_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logs_data = None
        if logs_data == []:
            issues.append(
                ReplayEvaluationIssue(
                    code="empty_partial_logs",
                    round_number=0,
                    detail="Partial replay has an error but game_logs.json is empty.",
                )
            )
```

- [ ] **Step 4: Add self-explosion and text checks**

Inside the round loop:

```python
        if round_state.get("werewolf_self_exploded"):
            recent_self_explosions.append(round_number)
            recent_self_explosions = [
                item for item in recent_self_explosions if round_number - item <= 2
            ]
            if len(recent_self_explosions) >= 3:
                _append_issue(
                    issues,
                    seen_issue_keys,
                    ReplayEvaluationIssue(
                        code="chain_self_explosion_overuse",
                        round_number=round_number,
                        detail="Three werewolf self-explosions occurred within three rounds.",
                    ),
                    key_detail="chain",
                )

        for speaker, text in _speech_entry_details(round_state.get("debate")):
            if _has_role_term_contradiction(text):
                _append_issue(
                    issues,
                    seen_issue_keys,
                    ReplayEvaluationIssue(
                        code="role_term_contradiction",
                        round_number=round_number,
                        detail="Speech combines incompatible role terms such as 查杀 and 好人.",
                    ),
                    key_detail=f"{speaker}:{text[:80]}",
                )
            if speaker and _has_self_reference_as_group(speaker, text):
                _append_issue(
                    issues,
                    seen_issue_keys,
                    ReplayEvaluationIssue(
                        code="self_reference_as_group",
                        round_number=round_number,
                        detail="Speaker grouped their own seat with other seats as if they were separate.",
                    ),
                    key_detail=f"{speaker}:{text[:80]}",
                )
```

Add helpers:

```python
def _speech_entry_details(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    messages: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            message = item.get("message")
            if isinstance(message, str):
                speaker = str(item.get("speaker") or item.get("actor") or "")
                messages.append((speaker, message))
                continue
            choice = item.get("choice")
            if isinstance(choice, str):
                speaker = str(item.get("actor") or item.get("speaker") or "")
                messages.append((speaker, choice))
        elif isinstance(item, str):
            messages.append(("", item))
    return messages


def _has_role_term_contradiction(text: str) -> bool:
    return ("查杀" in text and "好人" in text) or ("金水" in text and "狼人" in text)


def _has_self_reference_as_group(speaker: str, text: str) -> bool:
    number = speaker.replace("玩家", "")
    return (
        ("后置位" in text or "他们" in text or "范围" in text)
        and (f"{number}、" in text or f"、{number}" in text or f"{number}和" in text)
    )
```

- [ ] **Step 5: Run evaluator tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_evaluator.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/evaluator.py apps/api/tests/test_werewolf_evaluator.py
git commit -m "feat: evaluate partial replay failures"
```

---

### Task 7: Frontend Debug And Monitor Visibility

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/api/adapters.ts`
- Modify: `apps/web/src/features/games/liveDirector.ts`
- Modify: `apps/web/src/features/games/liveDebugTrace.ts`
- Test: `apps/web/src/features/games/api/adapters.test.ts`
- Test: `apps/web/src/features/games/liveDirector.test.ts`
- Test: `apps/web/src/features/games/liveDebugTrace.test.ts`

- [ ] **Step 1: Write failing frontend metadata tests**

Append to `apps/web/src/features/games/api/adapters.test.ts`:

```typescript
it("normalizes invalid action fallback metadata into debug items", () => {
  const replay = normalizeGameReplay({
    ...rawReplay,
    logs: [
      {
        ...rawReplay.logs[0],
        witch_poison: {
          actor: "1号玩家",
          action: "witch_poison",
          options: ["6号玩家", "12号玩家", "不使用毒药"],
          choice: "不使用毒药",
          invalid_value: "10号玩家",
          fallback_choice: "不使用毒药",
          fallback_reason: "optional_action_invalid",
          attempt_count: 3,
          lm_log: {
            prompt: "请选择毒药目标。",
            raw_response: '{"poison":"10号玩家"}',
            result: { poison: "10号玩家" },
          },
        },
      },
    ],
  });

  expect(replay.debugItems[1]).toMatchObject({
    action: "witch_poison",
    invalidValue: "10号玩家",
    fallbackChoice: "不使用毒药",
    fallbackReason: "optional_action_invalid",
    attemptCount: 3,
  });
});
```

Append to `apps/web/src/features/games/liveDirector.test.ts`:

```typescript
it("renders retry and fallback warnings as safe status cues", () => {
  expect(
    toDirectorCue(
      event({
        type: "model_retry_scheduled",
        actor: "1号玩家",
        action: "witch_poison",
        payload: {
          attempt: 2,
          invalid_value: "10号玩家",
          message: "模型选择不在候选项中，正在带反馈重试。",
        },
      }),
    ),
  ).toMatchObject({
    title: "1号玩家 正在重试行动",
    body: "模型选择不在候选项中，正在带反馈重试。第 2 次尝试。",
    importance: "action",
  });

  expect(
    toDirectorCue(
      event({
        type: "action_quality_warning",
        actor: "1号玩家",
        action: "witch_poison",
        payload: {
          warnings: ["off_option_fallback"],
          invalid_value: "10号玩家",
          fallback_choice: "不使用毒药",
        },
      }),
    ).body,
  ).toContain("已使用安全兜底：不使用毒药");
});
```

Append to `apps/web/src/features/games/liveDebugTrace.test.ts`:

```typescript
it("attaches action quality fallback warnings to action traces", () => {
  const traces = buildLiveDebugTraces([
    event({
      id: 1,
      type: "action_requested",
      actor: "1号玩家",
      action: "witch_poison",
      payload: { options: ["不使用毒药"] },
    }),
    event({
      id: 2,
      type: "action_quality_warning",
      actor: "1号玩家",
      action: "witch_poison",
      payload: {
        warnings: ["off_option_fallback"],
        invalid_value: "10号玩家",
        fallback_choice: "不使用毒药",
      },
    }),
  ]);

  expect(traces[0].status).toBe("warning");
  expect(traces[0].warnings).toContain("off_option_fallback");
  expect(traces[0].impactSummary.join(" ")).toContain("不使用毒药");
});
```

- [ ] **Step 2: Run failing frontend tests**

Run:

```bash
pnpm --dir apps/web test -- --run \
  src/features/games/api/adapters.test.ts \
  src/features/games/liveDirector.test.ts \
  src/features/games/liveDebugTrace.test.ts
```

Expected: FAIL because fallback metadata and events are not normalized/rendered.

- [ ] **Step 3: Extend frontend types**

In `apps/web/src/features/games/types.ts`, add optional fields to `RawActionLog`:

```typescript
  invalid_value?: unknown;
  fallback_choice?: unknown;
  fallback_reason?: string | null;
  attempt_count?: number;
```

Add to `DebugItem`:

```typescript
  invalidValue?: unknown;
  fallbackChoice?: unknown;
  fallbackReason?: string | null;
  attemptCount?: number;
```

- [ ] **Step 4: Normalize metadata in adapters**

In `pushAction()` in `apps/web/src/features/games/api/adapters.ts`, add:

```typescript
    invalidValue: action.invalid_value,
    fallbackChoice: action.fallback_choice,
    fallbackReason: action.fallback_reason ?? null,
    attemptCount: action.attempt_count ?? 1,
```

- [ ] **Step 5: Render retry/fallback cues**

In `apps/web/src/features/games/liveDirector.ts`, before `model_request_started`:

```typescript
  if (event.type === "model_retry_scheduled") {
    const attempt = Number(payload.attempt ?? 0);
    return {
      ...base,
      title: `${event.actor ?? "玩家"} 正在重试行动`,
      body: `${stringField(payload, "message") || "模型输出不在候选项中，正在重试。"}${attempt ? `第 ${attempt} 次尝试。` : ""}`,
      importance: "action",
      durationMs: 3000,
      compressible: true,
    };
  }

  if (event.type === "action_quality_warning") {
    const fallbackChoice = stringField(payload, "fallback_choice");
    return {
      ...base,
      title: "行动质量提示",
      body: fallbackChoice
        ? `已使用安全兜底：${fallbackChoice}`
        : readablePayload(rawPayload),
      importance: "action",
      durationMs: 3500,
      compressible: true,
    };
  }
```

- [ ] **Step 6: Attach warning event in debug traces**

In `appendEventDetails()` in `apps/web/src/features/games/liveDebugTrace.ts`, add:

```typescript
  if (event.type === "action_quality_warning") {
    upsertNode(trace, {
      kind: "stage",
      eventId: event.id,
      label: "质量提示",
      status: "warning",
    });
    const warnings = arrayStrings(event.payload, "warnings");
    trace.warnings = uniqueStrings([...trace.warnings, ...warnings]);
    const fallbackChoice = stringField(event.payload, "fallback_choice");
    if (fallbackChoice) {
      trace.impactSummary = uniqueStrings([
        ...trace.impactSummary,
        `安全兜底：${fallbackChoice}`,
      ]);
      trace.choice = fallbackChoice;
    }
    return;
  }
```

Add helper:

```typescript
function arrayStrings(payload: unknown, field: string): string[] {
  if (!isRecord(payload)) {
    return [];
  }
  const value = payload[field];
  return Array.isArray(value) ? value.map(String) : [];
}
```

- [ ] **Step 7: Run frontend tests**

Run:

```bash
pnpm --dir apps/web test -- --run \
  src/features/games/api/adapters.test.ts \
  src/features/games/liveDirector.test.ts \
  src/features/games/liveDebugTrace.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/games/types.ts \
  apps/web/src/features/games/api/adapters.ts \
  apps/web/src/features/games/liveDirector.ts \
  apps/web/src/features/games/liveDebugTrace.ts \
  apps/web/src/features/games/api/adapters.test.ts \
  apps/web/src/features/games/liveDirector.test.ts \
  apps/web/src/features/games/liveDebugTrace.test.ts
git commit -m "feat: surface action retry fallback status"
```

---

### Task 8: Focused Regression On The Observed Partial Failure

**Files:**
- No production edits unless verification reveals a bug.

- [ ] **Step 1: Run focused API tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py \
  tests/test_werewolf_runner.py \
  tests/test_werewolf_resume.py \
  tests/test_werewolf_action_quality.py \
  tests/test_werewolf_evaluator.py
```

Expected: PASS.

- [ ] **Step 2: Run focused frontend tests**

Run:

```bash
pnpm --dir apps/web test -- --run \
  src/features/games/api/adapters.test.ts \
  src/features/games/liveDirector.test.ts \
  src/features/games/liveDebugTrace.test.ts
```

Expected: PASS.

- [ ] **Step 3: Re-run evaluator on the observed partial replay**

Run:

```bash
cd apps/api && .venv/bin/python -m app.cli evaluate-replay \
  --source ../../artifacts/real_12_player_eval_after_hardening/game_hardening_probe_20260614_01/game_partial.json
```

Expected output includes:

```text
session_id=game_hardening_probe_20260614_01
invalid_action_abort
empty_partial_logs
chain_self_explosion_overuse
```

If the artifact is not present in the execution workspace, skip this command and note that the committed fixture tests cover the same conditions.

- [ ] **Step 4: Run full API suite**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest
```

Expected: PASS.

- [ ] **Step 5: Run full web suite**

Run:

```bash
pnpm --dir apps/web test -- --run
```

Expected: PASS.

## Self-Review

- Spec coverage: Tasks 1-3 implement invalid feedback and fail-soft; Task 4 preserves partial logs; Task 5 strengthens prompts and quality checks; Task 6 extends evaluator; Task 7 surfaces retry/fallback status; Task 8 verifies the full upgrade.
- Placeholder scan: Python snippets avoid ellipsis placeholders; remaining TypeScript spread syntax is real source syntax and appears only inside frontend test/update examples.
- Type consistency: The plan uses `invalid_attempts` on `LmLog`, `invalid_value`/`fallback_choice`/`fallback_reason`/`attempt_count` on backend action logs, and camelCase equivalents on frontend `DebugItem`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-15-12-player-resilience-realism-upgrade.md`. Two execution options:

**1. Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
