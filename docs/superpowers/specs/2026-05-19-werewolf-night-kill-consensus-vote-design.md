# 夜晚狼人共识狼刀设计方案

## 背景

当前夜晚狼刀由后端在 `_run_night_phase()` 中选择 `active_wolves[0]` 代表整个狼人阵营执行 `remove` 行动。这个实现简单，但多狼局里只有一名狼人真正参与夜晚击杀决策，其他狼人只能通过初始队友视角间接影响白天发言，夜晚缺少狼队协作感。

目标是把夜晚狼刀改成“狼队先私密沟通，再持续投票直到所有存活狼人达成一致”。最终一致目标写入现有 `round_state.attacked`，后续守卫、女巫、猎人、警徽和夜死公布继续沿用现有结算链路。

## 目标

- 所有存活狼人都参与夜晚狼刀决策。
- 狼人在投票前可以私密沟通，降低分歧概率。
- 狼刀必须由所有存活狼人投出同一目标后才成立。
- 如果投票不一致，持续协调并重投，直到投票结果一致。
- 保持旧的夜晚死亡结算语义：`attacked` 只是最终狼刀目标，是否死亡仍由守卫、女巫等后续规则决定。
- 实时观战不能暴露狼人身份、狼队沟通内容或狼刀票型。
- 回放和调试数据能完整还原狼队沟通与每轮投票。

## 非目标

- 不改白天放逐投票规则。
- 不引入随机破平。
- 不让普通观战用户看到夜晚狼人私聊或票型。
- 不把狼刀沟通做成多人并发聊天；后端仍按顺序调用模型，模拟私密沟通。
- 不为不同规则集提供可配置的狼刀模式；第一阶段所有包含 `ACTION_REMOVE` 且多狼存活的规则集共用该机制。

## 规则定义

### 单狼情况

如果夜晚只剩 1 名存活狼人，行为保持接近当前实现：

1. 跳过狼人私聊。
2. 该狼人直接执行一次狼刀投票行动。
3. 选择的非狼人目标成为 `round_state.attacked`。

### 多狼情况

如果夜晚有 2 名及以上存活狼人：

1. 狼队先进行一轮私密沟通。
2. 每名存活狼人依次给出建议目标和简短理由。
3. 后发言狼人可以看到前面狼人沟通内容。
4. 沟通结束后进入投票循环。
5. 每轮投票中，每名存活狼人各投一票。
6. 本轮所有狼人投向同一个目标时，目标成为最终狼刀目标。
7. 只要本轮存在分歧，就记录票型，再进行一轮协调沟通与重投。
8. 重投持续进行，直到所有存活狼人投票一致。

### 重投候选范围

首轮投票候选人为所有存活非狼人。

从第二轮开始，候选人收窄为上一轮被投过的目标集合。例如上一轮 4 名狼人分别投给 `3号玩家、3号玩家、5号玩家、8号玩家`，下一轮候选人就是 `3号玩家、5号玩家、8号玩家`。

这样保留“持续重投直到一致”的规则，同时减少模型在全场候选中反复摇摆的概率。

### 工程保护

业务规则是持续重投直到一致。为了防止模型异常导致后端无限循环，增加保护阈值：

```python
MAX_WEREWOLF_KILL_VOTE_ROUNDS = 8
```

如果达到保护阈值仍未一致，后端不随机裁决，也不判定狼刀失败，而是抛出明确错误：

```text
狼人夜晚投票未能达成一致
```

这表示模型未能完成规则要求，属于对局运行错误。保护阈值只用于避免服务卡死，不改变游戏规则。

## 数据模型

在 `RoundState` 增加两个结构化字段：

```python
werewolf_discussion: list[dict[str, str]] = field(default_factory=list)
werewolf_vote_rounds: list[dict[str, object]] = field(default_factory=list)
```

`werewolf_discussion` 记录初始私聊和每次重投前的协调发言。每条记录包含：

```json
{
  "round": 1,
  "speaker": "2号玩家",
  "target": "5号玩家",
  "message": "建议刀5号，他白天持续压中狼坑。"
}
```

`round` 表示对应投票轮次前的沟通。首轮投票前的沟通为 `round: 1`，第一次重投前的协调为 `round: 2`。

`werewolf_vote_rounds` 记录每轮投票：

```json
{
  "round": 2,
  "candidates": ["5号玩家", "8号玩家"],
  "votes": {
    "2号玩家": "5号玩家",
    "4号玩家": "5号玩家",
    "7号玩家": "5号玩家"
  },
  "tally": {
    "5号玩家": 3
  },
  "unanimous": true,
  "result": "5号玩家"
}
```

字段含义：

- `round`：狼刀投票轮次，从 1 开始。
- `candidates`：本轮可选目标。
- `votes`：狼人到目标的映射。
- `tally`：目标票数统计。
- `unanimous`：是否所有狼人投向同一目标。
- `result`：一致时为最终目标，不一致时为 `null`。

`round_state.attacked` 继续作为最终狼刀目标。只有一致投票产生后才写入。旧回放缺少新字段时，前端和适配层使用空数组兜底。

## 日志模型

在 `RoundLog` 增加：

```python
werewolf_discussion: list[ActionLog] = field(default_factory=list)
werewolf_votes: list[list[ActionLog]] = field(default_factory=list)
```

- `werewolf_discussion` 保存每次狼人私密沟通模型调用。
- `werewolf_votes` 按投票轮次保存每名狼人的投票行动。

保留 `round_log.eliminate`。为了兼容旧调试视图，可以在最终一致轮中选择一条投给最终目标的行动日志赋给 `round_log.eliminate`。新 UI 和新调试面板优先读取完整的 `werewolf_votes`。

## 后端流程

把 `_run_night_phase()` 中当前单狼人代表行动替换为 helper：

```python
attacked = self._run_werewolf_kill_consensus(round_state, round_log, active_players)
round_state.attacked = attacked
```

helper 的职责：

1. 收集 `active_wolves` 和 `non_wolves`。
2. 如果规则集不包含 `ACTION_REMOVE`，直接返回 `None`。
3. 如果没有存活狼人或没有存活非狼人，返回 `None`。
4. 如果只有一名狼人，执行一次 `werewolf_kill_vote`，返回目标。
5. 多狼时先执行 `werewolf_discuss`。
6. 进入投票循环。
7. 每轮调用所有存活狼人执行 `werewolf_kill_vote`。
8. 统计票型并记录到 `round_state.werewolf_vote_rounds`。
9. 如果一致，返回目标。
10. 如果不一致，候选人收窄到上一轮被投过的目标集合，并执行下一轮协调沟通。
11. 超过保护阈值仍未一致，抛出运行错误。

投票循环不要把同一轮中前面狼人的票传给后面狼人，避免顺序调用变成“后手可跟票”。本轮投票结束后，完整票型才进入下一轮协调上下文。

## Prompt 设计

新增 action：

- `werewolf_discuss`
- `werewolf_kill_vote`

`werewolf_discuss` schema：

```json
{
  "reasoning": "string",
  "target": "string",
  "message": "string"
}
```

要求：

- 这是狼人夜晚私密沟通，仅狼人队友可见。
- 必须从候选人中建议一个袭击目标。
- `message` 用游戏术语说明理由，避免伤害性措辞。
- 重投前的协调 prompt 包含上一轮票型、分歧目标和当前候选人。

`werewolf_kill_vote` schema：

```json
{
  "reasoning": "string",
  "target": "string"
}
```

要求：

- 必须从候选人中选择一个目标。
- 首轮参考完整狼队沟通。
- 重投轮参考上一轮票型和协调发言。
- 目标必须能帮助狼队形成一致刀口。

为了减少对旧 `remove` 语义的混淆，建议新增 `ACTION_WEREWOLF_KILL_VOTE`，而不是继续复用 `ACTION_REMOVE`。`ACTION_REMOVE` 可以保留给旧日志兼容或作为规则概念，实际模型行动使用新 action。

## 实时事件与隐私

夜晚狼人沟通和投票是秘密行动。实时观战事件不能暴露：

- 狼人 actor 名称。
- 狼人沟通内容。
- 投票目标。
- 票型统计。
- 重投候选人。

可以发布公共进度文案：

- `狼人正在夜晚沟通...`
- `狼人正在秘密投票...`
- `狼人未达成一致，正在继续协调...`

内部事件仍可包含完整 payload，但前端面向普通观众的 live UI 必须按夜晚秘密行动处理，只显示等待状态。若后续支持上帝视角，可以由明确权限开关读取完整狼队日志。

## 结算影响

此设计只改变 `round_state.attacked` 的产生方式，不改变夜晚死亡结算。

现有逻辑继续适用：

- `attacked == protected` 时狼刀被守卫挡下。
- `attacked == saved_by_witch` 时狼刀被女巫解药救下。
- 未被保护或救下时，产生 `DeathEvent(attacked, "werewolf_attack", "狼人")`。
- 女巫毒药产生额外 `witch_poison` 夜死。
- 猎人因狼刀死亡时可开枪，因毒药死亡时不能开枪。
- 首夜警长竞选前的 pending 夜死继续延迟公布。

## 前端和回放

第一阶段前端可以只展示最终 `attacked` 和 `night_deaths`，保持现有观赛体验。

回放详情或调试面板可以新增夜晚狼队决策区：

- 狼人私密沟通记录。
- 每轮投票票型。
- 是否一致。
- 最终狼刀目标。

旧数据兼容：

- 缺少 `werewolf_discussion` 时视为空数组。
- 缺少 `werewolf_vote_rounds` 时视为空数组。
- 旧回放仍使用 `attacked` 展示狼刀目标。

## 测试计划

后端测试：

1. 单狼局仍能直接产生 `attacked`。
2. 多狼首轮全票一致，直接产生 `attacked`。
3. 多狼首轮不一致，触发第二轮协调和重投。
4. 第二轮一致后产生 `attacked`。
5. 第三轮或更后轮一致后产生 `attacked`。
6. 重投候选人只包含上一轮被投过的目标。
7. 同一投票轮内，后行动狼人看不到前行动狼人的本轮票。
8. 达到保护阈值仍未一致时抛出明确错误。
9. 守卫保护最终 `attacked` 时无人因狼刀死亡。
10. 女巫救最终 `attacked` 时无人因狼刀死亡。
11. 猎人被最终狼刀击杀时仍可开枪。
12. 12 人局首夜警长竞选前的 pending 夜死仍正确延迟公布。
13. `RoundState.to_dict()` 序列化新字段。
14. `RoundLog.to_dict()` 序列化新 action log。

前端和适配测试：

1. 新字段缺失时回放不报错。
2. 新字段存在时调试数据能展示完整狼队沟通和投票轮次。
3. live stream 对普通观众不显示狼人 actor、沟通内容或票型。

## 风险与缓解

- 模型调用次数增加：多狼局每轮至少调用每名狼人一次，另有沟通调用。通过候选范围收窄和 prompt 强调一致目标来降低重投轮数。
- 无限重投风险：用保护阈值中止异常对局，避免服务卡死。
- 夜晚隐私泄漏：新增 action 必须纳入秘密行动显示策略，前端不能直接渲染 actor。
- 旧日志兼容：保留 `attacked` 和 `round_log.eliminate`，新字段作为增强数据。
- 文件增长：`engine.py` 已经较大，实现时应把狼队共识逻辑拆成小 helper，避免把 `_run_night_phase()` 继续拉长。

## 验收标准

- 多狼夜晚击杀由所有存活狼人参与。
- 狼队投票必须全体一致才产生狼刀目标。
- 投票不一致会持续协调并重投，直到一致或触发工程保护错误。
- 最终 `attacked` 与现有夜死结算链路兼容。
- 普通实时观战不暴露狼人身份和夜晚秘密内容。
- 回放数据能还原每轮狼队沟通和投票。
