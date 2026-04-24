# 实时观战玩家聚焦体验设计方案

**日期**: 2026-04-24
**范围**: 优化 `/games/live/:runId` 的实时观战体验，把当前按事件逐条展开的列表改为“玩家列表 + 当前行动聚焦舞台 + 原始事件侧栏”。本设计只修改 `apps/web`，不改后端事件协议。

## 1. 背景

当前实时观战页已经可以通过 SSE 接收对局事件，但主界面仍是一条条事件列表。这个模式适合调试，不适合观看对局：用户需要自己从 `action_requested`、`model_response_received`、`action_parsed`、`state_updated` 中拼出“谁正在做什么”。

用户希望看到玩家列表，并在玩家行动或发言时聚焦到该玩家，让实时观战更像“对局正在发生”，而不是“日志正在滚动”。

## 2. 目标

- 在 live 页面展示玩家列表。
- 当事件包含 `actor` 时，自动聚焦到该玩家。
- 当前行动玩家在玩家列表中高亮并展开最近状态。
- 中间区域展示当前聚焦玩家、当前阶段、最近行动和关键内容。
- 保留原始事件列表，但降级为右侧调试/事件侧栏。
- 支持用户点击玩家进行手动聚焦。
- 支持“自动跟随当前行动玩家”开关，默认开启。

## 3. 非目标

- 不新增后端字段或事件类型。
- 不做 WebSocket。
- 不做暂停、恢复、人工干预。
- 不实现完整角色视角权限隐藏。
- 不引入虚拟列表；当前先把原始事件放到侧栏，日志量变大后再评估。
- 不重做已完成复盘页。

## 4. 推荐方案

使用前端派生状态，把 SSE 事件转换为观战 UI 状态：

```text
LiveGamePage
  events from useGameRunEvents
  -> deriveLiveSpectatorState(events)
  -> LivePlayerPanel
  -> LiveFocusStage
  -> LiveEventTimeline
```

页面布局：

```text
+----------------------+-------------------------------+----------------------+
| 玩家列表              | 当前聚焦舞台                    | 原始事件侧栏          |
| active / alive / log  | player / phase / latest action | timeline / debug      |
+----------------------+-------------------------------+----------------------+
```

桌面使用三栏布局；移动端纵向排列，玩家列表在上、聚焦舞台在中、事件侧栏在下。

## 5. 状态派生

新增前端 helper：

```text
apps/web/src/features/games/liveSpectator.ts
```

核心类型：

- `LivePlayer`: name、role、model、status、isAlive、lastAction、lastDetail。
- `LiveSpectatorState`: players、activePlayerName、currentRound、currentPhase、latestActorEvent、latestStateEvent。

事件规则：

- `game_started`: 从 `payload.players` 初始化玩家列表。
- `action_requested`: actor 进入 `thinking` 状态，记录最近行动。
- `model_request_started`: actor 进入 `requesting` 状态。
- `model_response_received`: actor 进入 `responded` 状态，记录 raw response 摘要。
- `action_parsed`: actor 进入 `acted` 状态，记录 choice/result。
- `state_updated`: 根据 payload 更新存活玩家、发言、投票、总结等摘要。
- `game_completed` / `game_failed`: 不改变玩家列表，只更新页面终态。

如果没有 `game_started`，但事件中出现 actor，则创建一个兜底玩家条目，避免页面空白。

## 6. 组件设计

新增组件：

```text
apps/web/src/features/games/components/LivePlayerPanel.tsx
apps/web/src/features/games/components/LiveFocusStage.tsx
```

`LivePlayerPanel`：

- 展示所有玩家。
- 高亮 active player。
- 显示状态：等待中、思考中、请求模型、已返回、已行动、出局。
- 点击玩家触发手动聚焦。
- 展示“自动跟随”开关。

`LiveFocusStage`：

- 展示当前聚焦玩家。
- 展示当前回合和阶段。
- 展示最近行动标题与内容。
- 发言/模型原文使用可读文本块，投票/保护/击杀使用摘要行。
- 没有事件时显示等待状态。

`LiveEventTimeline`：

- 保留现有行为。
- 在 live 页面中放入右侧侧栏，标题为“原始事件”。

## 7. 交互规则

- 默认自动跟随：最新 actor 事件会更新焦点。
- 用户点击玩家：关闭自动跟随并固定到该玩家。
- 用户重新打开自动跟随：焦点回到最新行动玩家。
- 当前 actor 事件到达时：
  - 玩家列表对应卡片高亮。
  - 聚焦舞台更新标题和内容。
  - 原始事件侧栏继续追加。
- 对局终态到达时：
  - 保留当前焦点。
  - 显示“查看完整复盘”按钮。

## 8. 测试策略

优先测试行为：

- `deriveLiveSpectatorState` 能从 `game_started` 初始化玩家。
- actor 事件会更新 active player 和玩家状态。
- `state_updated` 能把出局玩家标记为 not alive。
- `LiveGamePage` 收到 actor 事件后显示玩家列表和聚焦舞台。
- 点击玩家后固定焦点，后续 actor 事件不抢焦点。
- 重新开启自动跟随后焦点回到最新 actor。

验证命令：

```bash
cd apps/web && pnpm test -- --run
cd apps/web && pnpm build
```

## 9. 分阶段实施

第一步：派生状态

- 新增 `liveSpectator.ts`。
- 添加纯函数测试。

第二步：玩家列表和聚焦舞台组件

- 新增 `LivePlayerPanel`。
- 新增 `LiveFocusStage`。
- 添加组件或页面级测试。

第三步：集成 live 页面

- `LiveGamePage` 使用三栏布局。
- 接入自动跟随和手动聚焦状态。
- 保留 `LiveEventTimeline` 作为右侧原始事件侧栏。

第四步：验证与微调

- 跑前端测试和构建。
- 如有布局文字溢出，补响应式约束。
