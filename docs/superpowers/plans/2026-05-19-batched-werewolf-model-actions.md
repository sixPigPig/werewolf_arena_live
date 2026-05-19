# 狼人杀批量模型请求开发计划

> **给执行代理的要求：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行并用 checkbox 追踪进度。

**目标：** 将“同一动作、多名玩家、同一冻结上下文、收齐后统一结算”的模型请求改成并发发起，同时保持结算顺序、直播事件、断点恢复和历史回放兼容。

**架构：** `GameEngine` 仍保持同步阶段流程，不把整个引擎改成 async。新增一个批量动作 helper，在单个阶段步骤内部使用 `ThreadPoolExecutor` 并发执行模型调用。批量 helper 先为每个玩家冻结 `world_state`，并发请求模型，最后按标准玩家顺序写日志、更新状态、发布解析事件。断点恢复改成按 `model + prompt` 匹配缓存响应，避免并发返回顺序影响恢复确定性。

**技术栈：** Python 3.12、dataclasses、`concurrent.futures`、pytest、现有 live event sink 和 resume checkpoint 管线。

---

## 已确认范围

### 改成并发的场景

这些场景满足同一个判断标准：同一批玩家基于同一份已经冻结的上下文做同一种选择，单个玩家的结果不会改变同批其他玩家的选项，必须等所有结果收齐后才统一结算。

- `sheriff_run`：所有存活玩家同时决定 `上警 / 不上警`。
- `werewolf_self_explosion`：每个自爆检查点，所有存活狼人同时决定 `自爆 / 不自爆`。若多名狼人同时选择自爆，按当前 `active_players` 顺序结算第一名狼人。
- `sheriff_withdraw`：所有警上候选人同时决定 `退水 / 不退水`。
- `sheriff_vote`：所有警下投票者同时投警长票。
- `sheriff_runoff_vote`：警长 PK 后所有警下投票者同时二轮投票。
- `vote`：白天放逐阶段，所有有投票权玩家同时投票。
- `summarize`：回合总结阶段，所有存活玩家同时总结。
- `werewolf_kill_vote`：每一轮狼刀共识投票，所有存活狼人同时投票。

### 保持串行的场景

这些场景要么有规则顺序，要么前一个模型结果会改变后一个模型可见信息或可选项：

- `debate`、`sheriff_speech`、`sheriff_pk_speech`：公开发言有顺序，后发言者应看到前面发言内容。
- `werewolf_discuss`：狼人夜聊当前是顺序累积上下文，后发言狼人应看到前面狼人建议。
- `witch_save` 到 `witch_poison`：女巫是否能毒人依赖是否使用了解药。
- `protect`、`investigate`、`speech_order`、`hunter_shoot`、`sheriff_badge`：单人决策，不存在同类批量请求。
- 跨角色夜晚技能：狼刀、守卫、预言家、女巫之间暂不并发。本轮只做“同一动作、多名玩家”的并发。

### 删除旧抢发言权逻辑

旧 `bid` 抢发言权逻辑已经不在主流程中使用，本次顺手清理 active request 路径：

- 删除 `GameEngine._get_next_speaker()`。
- 删除后端 `ACTION_BID`。
- 删除 `prompts_zh.py` 中 `bid` schema、结果字段、字段标签和 prompt 分支。
- 删除 `debate` prompt 中的 `bidding_rationale` 引用。
- 保留 `Player.bidding_rationale`、`RoundState.bids`、`RoundLog.bid` 和前端 replay 对旧 `bid` 数据的读取能力，保证历史日志仍能打开。

---

## 关键设计

### 批量动作 helper

新增三个内部概念：

- `PlayerActionRequest`：保存一个玩家的一次模型请求，包括 player、action、options、result_key、phase、冻结后的 `world_state`、是否秘密狼人动作。
- `PlayerActionResult`：保存一次请求返回的 value 和 `LmLog`。
- `_player_actions_batch(requests)`：负责批量发布 `action_requested`，并发执行请求，最后按传入顺序 finalize。

现有 `_player_action()` 不删除，而是改成基于同一套 request / execute / finalize helper 的单请求包装。这样单人技能仍走原逻辑，批量动作和单人动作共享校验、日志和事件发布。

### 上下文冻结

所有批量请求必须先构造完整 `world_state`，再启动线程。禁止在模型请求过程中继续读取会变化的 `round_state` 内容。

例如狼刀投票每一轮都必须先固定：

- `candidates`
- `werewolf_discussion`
- `werewolf_previous_vote_round`
- `werewolf_kill_vote_round`

这样同轮狼人不会因为线程先后或前面狼人返回更早而获得额外信息。

### 顺序和结算

并发只改变“请求发起时间”，不改变“结算顺序”：

- `action_requested` 按标准玩家顺序发布。
- 模型请求可以并行返回，`model_request_started`、流式 delta、thinking tick 可能自然交错。
- `model_response_received`、`action_parsed`、`ActionLog`、`RoundState` 写入按标准玩家顺序执行。
- 白天投票、警长投票、自爆裁决、狼刀票型都按原来的玩家顺序生成稳定结果。

### 失败和断点恢复

并发后不能再依赖模型返回顺序恢复。必须先做 checkpoint 兼容改造：

- `ResumeCheckpointManager.record_success()` 保存 `prompt`。
- `ReplayThenLiveProvider` 优先按 `model + prompt` 查找缓存响应。
- 老 checkpoint 没有 `prompt` 时继续按旧的列表顺序回放。
- 批量请求中如果某个请求失败，记录第一个按玩家顺序遇到的失败请求并抛错；失败点之后即使已有线程返回，也可以在恢复时重新请求。

### 事件隐私

秘密狼人动作仍不能向公开 live event 暴露 actor 或内容：

- `werewolf_discuss` 保持秘密。
- `werewolf_kill_vote` 保持秘密。
- 公开观战仍只看到夜晚阶段和最终结算，不看到狼人私聊或狼刀票型。
- 调试数据和回放日志可以保留完整 `RoundLog`，供开发排查。

---

## 文件清单

- 修改 `apps/api/app/werewolf/checkpoint.py`：prompt-aware replay cache，线程安全。
- 修改 `apps/api/app/werewolf/engine.py`：拆分 `_player_action()`，新增批量 helper，接入所有已确认批量场景，删除 `_get_next_speaker()`。
- 修改 `apps/api/app/werewolf/prompts_zh.py`：删除 `bid` prompt 支持，删除发言动机里的 `bidding_rationale`。
- 修改 `apps/api/app/werewolf/rules.py`：删除 `ACTION_BID`。
- 修改 `apps/api/tests/test_werewolf_runner.py`：增加并发行为回归测试，更新 no-bid 测试。
- 修改 `apps/api/tests/test_werewolf_resume.py`：增加 prompt-keyed replay cache 测试。
- 修改 `apps/api/tests/test_werewolf_lm.py`：删除或改写 bid prompt/action 测试。
- 修改 `apps/api/tests/test_werewolf_rules.py`：保留官方规则集不包含 `"bid"` 的断言。

---

## 任务 1：让断点恢复支持并发缓存

**文件：**

- 修改：`apps/api/app/werewolf/checkpoint.py`
- 修改：`apps/api/app/werewolf/engine.py`
- 测试：`apps/api/tests/test_werewolf_resume.py`

- [ ] **步骤 1：写失败测试**

在 `apps/api/tests/test_werewolf_resume.py` 增加测试：

```python
def test_replay_provider_matches_cached_responses_by_prompt_when_available() -> None:
    delegate = ScriptedProvider()
    provider = ReplayThenLiveProvider(
        cached_model_responses=[
            {
                "actor": "Alice",
                "action": "vote",
                "phase": "vote",
                "model": "model-a",
                "prompt": "prompt-a",
                "raw_response": '{"reasoning":"A","vote":"Bob"}',
            },
            {
                "actor": "Bob",
                "action": "vote",
                "phase": "vote",
                "model": "model-b",
                "prompt": "prompt-b",
                "raw_response": '{"reasoning":"B","vote":"Alice"}',
            },
        ],
        delegate=delegate,
    )

    second = provider.complete_json(model="model-b", prompt="prompt-b", temperature=0.4)
    first = provider.complete_json(model="model-a", prompt="prompt-a", temperature=0.4)

    assert json.loads(second)["vote"] == "Alice"
    assert json.loads(first)["vote"] == "Bob"
    assert delegate.calls == 0
```

- [ ] **步骤 2：确认测试失败**

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_resume.py::test_replay_provider_matches_cached_responses_by_prompt_when_available -q
```

预期：失败，因为当前 `ReplayThenLiveProvider` 只按列表顺序回放缓存。

- [ ] **步骤 3：实现 prompt-aware replay cache**

在 `apps/api/app/werewolf/checkpoint.py` 中：

- 引入 `threading`。
- 给 `ReplayThenLiveProvider` 增加锁。
- 优先用 `model + prompt` 匹配缓存响应。
- 没有 prompt 的旧缓存继续按 `_index` 顺序回放。

核心实现形态：

```python
class ReplayThenLiveProvider:
    def __init__(
        self,
        *,
        cached_model_responses: list[dict[str, Any]],
        delegate: ModelProvider,
    ) -> None:
        self._cached_model_responses = copy.deepcopy(cached_model_responses)
        self._delegate = delegate
        self._index = 0
        self._lock = threading.Lock()

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        with self._lock:
            prompt_match_index = self._find_prompt_match(model=model, prompt=prompt)
            if prompt_match_index is not None:
                response = self._cached_model_responses.pop(prompt_match_index)
                return str(response["raw_response"])

            if self._index < len(self._cached_model_responses):
                response = self._cached_model_responses[self._index]
                self._index += 1
                return str(response["raw_response"])

        return self._delegate.complete_json(model=model, prompt=prompt, temperature=temperature)
```

- [ ] **步骤 4：checkpoint 成功记录写入 prompt**

扩展 `GameCheckpointManager.record_success()` 和 `GameEngine._checkpoint_model_success()`，增加可选参数：

```python
prompt: str | None = None
```

在 `_player_action()` 成功时传入：

```python
prompt=lm_log.prompt
```

保存缓存时写入：

```python
if prompt is not None:
    cached_response["prompt"] = prompt
```

- [ ] **步骤 5：验证**

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_resume.py -q
```

预期：通过。

- [ ] **步骤 6：提交**

```bash
git add apps/api/app/werewolf/checkpoint.py apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_resume.py
git commit -m "fix(api): make resume replay prompt-aware"
```

---

## 任务 2：新增批量动作基础设施

**文件：**

- 修改：`apps/api/app/werewolf/engine.py`
- 测试：`apps/api/tests/test_werewolf_runner.py`

- [ ] **步骤 1：写警长上警并发失败测试**

在 `apps/api/tests/test_werewolf_runner.py` 引入：

```python
import threading
```

新增测试 provider：

```python
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
            return json.dumps({"reasoning": "本轮不上警。", "run": "不上警"}, ensure_ascii=False)
        return super().complete_json(model=model, prompt=prompt, temperature=temperature)
```

新增测试：

```python
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
    engine = GameEngine(state=state, provider=provider, max_rounds=8, rule_set=rule_set)
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)

    engine._run_sheriff_election_if_needed(round_state, round_log, active_players)

    assert [actor for action, actor in provider.actions if action == "sheriff_run"] == active_players
    assert round_state.sheriff_candidates == []
    assert round_state.sheriff_voters == active_players
```

- [ ] **步骤 2：确认测试失败**

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_sheriff_run_requests_all_players_concurrently -q
```

预期：失败，当前逐个请求会卡在 barrier。

- [ ] **步骤 3：增加请求和结果数据结构**

在 `apps/api/app/werewolf/engine.py` 增加：

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
```

增加：

```python
@dataclass(frozen=True)
class PlayerActionRequest:
    player: Player
    action: str
    options: list[str]
    result_key: str
    round_state: RoundState
    phase: str
    world_state: dict[str, object]
    is_secret_wolf_action: bool


@dataclass(frozen=True)
class PlayerActionResult:
    request: PlayerActionRequest
    value: object | None
    lm_log: object
```

- [ ] **步骤 4：拆分 `_player_action()`**

新增三个内部方法：

- `_build_player_action_request(...)`
- `_execute_player_action_request(request)`
- `_finalize_player_action_result(result)`

要求：

- `_build...` 负责冻结 `world_state`。
- `_execute...` 只请求模型，不写 `RoundState`。
- `_finalize...` 按顺序写 checkpoint、发 `model_response_received`、发 `action_parsed`、构造 `ActionLog`、做 options 校验。

然后把 `_player_action()` 改成这三个方法的单请求包装，保证原有单人动作行为不变。

- [ ] **步骤 5：新增 `_player_actions_batch()`**

新增方法：

```python
def _player_actions_batch(
    self,
    requests: list[PlayerActionRequest],
) -> list[tuple[object | None, ActionLog]]:
    ...
```

行为要求：

- 空列表返回 `[]`。
- 单个请求走单请求路径。
- 多个请求先按顺序发布非秘密动作的 `action_requested`。
- 使用 `ThreadPoolExecutor(max_workers=len(requests))` 并发执行。
- 收齐所有 future 后按 `requests` 原顺序 finalize。
- 如果有异常，按 `requests` 原顺序记录第一个失败并抛出。

- [ ] **步骤 6：先接入 `sheriff_run`**

把 `_run_sheriff_election_if_needed()` 里的上警循环改成：

```python
run_requests = [
    self._build_player_action_request(
        player=players_by_name[name],
        action=ACTION_SHERIFF_RUN,
        options=[SHERIFF_RUN, SHERIFF_SKIP],
        result_key="run",
        round_state=round_state,
        phase="day",
    )
    for name in active_players
]
for name, (run_choice, action_log) in zip(
    active_players,
    self._player_actions_batch(run_requests),
    strict=True,
):
    round_log.sheriff_run.append(action_log)
    if run_choice == SHERIFF_RUN:
        candidates.append(name)
    else:
        voters.append(name)
```

- [ ] **步骤 7：验证并提交**

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_sheriff_run_requests_all_players_concurrently -q
```

预期：通过。

提交：

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat(api): add batched player action helper"
```

---

## 任务 3：接入所有已确认批量场景

**文件：**

- 修改：`apps/api/app/werewolf/engine.py`
- 测试：`apps/api/tests/test_werewolf_runner.py`

- [ ] **步骤 1：增加通用 barrier provider**

在 `apps/api/tests/test_werewolf_runner.py` 增加：

```python
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
        del model, temperature
        name = _extract_actor_name(prompt)
        if f'"{self.result_key}"' in prompt:
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
```

- [ ] **步骤 2：接入白天放逐投票**

写失败测试：所有有投票权玩家用 barrier 同时返回 `vote`。

然后把 `_run_voting()` 改成批量请求：

- 请求对象列表按 `_eligible_voters(active_players)` 顺序生成。
- 每名玩家 options 仍是除自己外的当前存活玩家。
- finalize 后按 voter 顺序写 `votes`、`vote_weights`、`logs`。

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_day_vote_requests_eligible_voters_concurrently -q
```

预期：通过。

- [ ] **步骤 3：接入狼人自爆检查**

写失败测试：多名狼人进入同一个自爆检查点，provider 用 barrier 证明所有狼同时收到请求。

实现要求：

- `_maybe_run_werewolf_self_explosion()` 对所有 `active_wolves` 建请求。
- 全部请求使用同一个 `self_explosion_stage`。
- 收齐后按 `active_wolves` 顺序找第一名 `WEREWOLF_SELF_EXPLODE`。
- 如果找到，设置 `round_log.werewolf_self_explosion`，调用 `_resolve_werewolf_self_explosion()`，返回 `True`。
- 如果都不自爆，返回 `False`。

运行对应测试，预期通过。

- [ ] **步骤 4：接入警长退水和警长投票**

把以下循环改成批量请求：

- `sheriff_withdraw`：按 `candidates` 顺序。
- `sheriff_vote`：按 `voters` 顺序。
- `sheriff_runoff_vote`：按 `voters` 顺序。

不改：

- `sheriff_speech`
- `sheriff_pk_speech`

运行：

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_sheriff_election_runs_pk_and_runoff_when_first_vote_ties \
  tests/test_werewolf_runner.py::test_sheriff_election_limits_speeches_to_candidates_and_votes_to_off_sheriff_players \
  -q
```

预期：通过。

- [ ] **步骤 5：接入狼刀共识投票**

只改 `werewolf_kill_vote`，不改 `werewolf_discuss`。

在 `_run_werewolf_kill_consensus()` 每一轮投票前冻结：

```python
discussion_context = self._werewolf_discussion_context(round_state)
previous_vote_context = self._werewolf_vote_round_context(previous_vote_round)
```

然后为所有 `active_wolves` 建同一轮请求，并发执行。收齐后按 `active_wolves` 顺序写：

- `votes`
- `vote_logs`
- `round_log.werewolf_votes`
- `round_state.werewolf_vote_rounds`

运行：

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py::test_werewolf_consensus_first_vote_sets_attacked \
  tests/test_werewolf_runner.py::test_werewolf_consensus_revotes_until_unanimous \
  tests/test_werewolf_runner.py::test_werewolf_consensus_can_converge_on_third_vote \
  -q
```

预期：通过。

- [ ] **步骤 6：接入回合总结**

把 `_run_summaries()` 改成批量请求：

- 按 `active_players` 建请求。
- 并发执行 `summarize`。
- 按 `active_players` 顺序写 `round_state.summaries` 和 `player.observations`。
- `state_updated` 仍按玩家顺序发布。

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_runs_game_and_writes_chinese_log -q
```

预期：通过。

- [ ] **步骤 7：后端 focused 验证并提交**

运行：

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py \
  tests/test_werewolf_resume.py \
  -q
```

预期：通过。

提交：

```bash
git add apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat(api): batch independent werewolf model actions"
```

---

## 任务 4：删除 active bid 支持

**文件：**

- 修改：`apps/api/app/werewolf/engine.py`
- 修改：`apps/api/app/werewolf/prompts_zh.py`
- 修改：`apps/api/app/werewolf/rules.py`
- 修改：`apps/api/tests/test_werewolf_lm.py`
- 修改：`apps/api/tests/test_werewolf_runner.py`
- 测试：`apps/api/tests/test_werewolf_rules.py`

- [ ] **步骤 1：写 bid 不再支持的失败测试**

在 `apps/api/tests/test_werewolf_lm.py` 增加：

```python
def test_bid_prompt_is_no_longer_supported() -> None:
    with pytest.raises(ValueError, match="Unsupported action: bid"):
        build_prompt("bid", _world_state_for_special_action("村民", "Alice、Bob"))
```

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_lm.py::test_bid_prompt_is_no_longer_supported -q
```

预期：失败，因为当前还支持 bid。

- [ ] **步骤 2：删除 prompt 层 bid 支持**

在 `apps/api/app/werewolf/prompts_zh.py` 中删除：

- `SCHEMAS["bid"]`
- `RESULT_FIELD_BY_ACTION["bid"]`
- `FIELD_LABELS["bid"]`
- `_render_instruction()` 中 `if action == "bid":` 分支
- `debate` 分支中的 `bidding_rationale` 文案

重新运行 no-bid 测试，预期通过。

- [ ] **步骤 3：删除规则常量**

在 `apps/api/app/werewolf/rules.py` 删除：

```python
ACTION_BID = "bid"
```

运行：

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_rules.py -q
```

预期：通过。

- [ ] **步骤 4：删除引擎旧 helper**

在 `apps/api/app/werewolf/engine.py` 删除：

```python
def _get_next_speaker(...)
```

并从 `_world_state()` 删除：

```python
"bidding_rationale": player.bidding_rationale,
```

保留模型和历史数据字段：

- `Player.bidding_rationale`
- `RoundState.bids`
- `RoundLog.bid`

这些字段只用于兼容旧日志，不再由新引擎主动写入。

- [ ] **步骤 5：更新测试**

在 `apps/api/tests/test_werewolf_lm.py` 中，把仍调用 `generate_action(action="bid")` 的测试改为 `vote` 或其他仍支持的 action。

保留 `test_small_rule_day_phase_uses_full_seat_order_without_bids()`，它用于证明当前主流程不会请求 bid。

- [ ] **步骤 6：验证并提交**

运行：

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_lm.py \
  tests/test_werewolf_rules.py \
  tests/test_werewolf_runner.py::test_small_rule_day_phase_uses_full_seat_order_without_bids \
  -q
```

预期：通过。

提交：

```bash
git add apps/api/app/werewolf/engine.py apps/api/app/werewolf/prompts_zh.py apps/api/app/werewolf/rules.py apps/api/tests/test_werewolf_lm.py apps/api/tests/test_werewolf_runner.py apps/api/tests/test_werewolf_rules.py
git commit -m "refactor(api): remove active bid action support"
```

---

## 任务 5：直播事件和确定性回归

**文件：**

- 修改：`apps/api/tests/test_werewolf_runner.py`
- 修改：`apps/api/tests/test_werewolf_resume.py`
- 修改：`apps/api/tests/test_games_api.py`

- [ ] **步骤 1：验证 `action_requested` 顺序**

新增测试：触发警长上警并发批次，收集 live sink 中：

```python
event["type"] == "action_requested" and event["action"] == "sheriff_run"
```

断言 actor 列表等于 `active_players`。

- [ ] **步骤 2：验证秘密狼人动作不泄露**

扩展 `test_werewolf_consensus_live_events_do_not_publish_wolf_actor()`：

- 不允许公开事件里出现 `werewolf_discuss` actor。
- 不允许公开事件里出现 `werewolf_kill_vote` actor。
- 并发后这个测试仍必须通过。

- [ ] **步骤 3：验证 checkpoint 写入 prompt**

在已有失败恢复测试中，至少有一次成功模型调用后断言：

```python
assert "prompt" in checkpoint["cached_model_responses"][0]
```

- [ ] **步骤 4：运行 API focused 测试**

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_werewolf_runner.py \
  tests/test_werewolf_resume.py \
  tests/test_games_api.py \
  -q
```

预期：通过。

- [ ] **步骤 5：提交**

```bash
git add apps/api/tests/test_werewolf_runner.py apps/api/tests/test_werewolf_resume.py apps/api/tests/test_games_api.py
git commit -m "test(api): cover batched action event ordering"
```

---

## 任务 6：最终验证

**文件：**

- 不修改文件。

- [ ] **步骤 1：运行后端完整测试**

```bash
cd apps/api && .venv/bin/python -m pytest -q
```

预期：通过。

- [ ] **步骤 2：必要时运行前端 smoke**

如果实施时改动了 replay payload、前端 adapter 或 live event 字段，运行：

```bash
pnpm --dir apps/web exec vitest run src/pages/GamePlaybackPage.test.tsx src/pages/LiveGamePage.test.tsx
pnpm --dir apps/web exec tsc --noEmit
```

预期：通过。

- [ ] **步骤 3：检查 diff**

```bash
git diff --stat main...HEAD
git diff --check
```

预期：

- 没有 whitespace error。
- 只包含本计划列出的文件。
- 没有重新引入 active `bid` 请求路径。

---

## 实施检查清单

- 并发只用于“同一动作、多名玩家、同一冻结上下文”。
- 跨角色夜晚技能不并发。
- 公开发言、警上发言、PK 发言和狼人夜聊不并发。
- 自爆多人同时选择时，按 `active_players` 顺序结算第一名狼人。
- checkpoint 先完成 prompt-aware replay，再接入并发。
- 新游戏不能再生成 `bid` 模型请求。
- 历史 replay 中已有的 `bids` / `bid` 数据仍能读取。
- 所有批量动作的最终 `ActionLog` 和 `RoundState` 写入顺序稳定。
