# 12 人局稳定性与真人感二次升级设计

## 背景

2026-06-15 在已合入“12 人局真人感与记忆可靠性优化”后，重新使用真实模型跑了一局 12 人预女猎白局：

- 规则集：`classic_12_seer_witch_hunter_idiot`
- 模型：`deepseek-v4-flash`
- seed：`2026061401`
- session：`game_hardening_probe_20260614_01`
- 日志目录：`artifacts/real_12_player_eval_after_hardening/game_hardening_probe_20260614_01/`
- 结果：第 5 夜失败，未完赛

这局证明上一轮 P0 问题已有改善：公开 replay 没有再泄漏 private summaries，`public_facts` 正常沉淀，`evaluate-replay` 对该 partial replay 输出 `issues=0`。但它也暴露了新的更底层问题：单个非法结构化动作仍会中断整局，失败日志不足以完整复盘，连续自爆和长时间静默监控影响真人感与可观测性。

## 关键证据

角色与状态：

- 1 号女巫，3 号预言家，6 号白痴，11 号猎人，2/7/8/12 四狼。
- 第 1 轮：5 号夜死，2 号狼人首爆，中断警长竞选。
- 第 2 轮：平安夜，7 号狼人自爆，触发双爆吞警徽。
- 第 3 轮：3 号预言家夜死，8 号狼人自爆。
- 第 4 轮：4 号夜死，9 号被放逐，系统生成公开总结 `第4轮；夜晚4号玩家出局；9号玩家被放逐。`
- 第 5 夜：12 号狼人刀 10 号；1 号女巫尝试毒 10 号，但 10 号是当夜被刀目标，不在毒药候选项中，最终失败。

女巫毒药失败的关键事实：

- 合法候选项为 `6号玩家、11号玩家、12号玩家、不使用毒药`。
- 模型连续多次返回 `{"poison":"10号玩家"}`。
- 当前重试只是重新调用相同 prompt，缺少“上次选择非法，只能从候选项中重新选择”的纠偏反馈。
- `resume_game()` 重放后仍失败在同一动作，说明这不是一次性网络抖动，而是约束表达和兜底策略不足。

失败日志问题：

- `game_partial.json` 保存了 state 和 rounds。
- `resume_checkpoint.json` 记录了 `failed_request` 与 cached model responses。
- `game_logs.json` 为空列表，当前轮进行中的 `RoundLog` 没有落盘，普通复盘无法直接看到失败动作链。

真人感与监控问题：

- 三名狼人 2、7、8 连续自爆，规则允许但观感偏“策略爆破”，压缩了公开讨论。
- 第 3、4 天白天动作长时间没有关键状态输出，看起来像卡住，实际是在顺序发言和投票。
- 发言中出现术语冲突和自指错位，例如“查杀5号好人”、10 号把自己放进“后置位10、11、12”一起第三人称盘。

## 目标

1. 让真实 12 人局不会因为单个可兜底的非法动作中断。
2. 让失败时的 partial replay 也能完整复盘当前轮和失败动作。
3. 让模型在结构化动作中更强地服从候选项，尤其是女巫毒药、猎人开枪、自爆。
4. 降低连续自爆、术语冲突、自指错位、模板归票等机器感。
5. 让 live/CLI 监控在长动作阶段保持可观测，不再像静默卡死。

## 非目标

- 不改变 12 人预女猎白局的角色配置、屠边胜利条件或双爆吞警徽规则。
- 不要求模型每一步策略都正确；本阶段目标是“不崩局、可复盘、少明显机械错误”。
- 不把夜晚狼刀、狼人私聊或 private summaries 暴露给普通观众。
- 不重做完整 agent 架构，不引入多模型裁判。

## 方案选择

### 方案 A：只加强 prompt

优点是改动小，可以快速提醒模型“必须从候选项选择”。缺点是这次真实局已经证明模型会连续多次忽略候选项，单靠 prompt 仍可能崩局。

### 方案 B：prompt 纠偏 + fail-soft 兜底

第一次非法后，把非法值、合法候选项、动作后果写入下一次重试 prompt。多次非法后，对可选动作走安全默认值，并发质量告警；对必须动作继续失败但保留完整日志。这个方案改动适中，能直接解决完赛稳定性。

### 方案 C：动作后处理自动改写为最近合法目标

优点是对局最不容易中断。缺点是会替模型做策略决定，例如把想毒 10 自动改成毒 11，破坏推理一致性，也很难解释给观众。

推荐采用方案 B。它尊重模型策略意图，又给可选动作留了安全出口。

## 设计

### 1. 非法动作纠偏重试

在 `apps/api/app/werewolf/lm.py` 中引入带反馈的重试上下文。当前 `generate_action()` 和 `generate_action_with_events()` 在值不属于 `allowed_values` 时只记录原始响应并重试相同 prompt。升级后：

- 第一次非法时记录 `invalid_value`。
- 下一次 prompt 追加一段“上次输出无效”的纠偏文本。
- 纠偏文本必须包含：
  - 上次非法值。
  - 合法候选项。
  - JSON 字段名。
  - 对女巫毒药这类动作的特殊解释，例如当夜被刀目标不在毒药候选中。

示例纠偏：

```text
上次输出的 poison 为“10号玩家”，但该值不在合法候选中。
本次必须从以下候选中选择 poison：6号玩家、11号玩家、12号玩家、不使用毒药。
如果你原本最怀疑的人不在候选中，请在剩余候选中重新排序，或选择不使用毒药。
```

该能力应保持通用：投票、毒药、猎人开枪、自爆、警徽移交都可以复用。

### 2. 可选动作 fail-soft

在 `apps/api/app/werewolf/engine.py` 中为可选动作定义安全默认值。多次非法后不应直接中断整局：

- `witch_poison` 默认 `不使用毒药`。
- `hunter_shoot` 默认 `不发动技能`。
- `werewolf_self_explosion` 默认 `不自爆`。
- `witch_save` 默认 `不使用解药`。
- `sheriff_withdraw` 默认保守选择“继续竞选”或现有规则定义的非破坏性选项。

fail-soft 必须记录到：

- `ActionLog`：保留原始 raw_response、parsed result、fallback choice、fallback reason。
- live event：发布 `action_quality_warning`，payload 包含 `invalid_value`、`fallback_choice`、`allowed_values`。
- checkpoint：保存失败前的原始模型响应和 fallback 决策，便于 resume 后确定性重放。

必须动作仍可失败，例如狼人夜刀或放逐投票没有合理默认值时，可以中断；但也必须保存完整 partial logs。

### 3. 女巫毒药候选解释

女巫毒药 prompt 增加候选解释：

- 明确列出当夜被袭击目标。
- 说明当夜被袭击目标不能同时作为毒药目标。
- 如果最可疑目标不在候选项中，要求在剩余候选中选择或不使用毒药。
- 强化 `poison` 字段必须完全等于候选项中的一个字符串。

这项提示只影响动作约束，不改变女巫规则。

### 4. 失败日志与 partial replay

当前 `run_game()` 捕获异常时保存 `state` 和 `logs`，但当前轮 RoundLog 还没进入 `logs`，因此 `game_logs.json` 为空或缺少失败轮。

升级后：

- `GameEngine` 持有当前轮日志快照，或者 checkpoint manager 在每次动作成功/失败后保存当前轮 log。
- 异常发生时，`save_game()` 接收 `logs_before_round + current_round_log`。
- `game_partial.json` 继续保存 state。
- `game_logs.json` 至少包含失败动作之前已完成的动作，以及失败动作的 `ActionLog`。
- `resume_checkpoint.json` 保留 `failed_request`，但 replay/evaluator 不依赖 checkpoint 才能解释失败。

### 5. 连续自爆抑制

在 `prompts_zh.py` 的狼人自爆提示中加入成本约束：

- 如果本局已有狼人自爆，后续狼人必须说明自爆能带来的明确收益。
- 收益包括吞警徽、阻止关键查验、保护最后隐狼、直接创造胜势。
- 如果收益不明确，应选择不自爆，保留白天发言空间。

在 `action_quality.py` 和 evaluator 中增加 `chain_self_explosion_overuse`：

- 三轮内连续多个狼人自爆时记录。
- 不阻止规则行为，只作为真人感风险输出。

### 6. 真人感质量检测

扩展 `action_quality.py` 和 `evaluator.py`，新增轻量文本检测：

- `role_term_contradiction`：检测“查杀好人”“金水狼人”等术语冲突。
- `self_reference_as_group`：玩家把自己放入“他们/后置位 X、自己、Y”中第三人称分析。
- `repeated_vote_reasoning`：同轮多名玩家使用高度相似的归票理由。
- `off_option_retry_failure`：模型多次选择合法候选外目标。
- `empty_partial_logs`：partial replay 有 error 但 logs 为空。

这些检测不直接改写发言，先进入 debug/evaluator 报告。后续若稳定命中，再考虑用纠偏重试。

### 7. 监控透明度

live/CLI 监控需要在长动作阶段可见：

- `model_request_started` 显示当前 actor/action。
- `model_thinking_tick` 显示已等待秒数。
- retry 时显示 `attempt` 和上次失败原因。
- 白天发言阶段显示已完成发言人数和剩余人数。
- summary 阶段显示正在生成私密总结，但不显示总结内容。

前端 live director 可继续过滤私密内容，但保留安全状态文本，例如“1号玩家正在重新选择女巫毒药目标，第 2 次尝试”。

## 数据结构

### ActionLog 扩展

新增可选字段：

```python
invalid_value: object | None
fallback_choice: object | None
fallback_reason: str | None
attempt_count: int
```

旧日志缺失这些字段时兜底为 `None` 或 `1`。

### LmLog 扩展

保留现有 `raw_response` 和 `result`。可选增加：

```python
invalid_attempts: list[dict[str, object]]
```

每项包含 `value`、`allowed_values`、`feedback`。

### Warning payload

```json
{
  "warnings": ["off_option_fallback"],
  "invalid_value": "10号玩家",
  "fallback_choice": "不使用毒药",
  "allowed_values": ["6号玩家", "11号玩家", "12号玩家", "不使用毒药"]
}
```

## 测试策略

### API 单元测试

- `generate_action` 第一次返回非法值、第二次返回合法值时，第二次 prompt 包含纠偏文本。
- `generate_action` 多次非法时返回 `None` 和完整 invalid attempts。
- 女巫毒药多次非法时 engine fail-soft 为 `不使用毒药`，不抛异常。
- 猎人开枪多次非法时 engine fail-soft 为 `不发动技能`。
- 必须动作多次非法仍抛异常，但保存 partial logs。

### 回放与 checkpoint 测试

- partial replay error 非空时，`game_logs.json` 不为空。
- 失败动作的 `ActionLog` 包含 raw_response、invalid_value、fallback 或 error。
- resume 后不会重复丢失已成功动作。

### evaluator 测试

- 构造最小 replay，覆盖 `invalid_action_abort`、`empty_partial_logs`、`chain_self_explosion_overuse`、`role_term_contradiction`、`self_reference_as_group`。
- 对 `game_hardening_probe_20260614_01` 的 partial replay，evaluator 应至少能报出 `invalid_action_abort` 和 `empty_partial_logs`。

### 前端测试

- live director 渲染 retry/fallback warning，不展示 private summary。
- debug trace 显示 fallback choice 和 invalid value。
- 长时间 thinking tick 不进入公开发言文本。

## 验收标准

下一次真实 12 人局应满足：

- 可选动作非法时不直接中断整局。
- 第 5 夜类似“女巫想毒当夜被刀目标”的情况能纠偏或 fail-soft。
- partial replay 可完整解释失败动作，不再只有 state 没有 logs。
- evaluator 能识别非法动作中断、空 partial logs、连续自爆、术语冲突、自指错位。
- live 监控长白天阶段有安全进度显示，不再像静默卡住。
- 公开 summary/private summary 边界继续保持不泄漏。

## 交付顺序

1. 非法动作纠偏重试。
2. 可选动作 fail-soft。
3. 失败日志保存当前轮。
4. 女巫毒药与自爆 prompt 强化。
5. evaluator 与 action quality 扩展。
6. live/CLI 监控透明度升级。

## 风险与取舍

- fail-soft 可能改变局势结果，但比整局崩溃更可接受；所有 fallback 必须进入日志。
- 纠偏 prompt 可能增加 token 成本，但只在非法输出后触发。
- 术语/真人感检测可能误报，因此第一阶段只记录，不自动重写发言。
- 连续自爆抑制不能破坏规则合法性，只能通过 prompt 和质量告警影响模型行为。
