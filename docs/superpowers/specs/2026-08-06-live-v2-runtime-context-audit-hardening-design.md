# Live V2 运行时、模型上下文与审计契约加固开发文档

**Date:** 2026-08-06

**Status:** Approved for implementation

> 2026-08-20 核对：本文的 Status 自创建以来未更新过。音频模式、执行所有权、终局派生在代码中有对应实现，但本文提到的 V9 上下文版本早已被取代（当前 schema 为 13）。实际完成度需按代码核对。

**Priority:** P0 Runtime Safety / P1 Context Correctness / P1 Auditability

**Scope:** `apps/api`、`apps/admin-web`、`apps/mobile-web` 的 Live V2 对局级音频模式、执行所有权、终局状态派生、V9 模型上下文、机器格式确定性修复、私密 audience 审计、被动诊断与狼人分歧分支验收

**Source Game:** `v2_game_1cdaa76e80aa49a7`

**Source Run:** `v2_run_4af2e5dd20624094`

**Frozen Rule Revision:** `0489f6ac-16fd-5323-96ce-ee256c98cf32`

**Related Designs:**

- `docs/superpowers/specs/2026-08-05-live-v2-full-match-stability-remediation-design.md`
- `docs/superpowers/specs/2026-07-15-privacy-audience-contract-v2-remediation-design.md`
- `docs/live-v2-realtime-action-protocol.md`

## 1. 决策摘要

本开发包处理排除“模型自身策略判断”和“模型生成耗时”后，仍由系统合同造成或放大的问题。核心决策如下：

1. 音频模式从进程环境开关改为对局创建时冻结的 `audio_mode`；同一 API runtime 必须能并存 `tts` 与 `text_only` 对局。
2. V2 对局执行必须取得数据库所有权并携带 fence 写入；未取得所有权的 worker 不得仅因数据库状态为 `ready` 就启动本地 engine。
3. 本轮执行所有权只提供防重和失联 fail-closed，不宣称支持 stale owner 自动接管；当前 FlowEngine 没有按 phase/state 恢复入口。
4. `awaiting_observation` 继续作为兼容的实时流状态，不再被 UI 或 API 推断为“比赛已完成”。终局必须由权威比赛事实派生。
5. 新局冻结 V9 模型上下文。V9 给警长完整发言顺序后果，投射紧凑的问题/回答关系，并消除狼人队友的双重事实源。
6. 对重复输出的两个语义等价 JSON 做严格、确定性、可审计的本地修复；两个对象不一致时仍拒绝，不任意取第一个。
7. 私密发言的实时 audience 路由保持不变，同时让 canonical action/model/ability/speech/TTS 事件自带 transport audience，历史缺失值按 fail-closed 处理。
8. 被动诊断修复投票人解析误报，并新增窄范围的公开事件因果倒置诊断；所有诊断继续 `observed_only`，不得触发重试、改写或拦截。
9. 狼人二次讨论后仍分歧、轮转裁决的算法不重写，补齐完整 API、持久化、隐私和无 TTS 集成验收。
10. `unanimous_no_attack` 与 `allow_no_attack=false` 是合法且语义正交的组合，不新增配置错误、不改枚举、不重算规则快照哈希；只补无歧义模型投射与回归测试。

本开发包按依赖拆为四个可独立评审、依次合并的工作包：

| 工作包 | 内容 | 优先级 | 前置依赖 |
| --- | --- | --- | --- |
| A | 对局级音频、执行所有权、终局派生 | P0 | 数据迁移先上线 |
| B | V9 上下文、警长顺序、问题关系、狼人私有事实 | P1 | A 无逻辑依赖，但建议在运行时稳定后跑真局 |
| C | 双 JSON 修复、audience 自描述、被动诊断 | P1 | 可与 B 并行开发 |
| D | 狼人持续分歧完整集成验收、Admin/Mobile 收口 | P1 | A、B、C |

## 2. 已确认运行证据

### 2.1 完整局结果

源对局为 12 人经典配置：4 狼、预言家、女巫、猎人、白痴和 4 平民。运行结果如下：

| 指标 | 结果 |
| --- | --- |
| 比赛结果 | 好人阵营胜利 |
| 最终阶段 | `day_4 / game_completed` |
| 最终 game/run status | `awaiting_observation` |
| 结束事件 | `record_seq=1702` 的 `game_completed` |
| 总运行时间 | 58 分 28 秒 |
| 动作 | 210 `action_opened` / 210 `action_succeeded` |
| 模型调用 | 163 请求 / 162 首次成功响应 / 1 次机器格式重试后成功 |
| TTS | 89 次 presentation / 89 `tts_skipped` / 0 TTS stream |
| 上下文裁剪 | 0/163 请求丢弃事件；最大 `known_events` 115 条 |
| 最大请求体 | 约 62.7K 字符；本开发不据此推断模型窗口压力 |

该局没有 action failure、timeout 或比赛流程中断。因此本文件所列问题不是“该局没有完成”，而是从完整事件链、冻结请求和运行拓扑中确认的合同缺口与下一次风险。

### 2.2 无 TTS 运行依赖第二个 API 进程

该局为了关闭 TTS，使用了单独的 API 进程，并设置：

```text
LIVE_V2_TTS_ENABLED=false
```

常规 API 进程仍启用 TTS。当前 `build_v2_live_runtime()` 在进程启动时只构造一个 `V2TtsClient` 或一个 `V2DisabledTtsClient`，`V2ActionEngine` 对所有游戏共享该 client。对局记录和创建请求均没有音频模式字段。

这证明当前无 TTS 不是对局合同，而是运行拓扑差异。它同时放大了跨进程重复启动和 WebSocket 频道割裂风险。

### 2.3 狼人首轮盲选与二次讨论

首夜四狼并发盲选结果为：

| 狼人座位 | 初选刀口 | 首轮输出 |
| ---: | ---: | --- |
| 4 | 7 | `decision_note`，无 speech |
| 5 | 9 | `decision_note`，无 speech |
| 6 | 7 | `decision_note`，无 speech |
| 11 | 1 | `decision_note`，无 speech |

发生分歧后，四狼按顺序收到全体初选刀口、自己的初选理由以及此前已发表的狼聊，重新选择刀口并用一句话在狼人私聊中说明理由，最终一致归到 7 号。

该局同时确认：

- 盲选理由只对本人可见；
- 全体初选目标在分歧后共享；
- 后发狼人能看到此前二次讨论；
- 普通玩家没有收到这些私密字符串；
- 后续夜晚若初选一致则跳过二次讨论；
- 只剩一狼时直接作出最终选择。

但该局没有覆盖“二次讨论后仍平票，再进入轮转裁决”的持久化完整分支。

### 2.4 警长选择发言顺序缺少选择后果

本局 `record_seq=430` 的 `sheriff_speech_order` 请求只告诉警长：

```text
选择本轮第一位发言者。
```

请求只有警长左右相邻的两个候选，没有每个选择对应的完整发言顺序，也没有说明警长本人会在最后发言。警长选中 3 号后，engine 才计算出：

```text
3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2
```

即警长 2 号最后发言。完整顺序在选择后才进入私有决策上下文和 `day_speech_order_selected` 事件，无法作为选择依据。

### 2.5 问题账本没有进入模型可见输入

V8 已构造 discourse ledger、问题、回答关系和 `reply_opportunity`，但它们主要进入 observation context。模型可见请求仍只有事件数组和 `speech_progress`。

本局部分请求已经识别出 17～18 个问题和 7 个回答关系，但冻结请求仍表现为：

```text
known_events keys = [schema_version, events]
prompt_projection.question_count = 0
prompt_projection.relation_count = 0
prompt_projection.ledger_question_count > 0
```

模型能看到剩余发言人，却看不到结构化的“谁问了谁、被问者是否已经轮到、此前是否已解释、后续发言是否确实回答了问题”。

### 2.6 狼人队友存在两个相反事实源

本局狼人公开发言请求中同时出现：

```json
{
  "self": {
    "werewolf_coordination": {
      "mode": "team",
      "living_teammate_refs": []
    }
  }
}
```

和一条包含正确存活队友的 actor-private `known_event`。根因是 `_model_self_v8()` 显式以空 `private_facts` 构造 self，而 `_known_events()` 又独立投射了私有事实。

正确事实确实传给了模型，但同一请求中的空列表构成相反的结构化含义，不能归类为模型自己的推理错误。

### 2.7 机器格式失败是两个等价 JSON 串联

唯一一次机器格式失败发生在：

```text
action_id  = v2_action_647d866a0b3b4a7d
attempt_id = v2_model_ff61a9421bd744fa
record_seq = 653
```

原始响应包含一个普通 JSON，随后又在 Markdown `json` fence 中重复了同义 JSON。当前 `_decision_object()` 从第一个 `{` 截到最后一个 `}`，得到两个串联对象，整体解析失败，随后被误报为 `model_decision_structured_speech_leak` 并重试。

这不是策略错误，也不是 speech 泄漏，而是可确定性识别的重复机器输出。

### 2.8 私密 audience 已持久化，但 canonical 事件不自描述

当前实时路由会按 audience 过滤；`V2LivePresentation.audience` 与 `V2VoiceAsset.audience` 也已持久化。缺口是以下事件 payload 没有 audience：

- `speech_opened`；
- `speech_segment_committed`；
- `speech_sealed`；
- 部分 `tts_*` 事件。

Admin 需要依赖 presentation 或 `model_request_started` 反查。新的历史投影、导出器或回放消费者若只读取 canonical event，可能把缺失值错误默认成公开。

因此这是一项审计和未来投影安全加固，不是“当前直播已经向普通玩家泄漏”。

### 2.9 被动诊断有一项误报和一项漏报

当前投票解析把下列真实句子中的“9，1号”误识别为下一组投票人：

```text
4号、5号、11号跟我出9，1号也投了9
```

结果虚构出“9 号投 9 号”的 claim，并触发 `public_vote_fact_contradiction`。

另一方面，本局 9 号先发言，6 号之后才公布查杀；4 号和 11 号却把 9 号更早的发言描述为“被查杀后的应激”。该公开事件因果倒置没有被现有 detector 捕获。10 号随后正确指出时间顺序，不应被误报。

## 3. 需要明确纠正的非缺陷

### 3.1 `unanimous_no_attack` 与 `allow_no_attack=false`

两字段含义正交：

- `resolution=unanimous_no_attack`：团队终票不一致时，结算为空刀；
- `allow_no_attack=false`：单个狼人不能主动提交 `null`，每狼必须选择一个目标。

所以“每狼必须投目标，但团队未全票一致时空刀”完全合法。现有 Admin 文案“必须全票一致，否则空刀”和“允许狼人主动空刀”也已正确区分。

开发要求：

- 不新增发布校验错误；
- 不改数据库枚举；
- 不改既有规则修订；
- 不重算历史内容哈希；
- 只在 V9 中投射无歧义的派生机械语义，并补回归测试。

### 3.2 `awaiting_observation`

该状态表示实时流程已停止或等待观察，不等于比赛一定完成。完整比赛和 direct/terminal 流程都可能进入该状态；后者可以没有 winner 和 `game_completed`。

开发要求：保留 wire enum 兼容，新增权威派生状态，不把现有 status 值重命名为 `completed`。

### 3.3 模型策略与生成耗时

本开发不因以下情况重试、改写或加入广泛提示：

- 模型作出合法但差的推理；
- 模型忽略已经提供且无冲突的事实；
- 模型生成时间较长但仍在既定预算内完成；
- 只凭请求字符数推断 token/window 压力。

## 4. 开发目标与非目标

### 4.1 目标

1. 无 TTS 对局不依赖第二个 API 进程，不实例化或调用外部 TTS client。
2. 同一 runtime 能并发运行有声和纯文本游戏，且模式在创建后不可漂移。
3. 两个 worker 同时 ready 同一游戏时只有一个执行 owner、一个 engine task 和一条 opening action。
4. stale owner 的旧 fence 不能继续写入；本轮 owner 失联明确 fail closed。
5. API、Admin 与 Mobile 能区分比赛结果、实时流状态和执行器状态。
6. 新模型上下文准确表达警长选择后果、回应机会和狼人队友，不复制整段历史。
7. 历史冻结 V7/V8 对局在部署后继续使用原合同，不原地改变请求形状。
8. 可安全修复的重复等价 JSON 不再消耗第二次模型请求，且原始响应与修复事实完整保留。
9. canonical action/model/ability/speech/TTS 事件可独立判断 transport audience；旧记录缺失 audience 时在 Admin 中默认未知而非公开。
10. 被动诊断更精确但仍完全不影响游戏执行和模型输出。
11. 狼人持续分歧和轮转裁决具备完整跨层回归证据。

### 4.2 非目标

- 不在本开发中实现 stale owner 自动续局；
- 不实现任意 worker 的 WebSocket/PCM 跨节点 durable pub/sub；
- 不把 lease 等同于 phase-aware recovery；
- 不从历史事件伪造所有旧局的精确音频意图；
- 不修改狼人攻击三种持久化 resolution 枚举；
- 不重写已经存在的狼人盲选、二次讨论和轮转裁决算法；
- 不把 passive observation 注入后续玩家模型上下文；
- 不恢复完整 legacy history 或重复 public timeline；
- 不用新的通用规则提示替代结构化事实；
- 不因诊断命中而重试、标准化或隐藏原始发言。

## 5. 系统不变量

### 5.1 音频不变量

对所有新局：

```text
effective_audio_mode(action) == frozen_game.audio_mode
```

并满足：

```text
audio_mode == text_only
  -> this game path does not resolve, construct or call an enabled TTS client
  -> no external TTS request
  -> no V2VoiceAsset
  -> presentation still opens and closes
  -> tts_skipped(configured_audio_mode=text_only)

audio_mode == tts
  -> runtime capability must be available before game start
  -> every spoken presentation follows the existing voice/TTS contract
  -> no silent fallback to text_only
```

环境变量只决定集群能力和兼容创建默认值，不得在动作执行时重新决定某局模式。

### 5.2 执行所有权不变量

同一 `run_id` 任一时刻至多有一个有效写入者：

```text
valid_writer == (worker_id, fence_token, lease_expires_at > now)
```

任何改变 V2 对局状态、动作、展示、语音、能力 activation、effect 或事件序列的写入都必须验证该三元组。仅检查 `game.status`、仅持有行锁、仅持有本地 `_task` 均不构成执行所有权。

本轮不允许 stale lease 自动 takeover。owner 丢失后必须停止写入、记录可诊断状态并等待人工处理或后续恢复能力。

### 5.3 终局不变量

`match_status=completed` 至少要求：

```text
phase_state == game_completed
AND winner IS NOT NULL
AND completion_reason IS NOT NULL
AND current_run.completed_at IS NOT NULL
```

并应存在同 run 的 `game_completed` 事件。若旧数据缺少其中一项，Admin 标记“终局证据不完整”，不得只因 `awaiting_observation` 显示完成。

胜负事实必须先持久化，终局 judge speech 继续 best-effort。TTS 或终局播报失败不得回滚 winner、completion reason 或 completed_at。

### 5.4 上下文时序与隐私不变量

- 模型可见 event 必须满足 `known_at_seq <= task.at_seq`；
- question 必须满足 `asked_at_seq <= task.at_seq`，且 `source_event_ref` 指向已保留 event；
- relation 的 question/event 两端必须都已保留，且端点时间不晚于 `task.at_seq`；
- question 的回答必须发生在问题之后，且由被问者本人作出；
- 尚未轮到发言只能表示 `awaiting_scheduled_turn`，不能表示拒绝回应；
- V9 多狼动作恰有一个当前存活队友的权威 actor-private 事实源；
- 非狼人请求不得出现狼人队友、狼聊、盲选理由或刀口；
- 事件 audience 缺失且无法关联恢复时必须视为 `legacy_unknown` 并 fail closed。

### 5.5 机器输出修复不变量

本地修复只允许把一个原始字符串确定性映射到唯一合法决定。若存在两个不同合法决定，结果不是“可选一个”，而是：

```text
model_decision_ambiguous_multiple_objects
```

原始响应永远保存；修复不得修改候选范围、目标值、speech、decision note 或 boolean 的语义。

## 6. 工作包 A：对局级音频、执行所有权与终局状态

### 6.1 创建与冻结合同

新增请求合同：

```json
{
  "title": "12人无 TTS 对局",
  "audio_mode": "text_only",
  "lobby_snapshot": {}
}
```

新请求只允许：

```text
tts | text_only
```

新增冻结快照：

```json
{
  "schema_version": 1,
  "mode": "text_only",
  "source": "explicit_create_request"
}
```

数据库使用 `delivery_snapshot` JSON，而不是只存一个布尔值，避免以后加入字幕、音频编码或分段策略时再次改列。应用层暴露稳定派生字段 `audio_mode`。

创建兼容分两步发布：

1. 第一阶段请求字段允许省略；服务端只在创建事务中根据当前 `LIVE_V2_TTS_ENABLED` 解析一次并冻结，`source=legacy_runtime_default`，同时记录兼容计数。
2. Mobile/Admin 创建端全部显式提交后，将请求字段收紧为必填；此后环境变量仅表示 runtime 是否具备 TTS 能力。

若显式请求 `tts` 但 runtime/cluster 不具备能力，创建返回：

```json
{
  "code": "v2_audio_mode_unavailable",
  "requested_audio_mode": "tts"
}
```

不得创建 game/run，也不得静默降级为纯文本。

创建响应、三类 live snapshot、Admin list/detail 和 `game_created` 事件都返回/持久化最终冻结的 `audio_mode`。

`model_binding_mode=profile_library` 同时属于服务端权威冻结路径：外层
`rule_set_revision_id` 与内层 `rule_set.revision_id` 都必须存在且一致；创建事务内按
该 revision 锁定当前 published rule，最终只冻结服务端 compiled snapshot，不能信任
客户端提交的 roles、机械字段或 `werewolf_attack_policy`。预览后 revision 已变化时返回
`409 rule_revision_changed`，Mobile 刷新目录并要求重新确认。`explicit_snapshot` 继续保留
客户端自有快照语义，不套用 published catalog 锁定。

### 6.2 历史数据迁移

计划迁移：

```text
apps/api/alembic/versions/20260806_54_add_v2_delivery_and_execution_contracts.py
```

`v2_game_records` 新增：

```text
delivery_snapshot JSON NULL
```

迁移不得根据“没有 voice asset”推断历史意图，因为无 presentation 的局、启动前取消局和旧进程配置都无法可靠还原。旧记录写入：

```json
{
  "schema_version": 1,
  "mode": "legacy_unknown",
  "source": "pre_contract_record"
}
```

应用创建路径只允许写 `tts` 或 `text_only`；`legacy_unknown` 仅为历史读取值。待全部活跃旧局 drain 后可将列收紧为非空，但不得把历史 unknown 伪装成某个确定模式。

### 6.3 Runtime 音频路由

将 `V2ActionEngine` 的单一 `tts_client` 替换为按 claim 解析的音频端口：

```text
V2ActionClaim.audio_mode
V2TtsRouter.client_for(claim)
```

要求：

1. `claim_action()` 在锁住 game 的同一事务中读取冻结 snapshot，并把 `audio_mode` 放进不可变 claim。
2. `text_only` 返回 disabled port；不得因该局触发 enabled client 的惰性构造。若同一进程已有其他 `tts` 对局缓存了 enabled client，本局仍不得解析或调用它。
3. `tts` 才惰性构造并缓存进程级可复用 client。
4. ActionEngine 在 `open_presentation()` 前验证模式与 client capability 一致。
5. `tts_skipped` 增加 `configured_audio_mode=text_only`；禁止用笼统 `tts_disabled` 隐藏配置错误。
6. `tts` client 运行中故障沿用既有 TTS failure 合同，不改变比赛终局事实。

### 6.4 Run execution lease 与 fence

`v2_game_runs` 新增：

```text
worker_id              VARCHAR(64) NULL
worker_heartbeat_at    TIMESTAMPTZ NULL
lease_expires_at       TIMESTAMPTZ NULL
fence_token            BIGINT NOT NULL DEFAULT 0 CHECK (fence_token >= 0)
```

新增索引：

- `ix_v2_game_runs_worker_id`；
- `ix_v2_game_runs_lease_expires_at`；
- active status + lease 的部分索引，具体 PostgreSQL/SQLite 表达沿用现有 migration 测试风格。

不得从 legacy V1 runtime 直接 import store/runtime；V2 import boundary 必须保持。可以抽取无领域依赖的 lease 原语，或在 V2 repository 中实现同一协议。

启动事务由原先分离的 `start_game()` 和本地 task 判断改为：

```text
start_and_claim_execution(game_id, worker_id, now, lease_expires_at)
  -> owned(run_id, fence_token)
  -> already_owned(run_id, owner_hint)
  -> not_startable(current_state)
```

只有 `owned` 分支可以创建 `_GameChannel._task`。禁止继续使用：

```python
if snapshot["live_state"] == "ready" and self._task is None:
    create_task(...)
```

每个 runtime 在进程生命周期内使用稳定 `worker_id`。task 运行期间独立 heartbeat，结束、失败或取消时释放 lease 并记录 reason。heartbeat 失败或 fence 变化时，engine 必须取消后续动作并停止所有写入。

成功释放 owner 后，channel 必须向每种现有 subscriber audience 主动重发一次当前
snapshot，使客户端从 `owned` 收敛为 `stopped`，不能只依赖下一次重连。TTS 文件在
final rename 后、`mark_voice_ready` 成功返回前仍视为未提交；若此时取消、失去 owner
或 ready 持久化失败，必须删除本次 final 与 `.writing` 文件，数据库 voice 保持非 ready
或由失败收口写为 failed。

所有 repository mutation 接收显式 `V2RunFence`：

```text
run_id
worker_id
fence_token
```

写入 SQL 必须同时校验 fence 和未过期 lease；只在入口检查一次不够，因为旧 owner 可能在检查后失去 lease。

### 6.5 本轮 fail-closed 边界

当前 `V2LiveFlowEngine._run_active()` 固定从 opening 开始，Night/Day engine 也没有按 phase checkpoint 恢复入口。因此：

- stale lease 本轮不得自动转移并从 opening 重跑；
- owner 失联后 `execution_state=stale`，发出运维告警；
- Admin 明确显示“执行器失联，当前版本不可自动续局”；
- 操作者可以取消该局，但“恢复”必须等待 phase-aware recovery 工作包；
- 上线迁移前必须 drain 活跃 V2 对局，滚动重启不是可恢复操作。

lease 不解决跨 worker 广播。本轮部署必须满足下列至少一项：

1. 只启用一个 V2 execution worker；或
2. 按 `game_id` 对 public/director/god-view WebSocket 做 sticky affinity，全部落到 owner。

任意 worker 接入与 PCM durable pub/sub 属于后续独立设计，不在本开发中伪装成已支持。

### 6.6 终局派生状态

保留现有 `live_state`，新增：

```text
match_status: waiting | running | completed | failed | canceled
execution_state: unowned | owned | stale | stopped
winner: villagers | werewolves | null
completion_reason: string | null
completed_at: datetime | null
```

派生规则：

| 条件 | `match_status` |
| --- | --- |
| 权威完成不变量全部成立 | `completed` |
| 明确 `phase_state=failed` 或 run/game failed | `failed` |
| game/run canceled | `canceled` |
| 尚未开始 | `waiting` |
| 其他 | `running` |

`awaiting_observation` 且无 winner 时，Mobile/GodView 显示“实时流程已停止”，不得显示“完整对局已经结束”。Admin 分三项展示：

- 对局结果；
- 实时流状态；
- 执行器状态。

## 7. 工作包 B：V9 模型上下文合同

### 7.1 版本冻结与兼容

新局冻结：

```json
{
  "model_context_schema_version": 9,
  "prompt_template_version": 1,
  "known_events_schema_version": 3,
  "ledger_schema_version": 2,
  "model_view_schema_version": 3,
  "model_view_selector_version": 1
}
```

实现必须新增并保留：

- `legacy_v8_prompt_v3_model_context_contract()`；
- `is_v9_model_context_contract()`；
- 独立 V9 projection 和 prompt 分支；
- V7、V8 Prompt 1/2/3、V9 Prompt 1 的支持集合。

已创建对局继续使用冻结合同，不回填、不原地升级。尤其不能让部署前未结束的 V8 对局在部署后突然收到 V9 形状。

### 7.2 警长完整顺序预览

提取唯一纯函数：

```text
speech_order_from_start(alive_by_seat, sheriff_player_id, start_player_id)
```

动作打开前用该纯函数一次生成两个不可变 option。V9 projector 读取 option 作为模型请求预览；模型选中 `target_player_id` 后，engine、私有 action decision context 和 `day_speech_order_selected` 共同复用同一个选中 option/result 对象，不再重复计算顺序。

option 放在 raw action context 的 V9 专用 extension 中，只由 V9 projector 搬入 `task.mechanical_effect`。不得把 option 直接加入 V8 会透传的 `current_action_effect`，否则历史 V8 Prompt 3 对局会在部署后改变输入形状。

V9 `task.mechanical_effect`：

```json
{
  "action_type": "sheriff_speech_order",
  "target_mode": "required",
  "selected_target_becomes_first_speaker": true,
  "sheriff_speaks_last": true,
  "options": [
    {
      "target_player_id": "seat_1",
      "resulting_speech_order": ["seat_1", "seat_4", "seat_3", "seat_2"],
      "sheriff_position": 4
    },
    {
      "target_player_id": "seat_3",
      "resulting_speech_order": ["seat_3", "seat_4", "seat_1", "seat_2"],
      "sheriff_position": 4
    }
  ],
  "speech_has_gameplay_effect": false
}
```

示例为四名存活玩家的缩短表示。真实数组必须包含且只包含全部存活玩家的完整 `seat_N` 引用，不允许使用 `"..."` 占位；恒有 `sheriff_position == len(resulting_speech_order)`。

目标文案改为“根据每个候选对应的完整发言顺序，选择本轮起始发言者”。完整顺序是机械事实，不应藏在宽泛提示中。

### 7.3 紧凑问题与回答关系

V9 扩展 `known_events`，不恢复完整 history，也不重复原始发言：

```json
{
  "schema_version": 3,
  "events": [],
  "questions": [
    {
      "question_id": "question_471_1",
      "source_event_ref": "471",
      "asked_by": "seat_9",
      "addressed_to": "seat_5",
      "asked_at_seq": 471,
      "topic": "investigation_reason",
      "status": "open",
      "reply_opportunity": "awaiting_scheduled_turn",
      "prior_relevant_event_refs": ["437"]
    }
  ],
  "relations": [
    {
      "relation_id": "relation_520_question_471_1",
      "type": "answers_question",
      "from_event_ref": "520",
      "to_question_id": "question_471_1",
      "temporal_order_valid": true
    }
  ]
}
```

投射规则：

1. 投射当前 action 时点可见的当前轮全部问题与合法关系；本轮不新增 question/relation 裁剪器，`model_view_selector_version` 继续为 1。
2. 引用现有 event ref，不复制 `exact_quote` 或整段 speech。
3. question `status` 只允许 `open | answered | unresolved_target`。
4. 回答关系必须满足问题之后、被问者本人、同轮、主题匹配。
5. relation 只有在对应 question、回答 event 和 question source event 都存在于实际 V9 请求时才可出现。
6. `prior_relevant_event_refs` 只能指向实际保留的 event。
7. `reply_opportunity` 只在 question 有明确 `addressed_to` 且当前 speech action 有 `speech_order` 时出现；非发言动作、无明确对象或无发言顺序时省略。
8. 与 reply/prior-explanation 相关的 observation detector 只能消费实际投射进 V9 请求的 event/question/relation；完整 ledger 只用于数量审计，不能用模型未收到的派生关系评判模型。

`reply_opportunity` 只允许：

```text
awaiting_scheduled_turn
current_speaker_turn
scheduled_turn_passed
not_in_current_speech_order
```

V9 prompt 只需解释结构字段的机械含义：尚未轮到不等于拒绝回应；问题之前的相关发言不能算对后来问题的回答，但能证明此前已经解释。不得增加针对某局人物或策略的提示。

审计元数据：

```text
question_count
relation_count
ledger_question_count
ledger_relation_count
awaiting_scheduled_turn_question_count
dropped_question_count
dropped_relation_count
```

其中 `question_count`/`relation_count` 必须等于实际模型请求数组长度；本版本 `dropped_question_count` 与 `dropped_relation_count` 恒为 0。不能再把完整账本数量和实际投射数量混为一谈。

### 7.4 狼人队友唯一事实源

V9 self 只保留协调模式：

```json
{
  "werewolf_coordination": {
    "mode": "team"
  }
}
```

存活队友只保留在一个权威 actor-private event：

```json
{
  "event_ref": "current_living_werewolf_teammates",
  "kind": "living_werewolf_teammates",
  "authority": "judge_fact",
  "visibility": "actor_private",
  "known_at_seq": 1014,
  "occurred_in": {"period": "day", "round_no": 2},
  "data": {
    "teammate_refs": ["seat_5", "seat_6", "seat_11"]
  }
}
```

约束：

- 多狼的每个玩家动作恰有一条当前 `living_werewolf_teammates`；
- 已死亡狼人不出现；
- 单狼只输出 `mode=solo`，不输出 teammate event；
- 非狼人上下文不得出现该 event；
- V9 不再输出 `self.werewolf_coordination.living_teammate_refs`；
- action-specific task 可保留协调阶段和初选/终票事实，但不再复制静态队友数组。

V9 projector 必须先从输入 private facts 中过滤所有历史 `werewolf_teammates` 与 `living_werewolf_teammates`，再依据 action 时点的当前存活状态生成上述唯一 canonical event。不得简单取最后一条旧 fact，否则死亡后的队友列表可能陈旧。`event_ref` 在同一 action 内稳定，`known_at_seq` 不晚于 `task.at_seq`，`occurred_in` 使用当前 period/round。

### 7.5 狼刀规则无歧义派生语义

持久化规则保持不变，V9 在 `rules.current_ability` 下投射：

```json
{
  "team_resolution": {
    "strategy": "unanimity_required",
    "on_disagreement": "no_attack"
  },
  "individual_ballot": {
    "target_mode": "required",
    "allow_no_attack": false,
    "allow_wolf_target": false
  }
}
```

映射规则：

- `unanimous_no_attack` -> `strategy=unanimity_required`、`on_disagreement=no_attack`；
- `plurality_rotating_tiebreak` -> `strategy=plurality`、`on_tie=explicit_rotating_werewolf_decision`；
- `plurality_seeded_random` -> `strategy=plurality`、`on_tie=deterministic_seeded_choice`；
- `allow_no_attack=false` -> `individual_ballot.target_mode=required`；
- `allow_no_attack=true` -> `individual_ballot.target_mode=optional`。

两种 plurality 策略在唯一最高票时都使用 `unique_highest`。只有一名存活狼人时，`team_resolution={"strategy":"single_actor_direct","on_tie":"not_applicable"}`，仍保留 `individual_ballot` 的 target/allow 约束，避免调用方猜测字段缺失原因。

该投射只消除模型输入歧义，不改变 engine 结算。

## 8. 工作包 C：解析、audience 与被动诊断

### 8.1 重复等价 JSON 的严格修复

新增内部解析结果：

```text
ParsedDecisionDocument(value, repair_kind)
```

算法顺序：

1. 保留现有单尾括号、结构智能引号、NFKC key 等兼容修复。
2. 使用 `json.JSONDecoder().raw_decode()` 顺序识别顶层对象，不用正则匹配嵌套大括号。
3. 允许的重复形状仅为：对象 A、可选空白、可选 JSON fence、对象 B、可选结束 fence、EOF。
4. A、B 分别经过现有 wrapper 解包、expected output field、字段类型和 output shape 校验。
5. 对 shape 合法的 payload 做 canonical JSON 序列化后比较语义；candidate 是否在 action 允许集合中仍由 `V2ActionEngine._validate_model_target_decision()` 校验，speech/decision-note 的字数、句数和 normalization 仍走现有合同。
6. 若所有合法对象语义相同，采用 A，设置：

```text
repair_kind=duplicate_identical_json_ignored
```

7. 若存在两个不同合法 payload，抛出：

```text
model_decision_ambiguous_multiple_objects
```

8. 第二对象不完整、包含 context echo、超过两个对象或 fence 不闭合时，维持机器格式失败与既有重试策略。对象 A/B 之外存在 prose 时，只有“重复对象修复”不适用；现有“外围说明文字中只有一个合法 JSON”的单对象兼容行为保持不变。

`generate_action_decision()` 必须在 raw-response 保护的 `try` 内只解析一次，并把同一个 `ParsedDecisionDocument` 传给 field、decision-note 和 repair audit。不得继续由 `_decision_repair_kind()`、`_decision_fields()`、`_decision_note()` 各自重新解析，否则 ambiguity error 可能丢失 `raw_response`，不同字段也可能来自不同解析路径。

成功修复必须：

- 只产生一次 `model_request_started`；
- 不产生 `model_request_failed` 或 `model_retry_scheduled`；
- 完整保留原始响应；
- 在 `model_response_received.repair_kind` 和独立 `model_response_repair_applied` 中记录修复；
- 不覆盖任何原始文本。

### 8.2 Canonical event audience 自描述

本期只补齐 transport audience，不新增尚无权威来源的 semantic `visibility_scope`。当前 `audience=god_view` 实际路由到 directed 与 god-view，不能被命名成 `god_view_only`；狼人团队私密、法官私密和角色动作也不能只凭同一个 transport audience 相互推导。若以后需要语义授权范围，应另行给 action spec、presentation、voice asset 和事件建立持久化合同与迁移。

所有新 canonical record event 至少增加：

```text
audience
audience_contract_version=1
```

携带 action/presentation 的事件还必须带可用的关联键：

```text
action_id
presentation_id
tts_attempt_id
```

audience 来源必须显式沿调用链传播：

- `action_opened.context` 若承载玩家身份或私有事实，使用与 model lifecycle 相同的收窄
  audience；不含玩家私有上下文的 action 事件继承不可变 action spec/claim audience；
- model lifecycle 事件包含完整请求、角色私有事实、raw response 和 `decision_note`，必须
  在 action 开始时统一收窄：已有 `god_view`/`director`/`player_private` 保持，公开玩家
  action 的 model 事件使用 `player_private`，公开非玩家 action 使用 `director`；
- presentation/voice 事件继承 `V2PresentationIdentity.audience`；
- ability/effect 事件由调用者显式传入 audience；
- 禁止从 `action_type` 字符串或 payload 内容猜测 audience；
- `_append_event()` 对新写入要求显式 audience，避免继续生成未分类事件。

presentation/voice 生命周期至少覆盖：

- `speech_opened`；
- `speech_segment_committed`；
- `speech_sealed`；
- 新增 durable `speech_closed`，使 text-only 也有 canonical close；
- `speech_interrupted`；
- `tts_skipped`；
- `tts_stream_started`；
- `tts_stream_completed`；
- `voice_asset_saved`；
- `voice_recording_failed`；
- `voice_recording_canceled`；
- `audio_drained`；
- 对应 presentation/voice asset 的一致性。

无 presentation 的并发盲选同样会把 target 与 actor-private `decision_note` 保存到 model/action/ability event，因此 audience 加固不能只覆盖 speech/TTS。玩家 `action_opened.context` 与所有 `model_*` 使用上面的更窄 audience；不含私有上下文的 `action_succeeded/failed`、ability activation/progress/resolution 和 effect intent/result 继承 action audience。公开发言 presentation 仍可为 `all`，但其 action context、模型请求与响应不得因此标为公开。现有普通玩家模型上下文继续只通过明确 visibility/audience 规则选择 known facts，未分类 record event 不得自动进入。

本项只给 event payload 增加 transport audience，不改 presentation/voice 表结构，因此不需要额外数据库列迁移。

Admin 历史事件 audience 的恢复顺序：

1. 通过 `presentation_id` 关联 `V2LivePresentation.audience`；
2. 再通过 `action_id` 关联 `model_request_started.audience`；
3. 对旧 `tts_stream_completed`，通过 `tts_attempt_id -> tts_stream_started.attempt_id -> action_id` 再关联 action/presentation；
4. 都无法唯一恢复时使用 `legacy_unknown`；
5. Admin 显示“旧记录范围未知”，不得显示公开。

禁止继续使用 `?? "all"` 把缺失值默认公开。

本轮不新增公共 raw-event history endpoint。现有 public WebSocket、snapshot 和普通玩家模型上下文继续使用各自的显式投影；测试分别验证这些真实消费者，不以不存在的“历史 public projection”作为验收对象。未来若新增公共事件导出，必须使用明确 event allowlist，缺失/未知 audience 一律 fail closed。

### 8.3 投票 claim 解析误报修复

修复 `_vote_claims()` 时必须同时保留以下合法写法：

- `12投10`；
- `2号、5号给10号`；
- 带明确“出/投/给”的多人表达；
- 多位数座位号。

边界规则：

1. 裸数字投票人只能紧邻投票动词；
2. 逗号分隔的多人 voter list 必须显式带“号”，或从可靠子句边界开始；
3. 若首个裸数字之前是“出、投、验、刀、查”等动作词，不得把该数字当作下一组投票人；
4. 否定、猜测、转述和不确定表达继续过滤。

真实回归句必须保留 `4、5、11 -> 9` 和 `1 -> 9` 两组真实 claim，同时不产生“9 号投 9 号”；给定对应权威投票事实时不得产生 contradiction：

```text
4号、5号、11号跟我出9，1号也投了9
```

### 8.4 公开事件因果倒置诊断

新增：

```text
_observe_public_statement_causality()
```

只识别高置信、窄范围表达，例如：

- “X 被 Y 查杀后的应激”；
- “X 听到 Y 报验后反咬/回应”。

detector 只判断公开陈述的先后关系，不判断 Y 的验人声明是否真实。trigger 是 Y 后续公开发言中对 X 的报验声明；reaction 是 X 更早的公开发言。使用模型可见稳定时钟 `known_at_seq` 比较，`source_record_seq` 只作为存在时的可选审计字段。

若 reaction 的 `known_at_seq` 早于 trigger，记录：

```json
{
  "code": "public_event_causality_contradiction",
  "severity": "warning",
  "confidence": "high",
  "detector_version": 1,
  "authority": "event_chronology",
  "effect": "observed_only",
  "signals": [
    {
      "reaction_actor_ref": "seat_9",
      "trigger_actor_ref": "seat_6",
      "reaction_event_ref": "984",
      "trigger_event_ref": "1014",
      "reaction_known_at_seq": 984,
      "trigger_known_at_seq": 1014,
      "reaction_source_record_seq": 984,
      "trigger_source_record_seq": 1014,
      "evidence": "claimed_reaction_precedes_claimed_trigger"
    }
  ]
}
```

必须排除：

- 否定：“不是被查杀后的应激”；
- 假设：“如果……才算”；
- 单纯转述：“4号说他是应激”；
- 缺少唯一事件引用或时序证据；
- 只有语义相似、没有明确因果连接的表达。

一句话包含多个独立因果 claim 时，每对事件形成一个 signal，经稳定 event-ref key 去重；顶层 observation 只生成一条。

所有 observation 均 fail-open，只写入 `model_response_received.passive_observations`，不得影响输出、重试、presentation、TTS 或后续模型上下文。

## 9. 工作包 D：狼人持续分歧与跨端验收

现有算法保留：

```text
parallel_preference_probe
  -> disagreement
  -> sequential_shared_discussion
  -> tied final votes
  -> explicit_rotating_tiebreak
  -> team_resolution
  -> attack effect
```

扩展 `FakeV2ModelClient`，按下列稳定键返回决定：

```text
(night_no, decision_stage, actor_id)
```

不得依赖候选数组的偶然排序。

完整集成验收拆成四个确定性 fixture，不能要求一局自然同时命中互斥条件：

1. `text_only` 持续分歧 fixture：并发盲选分歧、二次讨论后仍平、轮转裁决只从平票刀口选择；断言 0 voice asset 和 0 external TTS。
2. `tts` audience fixture：同样形成私密狼人 presentation；仅在 voice asset 存在时断言 presentation、speech/TTS event 与 voice asset audience 一致。
3. 第二夜轮转 fixture：连续两夜构造平票，断言轮转裁决人按规则改变。
4. survivor rotation fixture：先使一狼死亡，再构造平票，断言只在存活狼人集合中轮转。

四个 fixture 合计必须断言：

- 裁决上下文包含盲选目标、允许可见的初选理由、已有狼聊、最终票和平票目标；
- 每狼只能看到合同允许的私有 `decision_note`；
- public WebSocket、snapshot 和非狼人模型请求都没有狼聊、刀口和私有进度；
- director/god-view 可以看到设计允许的事件；
- 所有 activation 结束；
- `team_resolution`、attack effect 和最终目标一致。

## 10. API、数据与事件合同汇总

### 10.1 新增或变化字段

| 位置 | 字段 | 兼容策略 |
| --- | --- | --- |
| `V2GameCreateRequest` | `audio_mode` | 第一阶段 optional 并在创建时冻结；第二阶段 required |
| `V2GameCreateResponse` | `audio_mode` | 新增 |
| `V2GameRecord` | `delivery_snapshot` | 历史 `legacy_unknown` |
| 三类 live snapshot | `audio_mode`, `match_status`, `execution_state`, completion fields | 新增 |
| Admin list/detail | 同上 | 新增 |
| `V2GameRun` | worker/heartbeat/lease/fence | nullable owner fields，fence 默认 0 |
| V9 `known_events` | `questions`, `relations` | 仅 V9 |
| action/model/ability/speech/TTS events | transport audience contract | payload additive |
| passive observation | `public_event_causality_contradiction` | 新 code，仍 observed_only |

### 10.2 新事件或事件变化

建议新增：

- `v2_run_execution_claimed`；
- `v2_run_execution_heartbeat_lost`；
- `v2_run_execution_released`。

事件至少包含：

```text
run_id
worker_id
fence_token
reason
lease_expires_at
```

`game_created` 增加冻结 delivery snapshot；`game_started` 增加 owner/fence。所有事件仍按 `record_seq` 排序。

### 10.3 错误码

| 错误码 | 类别 | 是否重试模型 |
| --- | --- | --- |
| `v2_audio_mode_unavailable` | 创建/运行能力 | 否 |
| `v2_run_execution_owned_elsewhere` | runtime ownership | 否 |
| `v2_run_execution_lease_lost` | runtime ownership | 否，fail closed |
| `model_decision_ambiguous_multiple_objects` | machine format | 沿用机器格式重试合同 |

## 11. 代码改动地图

### 11.1 Backend

核心文件：

- `apps/api/app/v2/models.py`
- `apps/api/app/v2/contracts.py`
- `apps/api/app/v2/router.py`
- `apps/api/app/v2/live_runtime.py`
- `apps/api/app/v2/flow_engine.py`
- `apps/api/app/v2/action_engine.py`
- `apps/api/app/v2/repository.py`
- `apps/api/app/v2/match_repository.py`
- `apps/api/app/v2/night_repository.py`
- `apps/api/app/v2/day_engine.py`
- `apps/api/app/v2/first_night_engine.py`
- `apps/api/app/v2/model_context_contract.py`
- `apps/api/app/v2/model_context.py`
- `apps/api/app/v2/discourse_ledger.py`
- `apps/api/app/v2/discourse_model_view.py`
- `apps/api/app/v2/model_client.py`
- `apps/api/app/v2/model_observation.py`
- `apps/api/app/v2/protocol.py`

### 11.2 Admin

- `apps/admin-web/src/v2/game-records/types.ts`
- `apps/admin-web/src/v2/game-records/parsers.ts`
- `apps/admin-web/src/v2/game-records/presentation.ts`
- `apps/admin-web/src/v2/game-records/request-presentation.tsx`
- `apps/admin-web/src/v2/game-records/V2GameRecordsPage.tsx`
- `apps/admin-web/src/v2/game-records/V2GameRecordDetailPage.tsx`
- `apps/admin-web/src/v2/game-records/V2OmniscientSituationPanel.tsx`

### 11.3 Mobile

- `apps/mobile-web/src/v2/contracts.ts`
- `apps/mobile-web/src/v2/api.ts`
- `apps/mobile-web/src/v2/live/LiveV2Page.tsx`
- `apps/mobile-web/src/v2/god-view/GodViewPage.tsx`
- 实际创建 V2 game 的 lobby/start 页面与 state 文件

## 12. 测试矩阵

### 12.1 Backend unit

`apps/api/tests/test_v2_protocol_units.py`：

- 双等价 JSON，包括普通对象 + fenced 对象；
- 格式不同但语义相等；
- target 不同、decision note 不同、context echo、不完整 fence、超过两个对象均拒绝；重复对象外围有 prose 时不应用该 repair，同时保留现有唯一单对象外围 prose 兼容；
- parser 返回唯一 value 与 repair kind。

`apps/api/tests/test_v2_model_provider_routing.py`：

- `generate_action_decision()` 只解析一次；
- ambiguity/shape error 保留精确 raw response；
- field、decision note 与 repair kind 来自同一 parsed document。

`apps/api/tests/test_v2_model_context.py`：

- V9 警长两个 option 都包含完整顺序且以警长结尾；
- 预览与纯函数结算一致；
- 四种 `reply_opportunity`；
- 问题前相关说明进入 `prior_relevant_event_refs`；
- 未来事件不进入 question/relation/ref；
- question/relation/event 引用闭包完整，V9 当前版本 dropped count 恒为 0；
- reply/prior detector 只消费实际投射结构；
- V9 多狼只有一个正确的 actor-private teammate fact；
- 单狼和非狼人无 teammate 泄漏；
- 显式 V8 Prompt 3 请求保持当前形状。

`apps/api/tests/test_v2_model_observation.py`：

- 真实投票句保留 `4、5、11 -> 9`、`1 -> 9`，不虚构 9 号自投且不产生 contradiction；
- `12投10`、多人显式“号”、否定/猜测/转述仍正确；
- 因果倒置正例；
- 否定、假设、转述和证据不足不命中；
- detector 异常 fail-open。

`apps/api/tests/test_v2_werewolf_attack_policy.py`：

- `unanimous_no_attack + allow_no_attack=false` 合法；
- 每狼目标必选且分歧后团队空刀；
- `allow_no_attack=true` 可以主动 `null`；
- 三种策略的 V9 派生语义；
- 现有轮转裁决单元测试保留。

规则层同时增加：

- `test_rule_set_validation.py`：合法组合可发布；
- `test_rule_set_snapshots.py`：历史内容哈希和快照不变；
- `test_v2_ability_runtime.py`：冻结策略正确编译为 V2 runtime policy。

### 12.2 Backend integration

`apps/api/tests/test_v2_api.py`：

- 同 runtime 并发一局 `tts`、一局 `text_only`；
- text-only 路径不解析、构造或调用 enabled client，且没有外部请求或 voice asset；
- TTS capability 缺失时显式拒绝；
- 创建后修改环境/default 不改变已冻结模式；
- 两个 runtime 同时 ready，恰有一个 owner/task/game_started/opening action；
- loser 不调用 model/TTS；
- 旧 fence 的所有写入均被拒绝；
- owner stale 时不从 opening 自动重跑；
- `awaiting_observation` 无 winner 不派生 completed；
- 权威完成派生 completed，终局 TTS 失败不回滚；
- 警长预览、实际顺序、私有 context 和事件完全一致；
- projection count 等于请求实际数组长度；
- 多狼夜间、日间发言和自爆请求都只有一个 canonical teammate event，非狼人请求没有泄漏；
- action/ability/presentation/voice/speech/TTS audience 沿权威来源一致，model lifecycle
  audience 按私有 payload 收窄且不得宽于 action audience；
- legacy unknown audience 在 Admin 显示未知，且不被普通玩家模型上下文或 public WebSocket/snapshot 消费；
- 狼人持续分歧四个 fixture 满足第 9 节全部断言；
- 因果 observation 被持久化，且没有 retry、speech rewrite 或 presentation 变化。

新增 `apps/api/tests/test_v2_delivery_execution_migration.py`，沿用 `test_v2_model_action_recovery_migration.py` 风格验证 upgrade、legacy unknown、check/default、索引和 downgrade。

### 12.3 Admin

- parsers/types 精确解析 audio、match、execution 字段；
- list/detail 覆盖进行中、权威完成、awaiting 无结果、stale owner、legacy unknown audio；
- Admin 区分 ledger 数量与实际 projected 数量；
- 新 observation code 有中文标签并显示证据 refs；
- legacy unknown audience 显示“旧记录范围未知”，不显示公开；
- terminal match 在 `execution_state in {owned, stale}` 时仍继续 live refresh，以接收终局
  presentation、voice、尾部事件和 owner release；只有 execution 已 `stopped`，或不存在
  活跃/失联 owner 时才停止轮询。不得只因 `live_state=awaiting_observation` 或
  `match_status=completed` 提前停止。

### 12.4 Mobile

- 创建请求明确提交 `audio_mode`；
- lineup preview 与 create 任一阶段返回 `409 rule_revision_changed` 时都刷新规则目录、
  清除旧质量报告并要求用户重新确认，不能让 stale preview 阻断 create 的冲突恢复；
- snapshot 合同覆盖两种新模式和历史 unknown 只读兼容；
- text-only 不等待 PCM unlock/capability；
- awaiting 无 winner 时结合 `execution_state`/phase 显示：owner 仍有效则为“等待观察/播放确认”，只有 `stopped` 或 `stale` 才显示“实时流程已停止”；
- 有权威 winner 才显示比赛结束；
- 终局 TTS 失败或缺失仍收敛到完成 UI。

## 13. 实施顺序

### Phase 0：迁移与兼容读

1. 新增 delivery snapshot、run lease/fence 字段和迁移测试。
2. API/Admin/Mobile 先兼容读取新旧数据。
3. 部署前 drain 活跃 V2 局。

### Phase 1：P0 Runtime

1. 创建时冻结 audio mode。
2. claim 携带 audio mode，接入 lazy TTS router。
3. 合并 start + ownership claim。
4. 全部 mutation 接入 fence 校验。
5. heartbeat、release、stale 诊断和部署 guard。
6. 终局派生字段与跨端文案。

### Phase 2：V9 Context

1. 增加 V8 Prompt 3 legacy reader 与 fixture。
2. 实现并验证 V9 projector、prompt、支持判定。
3. 提取 sheriff order 纯函数并增加 option 预览。
4. 投射紧凑 question/relation。
5. 狼队事实单一来源与规则派生语义。
6. Admin projection 审计展示。
7. 全部测试通过后，最后把 `current_model_context_contract()` 切换为 V9，避免中间版本创建出无法执行的新局。

### Phase 3：Parser、事件与诊断

1. 严格双 JSON parser 与 repair audit。
2. action/model/ability/speech/TTS event audience 和 fail-closed legacy Admin 解析。
3. vote parser regression。
4. 因果倒置 observed-only detector。

### Phase 4：完整分支与真局验收

1. 狼人持续分歧 API 集成测试。
2. 同进程混合 TTS/text-only 并发测试。
3. 双 runtime ownership 竞争测试。
4. 开一局新的 12 人 `text_only` 完整局。
5. 按第 14 节逐项核对冻结请求、事件序列、隐私投影和最终 UI。

## 14. 验收标准

### 14.1 自动化验收

至少执行：

```bash
cd apps/api
.venv/bin/python -m pytest \
  tests/test_v2_protocol_units.py \
  tests/test_v2_model_context.py \
  tests/test_v2_discourse_ledger.py \
  tests/test_v2_model_observation.py \
  tests/test_v2_model_provider_routing.py \
  tests/test_v2_werewolf_attack_policy.py \
  tests/test_v2_ability_runtime.py \
  tests/test_rule_set_validation.py \
  tests/test_rule_set_snapshots.py \
  tests/test_v2_delivery_execution_migration.py \
  tests/test_v2_api.py

.venv/bin/python -m pytest tests/test_v2_import_boundary.py

cd ../admin-web
pnpm test --run
pnpm lint
pnpm build

cd ../mobile-web
pnpm test --run
pnpm lint
pnpm build

cd ../..
git diff --check
```

上述命令与当前 package scripts 一致；不得省略 test、lint、TypeScript build 和 migration 验证。

### 14.2 新 12 人 text-only 真局

新局必须满足：

- create request 和 game snapshot 明确为 `text_only`；
- 不启动第二个 API 进程；
- 该 text-only game/run 路径不解析、不构造、不调用 enabled TTS client；真局验收期间若进程还运行其他 `tts` 局，不使用进程级 construction 总数作为该局断言；
- 0 external TTS request；
- 0 voice asset；
- 每段发言都有完整 presentation open/commit/seal/close，text-only 也持久化 canonical `speech_closed`；
- 每个 action/model/ability/speech/TTS lifecycle event 自带正确 audience；验收器必须按
  payload 实际敏感度检查，不能只验证 audience 是合法枚举；
- 只有一个 run owner 和持续有效的 fence；
- 0 duplicate action；
- 若真局触发警长顺序动作，则 V9 请求包含正确选项；该分支必达覆盖由确定性 integration fixture 保证；
- V9 问题/关系 projection count 与实际数组一致；
- 狼人请求只有一个正确队友事实源；
- public WebSocket/snapshot 与非狼人模型请求无狼聊、刀口、decision note；
- game completed 时 winner/reason/completed_at/event 一致；
- Admin/Mobile 显示“已完成 · 好人/狼人胜利”，而不是仅显示“等待观察”。

### 14.3 源问题回归

必须使用冻结 fixture 或精简同构 fixture 证明：

1. `v2_action_647d866a0b3b4a7d` 的双等价 JSON 形状只产生一次请求和一条 repair event。
2. 警长能在选择前看到两条完整顺序，并且预览与 engine 结果一致。
3. “4号、5号、11号跟我出9，1号也投了9”保留两组真实 claim，不生成 9 号自投，也不产生 contradiction。
4. 明确的“先发言、后报验，却称为报验后反应”产生 observed-only 因果诊断；正确否定不命中。
5. `unanimous_no_attack + allow_no_attack=false` 可发布、可运行、分歧时团队空刀。
6. 已解析 question/relation 实际进入 V9 请求，`reply_opportunity` 正确且 projection count 一致。
7. 多狼请求不再同时出现空 `living_teammate_refs` 与正确私有事实，只保留唯一 canonical teammate event。

## 15. 发布、回滚与运维

### 15.1 发布

1. 宣布 V2 维护窗口，等待所有活跃局完成或取消。
2. 先部署数据库迁移和兼容读取代码。
3. 再部署 runtime ownership 与 audio mode 写入路径。
4. 确认只有支持 sticky/single-owner 契约的 V2 流量入口。
5. 部署前端显式 audio mode 创建字段。
6. 观察一段兼容字段缺失率，归零后收紧 create contract。
7. 最后启用 V9 新局冻结。

### 15.2 监控

至少增加：

- 按 audio mode 的 game/action/presentation 数量；
- text-only 局 external TTS request 数，必须恒为 0；
- execution claim 成功/冲突/lease lost 数；
- stale owner 数；
- duplicate-identical JSON repair 数；
- ambiguous multiple JSON failure 数；
- Admin legacy unknown audience 数；
- 各 passive observation code 命中数与抽样误报率；
- V9 ledger 与 projected question/relation 数量差异。

### 15.3 回滚

- V9 通过冻结合同可停止给新局使用，旧 V9 局仍需保留 V9 reader/prompt，不能删除支持。
- audio mode 一旦冻结不可在运行中改回环境默认。
- lease/fence 上线后不能只回滚应用而保留无 fence 写入者；回滚必须 drain 活跃局并成套回退 runtime。
- additive event payload 可安全保留；旧消费者应忽略未知字段。
- passive detector 可单独关闭，但已经持久化的 observation 不删除。

## 16. 完成定义

本开发包只有在以下条件全部满足时才算完成：

1. 数据迁移、Backend、Admin、Mobile 和测试均已合并，不存在只改 prompt 的半实现。
2. 同进程混合有声/无声和双 runtime 竞争均通过自动化测试。
3. V9 与 V7/V8 frozen compatibility 都有 fixture 证明。
4. 私密 audience 在实时、持久化、Admin 历史解析三条路径一致且 legacy fail closed。
5. parser 修复、被动诊断和狼人持续分歧均有源问题回归。
6. 新 12 人 text-only 真局完成并通过第 14.2 节验收。
7. 文档中明确列为非目标的自动接管和跨 worker fanout 没有被发布说明误称为已支持。
