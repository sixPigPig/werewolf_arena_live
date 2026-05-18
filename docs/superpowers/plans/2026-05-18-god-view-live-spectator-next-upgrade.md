# 上帝视角直播台下一阶段升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 `/games/live/:runId` 从“已有上帝视角信息面板”继续升级为更接近参考图的哥特直播导播台，补齐中央大人物舞台、顶部总控栏、夜间结论、中文化回放点和规则态表达。

**Architecture:** 继续沿用当前前端派生层 `liveGodView.ts`，先增强可测试的直播台派生数据，再让 `LiveDirectorStage`、`GodViewIntelPanel`、`GodViewBottomBoard` 和 CSS 逐步消费这些字段。第一版不改后端事件协议，不新增依赖，不引入真实计时器；所有无法从当前事件得出的数据都以明确的规则态或空态表达。

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, Tailwind CSS utilities, existing gothic/glass CSS surfaces.

---

## 1. 当前对局核对结论

核对页面：

```text
http://127.0.0.1:5173/games/live/run_cb995553d12a
```

当前对局是 `经典 8 人局`：

- 角色结构：`2 狼人 / 1 预言家 / 1 守卫 / 4 村民`
- 规则标签：`无警长`、`顺序发言`、`标准`
- 当前阶段：第 1 天白天发言
- 当前发言席：4 号 Isaac
- 当前存活：8/8
- 当前夜间行动可见：预言家查验 Jackson、守卫守护 Isaac、狼人击杀 Isaac

当前页已经覆盖：

- 左侧身份牌表：席位、昵称、真实身份、阵营组、发言/存活状态、投票目标、票数、嫌疑值。
- 中央圆桌舞台：玩家围桌、当前发言高亮、自动跟随、当前关注。
- 右侧情报栈：事件记录、死亡信息、夜晚行动、身份线索、警长信息、阵营进度。
- 底部复盘板：发言顺序、票型矩阵、投票统计、放逐候选、公开信息、回放点。

但对照参考图仍有明显差距：

- 中央缺少当前发言玩家“大半身形象/大头像舞台”。
- 顶部局势信息有数据，但视觉权重不够，不像参考图的总控状态栏。
- 中台缺少“上一位 / 当前 / 下一位”发言顺序。
- 狼人击杀被守卫守护时，死亡区仍显示“暂无死亡信息”，应该明确展示“平安夜”或“被守护未死亡”。
- 夜晚行动只列结果，缺少行动顺序链。
- 回放点仍出现 `state_updated`，没有完全中文化。
- 当前规则无警长，但警长模块仍像“数据缺失”，应该显示“本局无警长规则”。
- 票型板在未投票时过空，参考图会保留矩阵/候选/统计骨架。
- 阵营进度只有数量，缺少“屠边临界/胜负压力”提示。
- 哥特金边、角标、表格密度和整体直播台视觉还可加强。

## 2. 非目标

本阶段不做这些事：

- 不新增后端字段或数据库迁移。
- 不引入 Canvas、Three.js、WebGL 或新 UI 依赖。
- 不实现真实倒计时。`00:45` 仍是直播台状态展示，直到后端提供精确计时。
- 不生成新图片素材。当前发言大舞台优先使用玩家 `avatarImageUrl`，没有头像时使用现有外观色、姓名缩写和哥特框构成大头像。
- 不把经典 8 人局强行显示成 12 人局。参考图中的 12 人信息只作为布局和密度参考。

## 3. 文件结构

计划修改：

- `apps/web/src/features/games/liveGodView.ts`
  - 增强派生字段：当前发言三元组、夜间结论、夜间行动顺序、警长规则态、胜负压力、中文回放点。

- `apps/web/src/features/games/liveGodView.test.ts`
  - 增加派生层测试，先红后绿。

- `apps/web/src/features/games/components/LiveDirectorStage.tsx`
  - 增加当前发言玩家大头像/半身舞台、上一位/当前/下一位、发言类型标签。

- `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
  - 优化死亡信息、夜晚行动回顾、警长信息、阵营进度。

- `apps/web/src/features/games/components/GodViewBottomBoard.tsx`
  - 优化票型空态、候选排名骨架、公开信息和回放点中文显示。

- `apps/web/src/pages/LiveGamePage.test.tsx`
  - 覆盖新舞台、夜间结论、无警长规则态、中文回放点。

- `apps/web/src/styles/index.css`
  - 加强哥特直播台视觉、短横屏和小屏适配。

可选拆分：

- 如果 `LiveDirectorStage.tsx` 继续膨胀，创建 `apps/web/src/features/games/components/GodViewSpeakerStage.tsx`，专门负责中央大人物舞台。
- 如果 `GodViewIntelPanel.tsx` 继续膨胀，创建 `apps/web/src/features/games/components/GodViewPanelSection.tsx`，抽出通用分区标题、空态和信息行。

## 4. 数据设计

在 `GodViewState` 中补充字段：

```ts
type GodViewState = {
  // existing fields remain
  speakerFlow: {
    previous: GodViewPlayer | null;
    current: GodViewPlayer | null;
    next: GodViewPlayer | null;
    modeLabel: string;
  };
  nightResolution: {
    label: string;
    detail: string;
    tone: "safe" | "danger" | "neutral";
  };
  nightActionOrder: Array<{
    order: number;
    label: string;
    value: string;
    tone: "danger" | "info" | "success" | "warning" | "muted";
  }>;
  sheriffRuleState: {
    enabled: boolean;
    label: string;
  };
  winPressure: {
    label: string;
    detail: string;
    tone: "danger" | "warning" | "safe" | "neutral";
  };
};
```

从当前事件推导：

- `speakerFlow`：
  - 优先使用 `state.speechOrder`。
  - 当前玩家来自 `activePlayerName`。
  - 找不到顺序时回退到 `players` 原始席位顺序。

- `nightResolution`：
  - 有 `night_deaths` 或 `eliminated`：显示死亡玩家和死亡原因。
  - 有 `attacked` 且 `protected === attacked` 或 `eliminated` 为空：显示“平安夜 / 被守护未死亡”。
  - 当前还没有夜间结算：显示“等待夜间结算”。

- `nightActionOrder`：
  - 固定展示当前可见行动顺序：狼人目标、守卫守护、预言家查验、女巫解药、女巫毒药。
  - 当前规则没有女巫时，女巫条目不显示。
  - 没有对应行动时显示“暂无记录”。

- `sheriffRuleState`：
  - 从 `run.rule_set.sheriff_enabled` 传入派生层，或在 `LiveGamePage` 外层把规则态传给 `GodViewIntelPanel`。
  - 当前经典 8 人局显示“本局无警长规则”。

- `winPressure`：
  - 狼人存活数 >= 好人存活数：显示“狼人接近屠城/压制”。
  - 狼人存活数为 1：显示“狼人濒危”。
  - 神职或平民任一归零风险：显示“接近屠边”。
  - 其他情况显示“局势未到临界”。

## 5. Task 1: 增强 `liveGodView` 派生层

**Files:**
- Modify: `apps/web/src/features/games/liveGodView.ts`
- Modify: `apps/web/src/features/games/liveGodView.test.ts`

- [ ] **Step 1: 写 speakerFlow 红灯测试**

在 `liveGodView.test.ts` 增加：

```ts
it("derives previous current and next speakers from speech order", () => {
  const events = [
    event({
      type: "game_started",
      payload: {
        players: [
          { name: "Harold", role: "seer", model: "deepseek-chat" },
          { name: "Jackson", role: "villager", model: "deepseek-chat" },
          { name: "Bert", role: "werewolf", model: "deepseek-chat" },
          { name: "Isaac", role: "guard", model: "deepseek-chat" },
        ],
      },
    }),
    event({
      id: 2,
      type: "state_updated",
      round: 1,
      phase: "day",
      payload: {
        active_players: ["Harold", "Jackson", "Bert", "Isaac"],
        speech_order: ["Harold", "Jackson", "Bert", "Isaac"],
      },
    }),
    event({
      id: 3,
      type: "action_requested",
      round: 1,
      phase: "day",
      actor: "Isaac",
      action: "debate",
    }),
  ];
  const spectator = deriveLiveSpectatorState(events);

  const state = deriveGodViewState(events, spectator, "经典 8 人局");

  expect(state.speakerFlow.previous?.name).toBe("Bert");
  expect(state.speakerFlow.current?.name).toBe("Isaac");
  expect(state.speakerFlow.next?.name).toBe("Harold");
  expect(state.speakerFlow.modeLabel).toBe("顺序发言");
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveGodView.test.ts -t "derives previous current and next speakers"
```

Expected: FAIL，提示 `speakerFlow` 不存在。

- [ ] **Step 3: 实现 `speakerFlow`**

在 `GodViewState` 类型中加入字段，并在 `deriveGodViewState()` return 前计算：

```ts
const speechOrder =
  view.speechOrder.length > 0
    ? view.speechOrder
    : players.map((player) => player.name);
const currentSpeakerIndex = speechOrder.findIndex(
  (name) => name === view.activePlayerName,
);
const speakerFlow =
  currentSpeakerIndex >= 0 && players.length > 0
    ? {
        previous: playerByName(players, speechOrder.at(currentSpeakerIndex - 1) ?? speechOrder.at(-1)),
        current: playerByName(players, speechOrder[currentSpeakerIndex]),
        next: playerByName(players, speechOrder[(currentSpeakerIndex + 1) % speechOrder.length]),
        modeLabel: "顺序发言",
      }
    : {
        previous: null,
        current: null,
        next: null,
        modeLabel: "等待发言",
      };
```

同时增加 helper：

```ts
function playerByName(players: GodViewPlayer[], name: string | undefined) {
  return name ? players.find((player) => player.name === name) ?? null : null;
}
```

- [ ] **Step 4: 写 nightResolution 和 actionOrder 红灯测试**

增加两个断言：

```ts
expect(state.nightResolution).toMatchObject({
  label: "平安夜",
  detail: "Isaac 被狼人袭击，但被守卫守护。",
  tone: "safe",
});
expect(state.nightActionOrder.map((item) => item.label)).toEqual([
  "狼人目标",
  "守卫守护",
  "预言家查验",
]);
```

测试事件使用：

```ts
payload: {
  active_players: ["Harold", "Jackson", "Bert", "Isaac"],
  attacked: "Isaac",
  protected: "Isaac",
  investigated: "Jackson",
  eliminated: null,
}
```

- [ ] **Step 5: 实现 nightResolution 和 actionOrder**

在 `MutableGodView` 中保存 `latestNightPayload`：

```ts
latestNightPayload: Record<string, unknown> | null;
```

在 `collectStateUpdate()` 中，当 `event.phase === "night"` 或 payload 有 `attacked/protected/investigated/eliminated` 时更新。

新增 helpers：

```ts
function buildNightResolution(payload: Record<string, unknown> | null): GodViewState["nightResolution"] {
  if (!payload) {
    return { label: "等待夜间结算", detail: "暂无夜间结论", tone: "neutral" };
  }
  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  const eliminated = stringField(payload, "eliminated");
  if (attacked && protectedPlayer === attacked && !eliminated) {
    return {
      label: "平安夜",
      detail: `${attacked} 被狼人袭击，但被守卫守护。`,
      tone: "safe",
    };
  }
  if (eliminated) {
    return {
      label: "昨夜死亡",
      detail: `${eliminated} 夜晚出局。`,
      tone: "danger",
    };
  }
  return { label: "夜间结算", detail: "暂无死亡玩家。", tone: "neutral" };
}
```

构建 `nightActionOrder` 时按固定顺序读取当前已有 `nightActions`。

- [ ] **Step 6: 写 sheriffRuleState 和 winPressure 测试**

先把 `deriveGodViewState()` 第四个参数设计为可选 options：

```ts
deriveGodViewState(events, spectator, "经典 8 人局", {
  sheriffEnabled: false,
});
```

测试断言：

```ts
expect(state.sheriffRuleState).toEqual({
  enabled: false,
  label: "本局无警长规则",
});
expect(state.winPressure.label).toBe("局势未到临界");
```

- [ ] **Step 7: 实现 options 参数**

类型：

```ts
export type GodViewOptions = {
  sheriffEnabled?: boolean;
};
```

函数签名：

```ts
export function deriveGodViewState(
  events: LiveGameEvent[],
  spectator: LiveSpectatorState,
  boardName: string,
  options: GodViewOptions = {},
): GodViewState
```

实现：

```ts
const sheriffRuleState =
  options.sheriffEnabled === false
    ? { enabled: false, label: "本局无警长规则" }
    : { enabled: true, label: "警长规则开启" };
```

- [ ] **Step 8: 运行派生层测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveGodView.test.ts
```

Expected: PASS。

## 6. Task 2: 中央发言舞台升级为“大人物直播台”

**Files:**
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`
- Optional Create: `apps/web/src/features/games/components/GodViewSpeakerStage.tsx`

- [ ] **Step 1: 写页面红灯测试**

在 `LiveGamePage.test.tsx` 增加：

```ts
it("shows the current speaker as a large god-view stage portrait", async () => {
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
          { name: "Harold", role: "预言家", model: "deepseek-chat" },
          { name: "Jackson", role: "村民", model: "deepseek-chat" },
          { name: "Bert", role: "狼人", model: "deepseek-chat" },
          { name: "Isaac", role: "守卫", model: "deepseek-chat" },
        ],
      },
    });
    emitEvent(source, {
      id: 2,
      type: "state_updated",
      round: 1,
      phase: "day",
      payload: {
        active_players: ["Harold", "Jackson", "Bert", "Isaac"],
        speech_order: ["Harold", "Jackson", "Bert", "Isaac"],
      },
    });
    emitEvent(source, {
      id: 3,
      type: "action_requested",
      round: 1,
      phase: "day",
      actor: "Isaac",
      action: "debate",
    });
  });

  const stage = await screen.findByTestId("god-view-speaker-stage");
  expect(within(stage).getByText("4 号")).toBeInTheDocument();
  expect(within(stage).getByText("Isaac")).toBeInTheDocument();
  expect(within(stage).getByText("守卫")).toBeInTheDocument();
  expect(within(stage).getByText("上一位：Bert")).toBeInTheDocument();
  expect(within(stage).getByText("下一位：Harold")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "large god-view stage portrait"
```

Expected: FAIL，找不到 `god-view-speaker-stage`。

- [ ] **Step 3: 实现大人物舞台**

在 `LiveDirectorStage.tsx` 的中心事件卡上方或内部新增：

```tsx
{focusedGodPlayer ? (
  <div
    className="god-view-speaker-stage mx-auto mb-3 grid max-w-xl grid-cols-[6rem_minmax(0,1fr)] items-center gap-3 rounded-lg border border-amber-300/30 bg-black/40 p-3 shadow-[0_0_36px_rgba(251,191,36,0.16)]"
    data-testid="god-view-speaker-stage"
  >
    <div className={`relative flex aspect-[3/4] items-center justify-center overflow-hidden rounded-md border-2 ${speakerTone(focusedGodPlayer)}`}>
      {focusedGodPlayer.avatarImageUrl ? (
        <img
          alt={`${focusedGodPlayer.name} 当前发言形象`}
          className="h-full w-full object-cover"
          src={focusedGodPlayer.avatarImageUrl}
        />
      ) : (
        <span className="text-3xl font-black text-amber-50">
          {avatarText(focusedGodPlayer.name)}
        </span>
      )}
    </div>
    <div className="min-w-0 text-left">
      <p className="text-xs font-semibold text-amber-200">
        {focusedGodPlayer.seatNumber} 号
      </p>
      <p className="truncate text-xl font-semibold text-amber-50">
        {focusedGodPlayer.name}
      </p>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        <span className="rounded border border-amber-300/30 px-2 py-1 text-amber-100">
          {focusedGodPlayer.role}
        </span>
        <span className="rounded border border-sky-300/25 px-2 py-1 text-sky-100">
          {focusedGodPlayer.camp}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-300">
        <span>上一位：{godViewState?.speakerFlow.previous?.name ?? "-"}</span>
        <span>下一位：{godViewState?.speakerFlow.next?.name ?? "-"}</span>
      </div>
    </div>
  </div>
) : null}
```

增加 helper：

```ts
function speakerTone(player: GodViewPlayer) {
  if (player.camp === "狼人阵营") {
    return "border-red-400 bg-red-950/45 shadow-[0_0_30px_rgba(248,113,113,0.28)]";
  }
  if (player.identityGroup === "神职") {
    return "border-sky-200 bg-sky-950/35 shadow-[0_0_30px_rgba(125,211,252,0.22)]";
  }
  return "border-stone-300 bg-stone-950/35";
}
```

- [ ] **Step 4: 运行页面测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "large god-view stage portrait"
```

Expected: PASS。

## 7. Task 3: 顶部总控栏视觉加强

**Files:**
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Modify: `apps/web/src/styles/index.css`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写测试确认总控栏字段**

新增断言：

```ts
const strip = screen.getByTestId("god-view-stage-strip");
expect(within(strip).getByText("经典 8 人局")).toBeInTheDocument();
expect(within(strip).getByText("第 1 天")).toBeInTheDocument();
expect(within(strip).getByText("白天发言")).toBeInTheDocument();
expect(within(strip).getByText("发言席：4 号")).toBeInTheDocument();
expect(within(strip).getByText("存活 8/8")).toBeInTheDocument();
```

- [ ] **Step 2: 改成参考图式强状态栏**

把 `god-view-stage-strip` 从普通 grid 调整为：

- 顶部居中标题：`boardName`
- 左右分隔：阶段、发言席、倒计时、存活、胜负
- 使用更强的金色边框、内阴影和横向装饰线

CSS hook：

```css
.god-view-stage-strip {
  position: relative;
  overflow: hidden;
  border-color: rgb(185 147 92 / 45%);
  background:
    linear-gradient(180deg, rgb(9 14 18 / 78%), rgb(2 6 13 / 72%)),
    radial-gradient(circle at 50% 0%, rgb(239 190 111 / 12%), transparent 42%);
}

.god-view-stage-strip::before,
.god-view-stage-strip::after {
  position: absolute;
  top: 0.35rem;
  width: 2.8rem;
  height: 1px;
  content: "";
  background: linear-gradient(90deg, transparent, rgb(185 147 92 / 70%));
}
```

- [ ] **Step 3: 运行页面测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx
```

Expected: PASS。

## 8. Task 4: 死亡信息和平安夜结论

**Files:**
- Modify: `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写平安夜 UI 测试**

在已有页面测试中发送：

```ts
emitEvent(source, {
  id: 4,
  type: "state_updated",
  round: 1,
  phase: "night",
  payload: {
    active_players: ["Harold", "Jackson", "Bert", "Isaac"],
    attacked: "Isaac",
    protected: "Isaac",
    eliminated: null,
  },
});
```

断言：

```ts
expect(screen.getByText("平安夜")).toBeInTheDocument();
expect(screen.getByText("Isaac 被狼人袭击，但被守卫守护。")).toBeInTheDocument();
```

- [ ] **Step 2: 修改死亡信息区**

在 `GodViewIntelPanel` 的死亡信息区优先显示：

```tsx
{state.nightResolution.tone === "safe" ? (
  <div className="rounded-md border border-emerald-300/25 bg-emerald-950/25 px-3 py-2">
    <p className="text-sm font-semibold text-emerald-100">
      {state.nightResolution.label}
    </p>
    <p className="mt-1 text-xs text-emerald-100/80">
      {state.nightResolution.detail}
    </p>
  </div>
) : null}
```

如果 `deaths.length > 0`，则死亡玩家卡片继续显示，包含：

- 死亡玩家
- 死亡原因
- 死亡时间
- 公开状态
- `遗言资格：待规则结算` 或 `遗言资格：无记录`

- [ ] **Step 3: 运行页面测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "平安夜"
```

Expected: PASS。

## 9. Task 5: 夜间行动顺序与规则态警长模块

**Files:**
- Modify: `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 把规则态传给派生层**

在 `LiveGamePage.tsx` 中调整：

```ts
const godViewState = useMemo(
  () =>
    deriveGodViewState(
      events,
      spectatorState,
      run?.rule_set?.name ?? "实时对局",
      { sheriffEnabled: run?.rule_set?.sheriff_enabled },
    ),
  [events, run?.rule_set?.name, run?.rule_set?.sheriff_enabled, spectatorState],
);
```

- [ ] **Step 2: 夜间行动改为顺序链**

在 `GodViewIntelPanel` 的夜晚行动回顾中使用 `state.nightActionOrder`：

```tsx
{state.nightActionOrder.map((action) => (
  <div
    className="grid grid-cols-[1.5rem_5rem_minmax(0,1fr)] gap-2 rounded-md border border-slate-700/45 bg-black/25 px-2.5 py-1.5 text-xs"
    key={`${action.order}-${action.label}`}
  >
    <span className="text-amber-200">{action.order}</span>
    <span className={actionTone(action.tone)}>{action.label}</span>
    <span className="truncate text-slate-200">{action.value}</span>
  </div>
))}
```

- [ ] **Step 3: 警长模块显示无警长规则态**

当 `state.sheriffRuleState.enabled === false`：

```tsx
<p className="rounded-md border border-slate-600/45 bg-slate-950/55 px-3 py-2 text-xs text-slate-300">
  本局无警长规则
</p>
```

不要再显示“当前警长 未产生 / 警徽流向 未移交 / 警上玩家 暂无”等看似缺数据的行。

- [ ] **Step 4: 运行测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx -t "god-view"
```

Expected: PASS。

## 10. Task 6: 中文化回放点和票型空态骨架

**Files:**
- Modify: `apps/web/src/features/games/liveGodView.ts`
- Modify: `apps/web/src/features/games/components/GodViewBottomBoard.tsx`
- Modify: `apps/web/src/features/games/liveGodView.test.ts`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 写回放点中文化测试**

派生层测试：

```ts
expect(state.replayMarks.map((mark) => mark.text)).not.toContain("state_updated");
expect(state.replayMarks.map((mark) => mark.text)).toContain("平安夜");
```

对于普通 `state_updated`：

- 有 votes：`投票结果更新`
- 有 exiled：`放逐 <name>`
- 有 eliminated：`夜晚死亡 <name>`
- 有 protected/attacked 且无人死亡：`平安夜`
- 有 debate_entry：`<speaker> 发言`
- 都没有：`局势更新`

- [ ] **Step 2: 实现 `stateUpdatedReplayText()`**

在 `liveGodView.ts` 新增：

```ts
function stateUpdatedReplayText(payload: Record<string, unknown>) {
  const exiled = stringField(payload, "exiled");
  if (exiled) return `放逐 ${exiled}`;
  const eliminated = stringField(payload, "eliminated");
  if (eliminated) return `夜晚死亡 ${eliminated}`;
  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  if (attacked && protectedPlayer === attacked) return "平安夜";
  if (recordField(payload, "votes")) return "投票结果更新";
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    return `${debateEntry.speaker} 发言`;
  }
  return "局势更新";
}
```

在 `eventLineFor()` 和 replay mark fallback 中使用它。

- [ ] **Step 3: 票型空态保留强骨架**

在 `GodViewBottomBoard` 中，未投票时不要只显示“暂无投票”，改为：

- 票型矩阵继续列所有席位。
- 投票统计显示三条空候选槽：`候选 1 / 0 票`、`候选 2 / 0 票`、`候选 3 / 0 票`。
- 放逐候选排名显示“等待投票”卡片。

测试断言：

```ts
expect(screen.getByText("候选 1")).toBeInTheDocument();
expect(screen.getByText("等待投票")).toBeInTheDocument();
```

- [ ] **Step 4: 运行测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveGodView.test.ts src/pages/LiveGamePage.test.tsx
```

Expected: PASS。

## 11. Task 7: 阵营胜负压力提示

**Files:**
- Modify: `apps/web/src/features/games/liveGodView.ts`
- Modify: `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
- Modify: `apps/web/src/features/games/liveGodView.test.ts`

- [ ] **Step 1: 写 winPressure 测试**

```ts
it("marks win pressure when wolves are near parity", () => {
  const events = [
    event({
      type: "game_started",
      payload: {
        players: [
          { name: "Wolf A", role: "werewolf", model: "deepseek-chat" },
          { name: "Wolf B", role: "werewolf", model: "deepseek-chat" },
          { name: "Seer", role: "seer", model: "deepseek-chat" },
          { name: "Villager", role: "villager", model: "deepseek-chat" },
        ],
      },
    }),
    event({
      id: 2,
      type: "state_updated",
      payload: {
        active_players: ["Wolf A", "Wolf B", "Seer", "Villager"],
      },
    }),
  ];
  const spectator = deriveLiveSpectatorState(events);

  const state = deriveGodViewState(events, spectator, "压力测试");

  expect(state.winPressure.label).toBe("狼人压制");
  expect(state.winPressure.tone).toBe("danger");
});
```

- [ ] **Step 2: 实现 winPressure**

规则：

```ts
function buildWinPressure(progress: GodViewState["progress"]): GodViewState["winPressure"] {
  const goodAlive = progress.godsAlive + progress.villagersAlive;
  if (progress.wolvesAlive === 0) {
    return { label: "好人胜势", detail: "狼人已清零。", tone: "safe" };
  }
  if (progress.wolvesAlive >= goodAlive) {
    return { label: "狼人压制", detail: "狼人数量已达到或超过好人数量。", tone: "danger" };
  }
  if (progress.godsAlive === 0 || progress.villagersAlive === 0) {
    return { label: "接近屠边", detail: "神职或平民阵线已到临界。", tone: "warning" };
  }
  return { label: "局势未到临界", detail: "双方仍需通过发言和投票推进。", tone: "neutral" };
}
```

- [ ] **Step 3: 右侧阵营进度显示压力**

在 `GodViewIntelPanel` 的阵营进度末尾显示：

```tsx
<div className={`rounded-md border px-2.5 py-2 text-xs ${winPressureTone(state.winPressure.tone)}`}>
  <p className="font-semibold">{state.winPressure.label}</p>
  <p className="mt-1 opacity-80">{state.winPressure.detail}</p>
</div>
```

- [ ] **Step 4: 运行派生层测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveGodView.test.ts
```

Expected: PASS。

## 12. Task 8: 哥特直播台视觉增强

**Files:**
- Modify: `apps/web/src/styles/index.css`
- Modify: `apps/web/src/features/games/components/GodViewRosterPanel.tsx`
- Modify: `apps/web/src/features/games/components/GodViewIntelPanel.tsx`
- Modify: `apps/web/src/features/games/components/GodViewBottomBoard.tsx`
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`

- [ ] **Step 1: 增加统一边框角标类**

在 CSS 中新增：

```css
.god-view-frame {
  position: relative;
  border-color: rgb(185 147 92 / 42%);
  background:
    linear-gradient(180deg, rgb(9 14 18 / 78%), rgb(2 6 13 / 74%)),
    radial-gradient(circle at 50% 0%, rgb(239 190 111 / 9%), transparent 38%);
  box-shadow:
    inset 0 1px 0 rgb(255 230 184 / 10%),
    inset 0 0 30px rgb(0 0 0 / 42%),
    0 18px 48px rgb(0 0 0 / 28%);
}

.god-view-frame::before,
.god-view-frame::after {
  position: absolute;
  width: 0.55rem;
  height: 0.55rem;
  content: "";
  pointer-events: none;
}
```

应用到三块面板和中心舞台，不替换现有 `glass-panel`，只叠加。

- [ ] **Step 2: 控制信息密度**

在短横屏媒体查询中：

```css
@media (orientation: landscape) and (max-height: 620px) {
  .god-view-speaker-stage {
    grid-template-columns: 4.5rem minmax(0, 1fr);
    padding: 0.5rem;
  }

  .god-view-stage-strip {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .god-view-intel-panel {
    max-height: 12rem;
    overflow: auto;
  }
}
```

- [ ] **Step 3: 浏览器视觉 QA**

启动：

```bash
pnpm --dir apps/web dev -- --host 127.0.0.1 --port 5173
```

用 Browser 检查：

- `http://127.0.0.1:5173/games/live/run_cb995553d12a`
- 桌面 1280x720：无页面级横向溢出，中心舞台可见，右侧信息不压住底部。
- 短横屏：面板可以滚动，不互相覆盖。
- 移动宽度：大头像舞台先显示，底部板横向滚动。

记录指标：

```js
document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1
document.querySelector("[data-testid='god-view-speaker-stage']") !== null
document.body.textContent.includes("平安夜") || document.body.textContent.includes("昨夜死亡")
```

## 13. Task 9: 全量验证

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

- [ ] **Step 3: 运行构建**

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS。

- [ ] **Step 4: 手动/Browser QA**

检查当前真实 run：

```text
http://127.0.0.1:5173/games/live/run_cb995553d12a
```

验收点：

- 顶部总控栏一眼能读出局名、天夜、阶段、发言席、倒计时、存活、胜负模式。
- 中央有当前发言玩家大头像/大形象，显示席位、昵称、身份、阵营。
- 中央显示上一位、当前、下一位。
- 被守卫救下时显示“平安夜”，不再显示“暂无死亡信息”。
- 夜晚行动按顺序展示。
- 无警长局显示“本局无警长规则”。
- 回放点没有 `state_updated`。
- 未投票时底部票型区域仍有结构化骨架。
- 阵营进度显示胜负压力。

## 14. 验收标准

- 当前 `run_cb995553d12a` 与参考图相比，至少补齐：
  - 中央大人物舞台。
  - 上一位/当前/下一位发言顺序。
  - 平安夜或昨夜死亡结论。
  - 夜间行动顺序链。
  - 中文化回放点。
  - 无警长规则态。
  - 胜负压力提示。
- 不引入后端改动。
- 不破坏当前自动跟随、手动点选玩家、导播队列、调试事件抽屉。
- `pnpm --dir apps/web test -- --run` 通过。
- `pnpm --dir apps/web build` 通过。

## 15. 执行建议

建议按顺序做：

1. 先增强 `liveGodView.ts`，因为所有 UI 都依赖它。
2. 再做中央大人物舞台，这是视觉差距最大的部分。
3. 再修右侧死亡/夜间/警长/阵营模块。
4. 最后做底部票型和 CSS 视觉增强。

每个任务完成后单独跑聚焦测试。不要一次性改完整页，否则很难判断失败来自派生层、布局还是旧测试断言。

## 16. 自检

- 覆盖性：本文档覆盖了用户指出的参考图差距，包括中央人物、顶部状态、发言顺序、夜间结论、死亡信息、投票、警长、回放点、阵营进度和视觉风格。
- 约束性：文档明确不做后端协议变更、不做真实计时器、不引入新依赖。
- 可执行性：每个任务都有明确文件、测试命令、期望结果和实现方向。
