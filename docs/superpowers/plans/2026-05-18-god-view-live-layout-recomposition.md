# 上帝视角观战页布局重组 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按用户确认的信息架构重排 `/games/live/:runId` 上帝视角观战页，让顶部、左侧、中心、右侧和底部各自承担清晰职责，并把玩家卡收敛为唯一玩家信息入口。

**Architecture:** 继续复用当前 `deriveGodViewState()` 的派生数据，不改后端协议。布局层从现有 `roster / stage / timeline / bottom` 四槽，重组为 `top / left / stage / right / bottom` 五槽；玩家信息从独立左侧身份牌迁移到中央舞台左右两侧的玩家卡轨道。右侧情报面板只保留事件、死亡、身份线索和技能触发；左侧新建局势面板承载局势总览、阵营进度和夜晚行动回顾。

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, Tailwind CSS utilities, existing gothic/glass CSS surfaces.

---

## 1. 用户确认的信息架构

最终页面分区：

- 顶部：房间名 / 第几天 / 当前阶段 / 发言席 / 倒计时 / 存活 / 胜负条件
- 左上：局势总览
- 左中：阵营进度
- 左下：夜晚行动回顾
- 中间：当前发言玩家大舞台
- 舞台左右：12 位玩家卡，唯一玩家信息入口
- 右上：事件记录
- 右中：死亡信息
- 右下：身份线索 / 技能触发
- 底部：发言顺序 / 票型矩阵 / 投票统计 / 公开信息

## 2. 当前页面差距

当前页面已经有：

- `LiveStageModule`：左侧 roster、中央 stage、右侧 timeline、底部 board。
- `LiveDirectorStage`：顶部局势条仍在舞台内部，玩家仍以圆桌座位按钮形式围绕舞台。
- `GodViewRosterPanel`：左侧身份牌表，是当前玩家信息主入口。
- `GodViewIntelPanel`：右侧同时包含事件、死亡、夜晚行动、身份线索、警长信息、阵营进度和调试事件。
- `GodViewBottomBoard`：底部包含发言顺序、票型矩阵、投票统计、放逐候选、公开信息、回放点。

需要调整为：

- 顶部总控条从舞台内移到页面布局顶部。
- 左栏不再展示玩家身份牌，改为局势总览、阵营进度、夜晚行动。
- 玩家入口从左栏表格迁到舞台左右两侧玩家卡。
- 右栏去掉夜晚行动、阵营进度、警长信息，改为事件记录、死亡信息、身份线索和技能触发。
- 底部去掉放逐候选排名和本局标记，只保留四个复盘模块。

## 3. 非目标

本次只做布局重组，不做这些事：

- 不改后端事件协议。
- 不新增数据库字段。
- 不新增 UI 依赖。
- 不生成新图片素材。
- 不改变 SSE 连接、导播节奏、继续对局、完整复盘链接等运行逻辑。
- 不把 8 人局强行补成 12 人数据；12 位玩家卡表示布局最多支持 12 人，当前局按实际玩家数渲染。
- 不改变玩家点击后的行为语义：点击玩家卡仍然设置手动关注，开启自动跟随后回到导播当前玩家。

## 4. 文件结构

计划修改：

- `apps/web/src/pages/components/LiveStageModule.tsx`
  - 把布局槽位从 `roster / stage / timeline / bottom` 改为 `top / left / stage / right / bottom`。
  - 新增稳定测试标识：`god-view-top-zone`、`god-view-left-zone`、`god-view-stage-zone`、`god-view-right-zone`、`god-view-bottom-zone`。

- `apps/web/src/pages/LiveGamePage.tsx`
  - 不再把 `GodViewRosterPanel` 传入左栏。
  - 新增顶部总控条组件、左侧局势组件、右侧情报组件的装配。
  - `LiveDirectorStage` 继续接收 `godViewState`、`players` 和选择玩家回调，用于舞台左右玩家卡。

- `apps/web/src/features/games/components/GodViewTopBar.tsx`
  - 新建顶部总控条。
  - 展示房间名、天夜、阶段、发言席、倒计时、存活、胜负条件。
  - 复用当前 `LiveDirectorStage` 内部 `StageStat` 的语义，但独立出舞台组件。

- `apps/web/src/features/games/components/GodViewSituationPanel.tsx`
  - 新建左侧局势面板。
  - 包含局势总览、阵营进度、夜晚行动回顾。
  - 从 `GodViewIntelPanel` 迁移阵营进度和夜晚行动 UI。

- `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
  - 改为右侧情报专用。
  - 保留事件记录、死亡信息、身份线索。
  - 新增技能触发区。
  - 移除夜晚行动回顾、阵营进度、警长信息。

- `apps/web/src/features/games/components/LiveDirectorStage.tsx`
  - 删除舞台内部顶部总控条。
  - 用左右玩家卡轨道替代当前圆桌座位玩家按钮。
  - 当前发言玩家大舞台继续居中展示。
  - 玩家卡成为唯一玩家信息入口。

- `apps/web/src/features/games/components/GodViewBottomBoard.tsx`
  - 底部改为四列：发言顺序、票型矩阵、投票统计、公开信息。
  - 移除放逐候选排名和本局标记。

- `apps/web/src/features/games/liveGodView.ts`
  - 可选新增 `skillTriggers` 派生字段，用于右下“技能触发”。
  - 不改变已有字段语义。

- `apps/web/src/features/games/liveGodView.test.ts`
  - 覆盖 `skillTriggers` 的最小派生行为。

- `apps/web/src/pages/LiveGamePage.test.tsx`
  - 覆盖新布局槽位、玩家卡入口、右侧/左侧内容归位、底部四列。

- `apps/web/src/styles/index.css`
  - 新增/调整三栏导播台布局 CSS。
  - 为玩家卡左右轨、短横屏、移动端堆叠提供稳定尺寸。

计划不再使用于该页面：

- `GodViewRosterPanel` 暂时保留文件，不在 `LiveGamePage` 中渲染。这样避免影响其他潜在引用，也方便以后如果需要做复盘身份表再复用。

## 5. 数据设计

当前 `GodViewState` 已满足大部分布局：

- 顶部：`boardName`、`dayNightLabel`、`phaseLabel`、`currentSeatLabel`、`countdownLabel`、`aliveLabel`、`winMode`
- 左侧局势：`progress`、`winPressure`、`nightActionOrder`、`nightResolution`
- 中央舞台：`players`、`speakerFlow`
- 右侧情报：`eventLines`、`deaths`、`players`
- 底部：`speechOrder`、`vote`、`publicFacts`

新增技能触发字段：

```ts
export type GodViewSkillTrigger = {
  id: number;
  label: string;
  detail: string;
  tone: "danger" | "info" | "success" | "warning" | "muted";
};

export type GodViewState = {
  // existing fields remain
  skillTriggers: GodViewSkillTrigger[];
};
```

派生规则：

- `werewolf_self_exploded`：`狼人自爆`
- `hunter_shot`：`猎人带走`
- `idiot_revealed`：`白痴翻牌`
- `sheriff_badge_lost`：`警徽撕毁`
- `sheriff_badge_target`：`警徽移交`
- 无技能触发时右下显示“暂无技能触发”。

## 6. Task 1: 派生技能触发数据

**Files:**
- Modify: `apps/web/src/features/games/liveGodView.ts`
- Modify: `apps/web/src/features/games/liveGodView.test.ts`

- [ ] **Step 1: 写技能触发红灯测试**

在 `liveGodView.test.ts` 增加：

```ts
it("derives skill trigger lines from state updates", () => {
  const events = [
    event({
      type: "game_started",
      payload: {
        players: [
          { name: "Wolf", role: "werewolf", model: "deepseek-chat" },
          { name: "Hunter", role: "hunter", model: "deepseek-chat" },
          { name: "Villager", role: "villager", model: "deepseek-chat" },
        ],
      },
    }),
    event({
      id: 2,
      type: "state_updated",
      round: 2,
      phase: "day",
      payload: {
        werewolf_self_exploded: "Wolf",
        hunter_shot: "Villager",
      },
    }),
  ];
  const spectator = deriveLiveSpectatorState(events);

  const state = deriveGodViewState(events, spectator, "技能测试");

  expect(state.skillTriggers).toEqual([
    expect.objectContaining({
      label: "狼人自爆",
      detail: "Wolf 发动自爆。",
      tone: "danger",
    }),
    expect.objectContaining({
      label: "猎人带走",
      detail: "Hunter 带走 Villager。",
      tone: "warning",
    }),
  ]);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveGodView.test.ts -t "skill trigger"
```

Expected: FAIL，提示 `skillTriggers` 不存在。

- [ ] **Step 3: 实现 `skillTriggers` 类型和收集器**

在 `liveGodView.ts` 中添加：

```ts
export type GodViewSkillTrigger = {
  id: number;
  label: string;
  detail: string;
  tone: "danger" | "info" | "success" | "warning" | "muted";
};
```

在 `GodViewState` 和 `MutableGodView` 中添加：

```ts
skillTriggers: GodViewSkillTrigger[];
```

初始化：

```ts
skillTriggers: [],
```

在 `collectStateUpdate()` 末尾调用：

```ts
collectSkillTriggers(view, event, payload);
```

新增函数：

```ts
function collectSkillTriggers(
  view: MutableGodView,
  event: LiveGameEvent,
  payload: Record<string, unknown>,
) {
  const selfExploded = stringField(payload, "werewolf_self_exploded");
  if (selfExploded) {
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "狼人自爆",
      detail: `${selfExploded} 发动自爆。`,
      tone: "danger",
    });
  }

  const hunterShot = stringField(payload, "hunter_shot");
  if (hunterShot) {
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "猎人带走",
      detail: `猎人带走 ${hunterShot}。`,
      tone: "warning",
    });
  }

  const idiotRevealed = stringField(payload, "idiot_revealed");
  if (idiotRevealed) {
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "白痴翻牌",
      detail: `${idiotRevealed} 翻牌留在场上。`,
      tone: "info",
    });
  }

  const badgeTarget = stringField(payload, "sheriff_badge_target");
  if (badgeTarget) {
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "警徽移交",
      detail: `警徽移交给 ${badgeTarget}。`,
      tone: "success",
    });
  }

  if (payload.sheriff_badge_lost === true) {
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "警徽撕毁",
      detail: "警徽被撕毁。",
      tone: "muted",
    });
  }
}

function pushUniqueSkillTrigger(
  view: MutableGodView,
  trigger: GodViewSkillTrigger,
) {
  const key = `${trigger.id}:${trigger.label}:${trigger.detail}`;
  if (
    view.skillTriggers.some(
      (item) => `${item.id}:${item.label}:${item.detail}` === key,
    )
  ) {
    return;
  }
  view.skillTriggers.push(trigger);
}
```

在 `deriveGodViewState()` return 中添加：

```ts
skillTriggers: view.skillTriggers.slice(-5).reverse(),
```

- [ ] **Step 4: 运行派生层测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveGodView.test.ts
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/games/liveGodView.ts apps/web/src/features/games/liveGodView.test.ts
git commit -m "feat: derive god view skill triggers"
```

## 7. Task 2: 重组页面布局槽位

**Files:**
- Modify: `apps/web/src/pages/components/LiveStageModule.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写布局红灯测试**

在 `LiveGamePage.test.tsx` 新增：

```ts
it("renders the recomposed god-view broadcast layout zones", async () => {
  vi.stubGlobal("EventSource", MockEventSource);
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(runningRunResponse()),
  );

  renderWithClient(
    <Routes>
      <Route path="/games/live/:runId" element={<LiveGamePage />} />
    </Routes>,
    "/games/live/run_1234abcd",
  );

  expect(await screen.findByText("实时观战")).toBeInTheDocument();

  expect(screen.getByTestId("god-view-top-zone")).toBeInTheDocument();
  expect(screen.getByTestId("god-view-left-zone")).toBeInTheDocument();
  expect(screen.getByTestId("god-view-stage-zone")).toBeInTheDocument();
  expect(screen.getByTestId("god-view-right-zone")).toBeInTheDocument();
  expect(screen.getByTestId("god-view-bottom-zone")).toBeInTheDocument();
  expect(screen.queryByTestId("god-view-roster-panel")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: FAIL，找不到 `god-view-top-zone`。

- [ ] **Step 3: 修改 `LiveStageModule` props**

把 `LiveStageModule.tsx` 调整为：

```tsx
import type { ReactNode } from "react";

type LiveStageModuleProps = {
  top: ReactNode;
  left: ReactNode;
  stage: ReactNode;
  right: ReactNode;
  bottom?: ReactNode;
};

export function LiveStageModule({
  bottom,
  left,
  right,
  stage,
  top,
}: LiveStageModuleProps) {
  return (
    <div
      className="live-stage-layout live-stage-module god-view-broadcast-layout grid gap-3"
      data-testid="live-stage-layout"
    >
      <div className="god-view-top-zone min-w-0" data-testid="god-view-top-zone">
        {top}
      </div>
      <div className="god-view-left-zone min-w-0" data-testid="god-view-left-zone">
        {left}
      </div>
      <div className="god-view-stage-zone min-w-0" data-testid="god-view-stage-zone">
        {stage}
      </div>
      <div className="god-view-right-zone min-w-0" data-testid="god-view-right-zone">
        {right}
      </div>
      {bottom ? (
        <div
          className="god-view-bottom-zone live-god-bottom-board min-w-0"
          data-testid="god-view-bottom-zone"
        >
          {bottom}
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: 临时更新 `LiveGamePage` 装配**

先把旧组件塞到新槽位，保证编译通过，后续任务再替换内容：

```tsx
<LiveStageModule
  bottom={<GodViewBottomBoard state={godViewState} />}
  left={<GodViewRosterPanel onSelectPlayer={handleSelectPlayer} players={godViewState.players} />}
  right={<GodViewIntelPanel debugTimeline={...} state={godViewState} />}
  stage={<LiveDirectorStage ... />}
  top={<div data-testid="god-view-top-bar-placeholder">{godViewState.boardName}</div>}
/>
```

实际实现时先抽出：

```ts
const handleSelectPlayer = (name: string) => {
  setAutoFollow(false);
  setManualFocusName(name);
};
```

并在两个位置复用。

- [ ] **Step 5: 运行布局测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: 这一阶段可以仍然 FAIL 于 `god-view-roster-panel` 仍存在；下一任务移除 roster 后通过。

## 8. Task 3: 顶部总控条独立化

**Files:**
- Create: `apps/web/src/features/games/components/GodViewTopBar.tsx`
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写顶部总控条测试**

在已有布局测试里追加：

```ts
const top = screen.getByTestId("god-view-top-zone");
expect(within(top).getByText("经典 8 人局")).toBeInTheDocument();
expect(within(top).getByText("第 1 天")).toBeInTheDocument();
expect(within(top).getByText("白天发言")).toBeInTheDocument();
expect(within(top).getByText("发言席：4 号")).toBeInTheDocument();
expect(within(top).getByText("00:45")).toBeInTheDocument();
expect(within(top).getByText("存活 4/4")).toBeInTheDocument();
expect(within(top).getByText("屠边")).toBeInTheDocument();
expect(
  within(screen.getByTestId("live-director-stage")).queryByTestId(
    "god-view-stage-strip",
  ),
).not.toBeInTheDocument();
```

测试事件沿用当前 `large god-view stage portrait` 测试中的 4 人事件。

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: FAIL，顶部只是 placeholder，舞台内仍有 `god-view-stage-strip`。

- [ ] **Step 3: 创建 `GodViewTopBar`**

新增文件：

```tsx
import { withGlassPanel } from "../../../components/ui/glass";
import type { GodViewState } from "../liveGodView";

type GodViewTopBarProps = {
  state: GodViewState;
};

export function GodViewTopBar({ state }: GodViewTopBarProps) {
  return (
    <section
      className={withGlassPanel(
        "god-view-top-bar god-view-frame overflow-hidden rounded-lg px-3 py-2 text-slate-100",
      )}
      data-testid="god-view-top-bar"
    >
      <div
        className="god-view-stage-strip grid grid-cols-2 gap-1 rounded-md border border-amber-300/35 px-3 py-2 text-[11px] text-slate-300 shadow-[0_16px_45px_rgba(0,0,0,0.24)] sm:grid-cols-4 xl:grid-cols-7"
        data-testid="god-view-stage-strip"
      >
        <TopStat label="房间名" value={state.boardName} />
        <TopStat label="天夜" value={state.dayNightLabel} />
        <TopStat label="阶段" value={state.phaseLabel} />
        <TopStat label="发言席" value={state.currentSeatLabel} />
        <TopStat label="倒计时" value={state.countdownLabel} />
        <TopStat label="存活" value={state.aliveLabel} />
        <TopStat label="胜负条件" value={state.winMode} />
      </div>
    </section>
  );
}

function TopStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="relative min-w-0 border-l border-amber-300/10 pl-2 first:border-l-0 first:pl-0">
      <span className="block text-[10px] text-amber-200/60">{label}</span>
      <span className="block truncate font-semibold text-amber-50">
        {value}
      </span>
    </div>
  );
}
```

- [ ] **Step 4: 从舞台移除内部顶部状态条**

在 `LiveDirectorStage.tsx` 删除：

```tsx
{godViewState ? (
  <div className="god-view-stage-strip ..." data-testid="god-view-stage-strip">
    ...
  </div>
) : null}
```

删除局部 `StageStat()` 函数。

- [ ] **Step 5: 在 `LiveGamePage` 使用 `GodViewTopBar`**

新增 import：

```ts
import { GodViewTopBar } from "../features/games/components/GodViewTopBar";
```

传入：

```tsx
top={<GodViewTopBar state={godViewState} />}
```

- [ ] **Step 6: 运行顶部测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: PASS 当前顶部断言。

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/games/components/GodViewTopBar.tsx apps/web/src/features/games/components/LiveDirectorStage.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/components/LiveStageModule.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat: split god view top control bar"
```

## 9. Task 4: 左侧局势面板

**Files:**
- Create: `apps/web/src/features/games/components/GodViewSituationPanel.tsx`
- Modify: `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写左侧面板测试**

在布局测试中追加：

```ts
const left = screen.getByTestId("god-view-left-zone");
expect(within(left).getByRole("heading", { name: "局势总览" })).toBeInTheDocument();
expect(within(left).getByRole("heading", { name: "阵营进度" })).toBeInTheDocument();
expect(within(left).getByRole("heading", { name: "夜晚行动回顾" })).toBeInTheDocument();
expect(within(left).queryByText("身份牌（上帝视角）")).not.toBeInTheDocument();

const right = screen.getByTestId("god-view-right-zone");
expect(within(right).queryByRole("heading", { name: "阵营进度" })).not.toBeInTheDocument();
expect(within(right).queryByRole("heading", { name: "夜晚行动回顾" })).not.toBeInTheDocument();
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: FAIL，左侧仍是身份牌。

- [ ] **Step 3: 创建 `GodViewSituationPanel`**

新增文件：

```tsx
import { withGlassPanel } from "../../../components/ui/glass";
import type { GodViewActionLine, GodViewState } from "../liveGodView";

type GodViewSituationPanelProps = {
  state: GodViewState;
};

export function GodViewSituationPanel({ state }: GodViewSituationPanelProps) {
  return (
    <aside
      className={withGlassPanel(
        "god-view-situation-panel god-view-frame min-w-0 overflow-hidden rounded-lg text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.32)]",
      )}
      data-testid="god-view-situation-panel"
    >
      <SituationSection title="局势总览">
        <div className="space-y-1.5">
          <InfoRow label="当前阶段" value={`${state.dayNightLabel} · ${state.phaseLabel}`} />
          <InfoRow label="当前发言" value={state.currentSeatLabel} />
          <InfoRow label="存活人数" value={state.aliveLabel} />
          <InfoRow label="胜负条件" value={state.winMode} />
          <div className={`rounded-md border px-2.5 py-2 text-xs ${winPressureTone(state.winPressure.tone)}`}>
            <p className="font-semibold">{state.winPressure.label}</p>
            <p className="mt-1 opacity-80">{state.winPressure.detail}</p>
          </div>
        </div>
      </SituationSection>

      <SituationSection title="阵营进度">
        <div className="space-y-2">
          <ProgressLine count={state.progress.wolvesAlive} label="狼人存活" max={state.progress.totalPlayers} tone="danger" />
          <ProgressLine count={state.progress.godsAlive} label="神职存活" max={state.progress.totalPlayers} tone="info" />
          <ProgressLine count={state.progress.villagersAlive} label="平民存活" max={state.progress.totalPlayers} tone="success" />
        </div>
      </SituationSection>

      <SituationSection title="夜晚行动回顾">
        <div className="space-y-1.5" data-testid="god-view-night-action-order">
          {state.nightActionOrder.map((action) => (
            <NightActionLine action={action} key={`${action.order}-${action.label}-${action.value}`} />
          ))}
        </div>
      </SituationSection>
    </aside>
  );
}

function SituationSection({
  children,
  title,
}: {
  children: React.ReactNode;
  title: string;
}) {
  return (
    <section className="border-b border-amber-500/15 px-4 py-3 last:border-b-0">
      <h2 className="text-sm font-semibold text-amber-50">{title}</h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-slate-700/45 bg-black/20 px-2.5 py-1.5 text-xs">
      <span className="shrink-0 text-slate-500">{label}</span>
      <span className="min-w-0 text-right text-slate-200">{value}</span>
    </div>
  );
}

function ProgressLine({
  count,
  label,
  max,
  tone,
}: {
  count: number;
  label: string;
  max: number;
  tone: "danger" | "info" | "success";
}) {
  const width = max > 0 ? Math.round((count / max) * 100) : 0;
  const toneClass =
    tone === "danger"
      ? "bg-red-400"
      : tone === "info"
        ? "bg-sky-300"
        : "bg-emerald-400";

  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-semibold text-slate-100">{count}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-black/45">
        <span className={`block h-full rounded-full ${toneClass}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function NightActionLine({ action }: { action: GodViewActionLine & { order: number } }) {
  return (
    <div
      className="grid grid-cols-[1.5rem_5rem_minmax(0,1fr)] gap-2 rounded-md border border-slate-700/45 bg-black/25 px-2.5 py-1.5 text-xs"
      data-testid="god-view-night-action"
    >
      <span className="text-amber-200">{action.order}</span>
      <span className={actionTone(action.tone)}>{action.label}</span>
      <span className="min-w-0 truncate text-slate-200">{action.value}</span>
    </div>
  );
}

function actionTone(tone: GodViewActionLine["tone"]) {
  if (tone === "danger") return "text-red-200";
  if (tone === "info") return "text-sky-200";
  if (tone === "success") return "text-emerald-200";
  if (tone === "warning") return "text-amber-200";
  return "text-slate-500";
}

function winPressureTone(tone: GodViewState["winPressure"]["tone"]) {
  if (tone === "danger") return "border-red-400/30 bg-red-950/25 text-red-100";
  if (tone === "warning") return "border-amber-300/30 bg-amber-950/25 text-amber-100";
  if (tone === "safe") return "border-emerald-300/30 bg-emerald-950/25 text-emerald-100";
  return "border-slate-600/45 bg-slate-950/40 text-slate-200";
}
```

- [ ] **Step 4: 从 `GodViewIntelPanel` 移除左侧职责**

删除 `GodViewIntelPanel` 中这两个 section：

```tsx
<IntelSection title="夜晚行动回顾">...</IntelSection>
<IntelSection title="阵营进度">...</IntelSection>
```

删除不再使用的 `ProgressLine()` 和 `winPressureTone()`。

- [ ] **Step 5: 在 `LiveGamePage` 左栏使用局势面板**

新增 import：

```ts
import { GodViewSituationPanel } from "../features/games/components/GodViewSituationPanel";
```

传入：

```tsx
left={<GodViewSituationPanel state={godViewState} />}
```

移除 `GodViewRosterPanel` import 和使用。

- [ ] **Step 6: 运行左侧面板测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: PASS 左侧归位断言。

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/games/components/GodViewSituationPanel.tsx apps/web/src/features/games/components/GodViewIntelPanel.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat: add god view situation panel"
```

## 10. Task 5: 舞台左右玩家卡成为唯一玩家入口

**Files:**
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`
- Modify: `apps/web/src/styles/index.css`

- [ ] **Step 1: 写玩家卡轨道红灯测试**

新增测试：

```ts
it("uses player cards around the stage as the only player information entry", async () => {
  vi.stubGlobal("EventSource", MockEventSource);
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(runningRunResponse()),
  );

  renderWithClient(
    <Routes>
      <Route path="/games/live/:runId" element={<LiveGamePage />} />
    </Routes>,
    "/games/live/run_1234abcd",
  );

  expect(await screen.findByText("实时观战")).toBeInTheDocument();
  const source = MockEventSource.instances[0];
  act(() => {
    emitEvent(source, {
      id: 1,
      type: "game_started",
      payload: {
        players: [
          { name: "P1", role: "预言家", model: "deepseek-chat" },
          { name: "P2", role: "村民", model: "deepseek-chat" },
          { name: "P3", role: "狼人", model: "deepseek-chat" },
          { name: "P4", role: "守卫", model: "deepseek-chat" },
          { name: "P5", role: "村民", model: "deepseek-chat" },
          { name: "P6", role: "狼人", model: "deepseek-chat" },
          { name: "P7", role: "村民", model: "deepseek-chat" },
          { name: "P8", role: "村民", model: "deepseek-chat" },
        ],
      },
    });
    emitEvent(source, {
      id: 2,
      type: "action_requested",
      round: 1,
      phase: "day",
      actor: "P4",
      action: "debate",
    });
  });

  const leftRail = screen.getByTestId("god-view-player-rail-left");
  const rightRail = screen.getByTestId("god-view-player-rail-right");
  expect(within(leftRail).getAllByTestId(/god-view-stage-player-card-/)).toHaveLength(4);
  expect(within(rightRail).getAllByTestId(/god-view-stage-player-card-/)).toHaveLength(4);
  expect(screen.queryByLabelText("圆桌座位")).not.toBeInTheDocument();

  await userEvent.click(screen.getByTestId("god-view-stage-player-card-P2"));
  expect(screen.getByTestId("god-view-stage-player-card-P2")).toHaveAttribute(
    "data-card-state",
    "focused",
  );
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "only player information entry"
```

Expected: FAIL，找不到玩家卡轨道。

- [ ] **Step 3: 在 `LiveDirectorStage` 建立玩家卡轨道**

在舞台圆桌背景之后、中心大舞台之前添加：

```tsx
{godViewState ? (
  <div className="god-view-stage-player-shell absolute inset-x-3 top-24 bottom-24 z-30 grid grid-cols-[minmax(7.5rem,11rem)_minmax(0,1fr)_minmax(7.5rem,11rem)] gap-3 sm:inset-x-5">
    <PlayerRail
      focusedPlayerName={focusedPlayerName}
      players={godViewState.players.slice(0, Math.ceil(godViewState.players.length / 2))}
      side="left"
      onSelectPlayer={onSelectPlayer}
    />
    <div aria-hidden="true" />
    <PlayerRail
      focusedPlayerName={focusedPlayerName}
      players={godViewState.players.slice(Math.ceil(godViewState.players.length / 2), 12)}
      side="right"
      onSelectPlayer={onSelectPlayer}
    />
  </div>
) : null}
```

新增组件：

```tsx
function PlayerRail({
  focusedPlayerName,
  onSelectPlayer,
  players,
  side,
}: {
  focusedPlayerName: string | null;
  onSelectPlayer: (name: string) => void;
  players: GodViewPlayer[];
  side: "left" | "right";
}) {
  return (
    <div
      className="god-view-stage-player-rail flex min-h-0 flex-col gap-1.5 overflow-auto"
      data-testid={`god-view-player-rail-${side}`}
    >
      {players.map((player) => (
        <StagePlayerCard
          isFocused={player.name === focusedPlayerName}
          key={player.name}
          onSelectPlayer={onSelectPlayer}
          player={player}
        />
      ))}
    </div>
  );
}

function StagePlayerCard({
  isFocused,
  onSelectPlayer,
  player,
}: {
  isFocused: boolean;
  onSelectPlayer: (name: string) => void;
  player: GodViewPlayer;
}) {
  const state = !player.isAlive ? "out" : isFocused ? "focused" : player.isSpeaking ? "speaking" : "idle";
  return (
    <button
      className={`god-view-stage-player-card grid grid-cols-[1.65rem_2.25rem_minmax(0,1fr)] items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs transition hover:-translate-y-0.5 ${stagePlayerTone(player, state)}`}
      data-card-state={state}
      data-testid={`god-view-stage-player-card-${player.name}`}
      onClick={() => onSelectPlayer(player.name)}
      type="button"
    >
      <span className="flex h-6 w-6 items-center justify-center rounded border border-amber-300/35 bg-black/55 text-[11px] font-semibold text-amber-100">
        {player.seatNumber}
      </span>
      <span
        className={`flex h-9 w-9 items-center justify-center overflow-hidden rounded-full border bg-gradient-to-br ${avatarGradient(player.name)} ${appearanceClassName(player.appearanceId)} text-[11px] font-semibold text-slate-100`}
      >
        {player.avatarImageUrl ? (
          <img alt={`${player.name} 玩家头像`} className="h-full w-full object-cover" src={player.avatarImageUrl} />
        ) : (
          avatarText(player.name)
        )}
      </span>
      <span className="min-w-0">
        <span className="block truncate font-semibold text-slate-100">{player.name}</span>
        <span className="mt-0.5 flex min-w-0 gap-1">
          <span className="truncate rounded bg-black/35 px-1.5 py-0.5 text-[10px] text-amber-100">{player.role}</span>
          <span className="truncate rounded bg-black/35 px-1.5 py-0.5 text-[10px] text-slate-300">{player.statusLabel}</span>
        </span>
      </span>
    </button>
  );
}
```

新增 tone helper：

```ts
function stagePlayerTone(player: GodViewPlayer, state: "focused" | "idle" | "out" | "speaking") {
  if (state === "out") {
    return "border-slate-600/45 bg-slate-950/70 opacity-70 grayscale";
  }
  if (state === "speaking") {
    return "border-teal-200/70 bg-teal-950/30 shadow-[0_0_24px_rgba(45,212,191,0.22)]";
  }
  if (state === "focused") {
    return "border-amber-200/70 bg-amber-950/25 shadow-[0_0_22px_rgba(251,191,36,0.22)]";
  }
  if (player.camp === "狼人阵营") {
    return "border-red-500/35 bg-red-950/22";
  }
  return "border-slate-700/45 bg-black/28";
}
```

- [ ] **Step 4: 移除圆桌座位按钮入口**

删除 `LiveDirectorStage.tsx` 中：

```tsx
<div aria-label="圆桌座位" ...>
  ...
</div>
```

保留圆桌背景装饰层和中心大舞台。

- [ ] **Step 5: 运行玩家卡测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "only player information entry"
```

Expected: PASS。

- [ ] **Step 6: 更新受影响旧测试**

当前旧测试可能断言：

```ts
screen.getByText("圆桌座位")
screen.getByRole("button", { name: /张三/ })
```

把这些断言改为新入口：

```ts
screen.getByTestId("god-view-player-rail-left")
screen.getByTestId("god-view-stage-player-card-张三")
```

如果旧测试验证点击玩家行为，改为点击 `god-view-stage-player-card-<name>`。

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/games/components/LiveDirectorStage.tsx apps/web/src/pages/LiveGamePage.test.tsx apps/web/src/styles/index.css
git commit -m "feat: move player entry cards into live stage"
```

## 11. Task 6: 右侧情报栈重组为事件 / 死亡 / 身份线索与技能触发

**Files:**
- Modify: `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写右侧情报测试**

在布局测试中追加：

```ts
const right = screen.getByTestId("god-view-right-zone");
expect(within(right).getByRole("heading", { name: "事件记录" })).toBeInTheDocument();
expect(within(right).getByRole("heading", { name: "死亡信息" })).toBeInTheDocument();
expect(within(right).getByRole("heading", { name: "身份线索 / 技能触发" })).toBeInTheDocument();
expect(within(right).queryByRole("heading", { name: "警长信息" })).not.toBeInTheDocument();
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: FAIL，标题仍是 `身份线索（上帝视角）` 或存在 `警长信息`。

- [ ] **Step 3: 合并身份线索与技能触发 section**

在 `GodViewIntelPanel.tsx` 中把身份线索 section 改为：

```tsx
<IntelSection title="身份线索 / 技能触发">
  <div className="space-y-3">
    <div className="space-y-1.5">
      {state.players.length === 0 ? (
        <p className="text-xs text-slate-500">暂无身份线索</p>
      ) : (
        state.players.slice(0, 6).map((player) => (
          <div
            className="flex items-center justify-between gap-2 rounded-md border border-slate-700/45 bg-black/25 px-2.5 py-1.5 text-xs"
            key={player.name}
          >
            <span className="min-w-0 truncate text-slate-200">
              {player.seatNumber} 号 {player.name}
            </span>
            <span className="shrink-0 text-amber-100">
              {player.role} · {player.identityGroup}
            </span>
          </div>
        ))
      )}
    </div>
    <div className="space-y-1.5 border-t border-amber-500/15 pt-2">
      {state.skillTriggers.length === 0 ? (
        <p className="text-xs text-slate-500">暂无技能触发</p>
      ) : (
        state.skillTriggers.map((trigger) => (
          <div
            className="rounded-md border border-slate-700/45 bg-black/25 px-2.5 py-1.5 text-xs"
            key={`${trigger.id}-${trigger.label}-${trigger.detail}`}
          >
            <p className={skillTriggerTone(trigger.tone)}>{trigger.label}</p>
            <p className="mt-1 text-slate-300">{trigger.detail}</p>
          </div>
        ))
      )}
    </div>
  </div>
</IntelSection>
```

新增 helper：

```ts
function skillTriggerTone(tone: GodViewState["skillTriggers"][number]["tone"]) {
  if (tone === "danger") return "font-semibold text-red-100";
  if (tone === "info") return "font-semibold text-sky-100";
  if (tone === "success") return "font-semibold text-emerald-100";
  if (tone === "warning") return "font-semibold text-amber-100";
  return "font-semibold text-slate-300";
}
```

- [ ] **Step 4: 移除警长信息 section**

删除：

```tsx
<IntelSection title="警长信息">...</IntelSection>
```

警长规则态不在新布局要求中展示。若以后需要，可进入身份线索/技能触发里的技能触发记录。

- [ ] **Step 5: 运行右侧情报测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/games/components/GodViewIntelPanel.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat: reorganize god view right intel stack"
```

## 12. Task 7: 底部复盘板改为四列

**Files:**
- Modify: `apps/web/src/features/games/components/GodViewBottomBoard.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写底部四列测试**

在布局测试中追加：

```ts
const bottom = screen.getByTestId("god-view-bottom-zone");
expect(within(bottom).getByRole("heading", { name: "发言顺序" })).toBeInTheDocument();
expect(within(bottom).getByRole("heading", { name: "票型矩阵" })).toBeInTheDocument();
expect(within(bottom).getByRole("heading", { name: "投票统计" })).toBeInTheDocument();
expect(within(bottom).getByRole("heading", { name: "公开信息" })).toBeInTheDocument();
expect(within(bottom).queryByRole("heading", { name: "放逐候选排名" })).not.toBeInTheDocument();
expect(within(bottom).queryByRole("heading", { name: "本局标记（回放点）" })).not.toBeInTheDocument();
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: FAIL，旧底部仍有六列。

- [ ] **Step 3: 改 `GodViewBottomBoard` 四列布局**

把根 grid 改为：

```tsx
<div className="grid min-w-[52rem] grid-cols-[1.1fr_1.15fr_1fr_1.1fr] divide-x divide-amber-500/15">
```

保留四个 `BottomColumn`：

```tsx
<BottomColumn title="发言顺序">...</BottomColumn>
<BottomColumn title="票型矩阵">...</BottomColumn>
<BottomColumn title="投票统计">...</BottomColumn>
<BottomColumn title="公开信息">...</BottomColumn>
```

删除：

```tsx
<BottomColumn title="放逐候选排名">...</BottomColumn>
<BottomColumn title="本局标记（回放点）">...</BottomColumn>
```

- [ ] **Step 4: 运行底部测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "recomposed god-view broadcast layout zones"
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/games/components/GodViewBottomBoard.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat: simplify god view bottom replay board"
```

## 13. Task 8: CSS 布局与响应式适配

**Files:**
- Modify: `apps/web/src/styles/index.css`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写布局 CSS 类测试**

在 `LiveGamePage.test.tsx` 的布局测试中追加：

```ts
expect(screen.getByTestId("live-stage-layout")).toHaveClass(
  "god-view-broadcast-layout",
);
expect(screen.getByTestId("god-view-top-zone")).toHaveClass("min-w-0");
expect(screen.getByTestId("god-view-stage-zone")).toHaveClass("min-w-0");
```

- [ ] **Step 2: 补 CSS 网格**

在 `index.css` 添加：

```css
.god-view-broadcast-layout {
  grid-template-columns: minmax(16rem, 18rem) minmax(0, 1fr) minmax(18rem, 22rem);
  grid-template-areas:
    "top top top"
    "left stage right"
    "bottom bottom bottom";
  align-items: start;
}

.god-view-top-zone {
  grid-area: top;
}

.god-view-left-zone {
  grid-area: left;
  position: sticky;
  top: 0.75rem;
  align-self: start;
}

.god-view-stage-zone {
  grid-area: stage;
}

.god-view-right-zone {
  grid-area: right;
  position: sticky;
  top: 0.75rem;
  align-self: start;
}

.god-view-bottom-zone {
  grid-area: bottom;
}

.god-view-stage-player-rail {
  scrollbar-width: thin;
  scrollbar-color: rgb(185 147 92 / 55%) rgb(2 6 23 / 45%);
}
```

- [ ] **Step 3: 补中屏布局**

在 CSS 中添加：

```css
@media (max-width: 1279px) {
  .god-view-broadcast-layout {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "top"
      "stage"
      "left"
      "right"
      "bottom";
  }

  .god-view-left-zone,
  .god-view-right-zone {
    position: static;
  }
}
```

- [ ] **Step 4: 补短横屏布局**

在现有短横屏 media query 中添加：

```css
@media (orientation: landscape) and (max-height: 620px) {
  .god-view-broadcast-layout {
    gap: 0.5rem;
  }

  .god-view-stage-player-shell {
    top: 5.6rem;
    bottom: 4.8rem;
    grid-template-columns: minmax(6.5rem, 8.5rem) minmax(0, 1fr) minmax(6.5rem, 8.5rem);
  }

  .god-view-stage-player-card {
    grid-template-columns: 1.4rem 1.9rem minmax(0, 1fr);
    padding: 0.35rem;
  }
}
```

- [ ] **Step 5: 补移动端玩家卡布局**

在 CSS 中添加：

```css
@media (max-width: 640px) {
  .god-view-stage-player-shell {
    position: static;
    display: grid;
    grid-template-columns: 1fr;
    margin-top: 0.75rem;
  }

  .god-view-stage-player-rail {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    max-height: none;
    overflow: visible;
  }
}
```

- [ ] **Step 6: 运行页面测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/styles/index.css apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "style: adapt god view broadcast layout"
```

## 14. Task 9: 全量验证与浏览器 QA

**Files:**
- No new files.

- [ ] **Step 1: 运行聚焦测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveGodView.test.ts src/pages/LiveGamePage.test.tsx
```

Expected: PASS。

- [ ] **Step 2: 运行全量前端测试**

Run:

```bash
pnpm --dir apps/web test -- --run
```

Expected: PASS。

- [ ] **Step 3: 运行 lint**

Run:

```bash
pnpm --dir apps/web lint
```

Expected: PASS。

- [ ] **Step 4: 运行构建**

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS。允许 Vite 保留现有大 chunk warning。

- [ ] **Step 5: 启动开发服务**

如果 5173 空闲：

```bash
pnpm --dir apps/web exec vite --host 127.0.0.1 --port 5173 --strictPort
```

如果 5173 被占用：

```bash
pnpm --dir apps/web exec vite --host 127.0.0.1 --port 5175 --strictPort
```

- [ ] **Step 6: Browser QA 当前真实 run**

打开：

```text
http://127.0.0.1:5173/games/live/run_cb995553d12a
```

或使用实际启动端口。

检查：

```js
document.querySelector("[data-testid='god-view-top-zone']") !== null
document.querySelector("[data-testid='god-view-left-zone']")?.textContent.includes("局势总览")
document.querySelector("[data-testid='god-view-stage-zone']")?.textContent.includes("当前关注")
document.querySelector("[data-testid='god-view-player-rail-left']") !== null
document.querySelector("[data-testid='god-view-player-rail-right']") !== null
document.querySelector("[data-testid='god-view-right-zone']")?.textContent.includes("事件记录")
document.querySelector("[data-testid='god-view-bottom-zone']")?.textContent.includes("票型矩阵")
document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1
```

视口检查：

- 1280x720：顶部一行总控、三栏主体、底部四列可见，无页面级横向溢出。
- 1024x560：短横屏下左右玩家卡不压住中央发言舞台，左右/右栏可滚动。
- 390x844：顶部、舞台、左栏、右栏、底部按单列堆叠；玩家卡在舞台下变成两列卡片。

- [ ] **Step 7: 清理开发服务**

停止本次启动的 Vite 进程，确认端口释放：

```bash
lsof -nP -iTCP:5173 -sTCP:LISTEN || true
lsof -nP -iTCP:5175 -sTCP:LISTEN || true
```

- [ ] **Step 8: 最终状态检查**

Run:

```bash
git status --short --branch
git log --oneline -5
```

Expected: 工作树只包含本次提交，或干净并位于目标分支。

## 15. 验收标准

功能验收：

- 顶部只负责总控信息：房间名、天夜、阶段、发言席、倒计时、存活、胜负条件。
- 左栏只有局势总览、阵营进度、夜晚行动回顾。
- 中央舞台只聚焦当前发言玩家大舞台和玩家卡入口。
- 舞台左右玩家卡最多支持 12 人，当前 run 按实际玩家数量展示。
- 玩家卡是唯一玩家信息入口；页面不再渲染左侧身份牌表，也不再渲染圆桌座位按钮入口。
- 右栏只有事件记录、死亡信息、身份线索 / 技能触发。
- 底部只有发言顺序、票型矩阵、投票统计、公开信息。
- 当前自动跟随、手动点击玩家关注、导播队列、调试事件、继续对局、查看完整复盘不被破坏。

视觉验收：

- 页面更接近用户给出的导播台分区：顶部横条、左右信息栈、中间主舞台、底部复盘条。
- 1280x720 无页面级横向溢出。
- 短横屏不遮挡中央发言舞台。
- 移动宽度不出现文字互相覆盖。

工程验收：

- `pnpm --dir apps/web exec vitest run src/features/games/liveGodView.test.ts src/pages/LiveGamePage.test.tsx` 通过。
- `pnpm --dir apps/web test -- --run` 通过。
- `pnpm --dir apps/web lint` 通过。
- `pnpm --dir apps/web build` 通过。

## 16. 执行建议

建议按以下顺序执行：

1. 先补 `skillTriggers` 派生字段，给右下角“技能触发”提供数据来源。
2. 再改布局槽位和顶部总控条，先让页面结构成型。
3. 再做左栏和右栏内容迁移，避免同一组件同时承担旧职责和新职责。
4. 再把玩家入口从圆桌座位迁到左右玩家卡，这是交互变化最大的一步。
5. 最后收底部四列和响应式 CSS。

每个任务完成后单独跑对应测试并提交，避免一次性大改导致失败来源不清楚。

## 17. 自检

- 覆盖性：本文档覆盖了用户列出的顶部、左侧、中间、右侧、底部所有分区。
- 约束性：明确不改后端、不新增依赖、不生成素材。
- 一致性：玩家信息入口从左侧身份牌和圆桌按钮收敛到舞台左右玩家卡。
- 可测试性：每个关键布局变化都有 Testing Library 断言，最终有 Browser QA。
- 风险点：旧测试中对“圆桌座位”和左侧身份牌的断言需要同步迁移到玩家卡入口。
