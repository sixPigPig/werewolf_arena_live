# 观赛玩家状态语义整理设计

**日期**: 2026-05-20
**状态**: 待确认实现
**范围**: 梳理实时观赛与历史回放舞台中玩家卡片、顶部席位、倒计时和高亮状态的观众可见语义，解决“不是发言却显示发言中”的问题，并为后续实现提供状态模型、映射规则和验收标准。

## 背景

观赛页的舞台正在承担两类职责：

- 叙事职责：让观众知道当前发生了什么，例如正在发言、正在投票、夜晚行动、白天放逐、游戏结束。
- 状态职责：让观众看懂每个玩家此刻和当前事件的关系，例如当前发言者、当前投票者、当前行动者、被结算对象、已出局玩家。

当前实现把这些关系压缩成了一个 `activePlayerName` / `isSpeaking`，导致只要事件里带 `actor`，玩家卡片就可能被当成“发言中”。这会让观众误以为玩家正在公开发言，但实际可能是在投票、夜间行动、总结、模型请求或结算。

## 当前问题定位

核心问题是“当前演员”和“当前发言者”被混用。

- `apps/web/src/features/games/components/LiveStageExperience.tsx:45` 优先使用 `director.currentCue?.actor`，否则使用 `spectatorState.activePlayerName` 作为舞台活跃玩家。
- `apps/web/src/features/games/liveSpectator.ts:70` 只要事件存在 `actor`，就会把 `state.activePlayerName` 更新为该玩家。
- `apps/web/src/features/games/liveGodView.ts:645` 用 `player.name === view.activePlayerName` 直接推导 `isSpeaking`。
- `apps/web/src/features/games/liveGodView.ts:1042` 中 `isSpeaking` 会覆盖玩家自身状态标签，直接显示 `发言中`。
- `apps/web/src/features/games/components/LiveDirectorStage.tsx:230` 用 `player.isSpeaking` 决定卡片进入 `speaking` 高亮态。
- `apps/web/src/features/games/liveGodView.ts:980` 顶部席位固定显示 `发言席`，即使当前事件是投票、夜间行动或结算。

现有测试也固化了错误语义：

- `apps/web/src/pages/LiveGamePage.test.tsx:1221` 投票 `action_requested` 之后，测试期望李四卡片为 `speaking`。
- `apps/web/src/pages/LiveGamePage.test.tsx:390` 放逐 `state_updated` 之后，张三仍然被期望显示 `发言中`，说明旧的发言高亮没有随结算语义清理。

后端事件本身没有把 `actor` 等同于“发言者”。例如：

- `apps/api/app/werewolf/engine.py:990` 白天发言的 `state_updated` 会带 `actor=speaker` 和 `action=ACTION_DEBATE`，这是合法发言。
- `apps/api/app/werewolf/engine.py:1627` 总结阶段也会带 `actor=name` 和 `action="summarize"`，但它不应该在观众卡片上显示为普通发言。
- `apps/api/app/werewolf/engine.py:1876` 公开的行动请求都会带 `actor` 和 `action`，其中包含投票、竞选、技能等多种非发言行为。

## 设计目标

- 只有玩家确实处于公开发言语义时，卡片才显示 `发言中`。
- 投票、夜间行动、竞选表态、总结、结算不再复用发言状态。
- 玩家卡片状态让观众一眼看懂“这个玩家和当前事件是什么关系”。
- 顶部席位和倒计时文案跟随当前语义变化，不再固定为 `发言席` / `00:45`。
- 不提前暴露私密信息。夜间私密行动可以显示为泛化的 `行动中` / `已行动`，不展示具体目标或身份推断。
- 优先在前端语义层解决，不要求后端事件协议变更。

## 非目标

- 不重新设计观赛舞台布局。
- 不改变游戏规则、行动顺序或后端事件生成逻辑。
- 不把所有模型内部状态直接展示给观众，例如请求 ID、解析细节、调试事件类型。
- 不在本次设计中新增时间轴拖拽、手动定位或复杂动画系统。

## 语义拆分

后续实现需要把以下概念拆开，不再共用 `activePlayerName`：

| 概念 | 含义 | 典型来源 | 可见用途 |
| --- | --- | --- | --- |
| `currentActorName` | 当前事件的执行主体 | `event.actor` / `cue.actor` | 内部推导，不直接等于发言 |
| `currentSpeakerName` | 正在公开发言的玩家 | 发言类 action 或可见发言流 | 卡片 `发言中`、顶部 `发言席` |
| `currentPerformerName` | 正在执行公开可感知动作的玩家 | 投票、竞选、总结、公开行动 | 卡片 `投票中` / `行动中` / `总结中` |
| `affectedPlayerNames` | 当前结算影响到的玩家 | `state_updated` payload 中的出局、死亡、保护、警徽等结果 | 卡片 `被放逐` / `夜晚出局` / `被守护` |
| `lastResolvedActorName` | 刚刚完成动作的玩家 | `action_parsed` / `model_response_received` / 相关 state update | 短暂显示 `已投票` / `已行动` |
| `highlightedPlayerNames` | 当前需要视觉强调的玩家集合 | 由以上语义综合得出 | 卡片描边、亮度、徽标 |

`activePlayerName` 可以继续作为底层历史状态存在，但不应直接驱动 `isSpeaking`、卡片 `speaking` 态或顶部 `发言席`。

## 观众可见状态模型

建议新增一个面向舞台展示的状态类型，例如 `PlayerStageStatus`：

```ts
type PlayerStageStatusKind =
  | "idle"
  | "preparing-speech"
  | "speaking"
  | "summarizing"
  | "voting"
  | "acting"
  | "resolved"
  | "affected"
  | "out";

type PlayerStageStatus = {
  kind: PlayerStageStatusKind;
  label: string;
  priority: number;
  sourceEventId: number | null;
};
```

同一个玩家同时命中多个关系时，按优先级展示：

1. `out`: 已死亡、已放逐、已出局。
2. `affected`: 当前事件正在结算该玩家，例如被放逐、夜晚出局、被守护。
3. `speaking`: 当前确实在公开发言。
4. `preparing-speech`: 发言请求已发出，但尚未出现可见发言内容。
5. `voting` / `summarizing` / `acting`: 当前正在投票、总结或行动。
6. `resolved`: 刚刚完成动作，例如已投票、已行动、已总结。
7. `idle`: 存活但与当前事件无直接关系。

## 状态文案映射

| 当前事件语义 | 卡片标签 | 卡片视觉态 | 顶部席位 | 倒计时/节奏文案 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 等待开局或无事件 | `存活` / `等待` | `idle` | `等待` | `待命` | 不高亮玩家 |
| 公开发言请求 | `准备发言` | `preparing-speech` | `发言席：N 号` | `准备中` | `action_requested` 是发言类 action 时使用 |
| 公开发言流式输出 | `发言中` | `speaking` | `发言席：N 号` | `00:45` 或发言中 | 只有此类状态可显示 `发言中` |
| 发言结算写入 | `已发言` | `resolved` | `发言席：N 号` | `已记录` | 例如 `state_updated` 携带 `debate_entry` |
| 投票请求或投票中 | `投票中` | `voting` | `投票席：N 号` | `投票中` | 不显示 `发言中` |
| 投票完成或解析 | `已投票` | `resolved` | `投票席：N 号` | `已投票` | 不暴露未公开目标时只显示完成状态 |
| 竞选表态 | `表态中` / `已表态` | `acting` / `resolved` | `竞选席：N 号` | `竞选中` | 包含上警、退水、警徽流转等公开动作 |
| 总结阶段 | `总结中` / `已总结` | `summarizing` / `resolved` | `总结席：N 号` | `总结中` | 不复用普通发言文案 |
| 夜间或私密行动 | `行动中` / `已行动` | `acting` / `resolved` | `行动席：N 号` 或 `夜间行动` | `夜间行动中` | 保持公开安全，不展示私密目标 |
| 自爆、猎人开枪等公开动作 | `公开行动中` / `已行动` | `acting` / `resolved` | `行动席：N 号` | `结算中` | 若结果公开，再进入 affected/out |
| 白天放逐 | `白天放逐` / `出局` | `affected` 或 `out` | `结算：玩家名` | `结算中` | 结算对象高亮，不保留上一位发言者高亮 |
| 夜晚死亡 | `夜晚出局` / `死亡` | `affected` 或 `out` | `结算：玩家名` | `夜晚结算` | 不高亮昨晚行动者为发言中 |
| 被守护、被救等公开结果 | `被守护` / `被救下` | `affected` | `结算：玩家名` | `结算中` | 只在结果公开时展示 |
| 游戏结束 | `胜利` / `失败` / `出局` / `存活` | `idle` 或 `out` | `对局结束` | `已结束` | 不再显示任何 `发言中` |

## Action 分类建议

实现时不要只看事件类型，也要结合 `action`、`phase` 和 payload。

### 公开发言类

这些 action 才允许进入 `preparing-speech` / `speaking`：

```text
debate
sheriff_speech
sheriff_pk_speech
```

如果后续新增遗言、公开辩论、公开竞选发言，应加入这个分类。是否把 `summarize` 视为发言不建议混入这里，面向观众应单独显示为 `总结中`。

### 投票类

```text
vote
sheriff_vote
sheriff_runoff_vote
```

投票类的当前玩家显示 `投票中` / `已投票`。即使事件有 `actor`，也不能触发 `isSpeaking`。

### 总结类

```text
summarize
```

总结属于复盘输出，不应显示为普通发言。建议卡片文案为 `总结中` / `已总结`，顶部显示 `总结席：N 号`。

### 公开行动类

```text
sheriff_run
sheriff_withdraw
sheriff_badge
werewolf_self_explosion
hunter_shoot
```

这些动作可以公开展示为 `表态中`、`行动中` 或更具体的公开文案。公开结果产生后，受影响玩家进入 `affected` / `out`。

### 私密或半私密行动类

```text
werewolf_kill
werewolf_kill_vote
guard_protect
seer_investigate
witch_save
witch_poison
```

观众侧只显示泛化的 `行动中` / `已行动`。除非后端已经通过公开 `state_updated` 发布结果，否则不要展示目标、角色推断或阵营推断。

### 结算类

结算通常来自 `state_updated` payload，而不是单纯来自 `actor`：

```text
exiled
day_deaths
night_deaths
deaths
eliminated
protected
sheriff
winner
```

结算类优先高亮受影响对象，而不是上一位 actor。进入结算后，应清理上一位发言者的 `speaking` 视觉态。

## 推荐实现方案

### 1. 新增舞台状态语义推导层

建议新增文件：

```text
apps/web/src/features/games/livePlayerStageStatus.ts
```

职责：

- 输入当前 `director.currentCue`、当前舞台事件窗口 `events`、`spectatorState` 和 `godViewState`。
- 输出每个玩家的 `PlayerStageStatus`。
- 输出顶部舞台摘要，例如 `seatLabel`、`tempoLabel`、`currentRelationLabel`。

这个层只做展示语义，不改变游戏事实状态。

### 2. 不再用 `activePlayerName` 直接生成 `isSpeaking`

`liveGodView.ts` 里的 `isSpeaking` 可以保留为兼容字段，但它的来源必须变成“公开发言语义”，而不是 `activePlayerName`。

推荐更进一步：

- `GodViewPlayer` 增加 `stageStatus` 或 `stageStatusKind`。
- `LiveDirectorStage` 根据 `stageStatus.kind` 决定卡片视觉态。
- `statusLabel` 优先展示 `stageStatus.label`，再回落到玩家长期状态。

### 3. 顶部席位和倒计时改为上下文文案

当前 `currentSeatLabel` 固定返回 `发言席：...`。应改为由当前语义决定：

| 语义 | 顶部文案 |
| --- | --- |
| 公开发言 | `发言席：N 号` |
| 投票 | `投票席：N 号` |
| 总结 | `总结席：N 号` |
| 公开行动 | `行动席：N 号` |
| 夜间私密行动 | `夜间行动` |
| 结算 | `结算：玩家名` |
| 终局 | `对局结束` |
| 无当前事件 | `等待` |

倒计时也应对应语义，不再只根据 phase 和 active player 判断：

| 语义 | 节奏文案 |
| --- | --- |
| 发言中 | `00:45` 或现有发言倒计时 |
| 准备发言 | `准备中` |
| 投票 | `投票中` |
| 总结 | `总结中` |
| 夜间行动 | `夜间行动中` |
| 结算 | `结算中` |
| 终局 | `已结束` |
| 无当前事件 | `待命` |

### 4. 复用现有叙事分类

`apps/web/src/features/games/liveNarrative.ts` 已经区分了发言、投票、玩家行动、结算和终局。状态语义层应尽量复用或对齐这些分类，避免叙事中心说“投票”，卡片却说“发言中”。

## 待修正的不一致清单

1. 投票事件带 `actor` 时，玩家卡片显示 `发言中`，应改为 `投票中` / `已投票`。
2. 夜间或技能行动带 `actor` 时，玩家卡片显示 `发言中`，应改为公开安全的 `行动中` / `已行动`。
3. 总结阶段 `summarize` 带 `actor` 时，玩家卡片显示 `发言中`，应改为 `总结中` / `已总结`。
4. 模型请求、模型返回、动作解析等过程状态被 `isSpeaking` 覆盖，导致 `请求中`、`思考中`、`已行动` 等状态无法正确呈现。
5. 结算事件到来后，上一位发言者仍可能保持 `speaking` 高亮，应切换为结算对象 `affected` / `out`。
6. `action_parsed` 表示动作已解析完成时，卡片仍可能显示 `发言中`，应根据 action 显示 `已投票`、`已行动`、`已总结` 或 `已发言`。
7. 顶部席位固定显示 `发言席`，在投票、行动、总结、结算、终局时语义错误。
8. 倒计时在非发言场景可能显示 `00:45`，应改为对应节奏文案。
9. 终局 cue 若仍有 active player，卡片可能显示最后活跃者状态，观众会误解为仍在行动，应切到 `对局结束` 语义。

## 测试建议

新增单元测试覆盖状态推导层：

- `debate` 发言请求：当前玩家为 `准备发言`，不是泛化 `行动中`。
- `model_response_delta` 携带可见发言内容：当前玩家为 `发言中`。
- `state_updated` 携带 `debate_entry`：当前玩家为 `已发言`。
- `vote` 行动请求：当前玩家为 `投票中`，卡片不进入 `speaking`。
- `action_parsed` 投票完成：当前玩家为 `已投票`。
- `summarize`：当前玩家为 `总结中` / `已总结`，不进入 `speaking`。
- 夜间行动：当前玩家为 `行动中` / `已行动`，不暴露目标。
- `state_updated` 携带 `exiled`：被放逐玩家为 `白天放逐` / `out`，上一位玩家不再 `speaking`。
- terminal event：顶部为 `对局结束`，无玩家显示 `发言中`。

更新页面级测试：

- 修改 `apps/web/src/pages/LiveGamePage.test.tsx:1221` 附近投票后期望，不再断言 `data-card-state="speaking"`。
- 修改 `apps/web/src/pages/LiveGamePage.test.tsx:390` 附近结算后期望，上一位发言者不应继续显示 `发言中`。
- 增加顶部文案断言：投票显示 `投票席`，总结显示 `总结席`，结算显示 `结算`，终局显示 `对局结束`。

## 验收标准

- 非发言事件不会让任何玩家卡片显示 `发言中`。
- 只有公开发言语义能触发卡片 `speaking` 视觉态。
- 投票、总结、夜间行动、公开行动、结算、终局都有独立观众文案。
- 结算事件优先高亮受影响对象，不保留上一位发言者的高亮。
- 顶部席位和倒计时与卡片状态一致。
- 私密行动不会通过卡片文案或高亮提前泄露目标、身份或阵营推断。
- 现有观赛舞台播放同步逻辑不回退，左右面板、底部面板和玩家卡仍跟随导播事件窗口。

## 开放问题

- `action_requested` 的公开发言阶段是否立即显示 `发言中`，还是先显示 `准备发言`。推荐先显示 `准备发言`，等出现可见文本或发言写入后再显示发言相关完成态。
- 总结是否要在视觉上接近发言。推荐文案独立为 `总结中`，避免观众误解为白天辩论发言。
- 夜间私密行动是否显示具体玩家名。推荐在不泄露规则信息的前提下显示泛化状态；如果产品希望更悬疑，可以仅显示 `夜间行动中`，不高亮具体玩家。
