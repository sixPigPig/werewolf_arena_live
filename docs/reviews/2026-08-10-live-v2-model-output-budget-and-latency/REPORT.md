# Live V2 模型输出预算与耗时治理开发文档 Review 报告

**Date:** 2026-08-10

**Result:** PASS

**Reviewed document:** `docs/superpowers/specs/2026-08-10-live-v2-model-output-budget-and-latency-remediation-design.md`

**Approval state:** 文档 review 已通过；用户已于 2026-08-10 明确回复“通过，进入开发”。本报告记录开发前 review 结论，不替代后续代码 review、测试与发布门禁。

## 1. Review 方法

本次 review 分四轮完成：

1. 对照 `docs/live-v2-refactor-guidelines.md` 的开发前门禁，检查范围、非范围、状态、事件、隐私、字幕/TTS、结束条件、自动化、真局观察与回滚；
2. 对照当前 `model_client.py`、`action_engine.py`、day/repository/runtime/cancel 路径，检查错误分类、attempt 上限、事务顺序与恢复语义；
3. 对照 f29 的 durable DB/event/request 证据，检查文档是否把终局、失败、人工等待、queue、first token、reasoning-only 和 active latency 分开；
4. 由独立 reviewer 对每轮修订重新检查，直到没有 P0/P1 阻断。

review 只读取代码与证据，没有修改运行时代码、测试、数据库、现有对局、并发配置或 Provider 配置。

## 2. 首轮阻断项与修订

| Finding | 处理结果 |
| --- | --- |
| 不可变 `model_request_failed` 不能预写未来 resolution | failure 事件只写当时已知 retry decision；最终结果改用稳定 episode ID 与后续 durable facts 聚合 |
| V12 preflight 使用了不存在的 waiting/running/paused 泛称 | 改为真实 live states，并定义 completed/canceled/failed、ownership、open resources 与 recovery 的完整 terminal predicate |
| “speech 不得第三次”会误排除 required target + required speech | 只排除 `kind=speech`；源动作的 target-kind + required speech 明确保留资格 |
| “无技术兜底”不是冻结合同字段 | 从谓词删除伪字段；记录当前 target-kind 无技术兜底，未来变更必须新增显式冻结合同 |
| God-view audience 可能被误解为允许 Mobile 读取模型诊断 | normal 与 god-view Mobile 均明确禁止 request/headers/usage/raw private context；仅 Admin 可读 |
| output-budget 移出 machine-format 后可能产生 decision-family 2+2+3 放大 | 新增独立 family output-budget lineage 与 automatic budget=3 |
| C1 shadow 被误写成已解决 active latency | 明确 C1 只观测；B 降人工等待、D 优化结构、E 降 queue，C2 才可能截断 reasoning-only 长尾 |
| V12 canonical/hash、模型基准和 canary 样本口径不够精确 | 固定 canonical JSON/hash、全请求 valid-adopted denominator、失败 pair elapsed、固定 workload、条件 cap=6 与硬预算 |

## 3. 后续原子性与边界 Review

### 3.1 取消 resolution 写事件

曾考虑新增 `model_failure_resolved`，但 outcome 与 resolution 分事务会产生 crash gap；用唯一约束补救又会扩大到新表/迁移。

最终设计不新增该事件：

- 用 game/run/action/retry-cycle/first-failed-attempt 确定性生成 `failure_episode_id`；
- 用唯一纯函数 `derive_failure_episodes(events)` 在单一 run、单一 DB snapshot 内聚合；
- 没有 outcome 时显示 `unresolved`，互斥 evidence 显示 `invariant_conflict`；
- Admin、cancel 与全部 terminal-failure transaction 复用同一 deriver，避免两套判定漂移。

### 3.2 持久化顺序

最终规格要求：

- failure append 成功后立即标记 recorded，旁路 health/audit 失败不能重复写 failure；
- accepted response append 成功后立即标记 completed 并清空 active episode；
- committed pause 后同样清空 active episode；
- technical supporting event 与后续 `action_succeeded` 成对后才算 technical resolution；
- `fail_action()` 在 game lock 下复核 episode 仍 open，防止旧 ID 在 response/pause 后传播；
- cancel 与 day/night/phase/max-round terminal failure 在原事务中列出全部 open episode IDs。

### 3.3 Audience 与关联

source model lifecycle events 必须保持 model audience 一致；terminal evidence 保留现有安全 audience。关联只能通过：

- action-level 白名单事件、同 game/run/action、严格 record order 与显式 disposition/supporting ref；
- `game_canceled.canceled_failure_episode_ids`；
- run-level failure event 的 `failed_failure_episode_ids`。

episode ID、supporting refs 与 open-ID lists 必须从 normal/god-view Mobile 和玩家模型上下文移除。

### 3.4 Decision-family

isolated action 的 episode 由其 `action_failed` 终结。后续 sequential preflight pause 没有新的模型请求，不创建或二次终结 episode；它只引用完整、有序、去重的 `source_failure_episode_ids`，解释 initial/recovery 如何共同耗尽 family budget。

## 4. 最终 Review 结论

独立 reviewer 第四轮结论为 PASS，无 P0/P1 阻断。以下范围可在用户批准后按顺序实施：

1. A：`output_budget` 独立分类、完整流诊断与 failure episode 只读聚合；
2. B：blocking required-target 在原 action budget 足够时的第三次同语义 attempt；
3. C1：冻结 generation policy 与 reasoning-only shadow，保持模型参数不变；
4. D：V12 lossless compact context 与严格 V11/V12 cutover；
5. E1：隔离 Agent Plan cap=3/4，4 通过后才测 6；生产值不变。

C2 reasoning timeout enforce、E2 公平 scheduler、生产并发修改、Git commit/push 和生产发布均不在本次自动授权范围。

## 5. 非阻断残余风险

1. terminal transaction 在 game lock 下派生 episode 可能延长长局锁持有时间；实现时必须测量，并可只查询 deriver 所需事件类型，但不能改变完整语义。
2. 当前没有 started-run takeover；worker crash 后 open episode 会保持 unresolved，直到管理员取消。本工作包不得顺手新增接管能力。
3. 首个 V12 游戏创建后不能回滚到仅支持 V11 的 binary，只能暂停新建并 fix-forward；上线 preflight 是硬门禁。
4. 外部 A/B 与 canary 样本量只适合发现明显回退，不能证明长期 SLA；报告必须保留样本量与置信边界，不得过度结论。

## 6. 用户批准门禁

只有用户明确批准后才能开始 A/B/C1/D 的运行时代码与测试开发，并按文档硬上限进行 E1/真局验证。批准不等于 Git 提交、push、生产发布、生产并发修改或存量私密请求回放授权。

用户批准已取得。实施后只读 cutover preflight 仍报告 149 个 blocker，当前无法证明外部模型实验不会产生 overage，且 E1 live runner 尚未实现；因此 V12 发布、V11/V12 外部配对、E1 真实 canary 与 12 人真局仍保持暂停。这些是原 review 已批准的停止条件正常生效，不是对批准范围的扩大。

## 7. 实施后代码 Review（2026-08-10）

实现完成后又进行了独立的后端、隐私/fail-closed、Admin 前端、E1 对抗与文档一致性复核；最终均为 PASS，无剩余 P0/P1/P2 阻断：

- 后端复核确认 output-budget、第三次 required-target 重试、decision-family budget、failure episode terminal evidence、C1 observe-only、V12 编解码和 E1 门禁均符合本文；
- 隐私复核确认 failure episode/生成策略内部字段不进入 Mobile、god-view 或模型输入；Admin hybrid 合同拒绝展开；f29 fixture 不含原始发言、私有 ID、冻结请求、原始响应或凭据；
- E1 对抗复核曾发现外部聚合报告、跳档与异常预算账本可成为未来 live 授权缺口，现已收紧为：移除 CLI 外部 cap4 report、任何 cap6 live 计划固定拒绝、live 只允许 `(3,)`/`(3,4)`、账本全部字段二次校验；
- 文档复核确认没有把 C1 shadow、D 字符压缩或 E1 离线 harness 误报为 active latency、queue、吞吐或生产发布已经改善。

最终验证口径为：任务相关后端组合 `599 passed`；后端全量 `2772 passed, 10 skipped, 2 failed`，两条失败均来自本次未修改文件中的既有 V2 import-boundary 违规；Admin Web 全量 `380 passed`、production build 与 ESLint 通过；Python Ruff lint 与 `git diff --check` 通过。仓库全量 format check 仍存在历史/现有未统一格式文件，本次新增的 9 个 Python artifact 已通过格式检查，未机械改写无关文件。

该 PASS 只表示已授权代码范围可以交付 review，不解除 V12 cutover、外部计费、E1 live runner、生产并发、真局、Git commit/push 或生产发布门禁。
