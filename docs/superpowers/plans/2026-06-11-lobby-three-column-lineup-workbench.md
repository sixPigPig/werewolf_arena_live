# 大厅页三栏组局台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `/games` 大厅改造成桌面三栏、平板双栏、手机单栏的组局工作台，同时保留现有规则、选人、校验和创建对局契约。

**Architecture:** `CreateGameRunForm` 继续持有规则、参数、玩家配置和提交状态；规则栏、组局工作区、规则详情抽屉和底部操作栏拆成独立展示组件。规则切换裁剪使用纯函数，席位选择继续由组局工作区管理，所有创建请求仍通过现有 `createGameRun` 流程发送。

**Tech Stack:** React 19、TypeScript 6、React Router、TanStack Query、Vitest、Testing Library、现有 Gothic UI 组件与 CSS。

---

## 文件结构

**新增文件**

- `apps/web/src/features/games/rulePresentation.ts`：规则名称、阵营、警长、胜利条件和复盘提示的纯格式化函数。
- `apps/web/src/features/games/rulePresentation.test.ts`：规则展示格式的单元测试。
- `apps/web/src/features/games/components/LobbyRuleSelector.tsx`：左栏规则列表。
- `apps/web/src/features/games/components/LobbyRuleSelector.test.tsx`：规则列表交互测试。
- `apps/web/src/features/games/components/RuleDetailsDrawer.tsx`：桌面右侧抽屉和手机底部规则面板。
- `apps/web/src/features/games/components/RuleDetailsDrawer.test.tsx`：抽屉内容、关闭和焦点恢复测试。
- `apps/web/src/features/games/components/LobbyLineupWorkbench.tsx`：中栏席位和右栏玩家库组合。
- `apps/web/src/features/games/components/LobbyActionBar.tsx`：参数、阵容快捷操作、清空确认和发起对局。
- `apps/web/src/features/games/components/LobbyActionBar.test.tsx`：底部操作栏与清空确认测试。

**修改文件**

- `apps/web/src/features/games/lineupUtils.ts`：增加规则人数变化时的席位裁剪函数。
- `apps/web/src/features/games/lineupUtils.test.ts`：覆盖扩容、缩容和移除席位报告。
- `apps/web/src/features/games/components/CreateGameRunForm.tsx`：组合新工作台组件并保持提交逻辑。
- `apps/web/src/features/games/components/SeatDetailPanel.tsx`：只保留当前席位级操作。
- `apps/web/src/features/games/components/SeatGrid.tsx`：补充稳定的席位区结构标识。
- `apps/web/src/features/games/components/ProfilePicker.tsx`：适配独立滚动的玩家库栏。
- `apps/web/src/features/games/components/LineupSummary.tsx`：压缩为中栏次级摘要。
- `apps/web/src/pages/GamesPage.test.tsx`：更新三栏结构、规则切换、抽屉和提交回归测试。
- `apps/web/src/styles/index.css`：实现桌面三栏、平板双栏、手机单栏及抽屉样式。

**删除文件**

- `apps/web/src/features/games/components/PlayerConfigPanel.tsx`：职责由 `LobbyLineupWorkbench.tsx` 接管。

---

### Task 1: 规则切换时裁剪无效席位

**Files:**
- Modify: `apps/web/src/features/games/lineupUtils.ts`
- Test: `apps/web/src/features/games/lineupUtils.test.ts`

- [ ] **Step 1: 写失败测试**

在 `lineupUtils.test.ts` 的 import 中加入 `resizeLineupForPlayerCount`，并在 `describe("lineupUtils")` 末尾加入：

```ts
it("keeps valid seats and reports configured seats removed by a smaller rule", () => {
  const result = resizeLineupForPlayerCount(
    [
      { seat: 1, profile_id: "profile-1" },
      { seat: 8, model: "Kimi" },
      { seat: 9, profile_id: "profile-2" },
      { seat: 12, appearance_id: "moonlit" },
    ],
    8,
  );

  expect(result).toEqual({
    configs: [
      { seat: 1, profile_id: "profile-1" },
      { seat: 8, model: "Kimi" },
    ],
    removedSeats: [9, 12],
  });
});

it("preserves every valid config when the rule grows", () => {
  expect(
    resizeLineupForPlayerCount(
      [
        { seat: 1, profile_id: "profile-1" },
        { seat: 6, profile_id: "profile-2" },
      ],
      12,
    ),
  ).toEqual({
    configs: [
      { seat: 1, profile_id: "profile-1" },
      { seat: 6, profile_id: "profile-2" },
    ],
    removedSeats: [],
  });
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/lineupUtils.test.ts
```

Expected: FAIL，提示 `resizeLineupForPlayerCount` 未导出。

- [ ] **Step 3: 添加最小实现**

在 `lineupUtils.ts` 中加入：

```ts
export type ResizedLineup = {
  configs: PlayerConfig[];
  removedSeats: number[];
};

export function resizeLineupForPlayerCount(
  configs: PlayerConfig[],
  playerCount: number,
): ResizedLineup {
  const configsInRange = configs.filter(
    (config) => config.seat >= 1 && config.seat <= playerCount,
  );
  const removedSeats = configs
    .filter(
      (config) =>
        (config.seat < 1 || config.seat > playerCount) && hasPlayerConfig(config),
    )
    .map((config) => config.seat)
    .sort((left, right) => left - right);

  return {
    configs: sortConfigs(configsInRange),
    removedSeats,
  };
}
```

- [ ] **Step 4: 运行单元测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/lineupUtils.test.ts
```

Expected: PASS，全部 `lineupUtils` 测试通过。

- [ ] **Step 5: 提交纯函数改动**

```bash
git add apps/web/src/features/games/lineupUtils.ts apps/web/src/features/games/lineupUtils.test.ts
git commit -m "feat(web): resize lobby lineup for rule changes"
```

---

### Task 2: 提取规则展示逻辑并建立左栏规则选择器

**Files:**
- Create: `apps/web/src/features/games/rulePresentation.ts`
- Create: `apps/web/src/features/games/rulePresentation.test.ts`
- Create: `apps/web/src/features/games/components/LobbyRuleSelector.tsx`
- Create: `apps/web/src/features/games/components/LobbyRuleSelector.test.tsx`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`

- [ ] **Step 1: 写规则展示与选择器失败测试**

创建 `rulePresentation.test.ts`：

```ts
import { describe, expect, it } from "vitest";

import type { RuleSetSummary } from "./types";
import {
  formatReplayHint,
  formatRoleSummary,
  formatSheriffRule,
  formatSpeechPolicy,
  formatWinCondition,
  getRuleEmblem,
} from "./rulePresentation";

const rule: RuleSetSummary = {
  id: "sheriff_12",
  version: "2026.04",
  name: "标准 12 人警长局",
  player_count: 12,
  roles: [{ role: "werewolf", count: 4 }],
  role_summary: "4 狼人 / 8 好人",
  sheriff_enabled: true,
  sheriff_vote_weight: 1.5,
  speech_policy: "sheriff_directed",
  win_condition: "slaughter_side",
};

describe("rulePresentation", () => {
  it("formats rule card and detail copy consistently", () => {
    expect(formatRoleSummary(rule)).toBe("4 狼人 / 8 好人");
    expect(getRuleEmblem(rule)).toBe("警");
    expect(formatSpeechPolicy(rule)).toContain("警长决定");
    expect(formatSheriffRule(rule)).toBe("有警长，警徽 1.5 票");
    expect(formatWinCondition(rule)).toContain("好人放逐所有狼人");
    expect(formatReplayHint(rule)).toContain("上警");
  });
});
```

创建 `LobbyRuleSelector.test.tsx`：

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RuleSetSummary } from "../types";
import { LobbyRuleSelector } from "./LobbyRuleSelector";

const rules: RuleSetSummary[] = [
  {
    id: "classic_8",
    version: "2026.04",
    name: "经典 8 人局",
    player_count: 8,
    roles: [],
    role_summary: "2 狼人 / 6 好人",
  },
  {
    id: "starter_6",
    version: "2026.04",
    name: "新手 6 人快局",
    player_count: 6,
    roles: [],
    role_summary: "2 狼人 / 4 好人",
  },
];

describe("LobbyRuleSelector", () => {
  it("renders a vertical rule radio group and reports the selected id", async () => {
    const onValueChange = vi.fn();
    render(
      <LobbyRuleSelector
        error={false}
        loading={false}
        onValueChange={onValueChange}
        rules={rules}
        value="classic_8"
      />,
    );

    expect(screen.getByTestId("lobby-rule-column")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("新手 6 人快局"));
    expect(onValueChange).toHaveBeenCalledWith("starter_6");
  });
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/rulePresentation.test.ts src/features/games/components/LobbyRuleSelector.test.tsx
```

Expected: FAIL，两个新模块均不存在。

- [ ] **Step 3: 添加规则格式化模块和选择器**

将 `CreateGameRunForm.tsx` 中的 `formatRoleSummary`、`getRuleEmblem`、`formatSpeechPolicy`、`formatSheriffRule`、`formatWinCondition`、`formatReplayHint` 原样移动到 `rulePresentation.ts` 并导出。

创建 `LobbyRuleSelector.tsx`，组件契约固定为：

```tsx
type LobbyRuleSelectorProps = {
  error: boolean;
  loading: boolean;
  onValueChange: (ruleId: string) => void;
  rules: RuleSetSummary[];
  value: string;
};

export function LobbyRuleSelector({
  error,
  loading,
  onValueChange,
  rules,
  value,
}: LobbyRuleSelectorProps) {
  return (
    <section
      aria-labelledby="lobby-rule-selector-title"
      className="lobby-workbench-column lobby-rule-column"
      data-testid="lobby-rule-column"
    >
      <h2 id="lobby-rule-selector-title">规则选择</h2>
      {loading ? <p className="lobby-rules-status">正在读取官方规则...</p> : null}
      {error ? <p className="lobby-rules-error">无法读取官方规则</p> : null}
      {rules.length > 0 ? (
        <RadioCards.Root
          aria-label="官方规则"
          className="lobby-rule-list"
          highContrast
          onValueChange={onValueChange}
          value={value}
          variant="surface"
        >
          {rules.map((rule) => (
            <RadioCards.Item
              aria-label={rule.name}
              className={[
                "lobby-rule-card",
                value === rule.id ? "lobby-rule-card-selected" : "",
              ].join(" ")}
              key={rule.id}
              value={rule.id}
            >
              <span aria-hidden="true" className="lobby-rule-emblem">
                {getRuleEmblem(rule)}
              </span>
              <span className="lobby-rule-copy">
                <strong className="lobby-rule-name">{rule.name}</strong>
                <span className="lobby-rule-meta">
                  {rule.player_count} 人 · {rule.complexity ?? "标准"}
                </span>
                <span className="lobby-rule-roles">{formatRoleSummary(rule)}</span>
              </span>
            </RadioCards.Item>
          ))}
        </RadioCards.Root>
      ) : null}
    </section>
  );
}
```

在 `CreateGameRunForm.tsx` 中删除内联 `renderRuleCard` 和六个格式化函数，改为 import 新模块。本任务保留现有纵向容器，工作台重排由后续任务完成。

- [ ] **Step 4: 运行新测试和现有大厅测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/rulePresentation.test.ts src/features/games/components/LobbyRuleSelector.test.tsx src/pages/GamesPage.test.tsx
```

Expected: PASS；现有规则文案和规则切换行为不回归。

- [ ] **Step 5: 提交规则栏拆分**

```bash
git add apps/web/src/features/games/rulePresentation.ts apps/web/src/features/games/rulePresentation.test.ts apps/web/src/features/games/components/LobbyRuleSelector.tsx apps/web/src/features/games/components/LobbyRuleSelector.test.tsx apps/web/src/features/games/components/CreateGameRunForm.tsx
git commit -m "refactor(web): extract lobby rule selector"
```

---

### Task 3: 将完整规则说明改为可访问抽屉

**Files:**
- Create: `apps/web/src/features/games/components/RuleDetailsDrawer.tsx`
- Create: `apps/web/src/features/games/components/RuleDetailsDrawer.test.tsx`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`

- [ ] **Step 1: 写抽屉失败测试**

创建 `RuleDetailsDrawer.test.tsx`：

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";

import type { RuleSetSummary } from "../types";
import { RuleDetailsDrawer } from "./RuleDetailsDrawer";

const rule: RuleSetSummary = {
  id: "classic_8",
  version: "2026.04",
  name: "经典 8 人局",
  description: "标准配置，适合完整推演。",
  player_count: 8,
  roles: [],
  role_summary: "2 狼人 / 6 好人",
  sheriff_enabled: false,
  speech_policy: "sequential",
  rule_tags: ["屠边"],
};

function Harness() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={triggerRef} onClick={() => setOpen(true)} type="button">
        规则详情
      </button>
      <RuleDetailsDrawer
        open={open}
        onClose={() => setOpen(false)}
        returnFocusRef={triggerRef}
        rule={rule}
      />
    </>
  );
}

describe("RuleDetailsDrawer", () => {
  it("shows complete rule details and restores focus after Escape", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "规则详情" });
    await userEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "经典 8 人局规则" });
    expect(within(dialog).getByText("阵营配置")).toBeInTheDocument();
    expect(within(dialog).getByText("无警长")).toBeInTheDocument();
    expect(within(dialog).getByText(/好人放逐所有狼人/)).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/RuleDetailsDrawer.test.tsx
```

Expected: FAIL，提示 `RuleDetailsDrawer` 不存在。

- [ ] **Step 3: 实现抽屉与焦点管理**

创建 `RuleDetailsDrawer.tsx`，实现以下固定行为：

```tsx
type RuleDetailsDrawerProps = {
  open: boolean;
  onClose: () => void;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  rule: RuleSetSummary;
};

export function RuleDetailsDrawer({
  open,
  onClose,
  returnFocusRef,
  rule,
}: RuleDetailsDrawerProps) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [onClose, open, returnFocusRef]);

  if (!open) return null;

  const rows = [
    { label: "阵营配置", value: formatRoleSummary(rule) },
    { label: "发言顺序", value: formatSpeechPolicy(rule) },
    { label: "警长规则", value: formatSheriffRule(rule) },
    { label: "胜利条件", value: formatWinCondition(rule) },
    { label: "复盘提示", value: formatReplayHint(rule) },
  ];

  return (
    <div
      className="lobby-rule-drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        aria-labelledby="lobby-rule-drawer-title"
        aria-modal="true"
        className="lobby-rule-drawer"
        ref={dialogRef}
        role="dialog"
      >
        <button
          aria-label="关闭规则详情"
          className="lobby-rule-drawer-close"
          onClick={onClose}
          ref={closeRef}
          type="button"
        >
          ×
        </button>
        <h2 id="lobby-rule-drawer-title">{rule.name}规则</h2>
        {rule.description ? <p>{rule.description}</p> : null}
        <dl>
          {rows.map((row) => (
            <div key={row.label}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
```

在 `CreateGameRunForm.tsx` 中增加 `isRuleDrawerOpen` 状态和 `ruleDetailsTriggerRef`，删除内联 `SelectedRuleDetails`，本任务在原规则详情位置渲染“规则详情”按钮和抽屉。

先在 `GamesPage.test.tsx` 顶部增加公共请求 helper：

```ts
function mockLobbyRequests(profilesResponse = fullPlayerProfilesResponse(8)) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/api/v1/games/rule-sets")) {
      return Promise.resolve(
        new Response(JSON.stringify(ruleSetsResponse()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.endsWith("/api/v1/player-profiles")) {
      return Promise.resolve(
        new Response(JSON.stringify(profilesResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
}
```

然后将旧常驻详情测试改为显式打开抽屉：

```tsx
it("opens complete details for the selected rule in a drawer", async () => {
  mockLobbyRequests(fullPlayerProfilesResponse(12));
  renderWithClient(<GamesPage />, "/games");

  expect(
    screen.queryByRole("dialog", { name: "经典 8 人局规则" }),
  ).not.toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: "规则详情" }));
  expect(screen.getByRole("dialog", { name: "经典 8 人局规则" })).toHaveTextContent(
    "2 狼人 / 4 村民 / 1 预言家 / 1 守卫",
  );

  await userEvent.click(screen.getByRole("button", { name: "关闭规则详情" }));
  await userEvent.click(screen.getByLabelText("标准 12 人警长局"));
  await userEvent.click(screen.getByRole("button", { name: "规则详情" }));
  expect(
    screen.getByRole("dialog", { name: "标准 12 人警长局规则" }),
  ).toHaveTextContent("有警长，警徽 1.5 票");
});
```

- [ ] **Step 4: 运行抽屉和大厅回归测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/RuleDetailsDrawer.test.tsx src/pages/GamesPage.test.tsx
```

Expected: PASS；规则说明不再默认常驻，打开后内容完整，关闭后焦点回到触发按钮。

- [ ] **Step 5: 提交规则抽屉**

```bash
git add apps/web/src/features/games/components/RuleDetailsDrawer.tsx apps/web/src/features/games/components/RuleDetailsDrawer.test.tsx apps/web/src/features/games/components/CreateGameRunForm.tsx
git commit -m "feat(web): add lobby rule details drawer"
```

---

### Task 4: 建立中栏席位与右栏玩家库工作区

**Files:**
- Create: `apps/web/src/features/games/components/LobbyLineupWorkbench.tsx`
- Delete: `apps/web/src/features/games/components/PlayerConfigPanel.tsx`
- Modify: `apps/web/src/features/games/components/SeatDetailPanel.tsx`
- Modify: `apps/web/src/features/games/components/SeatGrid.tsx`
- Modify: `apps/web/src/features/games/components/ProfilePicker.tsx`
- Modify: `apps/web/src/features/games/components/LineupSummary.tsx`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Test: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: 更新页面测试，锁定中栏与右栏结构**

在 `GamesPage.test.tsx` 的首个大厅渲染测试中，将旧 `席位模块` 结构断言替换为：

```tsx
const workbench = await screen.findByTestId("lobby-lineup-workbench");
expect(within(workbench).getByTestId("lobby-lineup-column")).toBeInTheDocument();
expect(within(workbench).getByTestId("lobby-player-column")).toBeInTheDocument();
expect(
  within(workbench).getByRole("heading", { name: "组建阵容" }),
).toBeInTheDocument();
expect(
  within(workbench).getByRole("heading", { name: "玩家卡牌库" }),
).toBeInTheDocument();
expect(
  within(workbench).getByRole("button", { name: "1号空席" }),
).toBeInTheDocument();
expect(within(workbench).getByText("当前席位 · 1 号")).toBeInTheDocument();
```

在“applies player cards immediately”测试中补充：

```tsx
await userEvent.click(screen.getByRole("button", { name: "2号空席" }));
expect(screen.getByText("当前席位 · 2 号")).toBeInTheDocument();
await userEvent.click(
  screen.getByRole("button", { name: "为 2 号座位选择 影刃" }),
);
expect(screen.getByRole("button", { name: "2号影刃" })).toBeInTheDocument();
```

- [ ] **Step 2: 运行页面测试并确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL，缺少 `lobby-lineup-workbench`、中栏和右栏结构。

- [ ] **Step 3: 创建工作区并收窄席位详情职责**

创建 `LobbyLineupWorkbench.tsx`，使用以下接口：

```tsx
type LobbyLineupWorkbenchProps = {
  configs: PlayerConfig[];
  isProfileListLoaded: boolean;
  onChange: (configs: PlayerConfig[]) => void;
  onOpenRuleDetails: () => void;
  playerCount: number;
  profiles: VirtualPlayerProfile[];
  rule: RuleSetSummary;
  ruleDetailsTriggerRef: RefObject<HTMLButtonElement | null>;
};
```

组件内部保留当前 `PlayerConfigPanel` 的 `selectedSeat`、`updateSeatConfig` 和 `updateSeatModel` 逻辑，并增加人数收缩后的席位回退：

```tsx
const [selectedSeat, setSelectedSeat] = useState(1);
const activeSeat = Math.min(selectedSeat, playerCount);
const playerColumnRef = useRef<HTMLDivElement>(null);

useEffect(() => {
  if (selectedSeat > playerCount) setSelectedSeat(playerCount);
}, [playerCount, selectedSeat]);

const selectSeat = (seat: number) => {
  setSelectedSeat(seat);
  if (window.innerWidth <= 720) {
    playerColumnRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }
};
```

返回结构固定为两个兄弟栏：

```tsx
<section
  className="lobby-lineup-workbench"
  data-testid="lobby-lineup-workbench"
>
  <div className="lobby-workbench-column lobby-lineup-column" data-testid="lobby-lineup-column">
    <header className="lobby-column-header">
      <div>
        <h2>组建阵容</h2>
        <span>{rule.name} · 已选阵容</span>
      </div>
      <button
        onClick={onOpenRuleDetails}
        ref={ruleDetailsTriggerRef}
        type="button"
      >
        规则详情
      </button>
    </header>
    <p className="lobby-rule-summary">{formatRoleSummary(rule)}</p>
    <LineupSummary configs={configs} playerCount={playerCount} profiles={profiles} />
    <SeatGrid
      configs={configs}
      onSelectSeat={selectSeat}
      playerCount={playerCount}
      profiles={profiles}
      selectedSeat={activeSeat}
    />
  </div>
  <div
    className="lobby-workbench-column lobby-player-column"
    data-testid="lobby-player-column"
    ref={playerColumnRef}
  >
    <div className="lobby-column-header">
      <div>
        <h2>玩家卡牌库</h2>
        <span>当前席位 · {activeSeat} 号</span>
      </div>
    </div>
    <ProfilePicker
      configs={configs}
      isProfileListLoaded={isProfileListLoaded}
      onSelectProfile={(profileId) =>
        onChange(applyProfileToSeat(configs, activeSeat, profileId))
      }
      profiles={profiles}
      selectedSeat={activeSeat}
    />
    <SeatDetailPanel
      onClearSeat={() => onChange(clearSeat(configs, activeSeat))}
      onModelChange={updateSeatModel}
      selectedConfig={selectedConfig}
      selectedProfile={selectedProfile}
      selectedSeat={activeSeat}
    />
  </div>
</section>
```

从 `SeatDetailPanel` 删除 `onClearAllSeats`、`onFillFavorites`、`onRandomFill` props 及对应按钮，只保留清空当前座位和模型覆盖。给 `SeatGrid` 根节点增加 `data-testid="lobby-seat-grid"`，给 `ProfilePicker` 卡片容器增加 `data-testid="lobby-player-card-grid"`。

在 `CreateGameRunForm.tsx` 中用 `LobbyLineupWorkbench` 替换 `PlayerConfigPanel`，随后删除旧文件。

- [ ] **Step 4: 运行页面测试与类型构建**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
pnpm --dir apps/web build
```

Expected: 两条命令均 PASS；选中席位、即时选人、重复玩家禁用和模型覆盖行为保持不变。

- [ ] **Step 5: 提交组局工作区**

```bash
git add apps/web/src/features/games/components/LobbyLineupWorkbench.tsx apps/web/src/features/games/components/SeatDetailPanel.tsx apps/web/src/features/games/components/SeatGrid.tsx apps/web/src/features/games/components/ProfilePicker.tsx apps/web/src/features/games/components/LineupSummary.tsx apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/pages/GamesPage.test.tsx
git rm apps/web/src/features/games/components/PlayerConfigPanel.tsx
git commit -m "refactor(web): split lobby lineup and player columns"
```

---

### Task 5: 将参数和全局阵容操作集中到底部操作栏

**Files:**
- Create: `apps/web/src/features/games/components/LobbyActionBar.tsx`
- Create: `apps/web/src/features/games/components/LobbyActionBar.test.tsx`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`

- [ ] **Step 1: 写操作栏失败测试**

创建 `LobbyActionBar.test.tsx`：

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LobbyActionBar } from "./LobbyActionBar";

describe("LobbyActionBar", () => {
  it("groups parameters and global lineup actions and confirms clearing", async () => {
    const onClearAll = vi.fn();
    render(
      <LobbyActionBar
        disabled={false}
        loading={false}
        maxRounds="8"
        onClearAll={onClearAll}
        onFillFavorites={vi.fn()}
        onMaxRoundsChange={vi.fn()}
        onRandomFill={vi.fn()}
        onSeedChange={vi.fn()}
        seed="884512"
      />,
    );

    const bar = screen.getByTestId("lobby-action-bar");
    expect(within(bar).getByLabelText("随机种子")).toHaveValue("884512");
    expect(within(bar).getByLabelText("最大轮数")).toHaveValue(8);
    expect(within(bar).getByRole("button", { name: "发起对局" })).toBeInTheDocument();

    await userEvent.click(within(bar).getByRole("button", { name: "清空阵容" }));
    const dialog = screen.getByRole("alertdialog", { name: "确认清空阵容" });
    await userEvent.click(within(dialog).getByRole("button", { name: "确认清空" }));
    expect(onClearAll).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/LobbyActionBar.test.tsx
```

Expected: FAIL，提示 `LobbyActionBar` 不存在。

- [ ] **Step 3: 实现操作栏和清空确认**

创建 `LobbyActionBar.tsx`，props 固定为：

```tsx
type LobbyActionBarProps = {
  disabled: boolean;
  loading: boolean;
  maxRounds: string;
  onClearAll: () => void;
  onFillFavorites: () => void;
  onMaxRoundsChange: (value: string) => void;
  onRandomFill: () => void;
  onSeedChange: (value: string) => void;
  seed: string;
};
```

组件使用本地 `confirmingClear` 状态，返回：

```tsx
<footer className="lobby-action-bar" data-testid="lobby-action-bar">
  <div className="lobby-action-parameters">
    <label>
      <span>随机种子</span>
      <TextField.Root
        aria-label="随机种子"
        inputMode="numeric"
        placeholder="可留空"
        value={seed}
        onChange={(event) => onSeedChange(event.target.value)}
      />
    </label>
    <label>
      <span>最大轮数</span>
      <TextField.Root
        aria-label="最大轮数"
        max={20}
        min={1}
        required
        type="number"
        value={maxRounds}
        onChange={(event) => onMaxRoundsChange(event.target.value)}
      />
    </label>
  </div>
  <div className="lobby-action-buttons">
    <Button onClick={onRandomFill} skin="gothic" type="button">随机填充空席</Button>
    <Button onClick={onFillFavorites} skin="gothic" type="button">只用收藏填充</Button>
    <Button onClick={() => setConfirmingClear(true)} skin="gothic" type="button">清空阵容</Button>
    <Button
      className="lobby-action-launch"
      disabled={disabled}
      intent="warning"
      loading={loading}
      skin="gothic"
      type="submit"
    >
      发起对局
    </Button>
  </div>
  {confirmingClear ? (
    <div className="lobby-clear-dialog-backdrop">
      <section aria-labelledby="lobby-clear-dialog-title" aria-modal="true" role="alertdialog">
        <h2 id="lobby-clear-dialog-title">确认清空阵容</h2>
        <p>全部席位玩家与临时模型覆盖都会被移除。</p>
        <Button onClick={() => setConfirmingClear(false)} type="button">取消</Button>
        <Button
          intent="warning"
          onClick={() => {
            onClearAll();
            setConfirmingClear(false);
          }}
          type="button"
        >
          确认清空
        </Button>
      </section>
    </div>
  ) : null}
</footer>
```

在 `CreateGameRunForm.tsx` 中删除顶部参数控制条，把 `LobbyActionBar` 放到工作台之后，并接入：

```tsx
onRandomFill={() =>
  selectedRuleSet &&
  setPlayerConfigs(
    randomFillEmptySeats(visiblePlayerConfigs, profiles, selectedRuleSet.player_count),
  )
}
onFillFavorites={() =>
  selectedRuleSet &&
  setPlayerConfigs(
    randomFillEmptySeats(visiblePlayerConfigs, profiles, selectedRuleSet.player_count, {
      favoritesOnly: true,
    }),
  )
}
onClearAll={() => setPlayerConfigs(clearAllSeats())}
```

- [ ] **Step 4: 运行操作栏与大厅测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/LobbyActionBar.test.tsx src/pages/GamesPage.test.tsx
```

Expected: PASS；参数校验、随机填充、收藏填充和发起对局仍通过原页面测试。

- [ ] **Step 5: 提交底部操作栏**

```bash
git add apps/web/src/features/games/components/LobbyActionBar.tsx apps/web/src/features/games/components/LobbyActionBar.test.tsx apps/web/src/features/games/components/CreateGameRunForm.tsx
git commit -m "feat(web): add lobby action bar"
```

---

### Task 6: 组合三栏框架并完成规则切换裁剪提示

**Files:**
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: 写三栏与裁剪提示失败测试**

在 `GamesPage.test.tsx` 新增：

```tsx
it("renders the rule, lineup, and player columns inside one lobby workbench", async () => {
  mockLobbyRequests(fullPlayerProfilesResponse(12));
  renderWithClient(<GamesPage />, "/games");

  const frame = await screen.findByTestId("lobby-workbench-frame");
  expect(within(frame).getByTestId("lobby-rule-column")).toBeInTheDocument();
  expect(within(frame).getByTestId("lobby-lineup-column")).toBeInTheDocument();
  expect(within(frame).getByTestId("lobby-player-column")).toBeInTheDocument();
  expect(screen.getByTestId("lobby-action-bar")).toBeInTheDocument();
});

it("removes configured seats outside a smaller rule and reports the removed seats", async () => {
  mockLobbyRequests(fullPlayerProfilesResponse(12));
  renderWithClient(<GamesPage />, "/games");

  await userEvent.click(await screen.findByLabelText("标准 12 人警长局"));
  await userEvent.click(screen.getByRole("button", { name: "9号空席" }));
  await userEvent.click(
    screen.getByRole("button", { name: "为 9 号座位选择 随机玩家9" }),
  );
  await userEvent.click(screen.getByLabelText("经典 8 人局"));

  expect(screen.queryByRole("button", { name: "9号随机玩家9" })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("已移除 9 号位的 1 名玩家");
});
```

复用 Task 3 已加入的 `mockLobbyRequests`，不要再为这两个测试复制 fetch mock。

- [ ] **Step 2: 运行页面测试并确认失败**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL，缺少三栏 frame 或规则切换后裁剪提示。

- [ ] **Step 3: 在创建表单中完成最终组合**

在 `CreateGameRunForm.tsx` 增加：

```tsx
const [lineupResizeNotice, setLineupResizeNotice] = useState<string | null>(null);
const [isRuleDrawerOpen, setIsRuleDrawerOpen] = useState(false);
const ruleDetailsTriggerRef = useRef<HTMLButtonElement>(null);
const closeRuleDetails = useCallback(() => setIsRuleDrawerOpen(false), []);

const handleRuleSetChange = (ruleId: string) => {
  const nextRule = ruleSets.find((rule) => rule.id === ruleId);
  setSelectedRuleSetId(ruleId);
  setIsRuleDrawerOpen(false);
  if (!nextRule) return;

  const resized = resizeLineupForPlayerCount(
    visiblePlayerConfigs,
    nextRule.player_count,
  );
  setPlayerConfigs(resized.configs);
  setLineupResizeNotice(
    resized.removedSeats.length > 0
      ? `已移除 ${formatSeatRange(resized.removedSeats)} 的 ${resized.removedSeats.length} 名玩家`
      : null,
  );
};
```

同步将 React import 改为包含 `useCallback`、`useRef` 和 `useState`，并删除已经迁移到子组件、不再由本文件使用的 `Badge`、`Container`、`Flex`、`RadioCards`、`Text`、`TextField` import。

增加同文件私有 helper：

```ts
function formatSeatRange(seats: number[]) {
  if (seats.length === 1) return `${seats[0]} 号位`;
  const consecutive = seats.every(
    (seat, index) => index === 0 || seat === seats[index - 1] + 1,
  );
  return consecutive
    ? `${seats[0]}-${seats[seats.length - 1]} 号位`
    : `${seats.join("、")} 号位`;
}
```

保留现有 `<form>` 的 `onSubmit` 实现，在表单内部将旧控制条和规则容器替换为：

```tsx
<header className="lobby-workbench-heading">
  <h1>狼人杀对局大厅</h1>
  {lineupResizeNotice ? <p role="status">{lineupResizeNotice}</p> : null}
</header>
<div className="lobby-workbench-frame" data-testid="lobby-workbench-frame">
  <LobbyRuleSelector
    error={ruleSetsQuery.isError}
    loading={ruleSetsQuery.isPending}
    onValueChange={handleRuleSetChange}
    rules={ruleSets}
    value={selectedRuleSetId}
  />
  {selectedRuleSet ? (
    <LobbyLineupWorkbench
      configs={visiblePlayerConfigs}
      isProfileListLoaded={isProfileListLoaded}
      onChange={setPlayerConfigs}
      onOpenRuleDetails={() => setIsRuleDrawerOpen(true)}
      playerCount={selectedRuleSet.player_count}
      profiles={profiles}
      rule={selectedRuleSet}
      ruleDetailsTriggerRef={ruleDetailsTriggerRef}
    />
  ) : null}
</div>
<LobbyActionBar
  disabled={isSubmitDisabled}
  loading={mutation.isPending}
  maxRounds={maxRounds}
  onClearAll={() => setPlayerConfigs(clearAllSeats())}
  onFillFavorites={() => {
    if (!selectedRuleSet) return;
    setPlayerConfigs(
      randomFillEmptySeats(
        visiblePlayerConfigs,
        profiles,
        selectedRuleSet.player_count,
        { favoritesOnly: true },
      ),
    );
  }}
  onMaxRoundsChange={(value) => {
    setMaxRounds(value);
    setValidationError(null);
  }}
  onRandomFill={() => {
    if (!selectedRuleSet) return;
    setPlayerConfigs(
      randomFillEmptySeats(
        visiblePlayerConfigs,
        profiles,
        selectedRuleSet.player_count,
      ),
    );
  }}
  onSeedChange={setSeed}
  seed={seed}
/>
{selectedRuleSet ? (
  <RuleDetailsDrawer
    onClose={closeRuleDetails}
    open={isRuleDrawerOpen}
    returnFocusRef={ruleDetailsTriggerRef}
    rule={selectedRuleSet}
  />
) : null}
```

将现有 validation callout、mutation callout 和 `PlayerLibraryShortageDialog` 保持在上述结构之后。保留当前 submit handler 的最大轮数校验、随机补齐、玩家不足检查、mutation 和导航，不改变请求字段。

- [ ] **Step 4: 运行大厅测试**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
```

Expected: PASS；三栏、裁剪提示、抽屉、提交 payload 和导航全部通过。

- [ ] **Step 5: 提交最终组件组合**

```bash
git add apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat(web): compose three-column lobby workbench"
```

---

### Task 7: 实现桌面、平板和手机响应式视觉

**Files:**
- Modify: `apps/web/src/styles/index.css`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: 添加稳定样式契约断言**

在首个大厅渲染测试中加入：

```tsx
expect(screen.getByTestId("lobby-workbench-frame")).toHaveClass(
  "lobby-workbench-frame",
);
expect(screen.getByTestId("lobby-rule-column")).toHaveClass(
  "lobby-workbench-column",
  "lobby-rule-column",
);
expect(screen.getByTestId("lobby-lineup-column")).toHaveClass(
  "lobby-workbench-column",
  "lobby-lineup-column",
);
expect(screen.getByTestId("lobby-player-column")).toHaveClass(
  "lobby-workbench-column",
  "lobby-player-column",
);
expect(screen.getByTestId("lobby-action-bar")).toHaveClass("lobby-action-bar");
```

- [ ] **Step 2: 运行结构测试建立样式改造基线**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
```

Expected: PASS。该测试只锁定 DOM 样式契约；实际断点和溢出行为在 Task 8 用浏览器验证。

- [ ] **Step 3: 替换大厅 CSS 为三栏布局**

在 `index.css` 中删除不再使用的 `.lobby-console-bar`、`.lobby-rule-grid`、`.lobby-rule-details` 和旧 `player-config-panel` 外层布局规则，保留可复用的卡片、字段和肖像样式。新增核心布局：

```css
.lobby-console-form {
  display: grid;
  width: min(100%, 118rem);
  height: calc(100dvh - var(--arena-nav-height, 56px) - 2rem);
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 0.65rem;
  margin: 0 auto;
}

.lobby-workbench-frame {
  display: grid;
  min-height: 0;
  grid-template-columns: minmax(15rem, 24fr) minmax(0, 76fr);
  gap: 0.65rem;
}

.lobby-lineup-workbench {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-columns: minmax(0, 48fr) minmax(18rem, 28fr);
  gap: 0.65rem;
}

.lobby-workbench-column,
.lobby-action-bar {
  border: 1px solid rgb(185 147 92 / 44%);
  border-radius: 0.3rem;
  background: linear-gradient(180deg, rgb(6 11 15 / 92%), rgb(1 5 10 / 86%));
  box-shadow: inset 0 1px 0 rgb(255 230 184 / 10%), 0 14px 34px rgb(0 0 0 / 26%);
}

.lobby-rule-column,
.lobby-lineup-column,
.lobby-player-column {
  min-height: 0;
  padding: 0.75rem;
}

.lobby-rule-column,
.lobby-player-column {
  display: flex;
  overflow: hidden;
  flex-direction: column;
}

.lobby-lineup-column {
  overflow-y: auto;
}

.lobby-rule-list,
.lobby-player-column .player-config-role-cards {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.lobby-rule-list {
  display: grid;
  flex: 1;
  grid-template-columns: 1fr;
  gap: 0.55rem;
}

.lobby-player-column .profile-picker {
  min-height: 0;
  flex: 1;
  grid-template-rows: auto auto minmax(0, 1fr);
}

.lobby-action-bar {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.65rem 0.75rem;
}

.lobby-rule-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  justify-content: flex-end;
  background: rgb(0 0 0 / 62%);
}

.lobby-rule-drawer {
  width: min(31rem, 92vw);
  height: 100%;
  overflow-y: auto;
  border-left: 1px solid rgb(232 201 130 / 42%);
  background: linear-gradient(180deg, #091017, #02070c);
  padding: 1rem;
}
```

加入明确断点：

```css
@media (max-width: 1180px) {
  .lobby-workbench-frame {
    grid-template-columns: minmax(14rem, 34fr) minmax(0, 66fr);
  }

  .lobby-lineup-workbench {
    grid-template-columns: 1fr;
  }

  .lobby-action-bar {
    align-items: stretch;
    flex-direction: column;
  }

  .player-config-seat-module {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 899px) and (min-width: 721px) {
  .player-config-seat-module {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .lobby-console-form {
    height: auto;
    min-height: auto;
    grid-template-rows: auto;
  }

  .lobby-workbench-frame,
  .lobby-lineup-workbench {
    grid-template-columns: 1fr;
  }

  .lobby-rule-list {
    display: flex;
    overflow-x: auto;
    overflow-y: hidden;
  }

  .lobby-rule-card {
    min-width: 15rem;
  }

  .player-config-seat-module,
  .player-config-role-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .lobby-rule-drawer-backdrop {
    align-items: flex-end;
  }

  .lobby-rule-drawer {
    width: 100%;
    height: min(80dvh, 42rem);
    border-top: 1px solid rgb(232 201 130 / 42%);
    border-left: 0;
  }
}

@media (max-width: 360px) {
  .player-config-role-cards {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 4: 运行测试、lint 和构建**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: 三条命令均 PASS。

- [ ] **Step 5: 提交响应式样式**

```bash
git add apps/web/src/styles/index.css apps/web/src/pages/GamesPage.test.tsx
git commit -m "style(web): add responsive lobby workbench layout"
```

---

### Task 8: 完整回归与浏览器视觉验收

**Files:**
- Modify only if verification exposes a defect: lobby files listed above

- [ ] **Step 1: 运行大厅相关测试集合**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/lineupUtils.test.ts src/features/games/rulePresentation.test.ts src/features/games/components/LobbyRuleSelector.test.tsx src/features/games/components/RuleDetailsDrawer.test.tsx src/features/games/components/LobbyActionBar.test.tsx src/pages/GamesPage.test.tsx
```

Expected: PASS，0 个失败测试。

- [ ] **Step 2: 运行完整 Web 验证**

Run:

```bash
pnpm --dir apps/web test -- --run
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Expected: 全部 PASS；构建产物正常生成。

- [ ] **Step 3: 启动开发服务器**

Run:

```bash
pnpm --dir apps/web dev --host 127.0.0.1
```

Expected: Vite 输出本地 URL。保持进程运行直到视觉验证结束。

- [ ] **Step 4: 使用 in-app Browser 完成三个视口验收**

按顺序验证：

1. `1440 × 900`：规则、中间席位、玩家库和底部发起按钮同屏；12 人规则为四列三行；规则栏和玩家列表可独立滚动。
2. `1024 × 768`：左规则、右工作区双栏；席位区后接玩家区；操作栏分行但不横向溢出。
3. `390 × 844`：规则横向滚动、席位两列、玩家筛选纵向排列、规则详情从底部打开、完整流程可操作。

每个视口都执行：切换规则、选择席位、选择玩家、打开和关闭规则详情、随机填充、清空确认、修改最大轮数。不要在视觉验收中真正提交创建对局，提交行为已由测试覆盖。

Expected: 无页面级桌面滚动、无横向溢出、无抽屉焦点丢失、无被底部栏遮挡的控件。

- [ ] **Step 5: 检查最终 diff 并提交验证修复**

Run:

```bash
git diff --check
git status --short
```

如果视觉验收产生修复，重新运行 Step 1 和 Step 2 后提交：

```bash
git add apps/web/src/features/games apps/web/src/pages/GamesPage.test.tsx apps/web/src/styles/index.css
git commit -m "fix(web): polish lobby workbench verification issues"
```

如果没有修复，不创建空提交。

---

## 最终完成条件

- 设计文档中的三栏、规则抽屉、底部操作栏、规则切换裁剪、响应式和错误状态均有对应实现任务。
- 新增组件均有聚焦测试，创建请求和页面主流程由 `GamesPage.test.tsx` 覆盖。
- 完整 Web 测试、lint 和 build 通过。
- 1440px、1024px、390px 三个视口完成浏览器视觉验收。
- 后端 API、数据库、路由和直播页没有改动。
