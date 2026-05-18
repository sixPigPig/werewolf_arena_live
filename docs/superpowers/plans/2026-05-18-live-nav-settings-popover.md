# 实时导航设置弹窗 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将实时观战页导航栏重排为“对局 ID + 观战状态 + 可选复盘入口 + 设置按钮”，并把规则、播放控制、继续对局和返回大厅收进设置弹窗。

**Architecture:** 新增两个小组件：`LiveNavSessionBadge` 只负责导航栏对局 ID；`LiveNavSettingsMenu` 只负责设置按钮、弹窗、规则信息与操作区。`LiveGamePage` 继续持有 `run`、`terminalEvent`、`director` 和 `resumeMutation`，只把所需状态和回调传入新组件；底层连接、导播、舞台、时间线逻辑不改。

**Tech Stack:** React 19, TypeScript, React Router, Vitest, Testing Library, Tailwind utility classes, existing `Button` / `Badge` / `SelectField` UI primitives.

---

## File Structure

- Create `apps/web/src/features/games/components/LiveNavSessionBadge.tsx`：渲染导航栏中的对局 ID。
- Create `apps/web/src/features/games/components/LiveNavSessionBadge.test.tsx`：验证对局 ID 文案、等宽与截断类名。
- Create `apps/web/src/features/games/components/LiveNavSettingsMenu.tsx`：渲染最右侧设置按钮与弹窗内容。
- Create `apps/web/src/features/games/components/LiveNavSettingsMenu.test.tsx`：验证弹窗打开、规则信息、播放控制、继续对局互斥、返回大厅。
- Modify `apps/web/src/pages/LiveGamePage.tsx`：重排导航 context/action slots，移除导航栏中部播放控制，把设置弹窗放到最右。
- Modify `apps/web/src/pages/LiveGamePage.test.tsx`：更新导航栏结构、弹窗交互、失败继续对局和终局复盘入口断言。
- Leave unchanged `apps/web/src/features/games/hooks/useGameRunEvents.ts`、`apps/web/src/features/games/hooks/useLiveDirector.ts`、`apps/web/src/features/games/liveNavStatus.ts`、舞台和玩家状态组件。

### Task 1: 对局 ID 导航徽标

**Files:**
- Create: `apps/web/src/features/games/components/LiveNavSessionBadge.tsx`
- Create: `apps/web/src/features/games/components/LiveNavSessionBadge.test.tsx`

- [ ] **Step 1: 写失败测试**

Create `apps/web/src/features/games/components/LiveNavSessionBadge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveNavSessionBadge } from "./LiveNavSessionBadge";

describe("LiveNavSessionBadge", () => {
  it("renders the game session id as the first-class nav context", () => {
    render(<LiveNavSessionBadge sessionId="game_1200abcd" />);

    const badge = screen.getByTestId("live-nav-session");

    expect(badge).toHaveTextContent("对局");
    expect(badge).toHaveTextContent("game_1200abcd");
    expect(screen.getByText("game_1200abcd")).toHaveClass(
      "font-mono",
      "truncate",
    );
    expect(screen.getByText("game_1200abcd")).toHaveAttribute(
      "title",
      "game_1200abcd",
    );
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/components/LiveNavSessionBadge.test.tsx
```

Expected: FAIL，原因是 `LiveNavSessionBadge.tsx` 尚不存在。

- [ ] **Step 3: 实现对局 ID 组件**

Create `apps/web/src/features/games/components/LiveNavSessionBadge.tsx`:

```tsx
type LiveNavSessionBadgeProps = {
  sessionId: string;
};

export function LiveNavSessionBadge({ sessionId }: LiveNavSessionBadgeProps) {
  return (
    <div
      className="live-nav-session flex min-w-0 shrink-0 items-center gap-x-2 text-xs font-semibold text-slate-300"
      data-testid="live-nav-session"
    >
      <span className="shrink-0 text-slate-500">对局</span>
      <span
        className="max-w-[14rem] truncate font-mono tracking-wide text-slate-100"
        title={sessionId}
      >
        {sessionId}
      </span>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/components/LiveNavSessionBadge.test.tsx
```

Expected: PASS。

### Task 2: 设置弹窗组件

**Files:**
- Create: `apps/web/src/features/games/components/LiveNavSettingsMenu.tsx`
- Create: `apps/web/src/features/games/components/LiveNavSettingsMenu.test.tsx`

- [ ] **Step 1: 写设置弹窗失败测试**

Create `apps/web/src/features/games/components/LiveNavSettingsMenu.test.tsx`:

```tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { LiveNavStatus } from "../liveNavStatus";
import type { GameRun } from "../types";
import { LiveNavSettingsMenu } from "./LiveNavSettingsMenu";

const liveStatus: LiveNavStatus = {
  detailItems: ["1x"],
  kind: "live",
  label: "直播中",
  tone: "good",
};

const run: GameRun = {
  completed_at: null,
  created_at: "2026-04-24T12:00:00Z",
  error: null,
  event_count: 1,
  max_rounds: 8,
  rule_set: {
    id: "beginner_6",
    name: "新手 6 人快局",
    player_count: 6,
    role_summary: "1 狼人 / 1 预言家 / 1 医生 / 3 村民",
    roles: [
      { count: 1, role: "狼人" },
      { count: 1, role: "预言家" },
      { count: 1, role: "医生" },
      { count: 3, role: "村民" },
    ],
    rule_tags: ["新手"],
    version: "2026.04",
  },
  run_id: "run_1234abcd",
  seed: null,
  session_id: "game_1200abcd",
  started_at: "2026-04-24T12:00:01Z",
  status: "running",
  villager_model: "deepseek-chat",
  werewolf_model: "deepseek-chat",
  winner: null,
};

function renderMenu(overrides: Partial<Parameters<typeof LiveNavSettingsMenu>[0]> = {}) {
  const props = {
    backlogCount: 3,
    canResumeRun: false,
    isPaused: false,
    isResuming: false,
    onCatchUpToLatest: vi.fn(),
    onResumeRun: vi.fn(),
    onSpeedChange: vi.fn(),
    onTogglePaused: vi.fn(),
    run,
    speed: 1 as const,
    status: liveStatus,
    ...overrides,
  };

  render(
    <MemoryRouter>
      <LiveNavSettingsMenu {...props} />
    </MemoryRouter>,
  );

  return props;
}

describe("LiveNavSettingsMenu", () => {
  it("opens a settings dialog with rule info, playback controls, speed, and lobby link", async () => {
    const user = userEvent.setup();
    const props = renderMenu();

    await user.click(screen.getByRole("button", { name: "实时设置" }));

    const dialog = screen.getByRole("dialog", { name: "实时设置" });
    expect(dialog).toHaveTextContent("game_1200abcd");
    expect(dialog).toHaveTextContent("直播中");
    expect(dialog).toHaveTextContent("新手 6 人快局");
    expect(dialog).toHaveTextContent("v2026.04");
    expect(dialog).toHaveTextContent("6 人");
    expect(dialog).toHaveTextContent("1 狼人 / 1 预言家 / 1 医生 / 3 村民");
    expect(within(dialog).getByRole("button", { name: "暂停" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "追到最新" })).toBeInTheDocument();
    expect(within(dialog).getByLabelText("播放速度")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "返回大厅" })).toHaveAttribute(
      "href",
      "/games",
    );

    await user.click(within(dialog).getByRole("button", { name: "追到最新" }));
    expect(props.onCatchUpToLatest).toHaveBeenCalledTimes(1);

    await user.selectOptions(within(dialog).getByLabelText("播放速度"), "2");
    expect(props.onSpeedChange).toHaveBeenCalledWith(2);
  });

  it("shows resume instead of playback controls for resumable failed runs", async () => {
    const user = userEvent.setup();
    const props = renderMenu({
      canResumeRun: true,
      run: { ...run, error: "model timeout", status: "failed" },
      status: {
        detailItems: ["失败"],
        kind: "interrupted",
        label: "异常中断",
        tone: "danger",
      },
    });

    await user.click(screen.getByRole("button", { name: "实时设置" }));

    const dialog = screen.getByRole("dialog", { name: "实时设置" });
    expect(within(dialog).getByRole("button", { name: "继续对局" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "暂停" })).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("播放速度")).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "继续对局" }));
    expect(props.onResumeRun).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape and returns focus to the settings button", async () => {
    const user = userEvent.setup();
    renderMenu();

    const settingsButton = screen.getByRole("button", { name: "实时设置" });
    await user.click(settingsButton);
    expect(screen.getByRole("dialog", { name: "实时设置" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "实时设置" })).not.toBeInTheDocument();
    expect(settingsButton).toHaveFocus();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/components/LiveNavSettingsMenu.test.tsx
```

Expected: FAIL，原因是 `LiveNavSettingsMenu.tsx` 尚不存在。

- [ ] **Step 3: 实现设置弹窗组件**

Create `apps/web/src/features/games/components/LiveNavSettingsMenu.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, SelectField } from "../../../components/ui";
import type { LiveDirectorSpeed } from "../hooks/useLiveDirector";
import type { LiveNavStatus } from "../liveNavStatus";
import type { GameRun, RuleSetSummary } from "../types";
import { LiveNavStatusBadge } from "./LiveNavStatusBadge";

type LiveNavSettingsMenuProps = {
  backlogCount: number;
  canResumeRun: boolean;
  isPaused: boolean;
  isResuming: boolean;
  onCatchUpToLatest: () => void;
  onResumeRun: () => void;
  onSpeedChange: (speed: LiveDirectorSpeed) => void;
  onTogglePaused: () => void;
  run: GameRun;
  speed: LiveDirectorSpeed;
  status: LiveNavStatus;
};

export function LiveNavSettingsMenu({
  backlogCount,
  canResumeRun,
  isPaused,
  isResuming,
  onCatchUpToLatest,
  onResumeRun,
  onSpeedChange,
  onTogglePaused,
  run,
  speed,
  status,
}: LiveNavSettingsMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const rule = normalizeRule(run);
  const roleSummary =
    rule.role_summary ??
    rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");
  const showResumeAction = canResumeRun;

  const closeMenu = useCallback(() => {
    setIsOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  }, []);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    closeButtonRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMenu();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [closeMenu, isOpen]);

  return (
    <div className="live-nav-settings relative flex shrink-0" data-testid="live-nav-settings">
      <button
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-label="实时设置"
        className="flex h-10 w-10 items-center justify-center rounded-md border border-slate-200/70 bg-slate-100 px-0 text-base font-semibold text-slate-950 transition hover:bg-white focus:outline-none focus:ring-2 focus:ring-amber-300/70"
        onClick={() => setIsOpen((value) => !value)}
        ref={triggerRef}
        type="button"
      >
        <span aria-hidden="true">⚙</span>
      </button>

      {isOpen ? (
        <>
          <div
            aria-hidden="true"
            className="fixed inset-0 z-[55]"
            data-testid="live-settings-backdrop"
            onMouseDown={closeMenu}
          />
          <section
            aria-labelledby="live-settings-title"
            aria-modal="true"
            className="fixed right-3 top-[calc(var(--arena-nav-height,var(--app-top-nav-height,56px))+0.75rem)] z-[60] max-h-[calc(100vh-var(--arena-nav-height,var(--app-top-nav-height,56px))-1.5rem)] w-[min(24rem,calc(100vw-1.5rem))] overflow-y-auto rounded-lg border border-slate-500/35 bg-slate-950/95 p-4 text-slate-100 shadow-[0_18px_70px_rgba(0,0,0,0.45)] backdrop-blur-md"
            data-testid="live-settings-dialog"
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <header className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-amber-50" id="live-settings-title">
                实时设置
              </h2>
              <button
                aria-label="关闭实时设置"
                className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-500/35 text-slate-200 transition hover:border-amber-300/55 hover:text-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-300/70"
                onClick={closeMenu}
                ref={closeButtonRef}
                type="button"
              >
                <span aria-hidden="true">×</span>
              </button>
            </header>

            <section className="border-b border-slate-700/70 pb-4" aria-labelledby="live-settings-info-title">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400" id="live-settings-info-title">
                对局信息
              </h3>
              <dl className="grid gap-2 text-sm">
                <InfoRow label="对局 ID" value={run.session_id} mono />
                <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-2">
                  <dt className="text-slate-400">状态</dt>
                  <dd>
                    <LiveNavStatusBadge status={status} />
                  </dd>
                </div>
                <InfoRow label="规则" value={rule.name} />
                <InfoRow label="版本" value={`v${rule.version}`} />
                <InfoRow label="人数" value={`${rule.player_count} 人`} />
              </dl>
              {roleSummary ? (
                <p className="mt-3 text-xs leading-5 text-slate-300">{roleSummary}</p>
              ) : null}
              {rule.rule_tags && rule.rule_tags.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {rule.rule_tags.map((tag) => (
                    <Badge color="amber" key={tag} variant="surface">
                      {tag}
                    </Badge>
                  ))}
                </div>
              ) : null}
            </section>

            <section className="border-b border-slate-700/70 py-4" aria-labelledby="live-settings-controls-title">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400" id="live-settings-controls-title">
                观战控制
              </h3>
              {showResumeAction ? (
                <Button
                  className="w-full"
                  disabled={isResuming}
                  intent="primary"
                  loading={isResuming}
                  onClick={onResumeRun}
                  skin="gothic"
                  type="button"
                >
                  继续对局
                </Button>
              ) : (
                <div className="grid gap-3">
                  <div className="grid grid-cols-2 gap-2">
                    <Button onClick={onTogglePaused} skin="gothic" type="button">
                      {isPaused ? "继续播放" : "暂停"}
                    </Button>
                    <Button
                      disabled={backlogCount === 0}
                      onClick={onCatchUpToLatest}
                      skin="gothic"
                      type="button"
                    >
                      追到最新
                    </Button>
                  </div>
                  <label className="grid gap-1.5 text-xs font-semibold text-slate-300">
                    播放速度
                    <SelectField
                      aria-label="播放速度"
                      onChange={(event) =>
                        onSpeedChange(Number(event.target.value) as LiveDirectorSpeed)
                      }
                      value={String(speed)}
                    >
                      <option value="1">1x</option>
                      <option value="2">2x</option>
                    </SelectField>
                  </label>
                  <p className="text-xs text-slate-400">
                    {backlogCount > 0 ? `当前落后 ${backlogCount} 条事件` : "当前已在最新事件"}
                  </p>
                </div>
              )}
            </section>

            <section className="pt-4" aria-labelledby="live-settings-navigation-title">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400" id="live-settings-navigation-title">
                导航操作
              </h3>
              <Button asChild className="w-full" skin="gothic" variant="surface">
                <Link to="/games">返回大厅</Link>
              </Button>
            </section>
          </section>
        </>
      ) : null}
    </div>
  );
}

function InfoRow({
  label,
  mono = false,
  value,
}: {
  label: string;
  mono?: boolean;
  value: string;
}) {
  return (
    <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-2">
      <dt className="text-slate-400">{label}</dt>
      <dd className={mono ? "truncate font-mono text-slate-100" : "truncate text-slate-100"} title={value}>
        {value}
      </dd>
    </div>
  );
}

function normalizeRule(run: GameRun): RuleSetSummary {
  return (
    run.rule_set ?? {
      id: "live",
      name: "实时对局",
      player_count: run.player_configs?.length ?? 0,
      roles: [],
      version: "-",
    }
  );
}
```

- [ ] **Step 4: 运行设置弹窗测试确认通过**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/components/LiveNavSettingsMenu.test.tsx
```

Expected: PASS。

### Task 3: 接入实时页导航

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: 更新页面测试到新导航结构**

Modify the `uses a stage-first live layout with a separate timeline column` test in `apps/web/src/pages/LiveGamePage.test.tsx`:

```tsx
const liveNavContext = within(commandNav).getByTestId("live-nav-context");
const sessionBadge = within(liveNavContext).getByTestId("live-nav-session");
const navStatus = within(liveNavContext).getByTestId("live-nav-status");

expect(sessionBadge).toHaveTextContent("对局");
expect(sessionBadge).toHaveTextContent("game_1200abcd");
expect(
  sessionBadge.compareDocumentPosition(navStatus) &
    Node.DOCUMENT_POSITION_FOLLOWING,
).toBeTruthy();
expect(navStatus).toHaveTextContent("连接中");
expect(navStatus).toHaveAttribute("data-status-kind", "connecting");
expect(within(liveNavContext).queryByTestId("rule-set-summary")).not.toBeInTheDocument();
expect(within(liveNavContext).queryByTestId("live-status-strip")).not.toBeInTheDocument();
expect(screen.getByTestId("arena-command-controls")).toBeEmptyDOMElement();
expect(screen.queryByTestId("director-controls")).not.toBeInTheDocument();
expect(screen.queryByRole("link", { name: "返回大厅" })).not.toBeInTheDocument();

const actionRegion = screen.getByTestId("arena-command-action-region");
const settingsButton = within(actionRegion).getByRole("button", {
  name: "实时设置",
});
expect(settingsButton).toBeInTheDocument();
expect(actionRegion.lastElementChild).toContainElement(settingsButton);

await userEvent.click(settingsButton);
const settingsDialog = screen.getByRole("dialog", { name: "实时设置" });
expect(settingsDialog).toHaveTextContent("经典 8 人局");
expect(within(settingsDialog).getByRole("button", { name: "暂停" })).toBeInTheDocument();
expect(within(settingsDialog).getByRole("button", { name: "追到最新" })).toBeInTheDocument();
expect(within(settingsDialog).getByLabelText("播放速度")).toBeInTheDocument();
expect(within(settingsDialog).getByRole("link", { name: "返回大厅" })).toHaveAttribute(
  "href",
  "/games",
);
```

Remove from the same test the old assertions that expect:

```tsx
within(liveNavContext).getByTestId("rule-set-summary")
within(screen.getByTestId("arena-command-controls")).getByTestId("director-controls")
within(screen.getByTestId("arena-command-controls")).getByLabelText("播放速度")
within(screen.getByTestId("arena-command-actions")).getByRole("link", { name: "返回大厅" })
screen.getByTestId("rule-set-summary")
screen.getByTestId("director-controls")
```

Modify `resumes a failed live run from its saved checkpoint`:

```tsx
expect(await screen.findByText("实时观战")).toBeInTheDocument();
await userEvent.click(screen.getByRole("button", { name: "实时设置" }));
const settingsDialog = screen.getByRole("dialog", { name: "实时设置" });
const resumeButton = within(settingsDialog).getByRole("button", {
  name: "继续对局",
});
expect(resumeButton).toHaveClass("gothic-button");
expect(within(settingsDialog).queryByRole("button", { name: "暂停" })).not.toBeInTheDocument();
expect(within(settingsDialog).queryByLabelText("播放速度")).not.toBeInTheDocument();
await userEvent.click(resumeButton);
```

Modify the completed replay-link assertion in `renders live events and completed replay link` after the replay link appears:

```tsx
const replayLink = screen.getByRole("link", { name: "查看完整复盘" });
const actions = screen.getByTestId("arena-command-actions");
const settingsButton = within(actions).getByRole("button", { name: "实时设置" });
expect(replayLink).toHaveAttribute("href", "/games/game_1200abcd");
expect(
  replayLink.compareDocumentPosition(settingsButton) &
    Node.DOCUMENT_POSITION_FOLLOWING,
).toBeTruthy();
expect(within(actions).queryByRole("link", { name: "返回大厅" })).not.toBeInTheDocument();
```

- [ ] **Step 2: 运行页面测试确认失败**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx
```

Expected: FAIL，原因是页面仍在导航栏常驻渲染规则摘要、播放控制和返回大厅。

- [ ] **Step 3: 修改 `LiveGamePage` 接线**

Modify imports in `apps/web/src/pages/LiveGamePage.tsx`.

Remove:

```tsx
import { Button, Callout, Text } from "../components/ui";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArenaCommandNav, ArenaNavButton } from "../app/navigation";
import { LiveDirectorControls } from "../features/games/components/LiveDirectorControls";
import { RuleSetSummary } from "../features/games/components/RuleSetSummary";
```

Add:

```tsx
import { Callout, Text } from "../components/ui";
import { useNavigate, useParams } from "react-router-dom";
import { ArenaCommandNav, ArenaNavButton } from "../app/navigation";
import { LiveNavSessionBadge } from "../features/games/components/LiveNavSessionBadge";
import { LiveNavSettingsMenu } from "../features/games/components/LiveNavSettingsMenu";
```

Replace `topNavCommands` with:

```tsx
  const topNavCommands = null;
```

Replace `topNavActions` with:

```tsx
  const topNavActions = (
    <>
      {terminalEvent && run ? (
        <ArenaNavButton to={`/games/${run.session_id}`}>
          查看完整复盘
        </ArenaNavButton>
      ) : null}
      {run ? (
        <LiveNavSettingsMenu
          backlogCount={director.backlogCount}
          canResumeRun={Boolean(canResumeRun)}
          isPaused={director.isPaused}
          isResuming={resumeMutation.isPending}
          onCatchUpToLatest={director.catchUpToLatest}
          onResumeRun={() => resumeMutation.mutate(run.session_id)}
          onSpeedChange={director.setSpeed}
          onTogglePaused={director.togglePaused}
          run={run}
          speed={director.speed}
          status={liveNavStatus}
        />
      ) : null}
    </>
  );
```

Replace `topNavContext` body with:

```tsx
  const topNavContext = run ? (
    <div
      className="live-nav-context flex min-w-0 flex-1 flex-nowrap items-center gap-x-3 overflow-hidden"
      data-testid="live-nav-context"
    >
      <h1 className="sr-only">实时观战</h1>
      <LiveNavSessionBadge sessionId={run.session_id} />
      <LiveNavStatusBadge status={liveNavStatus} />
    </div>
  ) : null;
```

- [ ] **Step 4: 运行页面测试确认通过**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx
```

Expected: PASS。

### Task 4: 聚焦回归与清理

**Files:**
- Modify only the files from Tasks 1-3 if verification reveals a focused issue.

- [ ] **Step 1: 运行新增组件与实时页测试**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/components/LiveNavSessionBadge.test.tsx src/features/games/components/LiveNavSettingsMenu.test.tsx src/pages/LiveGamePage.test.tsx
```

Expected: PASS。

- [ ] **Step 2: 运行完整前端测试**

Run:

```bash
pnpm --dir apps/web exec vitest run
```

Expected: PASS。

- [ ] **Step 3: 运行 lint**

Run:

```bash
pnpm --dir apps/web lint
```

Expected: PASS。

- [ ] **Step 4: 运行生产构建**

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS。

- [ ] **Step 5: 检查 diff hygiene**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 6: 审查最终 diff**

Run:

```bash
git diff -- apps/web/src/features/games/components/LiveNavSessionBadge.tsx apps/web/src/features/games/components/LiveNavSessionBadge.test.tsx apps/web/src/features/games/components/LiveNavSettingsMenu.tsx apps/web/src/features/games/components/LiveNavSettingsMenu.test.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx
```

Expected: diff only changes the live nav arrangement, adds the session badge, adds the settings dialog, and updates tests for the new interaction.
