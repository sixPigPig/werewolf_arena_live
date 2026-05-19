# 删除观战页当前关注 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从当前观战页删除“当前关注 / 自动跟随 / 手动锁定玩家”这条已不再承担核心信息价值的交互链，保留导播当前行动玩家的舞台高亮和调试事件高亮。

**Architecture:** 观战页继续由 `LiveStageExperience` 统一组装导播 cue、叙事中心、上帝视角面板和调试面板；玩家卡只表达实时状态，不再承担“点击锁定关注”的交互。`LiveGameEvent.actor`、`director.currentCue.actor`、`GodViewState.activePlayerName` 仍然保留，用于当前发言/行动高亮、中央叙事和终局最后行动提示。

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, Tailwind utility classes.

---

## 删除范围确认

### 确认删除

- 舞台底部“当前关注”摘要条。
- “自动跟随”开关。
- `autoFollow` 状态。
- `manualFocusName` 状态。
- `focusedPlayerName` 传参链。
- 玩家卡点击后手动锁定关注的行为。
- 玩家卡 `data-card-state="focused"` 状态。
- 玩家卡 `is-focused` class。
- 调试 trace 选中后顺手改写手动关注的副作用。
- 未被任何页面引用的旧组件 `LivePlayerPanel.tsx`，它仍然保留旧“当前关注/自动跟随”模型，属于同一批冗余历史代码。

### 明确保留

- `LiveGameEvent.actor`。
- `deriveLiveSpectatorState(...).activePlayerName`。
- `useLiveDirector(...).currentCue.actor`。
- `LiveDirectorStage` 的 `activePlayerName` prop。
- `GodViewPlayer.isSpeaking` 和 `data-card-state="speaking"`。
- 终局 cue 下的 `data-card-state="last-active"`。
- Debug trace 的 `selectedTraceId`、展开状态和 `data-debug-highlighted="true"` 相关玩家高亮。
- 顶部“队列剩余”和“自动追进度中”徽标；这里的“自动追进度”是导播播放队列追赶，不是“自动跟随玩家”。

### 不删除的历史文档

`docs/superpowers/specs/*` 和旧 `docs/superpowers/plans/*` 中关于自动跟随的历史描述不在本次代码变更范围内。它们是历史设计记录，不参与运行时行为。

---

## File Structure

- Modify: `apps/web/src/features/games/components/LiveStageExperience.tsx`
  - 删除当前关注状态管理。
  - 调试 trace 选中只更新 `selectedTraceId`，不再改变玩家关注。
  - 只把 `activePlayerName` 传给舞台。

- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
  - 删除 `Switch` import。
  - 删除 `focusedPlayerName`、`autoFollow`、`onSelectPlayer`、`onAutoFollowChange` props。
  - 删除底部“当前关注”摘要条。
  - 将玩家卡从可点击 `button` 改成静态展示元素。
  - 删除 `focused` 卡片状态和 `is-focused` class。

- Delete: `apps/web/src/features/games/components/LivePlayerPanel.tsx`
  - 该组件没有任何引用，且只承载旧版玩家面板/当前关注模型。

- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`
  - 删除对 `is-focused`、`data-card-state="focused"`、自动跟随 switch 的断言。
  - 增加“当前关注控件不存在”的断言。
  - 保留并强化“当前行动玩家是 speaking”、“debug trace 只高亮相关玩家”的断言。

---

### Task 1: 先改测试，定义删减后的正确行为

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 修改调试面板用例，取消 trace 选中时改变当前关注的预期**

在现有调试面板测试中，删除这几行：

```tsx
await userEvent.click(liCard);
expect(liCard).toHaveClass("is-focused");
await userEvent.click(traceButton);
expect(traceButton).toHaveAttribute("aria-expanded", "true");
expect(zhangCard).toHaveClass("is-focused");
```

替换为：

```tsx
expect(screen.queryByText("当前关注")).not.toBeInTheDocument();
expect(
  screen.queryByRole("switch", { name: "自动跟随" }),
).not.toBeInTheDocument();

await userEvent.click(traceButton);
expect(traceButton).toHaveAttribute("aria-expanded", "true");
expect(zhangCard).toHaveAttribute("data-debug-highlighted", "true");
expect(liCard).toHaveAttribute("data-debug-highlighted", "false");
```

- [ ] **Step 2: 修改 12 人舞台用例，删除玩家卡点击锁定预期**

删除现有片段：

```tsx
await userEvent.click(
  within(stage).getByTestId("god-view-stage-player-card-P2"),
);
expect(
  within(stage).getByTestId("god-view-stage-player-card-P2"),
).toHaveAttribute("data-card-state", "focused");
```

替换为：

```tsx
expect(
  within(stage).getByTestId("god-view-stage-player-card-P2"),
).toHaveAttribute("data-card-state", "idle");
expect(
  within(stage).queryByRole("button", { name: /P2/ }),
).not.toBeInTheDocument();
```

- [ ] **Step 3: 重写“pin + auto follow”用例为“无当前关注控件，玩家高亮由 actor 驱动”**

把用例名：

```tsx
it("lets users pin a player and re-enable auto follow", async () => {
```

改成：

```tsx
it("removes current focus controls while keeping actor-driven speaking state", async () => {
```

将用例中点击李四、点击自动跟随 switch、断言 `is-focused` 的部分替换为：

```tsx
expect(screen.queryByText("当前关注")).not.toBeInTheDocument();
expect(
  screen.queryByRole("switch", { name: "自动跟随" }),
).not.toBeInTheDocument();
expect(zhangCard).toHaveAttribute("data-card-state", "speaking");
expect(liCard).toHaveAttribute("data-card-state", "idle");

act(() => {
  source.emit("action_requested", {
    id: 3,
    type: "action_requested",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: "2026-04-24T12:00:04Z",
    round: 1,
    phase: "day",
    actor: "李四",
    action: "vote",
    payload: { options: ["张三"] },
  });
});

expect(liCard).toHaveAttribute("data-card-state", "speaking");
expect(zhangCard).toHaveAttribute("data-card-state", "idle");
```

- [ ] **Step 4: 运行测试，确认当前实现失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: FAIL。失败点应来自仍然存在的“当前关注/自动跟随”控件、玩家卡仍是 button、或 trace/player click 仍产生 `is-focused`。

---

### Task 2: 删除 LiveStageExperience 中的关注状态链

**Files:**
- Modify: `apps/web/src/features/games/components/LiveStageExperience.tsx`

- [ ] **Step 1: 删除无用状态和改名自动 actor**

将：

```tsx
const [autoFollow, setAutoFollow] = useState(true);
const [manualFocusName, setManualFocusName] = useState<string | null>(null);
const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
const traces = useMemo(() => buildLiveDebugTraces(events), [events]);
const selectedTrace =
  traces.find((trace) => trace.id === selectedTraceId) ?? null;
const autoFocusName =
  director.currentCue?.actor ?? spectatorState.activePlayerName;
const focusedPlayerName = autoFollow
  ? autoFocusName
  : manualFocusName ?? autoFocusName;
```

替换为：

```tsx
const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
const traces = useMemo(() => buildLiveDebugTraces(events), [events]);
const selectedTrace =
  traces.find((trace) => trace.id === selectedTraceId) ?? null;
const activePlayerName =
  director.currentCue?.actor ?? spectatorState.activePlayerName;
```

- [ ] **Step 2: 删除 trace 选中时改变玩家关注的副作用**

将：

```tsx
const selectTrace = (trace: LiveDebugTrace | null) => {
  if (!trace) {
    setSelectedTraceId(null);
    return;
  }

  setSelectedTraceId(trace.id);
  const focusName = trace.actor ?? trace.relatedPlayers[0] ?? null;
  if (focusName) {
    setAutoFollow(false);
    setManualFocusName(focusName);
  }
};
```

替换为：

```tsx
const selectTrace = (trace: LiveDebugTrace | null) => {
  setSelectedTraceId(trace?.id ?? null);
};
```

- [ ] **Step 3: 简化 LiveDirectorStage 调用**

将：

```tsx
<LiveDirectorStage
  activePlayerName={autoFocusName}
  autoFollow={autoFollow}
  backlogCount={director.backlogCount}
  cue={director.currentCue}
  debugTrace={selectedTrace}
  focusedPlayerName={focusedPlayerName}
  godViewState={godViewState}
  isCatchingUp={director.isCatchingUp}
  narrativeState={narrativeState}
  onAutoFollowChange={(value) => {
    setAutoFollow(value);
    if (value) {
      setManualFocusName(null);
    }
  }}
  onSelectPlayer={(name) => {
    setAutoFollow(false);
    setManualFocusName(name);
  }}
  players={spectatorState.players}
/>
```

替换为：

```tsx
<LiveDirectorStage
  activePlayerName={activePlayerName}
  backlogCount={director.backlogCount}
  cue={director.currentCue}
  debugTrace={selectedTrace}
  godViewState={godViewState}
  isCatchingUp={director.isCatchingUp}
  narrativeState={narrativeState}
  players={spectatorState.players}
/>
```

- [ ] **Step 4: 清理 import**

如果 `useState` 仍用于 `selectedTraceId`，保留：

```tsx
import { useMemo, useState } from "react";
```

不得留下 `autoFollow`、`manualFocusName`、`focusedPlayerName`、`setAutoFollow`、`setManualFocusName` 的引用。

---

### Task 3: 删除 LiveDirectorStage 中的 UI 控件和卡片 focus 状态

**Files:**
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`

- [ ] **Step 1: 清理 import 和 props**

将：

```tsx
import { Badge, Switch } from "../../../components/ui";
```

替换为：

```tsx
import { Badge } from "../../../components/ui";
```

将 props 类型改为：

```tsx
type LiveDirectorStageProps = {
  cue: DirectorCue | null;
  backlogCount: number;
  isCatchingUp: boolean;
  players: LivePlayer[];
  activePlayerName: string | null;
  narrativeState: LiveNarrativeState;
  debugTrace?: LiveDebugTrace | null;
  godViewState?: GodViewState;
};
```

- [ ] **Step 2: 删除组件参数中的关注字段**

将：

```tsx
focusedPlayerName,
narrativeState,
debugTrace,
godViewState,
autoFollow,
onSelectPlayer,
onAutoFollowChange,
```

替换为：

```tsx
narrativeState,
debugTrace,
godViewState,
```

删除：

```tsx
const focusedPlayer =
  players.find((player) => player.name === focusedPlayerName) ?? null;
```

- [ ] **Step 3: 删除底部当前关注条**

删除整段：

```tsx
<div className="glass-panel-subtle absolute inset-x-4 bottom-4 z-40 flex flex-col gap-3 rounded-lg border border-amber-300/20 p-3 text-sm text-slate-200 shadow-[0_16px_45px_rgba(0,0,0,0.24)] sm:inset-x-6 sm:flex-row sm:items-center sm:justify-between">
  <div className="min-w-0">
    <p className="text-xs font-semibold text-amber-200">当前关注</p>
    <p className="mt-1 truncate">
      {focusedPlayer
        ? `${focusedPlayer.name} · ${focusedPlayer.role} · ${
            focusedPlayer.lastAction
              ? actionLabel(focusedPlayer.lastAction)
              : "等待行动"
          }`
        : "等待玩家行动"}
    </p>
  </div>
  <label className="flex shrink-0 items-center gap-2 text-xs text-slate-300">
    <Switch
      checked={autoFollow}
      color="amber"
      onCheckedChange={onAutoFollowChange}
    />
    自动跟随
  </label>
</div>
```

- [ ] **Step 4: 简化 PlayerRail props**

将 `PlayerRail` 调用从：

```tsx
<PlayerRail
  activePlayerName={activePlayerName}
  focusedPlayerName={focusedPlayerName}
  isTerminalCue={isTerminalCue}
  debugHighlightedPlayers={debugHighlightedPlayers}
  livePlayersByName={livePlayersByName}
  onSelectPlayer={onSelectPlayer}
  players={leftRailPlayers}
  side="left"
/>
```

改为：

```tsx
<PlayerRail
  activePlayerName={activePlayerName}
  isTerminalCue={isTerminalCue}
  debugHighlightedPlayers={debugHighlightedPlayers}
  livePlayersByName={livePlayersByName}
  players={leftRailPlayers}
  side="left"
/>
```

右侧 `PlayerRail` 做同样修改。

将 `PlayerRail` 参数类型改为：

```tsx
function PlayerRail({
  activePlayerName,
  isTerminalCue,
  debugHighlightedPlayers,
  livePlayersByName,
  players,
  side,
}: {
  activePlayerName: string | null;
  isTerminalCue: boolean;
  debugHighlightedPlayers: Set<string>;
  livePlayersByName: Map<string, LivePlayer>;
  players: GodViewPlayer[];
  side: "left" | "right";
}) {
```

- [ ] **Step 5: 将玩家卡从 button 改成静态 article**

将 `StagePlayerCard` 参数类型改为：

```tsx
function StagePlayerCard({
  activePlayerName,
  isTerminalCue,
  debugHighlighted,
  livePlayer,
  player,
  side,
}: {
  activePlayerName: string | null;
  isTerminalCue: boolean;
  debugHighlighted: boolean;
  livePlayer: LivePlayer | null;
  player: GodViewPlayer;
  side: "left" | "right";
}) {
```

删除：

```tsx
const isFocused = player.name === focusedPlayerName;
```

将 `cardState` 计算改为：

```tsx
const cardState = !player.isAlive
  ? "out"
  : isCurrentSpeaker
    ? "speaking"
    : isLastActive
      ? "last-active"
      : "idle";
```

将外层元素从：

```tsx
<button
  aria-label={`${player.seatNumber}号 ${player.name} ${player.role} ${status} ${liveAction} ${liveDetail}`}
  className={`god-view-player-card pointer-events-auto grid w-full max-w-[13rem] grid-cols-[2.2rem_minmax(0,1fr)] items-center gap-2 rounded-md border bg-black/45 px-2 py-2 text-left shadow-[0_12px_32px_rgba(0,0,0,0.26)] transition duration-200 hover:-translate-y-0.5 hover:border-amber-200/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-200 ${
    side === "right" ? "text-right" : ""
  } ${stagePlayerTone(player, cardState)} ${
    isFocused ? "is-focused ring-1 ring-amber-100/70" : ""
  } ${
    debugHighlighted
      ? "ring-2 ring-amber-300/85 shadow-[0_0_30px_rgba(251,191,36,0.38),0_12px_32px_rgba(0,0,0,0.26)]"
      : ""
  } ${!player.isAlive ? "opacity-65 grayscale" : ""}`}
  data-card-state={cardState}
  data-debug-highlighted={debugHighlighted ? "true" : "false"}
  data-testid={`god-view-stage-player-card-${player.name}`}
  onClick={() => onSelectPlayer(player.name)}
  type="button"
>
```

替换为：

```tsx
<article
  aria-label={`${player.seatNumber}号 ${player.name} ${player.role} ${status} ${liveAction} ${liveDetail}`}
  className={`god-view-player-card pointer-events-auto grid w-full max-w-[13rem] grid-cols-[2.2rem_minmax(0,1fr)] items-center gap-2 rounded-md border bg-black/45 px-2 py-2 text-left shadow-[0_12px_32px_rgba(0,0,0,0.26)] transition duration-200 ${
    side === "right" ? "text-right" : ""
  } ${stagePlayerTone(player, cardState)} ${
    debugHighlighted
      ? "ring-2 ring-amber-300/85 shadow-[0_0_30px_rgba(251,191,36,0.38),0_12px_32px_rgba(0,0,0,0.26)]"
      : ""
  } ${!player.isAlive ? "opacity-65 grayscale" : ""}`}
  data-card-state={cardState}
  data-debug-highlighted={debugHighlighted ? "true" : "false"}
  data-testid={`god-view-stage-player-card-${player.name}`}
>
```

并将闭合标签从：

```tsx
</button>
```

改为：

```tsx
</article>
```

- [ ] **Step 6: 确认没有残留 focus 分支**

Run:

```bash
rg -n "focusedPlayerName|autoFollow|manualFocusName|is-focused|data-card-state=\\\"focused\\\"|onAutoFollowChange|onSelectPlayer" apps/web/src/features/games/components/LiveStageExperience.tsx apps/web/src/features/games/components/LiveDirectorStage.tsx apps/web/src/pages/LiveGamePage.test.tsx
```

Expected: no matches。

---

### Task 4: 删除旧 LivePlayerPanel 死代码

**Files:**
- Delete: `apps/web/src/features/games/components/LivePlayerPanel.tsx`

- [ ] **Step 1: 删除文件**

删除：

```text
apps/web/src/features/games/components/LivePlayerPanel.tsx
```

- [ ] **Step 2: 确认没有引用**

Run:

```bash
rg -n "LivePlayerPanel" apps/web/src
```

Expected: no matches。

---

### Task 5: 运行验证并检查页面表现

**Files:**
- Test: `apps/web/src/pages/LiveGamePage.test.tsx`
- Build: `apps/web`

- [ ] **Step 1: 跑聚焦测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: PASS。

- [ ] **Step 2: 跑前端全量测试**

Run:

```bash
pnpm test:web
```

Expected: PASS。

- [ ] **Step 3: 跑前端构建**

Run:

```bash
pnpm build:web
```

Expected: PASS。

- [ ] **Step 4: 浏览器视觉检查**

启动本地前端：

```bash
pnpm dev:web
```

打开实时观战页或已有回放页，检查：

- 舞台底部不再出现“当前关注”条。
- 不再出现“自动跟随”开关。
- 当前 actor 对应玩家卡仍显示 `speaking` 高亮。
- 终局时最后行动玩家仍显示 `last-active`。
- 打开调试面板并点击 trace 后，相关玩家仍有 debug 高亮。
- 玩家卡不再表现为可点击控件。
- 中央叙事卡和玩家轨道之间没有明显空洞或遮挡。

---

## 风险与取舍

- 删除手动锁定后，用户不能再临时 pin 某个玩家；当前布局下这个能力没有配套详情面板，所以删除比保留更清晰。
- 玩家卡从 button 改为 article 后，可访问性语义更准确；它不再是可执行控件。
- Debug trace 仍然可以高亮相关玩家，但不会改变页面主焦点；这能避免“调试行为污染观赛状态”。
- `LivePlayerPanel.tsx` 是未引用死代码，删除风险低；若后续想做真正的玩家详情面板，应新建面向当前布局的组件，而不是复活旧关注模型。

## 自检清单

- [ ] 没有 `当前关注` 文案残留在运行时代码或活跃测试里。
- [ ] 没有 `自动跟随` switch 残留在 `LiveDirectorStage` 或 `LiveStageExperience`。
- [ ] 没有 `is-focused` class 残留在活跃代码。
- [ ] 没有 `data-card-state="focused"` 预期残留在测试。
- [ ] `speaking`、`last-active`、`out`、`idle` 四种玩家卡状态仍然正常。
- [ ] Debug trace 高亮仍通过 `data-debug-highlighted` 工作。
- [ ] `pnpm test:web` 和 `pnpm build:web` 通过。
