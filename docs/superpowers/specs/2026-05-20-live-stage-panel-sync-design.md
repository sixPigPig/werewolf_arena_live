# 观赛舞台面板同步播放设计

**日期**: 2026-05-20
**状态**: 已实现并验证
**范围**: 修复实时观赛页中观赛舞台两侧面板提前跳到最新局势的问题，让局势总览、情报面板、底部票型板和舞台内玩家状态跟随观赛舞台的导播进度同步播放。

## 背景

实时观赛页 `/games/live/:runId` 通过 SSE 持续接收 `LiveGameEvent[]`。页面当前有两类时间概念：

- 真实事件流进度：`useGameRunEvents(runId)` 收到的完整 `events`，代表后端已经发生到哪里。
- 观赛舞台播放进度：`useLiveDirector(events)` 当前播放到的 `director.currentEventId` / `director.currentCue`，代表观众此刻看到哪里。

导播会按事件重要性和文本长度逐条播放，因此当后端短时间推入多条事件时，`events` 可能已经包含最新胜负、死亡、投票等信息，但舞台仍停留在较早 cue。当前实时观赛页用完整 `events` 派生左右面板和底部面板，导致舞台还没播到的内容会提前出现在面板里，影响观看连贯性，也可能提前暴露结算信息。

历史回放页 `GamePlaybackPage` 已经采用正确模式：先根据 `director.currentEventId` 切出 `visibleEvents`，再用 `visibleEvents` 派生 `spectatorState` 和 `godViewState`。实时观赛页需要与该模式对齐。

## 目标

- 两侧面板跟随观赛舞台当前播放事件，而不是跟随 SSE 最新事件。
- 底部票型、公开信息、死亡信息、技能触发、当前发言和玩家卡状态都只展示已经播放到的事件。
- 保留实时导航栏对真实运行状态的感知，例如连接状态、运行完成、运行失败、可继续对局等。
- 保留导播的暂停、倍速和追到最新能力。
- 不改后端事件协议，不改游戏规则，不改模型调用和隐私边界。

## 非目标

- 不实现时间轴拖拽或手动跳转到任意事件。
- 不改变 `useLiveDirector` 的播放节奏算法。
- 不调整历史回放页的数据流，除非抽取共享工具时需要轻微复用。
- 不把调试面板改成仅显示播放进度；调试面板是否跟随舞台需要单独定义。本次优先保证观众可见舞台面板同步。

## 现状问题

实时页当前关键数据流：

```text
useGameRunEvents(runId)
-> events
-> deriveLiveSpectatorState(events)
-> deriveGodViewState(events, spectatorState, ...)
-> LiveStageExperience
-> 左侧局势 / 右侧情报 / 底部票型 / 舞台玩家卡

events
-> useLiveDirector(events)
-> director.currentCue
-> LiveDirectorStage 中央叙事舞台
```

问题是 `deriveLiveSpectatorState` 和 `deriveGodViewState` 使用的是完整 `events`，而中央舞台使用的是 `director.currentCue`。两者不在同一个播放游标上。

典型表现：

- 舞台还在播放第 1 轮开始，右侧事件记录已经出现对局结束。
- 舞台还没播到夜晚结算，死亡信息已经显示出局玩家。
- 舞台还没播到投票，底部票型矩阵已经展示最终投票结果。
- 玩家卡可能显示后续发言、行动或出局状态，和当前舞台叙事冲突。

## 推荐方案

采用“舞台可见事件窗口”方案：实时页仍订阅完整 `events`，但观众面板只消费当前舞台已经播放到的 `stageEvents`。

新增实时页派生链路：

```text
events
-> useLiveDirector(events)
-> director.currentEventId
-> stageEvents = events.filter(event.id <= director.currentEventId)
-> deriveLiveSpectatorState(stageEvents)
-> deriveGodViewState(stageEvents, stageSpectatorState, ...)
-> LiveStageExperience(events=stageEvents, ...)
```

导航栏和运行状态继续使用完整事件流：

```text
events + run + connectionState
-> terminalEvent / canResumeRun / liveNavStatus
```

这样页面同时保留两种必要信息：

- 用户看到的舞台和面板完全同步。
- 顶部导航仍能反映真实连接与运行状态。

## 方案对比

### 方案 A：只在 `LiveGamePage` 切 `stageEvents`

这是推荐方案。改动集中在页面装配层，复用现有 `deriveLiveSpectatorState`、`deriveGodViewState`、`LiveStageExperience` 和历史回放页的做法。

优点：

- 改动小，风险低。
- 和 `GamePlaybackPage` 的数据流一致。
- 不需要修改后端和事件类型。
- 不需要让每个面板单独理解导播进度。

缺点：

- `LiveGamePage` 中需要调整 `director` 的创建顺序，让它先于 `spectatorState/godViewState`。

### 方案 B：让 `LiveStageExperience` 内部自己切事件

`LiveStageExperience` 接收完整 `events` 和 `director.currentEventId`，内部派生面板状态。

优点：

- 页面层更薄。
- 直播和回放可以进一步统一。

缺点：

- `LiveStageExperience` 目前已经接收派生好的 `godViewState` 和 `spectatorState`，改成内部派生会扩大组件职责。
- 历史回放页已有清晰派生逻辑，迁移成本高于本次需求。

### 方案 C：保留完整面板，只给未播放内容加遮罩

左右面板仍用完整 `events`，但对未来事件做视觉弱化或遮挡。

优点：

- 能展示“真实已发生但尚未播放”的队列感。

缺点：

- 需要每个面板区分未来数据和当前数据，复杂度高。
- 容易继续提前暴露死亡、投票和胜负信息。
- 不符合“跟随播放舞台播放”的明确目标。

## 详细设计

### 1. 实时页新增舞台事件窗口

在 `apps/web/src/pages/LiveGamePage.tsx` 中，先创建 `director`，再根据导播游标切出舞台可见事件：

```ts
const director = useLiveDirector(events, {
  resetKey: runId,
  startAtLatestTerminal: shouldStartAtTerminal,
});

const currentEventId = director.currentEventId;
const stageEvents = useMemo(() => {
  if (currentEventId === null) {
    return EMPTY_EVENTS;
  }

  return events.filter((event) => event.id <= currentEventId);
}, [events, currentEventId]);
```

命名建议使用 `stageEvents`，避免和历史回放页的 `visibleEvents` 混淆。语义是“实时观赛舞台当前已经播到的事件窗口”。

### 2. 面板派生改用 `stageEvents`

实时页内以下派生改为使用 `stageEvents`：

```ts
const spectatorState = useMemo(
  () => deriveLiveSpectatorState(stageEvents),
  [stageEvents],
);

const godViewState = useMemo(
  () =>
    deriveGodViewState(
      stageEvents,
      spectatorState,
      run?.rule_set?.name ?? "实时对局",
      { sheriffEnabled: run?.rule_set?.sheriff_enabled },
    ),
  [stageEvents, run?.rule_set?.name, run?.rule_set?.sheriff_enabled, spectatorState],
);
```

`LiveStageExperience` 的 `events` prop 也传 `stageEvents`，这样叙事中心、左右面板、底部面板、舞台玩家卡和内嵌剧情事件都位于同一个播放进度。

### 3. 导航和运行状态保留完整 `events`

以下逻辑继续基于完整 `events`：

- `terminalEvent`
- `canResumeRun`
- `liveNavStatus`
- `useEffect` 中对终局事件触发的 query invalidation

原因是这些逻辑属于“系统运行状态”，不是“观众舞台播放状态”。例如后端已经完成时，顶部可以显示已完成；舞台仍可以慢慢播放剩余 cue。

### 4. 终局打开策略不变

现有逻辑会记录每个 run 初次进入时是否已经是 terminal 状态：

```ts
startAtLatestTerminal: shouldStartAtTerminal
```

该策略保持不变：

- 用户打开一个已经完成的 run：舞台直接定位到终局事件，面板也显示终局状态。
- 用户打开时 run 还在进行，之后 run 完成：舞台继续按顺序播放 backlog，面板跟着舞台推进，不突然跳终局。

### 5. 空态处理

当 `director.currentEventId === null` 时，`stageEvents` 为空。此时面板应保持现有空态：

- 舞台显示等待导播事件。
- 左右面板显示暂无事件、暂无身份线索、暂无票型等已有兜底文案。
- 不新增额外 loading 状态。

## 文件影响

主要文件：

```text
apps/web/src/pages/LiveGamePage.tsx
```

预期测试文件：

```text
apps/web/src/pages/LiveGamePage.test.tsx
```

可能无需修改：

```text
apps/web/src/features/games/components/LiveStageExperience.tsx
apps/web/src/features/games/liveSpectator.ts
apps/web/src/features/games/liveGodView.ts
apps/web/src/pages/GamePlaybackPage.tsx
```

## 测试策略

新增或更新 `LiveGamePage.test.tsx` 中的页面级测试。

建议新增用例：`syncs side panels to the director stage event window`。

测试流程：

1. 渲染 `/games/live/:runId`。
2. 用 fake timers 控制导播播放。
3. 通过 mock SSE 连续推入事件：
   - `game_started`，包含张三、李四。
   - `round_started`。
   - `phase_started` day。
   - 后续 `state_updated`，例如 `active_players: ["张三"]` 或 `exiled: "李四"`。
   - 可选 `game_completed`。
4. 在导播仍停在较早事件时断言：
   - 舞台中央仍显示较早 cue。
   - 右侧死亡信息不显示李四出局。
   - 底部公开信息或票型不显示后续结算。
   - 玩家卡不显示后续出局状态。
5. 推进 timer 或点击“追到最新”后断言：
   - 对应死亡、票型、公开信息和终局文案出现。

已有相关测试需要保持通过：

- `plays the director stage in order instead of jumping to the latest event`
- `keeps ordered playback when a live-opened run later completes`
- `keeps the director stage paused until users catch up to the latest key event`
- `opens completed runs at the terminal event instead of replaying the full backlog`

建议验证命令：

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx src/pages/GamePlaybackPage.test.tsx
pnpm --dir apps/web build
```

## 验收标准

- 实时观赛页中，左右面板和底部面板不会展示舞台尚未播放到的死亡、投票、技能触发、公开信息或胜负结算。
- 点击“追到最新”后，面板立即与最新关键事件对齐。
- 暂停播放时，面板停留在暂停时的舞台进度。
- 倍速播放时，面板随导播推进同步更新。
- 打开已完成 run 时，仍直接显示终局状态，不从头慢放完整 backlog。
- 历史回放页行为不退化。
- 后端 API、SSE 事件协议、游戏规则和隐私边界保持不变。

## 风险与注意事项

- `stageEvents` 为空时，`deriveLiveSpectatorState` 和 `deriveGodViewState` 必须保持安全空态。当前派生函数已有兜底，但测试应覆盖。
- 调试面板目前通过 `LiveStageExperience.events` 构建 trace。如果传入 `stageEvents`，调试面板也会跟随舞台进度。这个行为更符合“观赛体验同步”，但如果未来需要查看完整 SSE backlog，可以给调试面板单独传完整事件流。
- 顶部状态和面板状态会有意出现短暂差异：顶部可能已经显示完成，舞台与面板仍在播放历史 cue。这是设计选择，因为顶部表示真实运行状态，舞台表示观看进度。
- 事件 `id` 当前被用作播放顺序边界。若未来存在乱序或非递增事件，需要先在事件接收层保证排序或改用 cue index。

## 实现检查清单

1. 在 `LiveGamePage` 中调整 `director`、`stageEvents`、`spectatorState`、`godViewState` 的计算顺序。
2. 将传入 `LiveStageExperience` 的 `events` 从完整 `events` 改为 `stageEvents`。
3. 保留导航状态、终局判断和 query invalidation 使用完整 `events`。
4. 增加实时页面板同步测试。
5. 运行页面测试和前端构建。
