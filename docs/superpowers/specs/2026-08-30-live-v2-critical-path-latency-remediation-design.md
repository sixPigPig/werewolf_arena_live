# Live V2 关键路径耗时治理开发文档

**Date:** 2026-08-30

**Status:** A1 开发中。合同 V5、提交锁与日终后台记忆已落地；未收到“提交代码”前不 commit。A2 / B1 / B2 仍未授权。

**Priority:** P0 日终记忆阻塞入夜 / P1 Provider 批次排队 / P1 夜间第二轮串行合议 / P2 动作级思考分层

**Source Game:** `v2_game_b722305ceafc4d36`

**Source Run:** `v2_run_3b932928ef3b42f2`

**Scope:** `apps/api/app/match` 的日终私密记忆提交、generation policy 合同、夜间狼刀第二轮、E1 并发 canary 的生产决策门；`apps/api/tests` 的对应回归。不改大厅、规则目录、玩家库、TTS 适配、Mobile Live 页面或 Replay。

**Related Designs:**

- `docs/superpowers/specs/2026-08-10-live-v2-model-output-budget-and-latency-remediation-design.md`
- `docs/superpowers/specs/2026-08-08-live-v2-model-context-v11-contract-hardening-design.md`
- `docs/live-v2-refactor-guidelines.md`
- `docs/live-v2-realtime-action-protocol.md`

**对照复盘:**

- [本局战报](/Users/fanqiedanhuatang/.cursor/projects/Users-fanqiedanhuatang-Documents-werewolf-arena-live/canvases/v2-game-b722-match-review.canvas.tsx)
- [耗时排序](/Users/fanqiedanhuatang/.cursor/projects/Users-fanqiedanhuatang-Documents-werewolf-arena-live/canvases/v2-game-b722-latency-plan.canvas.tsx)

---

## 0. 审批边界

开发前门禁：

1. 固化实局证据（第 2 节，已完成）；
2. 按风险排序工作包（第 1.2 节）；
3. 用户明确回复“通过”“进入开发”或同等含义。

对本文的批准：

- **只授权** 第 1.2 节里标记为「本次实施」的工作包，以及这些包的隔离测试；
- **不授权** Git commit、push、生产发布、修改生产 `LIVE_V2_AGENT_PLAN_MAX_IN_FLIGHT`、回放含私密身份的冻结请求、产生未经确认的按量费用；
- **不自动批准** B1、B2、C 线产品改形态。它们写在本文是为了把后续边界钉死，避免 A1 预埋半成品。

按 `docs/live-v2-refactor-guidelines.md`：默认一次只开发一个最小环节。本文把 A1 定为第一个可独立验收的环节。用户可以在批准时写明“A1+A2 一并开发”，否则只做 A1。

---

## 1. 结论与实施顺序

### 1.1 问题定性

`v2_game_b722305ceafc4d36` 不是卡死，也不是等人：

- `game_completed` 已持久化，胜方 werewolves，原因 `deterministic_win_condition`；
- 单 run，`v2_model_action_recoveries` 为空，0 次 `action_paused`；
- wall time 5,305.4 秒（88.4 分钟）；模型 attempt 并集 4,219.3 秒（79.5%）。

8 月 10 日那局的主病（失败后等管理员）已经不在。本局剩下的是关键路径上的模型思考和被错误放在入夜之前的辅助批次。

连接和首 token 不是瓶颈：成功请求首 token P50 2.8 秒，首个可见文本 P50 31.3 秒，完成 P50 35.7 秒。大约 23 秒耗在 reasoning 已开始、可见 JSON 还没出现。

### 1.2 工作包

| 顺序 | 工作包 | 本次范围 | 直接可观察结果 | 本局外推 |
| --- | --- | --- | --- | ---: |
| 1 | A1：日终私密记忆改为夜间后台写 | **本次实施（需批准）** | 入夜不再等记忆批次；法官日结播报后立刻 `finish_day` | −6 到 −9 分钟 |
| 2 | A2：Agent Plan 并发 canary 后升槽 | 规格写清；**不改生产默认** | 离线/隔离 canary 报告 3/4/6 的 queue 与错误率 | −3 到 −6 分钟 |
| 条件项 | B1：狼刀第二轮减串行 | 本次不实施 | 第一轮已经并行；只改分歧后的 `sequential_final_vote` | −5 到 −8 分钟 |
| 条件项 | B2：boolean_light 思考分层 | 本次不实施 | 报名/退水/自爆允许降 effort；发言和归刀保持 strategic_full | −5 到 −8 分钟 |
| 否决 | A3：发言 lookahead 1→2 | 本次不实施 | 生成 35 秒、播报 10 秒，多超前一人盖不住空洞 | 小 |
| 产品 | C：12–18 分钟 SLO | 不在工程包 | 减人数/无警徽/短发言/非 thinking，是产品合同 | 才可能靠近 18 分 |

外推只基于这一局 n=1，且 A1 落地后 A2 对记忆批次的收益会消失。不得把数字相加写成 SLA。

### 1.3 明确否决

- 不加大 `max_tokens`、300 秒 hard timeout、first-token 或 stream-idle。本局猎人 D3 投票产生 8,192 个 reasoning delta、0 个可见字。
- 不按当前 C1 阈值（发言 180 秒 / 记忆 240 秒）启用 C2。本局 `shadow_would_timeout=0`，启用等于没启用。
- 不关闭投票、自爆、夜间归刀、神职技能的 Thinking。
- 不用系统随机目标、多数票硬切、规则推测或 hint 伪造模型决定。
- 不把 `reuse_previous_non_blocking` 做成“复用上一轮记忆、跳过本轮生成”。该字符串已被 V4 校验列为未知值 fail closed。A1 的新值是 `background_generation`：本轮仍生成，只是不挡入夜。
- 不新增模型路由、跨 Provider fallback、自动换模型。
- 不改历史事件，不回填旧局 `rule_snapshot`。
- 不把字符数、上下文压缩或单局模型耗时差异写成窗口溢出或模型质量排名。

---

## 2. 实局证据

时间均为 UTC。对局创建 `2026-08-20 06:15:00`，run 完成 `07:43:28`。

### 2.1 关键路径块

| 块 | attempt 并集 | 次数 | 完成 P50 | 是否挡观众 |
| --- | ---: | ---: | ---: | --- |
| `day_debate_speech` | 1,283 秒 | 30 | 35.7 秒 | 是，白天串行；lookahead=1 |
| `ability_werewolf.attack_decision` | 904 秒 | 38 | 27.7 秒 | 是，夜；第一轮已并行，第二轮串行 |
| `exile_vote` | 592 秒 | 46 | 21.5 秒 | 部分；16 次预取撞并发槽 3 |
| `private_round_memory` | 520 秒 | 28 | 94.9 秒 | **是，挡入夜** |
| `werewolf_self_explosion` | 515 秒 | 28 | 46.8 秒 | 是，讨论开头 / 放逐前 |

日终记忆批次墙钟（`day_private_memory_batch_started` → `completed`）：

| 轮 | 开始 | 结束 | 墙钟 | 随后入夜 |
| --- | --- | --- | ---: | --- |
| D1 | 06:41:19 | 06:43:22 | 123 秒 | 06:43:26 `night_2` |
| D2 | 07:07:42 | 07:10:16 | 154 秒 | 07:10:21 `night_3` |
| D3 | 07:29:54 | 07:33:59 | 245 秒 | 07:34:06 `night_4` |

合计 522 秒。这三分钟到四分钟里观众只听到一句“即将入夜”，然后空等。D3 更长，是因为同批里混进了输出预算耗尽。

### 2.2 夜间狼刀已经并行的部分

`NightEngine` 的 `preference_probe` 已用 `asyncio.gather` 并行盲选。本局 N1 四张初选时间戳同为 `06:15:19`。随后 `sequential_final_vote` 才串行：`06:15:42` / `06:16:39` / `06:17:03` / `06:17:31`。

本局五夜初选都不一致，因此每夜都走完四次第二轮。B1 若写成“把第一轮改并行”，是在改已经存在的行为。B1 只允许动第二轮。

### 2.3 并发与失败

- Agent Plan 默认 `LIVE_V2_AGENT_PLAN_MAX_IN_FLIGHT=3`，DeepSeek 32。
- 21 次失败：16 `model_prefetch_capacity_unavailable`（放逐预取）、3 `model_empty_stream`（DeepSeek）、2 `model_output_budget_exhausted`。
- 16 次容量失败都恢复成有效票；猎人 D3 记技术弃票。没有人工重试。

### 2.4 生成策略合同现状

`MODEL_GENERATION_POLICY_SCHEMA_VERSION = 4`，`enforcement=observe_only`，`reasoning_parameter_mode=inherit_frozen_model_configuration`。

- profile 只能改 `reasoning_only_timeout_ms` / `timeout_max_attempts`，**不能改 effort**。
- `private_round_memory_mode` 只接受 `blocking_generation`。缺合同的旧局解析为 `blocking_generation`（保持旧运行时，不是关闭记忆）。
- `private_round_memory` 映射 `isolated_auxiliary`，超时 240 秒，失败跳过，不暂停整局。

### 2.5 提交锁：为什么不能“入夜后再写”而不改仓库

`MatchRepository.record_private_round_memories()` 当前要求：

1. `game.phase_id.startswith("day_")`；
2. `phase_id` / `phase_state` / `round_no` / `run_id` 与提交参数完全一致；
3. owner **此刻** `alive`。

测试 `test_private_round_memory_batch_rejects_changed_frozen_phase_atomically` 和 `test_new_policy_generates_private_memory_before_advancing_night` 把“记忆提交 record_seq < `game_phase_changed`”写成了不变量。

若 A1 只把 `await` 挪到 `finish_day` 之后、不改这条锁，夜间一推进提交就会整批失败。若记忆拖过夜间刀口，被刀玩家还会撞上 “owner must be alive”。

A1 的核心不是“少 await 一行”，而是重写提交不变量。

---

## 3. 目标、非目标与不变量

### 3.1 A1 目标

在不改记忆正文语义、不删可见事实、不改 Thinking 参数的前提下：

1. 新局日终法官播报结束后立即进入夜晚；
2. 本轮滚动记忆在夜间（及必要时次日开场前）继续生成并提交；
3. 夜间刀口、神职、自爆、投票都不读取“刚刚这轮还没写完的记忆”；
4. 次日该玩家第一条需要 `private_round_memory` 的模型动作，只等待 **自己** 那条，不等整批；
5. 旧 V4 冻结合同的对局继续 `blocking_generation`，行为与今天完全相同。

### 3.2 非目标

- 不承诺整局 18 分钟，不承诺发言 P50 从 36 秒降到 15 秒；
- 不在 A1 改并发默认、lookahead、狼刀协议或 effort；
- 不把记忆改成摘要模型或固定模板；
- 不让 normal / god-view Mobile 看到记忆正文以外的诊断。

### 3.3 必须保持的不变量

1. 模型可见身份只用 `seat_N`。
2. 记忆原文按现有 `schema_version=2` 事实写入；不改 hash 算法，不改 `source_refs` 计算。
3. 每条记忆仍绑定 `action_id`、`attempt_id`、`model_response_record_seq`、request/context sha256。缺 lineage 不得提交。
4. 同一 `(game_id, owner_id, round_no)` 最多一条有效记忆。重放提交复用，不双写。
5. `source_cutoff_record_seq` 冻结在日终批次开始时，不随夜间事件前移。
6. 未知 generation policy 合同 fail closed；缺合同的旧局保持 blocking。
7. 法官 `judge_day_summary` 失败仍阻止入夜（公开日结失败不能偷偷进夜）。
8. required target 仍不得随机补齐；记忆失败仍跳过，不暂停、不伪造正文。
9. 模型 reasoning 正文不持久化。
10. 运行时不得按角色名写死阶段顺序。A1 只动记忆提交与 day close，不把“狼人先行动”写进 `flow_engine`。

---

## 4. 当前代码根因

### 4.1 日终把辅助批次绑在阶段推进上

`DayEngine._close_day()` 在 `summarize=True` 时：

1. `_run_day_summary_and_private_memories()` 里并行拉起全部存活玩家的记忆，并与 `judge_day_summary` `gather`；
2. 全部完成后 `record_private_round_memories()` 一次性提交；
3. 然后才 `finish_day()`。

法官播报本身只要数秒。墙钟被记忆 P50 95 秒和并发槽 3 拉长。

### 4.2 提交函数把“还在当天阶段”当成正确性

这在 blocking 模式下是合理的防串台。后台模式下必须改成：批次身份（`batch_id` + `round_no` + `source_cutoff` + 启动时的 `origin_phase_id`）不变，游戏当前 `phase_id` 可以离开当天。

### 4.3 第一轮狼刀已经并行

`first_night_engine.py` 中 `coordination=parallel_preference_probe` 已存在。本局 904 秒主要来自分歧后的顺序终票，不是初选。

### 4.4 并发槽与预取

白天放逐预取会同时打满 Agent Plan 3 槽。容量失败可恢复，但 queue P95 88 秒仍是墙钟。E1 离线 harness 已在 `model_concurrency_canary.py`，live runner 未实现，生产默认仍是 3。

---

## 5. Work Package A1：`background_generation`

### 5.1 合同

`MODEL_GENERATION_POLICY_SCHEMA_VERSION`：4 → **5**。

V5 与 V4 的唯一合法差异：

```text
execution.private_round_memory_mode = "background_generation"
```

其余字段、profile、action_profiles、required_target_exhaustion、enforcement、reasoning_parameter_mode 与 V4 完全相同。

校验规则：

| 合同 | 结果 |
| --- | --- |
| 缺 `model_generation_policy_contract` | 解析为 legacy，记忆模式 `blocking_generation` |
| V4 且 mode=`blocking_generation` | 支持，行为不变 |
| V5 且 mode=`background_generation` | 支持，走 A1 运行时 |
| V4/V5 但 mode 为其它字符串，包括 `reuse_previous_non_blocking` | `unsupported_model_generation_policy_contract` |
| schema 3 或 6+、缺键、多键 | fail closed |

`current_model_generation_policy_contract()` 对新局只发射 V5。`freeze_*` 覆盖写入，不保留创建请求里的旧合同碎片。

`ResolvedModelGenerationPolicy.private_round_memory_mode` 扩展为：

```text
"blocking_generation" | "background_generation" | "disabled"
```

`disabled` 只用于“合同存在但该动作被显式关”的未来值；V5 不发射它。

### 5.2 运行时序

```text
_close_day(summarize=True, V5):
  1. 冻结 cutoff、每人 source_refs、上一轮记忆快照
  2. 写 day_private_memory_batch_started
       mode=background_generation
       origin_phase_id / origin_phase_state
  3. 为每个存活玩家 create_task(_generate_private_round_memory)
       action claim 使用已有 non_blocking / defer_presentation 通道
  4. await judge_day_summary
       失败：取消未完成记忆任务，写 batch_completed.public_summary_status=failed，
             memories=[]，不 finish_day（与今天一致）
  5. 不 await 记忆任务
  6. finish_day → 广播 game_phase_changed
  7. 返回；FlowEngine 照常 announce_nightfall + NightEngine.run

记忆任务（仍在持有 lease 的同一 worker）:
  成功且 lineage 完整 → record_private_round_memory（单条）
  生成为空 / 失败 → 记 generation_failed，不写 fact
  owner 在提交瞬间已死亡 → 仍允许提交，若正文合法则写入；
       次日该玩家已死，不会被读到
  全部终态 → day_private_memory_batch_completed

DayEngine.run 次日开场（或任何将构建含 private_round_memory 的模型上下文之前）:
  await 该玩家 round_{n-1} 记忆任务，上限 = isolated_auxiliary 的
        reasoning_only_timeout_ms（240s）剩余值，不得再开一轮新的 blocking 整批
  仍未就绪：按现有 isolated_auxiliary 跳过，使用上一轮快照；
        写 private_round_memory_wait_expired（god_view）
```

`judge_day_summary` 必须仍在 `finish_day` 之前。它是公开“第 N 天结束、即将入夜”的唯一观众锚点。A1 省的是记忆，不是这句法官词。

### 5.3 提交不变量（替换 4.2）

新增 `record_private_round_memory()` 单条提交。整批一次性 API 保留给 V4 blocking 路径。

单条提交允许，当且仅当：

1. `batch_id` 已有 `day_private_memory_batch_started`，且未终态；
2. `run_id` 仍是 `game.current_run_id`；
3. `round_no` 与 started 事件一致；
4. `source_cutoff_record_seq` 与 started 事件一致，且 `<= game.last_record_seq`；
5. 当前 `phase_id` 是以下之一：
   - started 时的 `origin_phase_id`（仍在当天，兼容测试与早提交）；
   - `night_{round_no+1}` 及其 nightfall/night_running；
   - `day_{round_no+1}`（夜极短、记忆尚未写完就天亮）；
   - 终局 `day_*` / `game_completed`（允许补写，不得挡 `awaiting_observation` 超过 1 秒；见 5.5）；
6. `source_refs` / sha256 / model lineage 与今天相同；
7. 同一 `(owner_id, round_no)` 已有 fact 则 reuse，返回已有 id。

**删除** “当前必须是 day 且 phase_state 未变” 和 “owner 此刻必须存活” 作为硬条件。改为：

- owner 在 `source_cutoff` 时必须存活（用当时 `v2_player_states` 历史或 started 事件里的 `player_ids` 列表校验）；
- 提交时已死亡：**仍写入**。记忆描述的是白天刚结束时的私人结论，不是尸体发言。

V4 blocking 路径继续走旧函数，旧测试一句不改语义。

### 5.4 与夜间动作的并发

夜间 `preference_probe` 已经 `gather`。A1 再叠一批 `private_round_memory`，同 run、同 fence、同 Provider 槽。

约束：

- 记忆 action 必须 `non_blocking=True`，失败不得把 run 打成 failed；
- 记忆不得打开 night ability window，不得写 night 结算；
- Provider 槽争用可以让夜刀更慢——这是可接受的交换：观众已经在看夜，而不是看黑场。A1 验收看的是“日终到首个狼刀”的空隙，不是夜刀 P50。
- 取消 / stop / ownership lost：取消未完成记忆任务，写 `day_private_memory_batch_canceled`，与今天一致。

`DayEngine` 持有 `_background_memory_jobs: dict[str, BackgroundMemoryJob]`，key=`batch_id`。`FlowEngine.run` 在 run 结束（完成/失败/取消）时必须 `await job.wait(timeout=1.0)` 后 cancel，避免泄漏。

### 5.5 终局与自爆日

- 白天因胜负直接 `_close_day` 且 `winner is not None`：不启动新记忆批次（与今天一致）。
- 自爆日若规则 `day_actions` 不含 `summarize`：不启动批次。
- 若批次已启动、随后夜刀触发屠边：允许在 `game_completed` 后单条提交；`awaiting_observation` 不得因为等记忆而推迟超过 1 秒。超时则 cancel 剩余任务，`batch_completed` 带 `truncated_by=game_completed`。

### 5.6 事件合同

现有事件保持名字。V5 新增或加严字段：

| 事件 | 变化 |
| --- | --- |
| `day_private_memory_batch_started` | 必有 `private_round_memory_mode`；V5 加 `origin_phase_id`、`origin_phase_state`、`source_cutoff_record_seq` |
| `private_round_memory_committed` | **新**。单条提交成功。audience=`god_view`。字段：`owner_id`、`round_no`、`batch_id`、`knowledge_fact_id`、`phase_id_at_commit` |
| `day_private_memory_batch_completed` | 增加 `commit_phase_ids`（实际提交时所在 phase 的去重列表）；`memories[].status` 仍为 `committed` / `reused` / `generation_failed` |
| `private_round_memory_wait_expired` | **新**。次日等自己的记忆超时。god_view |
| `private_round_memory_normalized` | 不变 |

normal / god-view 直播协议不新增对玩家可见字段。Admin 事件列表按现有投影，新事件走 god_view。

### 5.7 次日等待

只在构建该玩家模型上下文且 selector 会读取 `private_round_memory` 时等待。夜间神职、狼刀、法官播报 **禁止** 等待本轮未完成记忆。

等待粒度：`(game_id, owner_id, round_no)` 一个 Event，不是整批 Event。

### 5.8 主要改动文件

| 文件 | 变化 |
| --- | --- |
| `apps/api/app/match/model_generation_policy_contract.py` | V5 发射与双版本校验 |
| `apps/api/app/match/day_engine.py` | close 时序、后台 job、次日等待 |
| `apps/api/app/match/match_repository.py` | 单条提交、放宽 phase/alive |
| `apps/api/app/match/flow_engine.py` | run 结束时回收后台 job |
| `apps/api/tests/test_v2_protocol_units.py` | V5 合同；V4 仍绿 |
| `apps/api/tests/test_v2_api.py` | 新增后台路径；blocking 旧测试保持 |

### 5.9 A1 验收

自动化：

1. V5 新局：`judge_day_summary` 的 `speech_closed` / 成功事件 record_seq **小于** 入夜 `game_phase_changed`；`day_private_memory_batch_completed` 允许 **大于** 入夜 `game_phase_changed`。
2. V4 旧冻结：行为与今天完全相同，`completed.record_seq < phase_changed.record_seq` 仍成立。
3. 夜间提交：`finish_day` 后插入单条 commit，不报 `phase changed`；fact 可被次日 snapshot 读到。
4. 提交时 owner 已死、但在 cutoff 存活：fact 仍写入。
5. 法官日结失败：不入夜、不写 fact，与 `test_new_policy_summary_failure_does_not_skip_memory_or_advance_phase` 相同。
6. 取消：`batch_canceled`，无泄漏任务。
7. 次日等待超时：写 `wait_expired`，使用上一轮快照，不暂停整局。
8. 畸形 V5 / 错误 mode fail closed。
9. 未知合同、缺合同 legacy 路径不变。
10. 记忆 lineage 被篡改仍整单拒绝，不写 fact。

真局观察（隔离，需另批费用）：

- 日终最后一句法官词到首个上帝视角狼刀的空隙 ≤ 20 秒（不含 nightfall 法官词本身的 TTS）；
- 次日第一条发言的上下文能读到上一轮记忆，或显式 `wait_expired` / `generation_failed`；
- 无新的 `action_paused`，无因记忆提交导致的 `match_runtime_failed`。

A1 **不**验收：整局时长、发言 P50、夜刀 P50、并发 429。

---

## 6. Work Package A2：并发 canary（不改生产默认）

### 6.1 现状

`model_concurrency_canary.py`：cap ∈ {3,4,6}，每档 120 attempt，离线 corpus 已钉 hash。E1 live runner 仍不存在。生产默认 3。

本局 16 次 `model_prefetch_capacity_unavailable` 证明 3 槽在放逐预取下会打满。这不是“单请求变慢”，是批次墙钟。

### 6.2 本次只做的事

写入决策门槛，供批准 A1 之后的下一份授权使用。**A1 实现不得改** `live_v2_agent_plan_max_in_flight` 默认值。

升槽最低门槛（沿用 8 月 10 日 E1，收紧一条）：

1. 同一 pinned corpus，cap=3 为对照；
2. cap=4 或 6 的 queue P95 相对 cap=3 下降，且 429+5xx 率不高于对照 +2 个百分点；
3. 成功请求的 **active** completion P50 不得比对照恶化超过 10%（防止把排队变成更慢的推理）；
4. 按 `per_process_limit × live_instances` 报告总槽，禁止六个副本各开 6；
5. 选择最小通过值，不追求 6。

未跑过上述报告，任何人不得把环境变量或 Settings 默认改成 4/6。

---

## 7. Work Package B1：第二轮狼刀（本次不实施）

### 7.1 禁止写成的方案

- “把 preference_probe 改成并行”——已经是。
- “初选有多数就系统直接落刀”——伪造模型终票。
- “第二轮也并行，且能看见队友第二轮改口”——时间上做不到，除非变成一轮。

### 7.2 若未来批准，唯一允许的最小改动

**分歧者顺序补票，已一致者不再重问。**

1. 第一轮保持现有并行盲选。
2. 若全员目标相同（含合法空刀）：与今天一样直接 `blind_choice_unanimous`，不进第二轮。
3. 若存在严格多数（票数 > 存活狼人数/2）且少数派非空：多数派沿用第一轮目标，不再调用模型；少数派按座位顺序做现有 `sequential_final_vote`，知识里仍带 `werewolf_first_round` 与已完成的第二轮。
4. 若无严格多数：保持今天的全员顺序终票。
5. 结算仍走现有 unanimous / sequential_final_vote / technical_no_action，不引入系统填刀。

本局五夜初选都有分歧且最终归到同一刀口。若多数派常在第一轮形成，每夜少问 2–3 次模型。这是猜测，必须用新局数据验收，不能用 b722 外推当成功标准。

B1 需要独立合同（夜间攻击策略版本 +1），不得塞进 V5 generation policy。

---

## 8. Work Package B2：boolean_light（本次不实施）

当前 `reasoning_parameter_mode` 禁止 profile 改 effort。要分层必须再升一版 generation policy（预计 V6），并显式打开例如 `allow_profile_reasoning_override`。

允许映射到新档 `boolean_light` 的动作只有：

- `sheriff_run`
- `sheriff_withdraw`
- `werewolf_self_explosion`

禁止放入：`exile_vote`、`day_debate_speech`、`ability_werewolf.attack_decision`、神职技能、遗言。

`boolean_light` 可以降低 `reasoning_effort` 或缩短可见输出合同，**不得**改候选集、不得改 false fallback 语义。验收按动作完成率、空流率、技术回退率，不按整局胜负。

8 月 10 日否决的“关掉投票/自爆 Thinking”仍然有效。B2 是降档，不是关闭。

---

## 9. 明确延后

| 项 | 原因 |
| --- | --- |
| 发言 lookahead=2 | pipeline 合同写死 `max_lookahead==1`；血统/失效/自爆打断回归面大，收益小于 A1 |
| 按 P99 启用 C2 | 切不到本局 P50 |
| 压缩上下文再砍一版 | 本局不是窗口溢出 |
| 8 人/无警徽/字数顶/非 thinking | 产品合同，另开文档 |

---

## 10. 测试计划

### 10.1 A1 聚焦

```text
apps/api/.venv/bin/python -m pytest \
  apps/api/tests/test_v2_protocol_units.py \
  apps/api/tests/test_v2_api.py \
  -k "generation_policy or private_memory or private_round_memory"
```

必须新增（名称可调整，语义不可少）：

- `test_v5_emits_background_generation_and_v4_fixture_still_resolves`
- `test_background_memory_allows_commit_after_finish_day`
- `test_background_memory_commit_when_owner_died_after_cutoff`
- `test_background_memory_does_not_block_night_phase_change`
- `test_background_memory_judge_failure_still_blocks_night`
- `test_next_day_waits_only_own_memory`
- `test_next_day_wait_expired_uses_previous_snapshot`

旧测试保持：

- `test_new_policy_generates_private_memory_before_advancing_night`（仅 V4 / blocking）
- `test_private_round_memory_batch_rejects_changed_frozen_phase_atomically`（仅 blocking API）
- `test_new_policy_summary_failure_does_not_skip_memory_or_advance_phase`
- `test_model_generation_policy_present_unknown_or_malformed_fails_closed` 继续拒绝 `reuse_previous_non_blocking`

### 10.2 全量门禁

与 8 月 10 日文档 12.6 相同：聚焦 pytest → API 全量 pytest → ruff → admin Vitest / tsc / eslint。与本文无关的既有失败必须原文记录，不得静默当通过。

### 10.3 真局

A1 合并后单独申请一局 12 人预女猎白。观察第 5.9 节真局三项。不把这一局的胜负当质量验收。

---

## 11. 发布与回滚

- 只影响新局：V5 写进创建时的 `rule_snapshot`。
- 进行中的 V4 局不迁移。
- 回滚：把 emitter 改回 V4，或紧急把 V5 校验改回只接受 blocking（会让已冻结 V5 新局 fail closed，只能停开新局）。后台 job 必须能被 stop/reaper 取消。
- 不在 A1 提交里夹带 A2 默认值、B1、B2。

---

## 12. 建议的批准语句

任选其一，避免范围漂移：

1. **“通过，进入开发 A1”** — 只实施第 5 节。
2. **“通过，进入开发 A1；A2 只跑 canary 不改默认”** — 可补 live runner，仍不改 Settings 默认。
3. **“A1+B1 一并开发”** — 必须同时接受第 7.2 节的多数派不再重问。

没有以上语句时，按重构准则停在文档，不改代码。
