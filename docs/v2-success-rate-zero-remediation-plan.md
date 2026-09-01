# 狼人杀 v2 对局成功率 0% — 根因分析与修复执行方案

> 日期：2026-09-01 ｜ 状态：已批准，按任务 0→7 顺序执行
> 数据来源：docker postgres（db=app）对局事件取证

## 背景

近 3 天 6/6 局全部失败，历史累计 132 failed / 0 completed，管理台「对局成功率」= 0%。
成功率口径：`completed / (completed + failed)`，按 `GameRun.started_at >= since` 过滤
（apps/api/app/match/router.py:732）。

## 根因清单（数据实锤）

| 根因 | 影响 run | 失败形态 |
|---|---|---|
| A. 降级弃票 `source_action_id` 血统不匹配 | cdee755e | `pre-exile technical abstention changed its speculative result` 直接杀局 |
| B. glm-5-3-flash 强制思考模型收到 `thinking.type=disabled` → HTTP 400 | cdee755e | 3 张 exile_vote 全部 400 → 触发根因 A |
| C. RunReaper 清理僵尸局（一次性，63 局） | 78ac4733 / c91da406 | `worker_lease_expired` 8-31 07:21 |
| D. 传输风暴 / 首 token 超时 | 844cb1f0 / adbb2f7e | `transport` / `model_first_token_timeout` 链路失败 |
| E. 开发中投票关思考特性污染冻结参数 | bb2b8a2e | 全模型 sheriff_vote `model_parameters_invalid`（修复已随任务 0 封存） |

### 根因 A 细节

day_engine 降级弃票时把 `source_action_id` 写为原始推演动作 id，而提交闸校验器
（apps/api/app/match/match_repository.py:2823）要求：
`vote.source_action_id == (result.recovery_action_id or result.action_id)`。
有恢复动作时两者不一致 → 校验抛错杀局。取证（run cdee755e，system-player-08）：
vote.source_action_id=`v2_action_35dd95a51df74a25`，
result.recovery_action_id=`v2_action_e89cf522e3ed436b`，其余 5 个字段全部匹配。

### 根因 B 细节

GLM-5.3 / GLM-5.3-Flash 为强制思考模型（官方文档：`thinking.type` 仅支持 `enabled`，
传 `disabled` 返回 HTTP 400）。本地 `reasoning_policy_for_model` 无 glm-5-3 家族策略，
回落到允许 disabled 的 `_GLM_5_2_POLICY`；投票关思考 override
（action_engine.py `_apply_provider_thinking_override`）无条件发送
`"thinking": {"type": "disabled"}`（事件载荷实测 `thinking_source=vote_phase_thinking_policy`）→ provider 400。

### 放大器

agent_plan `live_v2_agent_plan_max_in_flight=3`（config.py:149）导致 idle_only 投机预取
常态打不中（失败载荷实测 `provider_in_flight: 3/3`），投票全部走实时驱动，任何 provider
抖动都会沿「auto-retry 耗尽 → abandon → 降级弃票」链路暴露根因 A。

## 任务清单（按执行顺序，每任务独立 commit）

### 任务 0 — 封存工作区
将现有未提交改动（run_reaper、auto-retry、投票关思考、pre-exile 严格化、dashboard 重构）
作为单个 commit 封存，与本方案文档一起提交。

### 任务 1 (P0) — 修复降级弃票 `source_action_id` 血统
- day_engine.py `degrade_vote_to_abstain`：`"source_action_id": recovery_action_id or source_action_id`（一行，覆盖两个降级分支）
- 补测试断言：test_v2_pre_exile_orchestration.py（`source_action_id == "v2_action_recovery_player_1"`）、
  test_v2_pre_exile_pipeline_repository.py（DayVoteCommit 构造对齐校验器语义）
- Commit: `fix(v2): point degraded abstain lineage at recovery action`

### 任务 2 (P1) — 新增 GLM-5.3 家族推理策略
- apps/api/app/model_catalog/defaults.py：新增 `_GLM_5_3_POLICY`
  （thinking_options=("enabled",)、thinking_locked=True、effort low/high/max、disabled_max_tokens=None），
  在 `reasoning_policy_for_model` 的 glm-5-2 分支前插入 glm-5-3 分支
- apps/admin-web/src/features/models/preview.ts：前端策略镜像同步
- 策略单测：glm-5-3-flash 拒绝 disabled、接受 low/high/max

### 任务 3 (P1) — 投票关思考 override 策略守卫
- action_engine.py `_apply_provider_thinking_override`：查 `reasoning_policy_for_model`，
  `"disabled" not in thinking_options` 时不发 disabled；effort 档非空则保持 enabled + 最低 effort 档
  （thinking_source=`vote_phase_thinking_policy_effort_floor`），为空则不 override
- 扩展 test_v2_pre_exile_orchestration.py override 用例（glm-5-3-flash / kimi-k3）
- Commit（任务 2+3 合并）: `fix(v2): add glm-5-3 forced-thinking policy and guard vote thinking override`

### 任务 4 (P2) — 容量调优
- config.py `live_v2_agent_plan_max_in_flight` 默认 3→6（.env 可覆盖；部署前确认 Ark 配额）
- config.py `live_v2_vote_fanout_stagger_ms` 300→500
- 不改 idle_only 不可重试语义（设计使然）
- Commit: `chore(v2): raise agent_plan in-flight default to 6 and widen vote fanout stagger`

### 任务 5 (P2) — 恢复链路测试覆盖
- tests/test_v2_model_action_recovery_migration.py：补齐
  「auto-retry 耗尽 → abandon → 降级弃票落账」全链路断言，与任务 1 血统语义联动
- Commit: `test(v2): cover auto-retry exhaustion to degraded abstain chain`

### 任务 6 (P3) — 观测修复
- (a) router.py signal_events 查询 join GameRun，改按 `GameRun.started_at >= since` 过滤，
  与成功率口径统一
- (b) 一次性运维 SQL（不进代码）：5 个 7 月 `waiting_to_start` 僵尸 run → `canceled`，
  执行前备份 run id 清单
- Commit: `fix(v2): align signal event window with run started_at`

### 任务 7 (P3) — 端到端冒烟：史上首个 completed
- 新增 scripts/smoke_v2_full_game.py：创建 12 人局（classic_12，混合绑定 6 模型含
  glm-5-3-flash）→ ws ready 自动启动 → 轮询至 completed/failed →
  断言 completed 且技术弃票 lineage 一致；failed 时 dump 失败事件载荷
- 真实跑一局完整对局（消耗 Ark 额度，wall-clock 30 分钟+，已与用户确认）
- Commit: `test(v2): add full-game smoke script`

## 验证总览

1. 每任务对应 pytest 目标
2. 任务 3 后全量 `cd apps/api && python -m pytest -x -q` 无回归
3. admin-web 构建确认 preview.ts 同步无类型错误
4. 任务 7 真实对局跑通 = 终极验收（成功率 0 → >0）

## 风险与回滚

- 任务 1：一行改动 + 断言，revert 单 commit 即回滚，无 schema 变更
- 任务 2：新策略仅影响 glm-5-3 家族；前端镜像不同步会导致管理台预览与后端不一致
- 任务 3：新 thinking_source 值（观测性字段，非契约）出现在事件载荷中
- 任务 4：max_in_flight 依赖 Ark 配额，超限可 .env 调回 3
- 任务 6b：僵尸清理为一次性 SQL，执行前备份 run id 清单
