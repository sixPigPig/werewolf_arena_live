# Arena Navigation Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a newly named navigation system for lobby, history, replay, and live pages without modifying `AppTopNav`.

**Architecture:** Create a new `apps/web/src/app/navigation` module with shared scroll-surface state, a navigation-specific button wrapper, `ArenaGlobalNav` for normal pages, and `ArenaCommandNav` for the live command bar. Page code migrates to these new components while `AppTopNav` remains as legacy code.

**Tech Stack:** React, TypeScript, React Router, TanStack Query, Tailwind utility classes, Vitest, Testing Library, Vite.

---

## File Structure

- Create: `apps/web/src/app/navigation/arenaNav.types.ts`
  Shared navigation tone, density, brand, surface, and button prop types.
- Create: `apps/web/src/app/navigation/useArenaNavSurface.ts`
  One scroll listener that returns `transparent` at `window.scrollY === 0` and `frosted` once the page scrolls.
- Create: `apps/web/src/app/navigation/ArenaNavButton.tsx`
  Component-library `Button` wrapper with gothic navigation defaults.
- Create: `apps/web/src/app/navigation/ArenaGlobalNav.tsx`
  Standard global navigation shell for lobby/history/replay.
- Create: `apps/web/src/app/navigation/ArenaCommandNav.tsx`
  Live-page command navigation shell.
- Create: `apps/web/src/app/navigation/index.ts`
  Public exports for the new navigation module.
- Create tests:
  `apps/web/src/app/navigation/ArenaNavButton.test.tsx`,
  `apps/web/src/app/navigation/ArenaGlobalNav.test.tsx`,
  `apps/web/src/app/navigation/ArenaCommandNav.test.tsx`.
- Modify: `apps/web/src/styles/index.css`
  Add new navigation tokens and remove migrated `history-top-nav` navigation overrides.
- Modify: `apps/web/src/app/AppTheme.tsx`
  Use `--arena-nav-height` for content offset.
- Modify pages:
  `apps/web/src/pages/GamesPage.tsx`,
  `apps/web/src/pages/GameHistoryPage.tsx`,
  `apps/web/src/pages/GameDetailPage.tsx`,
  `apps/web/src/pages/LiveGamePage.tsx`.
- Modify page tests:
  `apps/web/src/pages/GamesPage.test.tsx`,
  `apps/web/src/pages/GameHistoryPage.test.tsx`,
  `apps/web/src/pages/GameDetailPage.test.tsx`,
  `apps/web/src/pages/LiveGamePage.test.tsx`.

Do not modify `apps/web/src/app/AppTopNav.tsx` in this plan.

---

### Task 1: Navigation Button And Surface Primitives

**Files:**
- Create: `apps/web/src/app/navigation/ArenaNavButton.test.tsx`
- Create: `apps/web/src/app/navigation/arenaNav.types.ts`
- Create: `apps/web/src/app/navigation/useArenaNavSurface.ts`
- Create: `apps/web/src/app/navigation/ArenaNavButton.tsx`
- Create: `apps/web/src/app/navigation/index.ts`

- [ ] **Step 1: Write failing `ArenaNavButton` tests**

Create `apps/web/src/app/navigation/ArenaNavButton.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ArenaNavButton } from "./ArenaNavButton";

describe("ArenaNavButton", () => {
  it("renders navigation text actions with the gothic component button skin", () => {
    render(
      <ArenaNavButton intent="primary" onClick={() => undefined}>
        新建对局
      </ArenaNavButton>,
    );

    const button = screen.getByRole("button", { name: "新建对局" });

    expect(button).toHaveClass("gothic-button", "gothic-button-sm");
    expect(button).toHaveAttribute("data-intent", "primary");
  });

  it("renders navigation links through the component button asChild path", () => {
    render(
      <MemoryRouter>
        <ArenaNavButton to="/games/history">对局历史</ArenaNavButton>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "对局历史" });

    expect(link).toHaveClass("gothic-button", "gothic-button-sm");
    expect(link).toHaveAttribute("data-intent", "default");
    expect(link).toHaveAttribute("href", "/games/history");
  });

  it("keeps loading navigation actions disabled and labelled by Button", () => {
    render(<ArenaNavButton loading>刷新列表</ArenaNavButton>);

    const button = screen.getByRole("button", { name: "处理中..." });

    expect(button).toBeDisabled();
    expect(button).toHaveClass("gothic-button");
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
pnpm --dir apps/web exec vitest run src/app/navigation/ArenaNavButton.test.tsx
```

Expected: FAIL because `./ArenaNavButton` does not exist yet.

- [ ] **Step 3: Add shared types**

Create `apps/web/src/app/navigation/arenaNav.types.ts`:

```ts
import type { ReactNode } from "react";

import type { ButtonProps } from "../../components/ui";

export type ArenaNavTone = "default" | "nocturne" | "ornate";

export type ArenaNavDensity = "regular" | "compact";

export type ArenaNavBrandMode = "full" | "compact";

export type ArenaNavSurface = "transparent" | "frosted";

export type ArenaNavButtonTone = NonNullable<ButtonProps["color"]>;

export type ArenaNavButtonVariant = NonNullable<ButtonProps["variant"]>;

export type ArenaNavButtonSize = NonNullable<ButtonProps["size"]>;

export type ArenaNavSlot = ReactNode;
```

- [ ] **Step 4: Add scroll surface hook**

Create `apps/web/src/app/navigation/useArenaNavSurface.ts`:

```ts
import { useEffect, useState } from "react";

import type { ArenaNavSurface } from "./arenaNav.types";

function getCurrentSurface(): ArenaNavSurface {
  if (typeof window === "undefined") {
    return "transparent";
  }

  return window.scrollY > 0 ? "frosted" : "transparent";
}

export function useArenaNavSurface() {
  const [surface, setSurface] = useState<ArenaNavSurface>(getCurrentSurface);

  useEffect(() => {
    const updateSurface = () => {
      setSurface(getCurrentSurface());
    };

    updateSurface();
    window.addEventListener("scroll", updateSurface, { passive: true });

    return () => {
      window.removeEventListener("scroll", updateSurface);
    };
  }, []);

  return surface;
}
```

- [ ] **Step 5: Add `ArenaNavButton` implementation**

Create `apps/web/src/app/navigation/ArenaNavButton.tsx`:

```tsx
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button, type ButtonProps } from "../../components/ui";

type ArenaNavButtonProps = Omit<
  ButtonProps,
  "asChild" | "children" | "size" | "skin"
> & {
  ariaLabel?: string;
  children: ReactNode;
  size?: ButtonProps["size"];
  to?: string;
};

export function ArenaNavButton({
  ariaLabel,
  children,
  color = "gray",
  intent,
  size = "1",
  to,
  type = "button",
  variant = "surface",
  ...props
}: ArenaNavButtonProps) {
  if (to) {
    return (
      <Button
        asChild
        color={color}
        intent={intent}
        size={size}
        skin="gothic"
        variant={variant}
      >
        <Link aria-label={ariaLabel} to={to}>
          {children}
        </Link>
      </Button>
    );
  }

  return (
    <Button
      color={color}
      intent={intent}
      size={size}
      skin="gothic"
      type={type}
      variant={variant}
      {...props}
    >
      {children}
    </Button>
  );
}
```

- [ ] **Step 6: Add module exports**

Create `apps/web/src/app/navigation/index.ts`:

```ts
export { ArenaNavButton } from "./ArenaNavButton";
export { useArenaNavSurface } from "./useArenaNavSurface";
export type {
  ArenaNavBrandMode,
  ArenaNavButtonSize,
  ArenaNavButtonTone,
  ArenaNavButtonVariant,
  ArenaNavDensity,
  ArenaNavSlot,
  ArenaNavSurface,
  ArenaNavTone,
} from "./arenaNav.types";
```

- [ ] **Step 7: Run the focused test and verify it passes**

Run:

```bash
pnpm --dir apps/web exec vitest run src/app/navigation/ArenaNavButton.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add apps/web/src/app/navigation/ArenaNavButton.test.tsx apps/web/src/app/navigation/ArenaNavButton.tsx apps/web/src/app/navigation/arenaNav.types.ts apps/web/src/app/navigation/useArenaNavSurface.ts apps/web/src/app/navigation/index.ts
git commit -m "feat: add arena navigation primitives"
```

---

### Task 2: Global Navigation Shell

**Files:**
- Create: `apps/web/src/app/navigation/ArenaGlobalNav.test.tsx`
- Create: `apps/web/src/app/navigation/ArenaGlobalNav.tsx`
- Modify: `apps/web/src/app/navigation/index.ts`

- [ ] **Step 1: Write failing global navigation tests**

Create `apps/web/src/app/navigation/ArenaGlobalNav.test.tsx`:

```tsx
import { act, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { ArenaGlobalNav } from "./ArenaGlobalNav";
import { ArenaNavButton } from "./ArenaNavButton";

function setScrollY(value: number) {
  Object.defineProperty(window, "scrollY", {
    configurable: true,
    value,
  });
}

function renderNav(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

afterEach(() => {
  setScrollY(0);
});

describe("ArenaGlobalNav", () => {
  it("renders transparent and borderless at the top of the page", () => {
    setScrollY(0);

    renderNav(
      <ArenaGlobalNav
        primaryAction={<ArenaNavButton intent="primary">新建对局</ArenaNavButton>}
        secondaryAction={<ArenaNavButton to="/games/history">对局历史</ArenaNavButton>}
      />,
    );

    const nav = screen.getByTestId("arena-global-nav");

    expect(nav).toHaveAttribute("data-surface", "transparent");
    expect(nav).toHaveClass(
      "h-[var(--arena-nav-height)]",
      "min-h-[var(--arena-nav-height)]",
      "bg-transparent",
      "border-transparent",
    );
    expect(nav).not.toHaveClass("backdrop-blur-xl");
    expect(screen.getByTestId("arena-brand-logo")).toHaveClass(
      "h-[var(--arena-nav-height)]",
      "w-auto",
    );
    expect(screen.getByRole("link", { name: "狼人杀竞技场" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(within(screen.getByTestId("arena-nav-primary-action")).getByRole(
      "button",
      { name: "新建对局" },
    )).toHaveClass("gothic-button");
    expect(within(screen.getByTestId("arena-nav-secondary-action")).getByRole(
      "link",
      { name: "对局历史" },
    )).toHaveClass("gothic-button");
  });

  it("switches to a very light frosted glass surface after scrolling", () => {
    setScrollY(0);
    renderNav(<ArenaGlobalNav />);

    const nav = screen.getByTestId("arena-global-nav");

    act(() => {
      setScrollY(16);
      window.dispatchEvent(new Event("scroll"));
    });

    expect(nav).toHaveAttribute("data-surface", "frosted");
    expect(nav).toHaveClass(
      "bg-slate-950/[0.08]",
      "backdrop-blur-xl",
      "border-white/10",
    );
  });

  it("exposes tone and density as explicit navigation state", () => {
    renderNav(<ArenaGlobalNav density="compact" tone="ornate" />);

    const nav = screen.getByTestId("arena-global-nav");

    expect(nav).toHaveAttribute("data-density", "compact");
    expect(nav).toHaveAttribute("data-tone", "ornate");
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
pnpm --dir apps/web exec vitest run src/app/navigation/ArenaGlobalNav.test.tsx
```

Expected: FAIL because `ArenaGlobalNav` does not exist.

- [ ] **Step 3: Implement `ArenaGlobalNav`**

Create `apps/web/src/app/navigation/ArenaGlobalNav.tsx`:

```tsx
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import brandLogoSrc from "../../assets/langrensha-arena-nav-logo.png";
import type { ArenaNavDensity, ArenaNavTone } from "./arenaNav.types";
import { useArenaNavSurface } from "./useArenaNavSurface";

type ArenaGlobalNavProps = {
  brandLabel?: string;
  className?: string;
  density?: ArenaNavDensity;
  primaryAction?: ReactNode;
  secondaryAction?: ReactNode;
  tone?: ArenaNavTone;
};

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function surfaceClass(surface: ReturnType<typeof useArenaNavSurface>) {
  return surface === "frosted"
    ? "border-white/10 bg-slate-950/[0.08] shadow-[0_12px_40px_rgba(0,0,0,0.10)] backdrop-blur-xl"
    : "border-transparent bg-transparent shadow-none";
}

function toneClass(tone: ArenaNavTone) {
  if (tone === "ornate" || tone === "nocturne") {
    return "text-amber-50";
  }

  return "text-slate-50";
}

export function ArenaGlobalNav({
  brandLabel = "狼人杀竞技场",
  className,
  density = "regular",
  primaryAction,
  secondaryAction,
  tone = "default",
}: ArenaGlobalNavProps) {
  const surface = useArenaNavSurface();

  return (
    <header
      className={cx(
        "arena-global-nav fixed inset-x-0 top-0 z-50 h-[var(--arena-nav-height)] min-h-[var(--arena-nav-height)] w-full border-b transition-[background-color,border-color,box-shadow,backdrop-filter] duration-200",
        surfaceClass(surface),
        toneClass(tone),
        className,
      )}
      data-density={density}
      data-surface={surface}
      data-testid="arena-global-nav"
      data-tone={tone}
      data-variant="global"
    >
      <div className="arena-nav-inner mx-auto flex h-full w-full max-w-none items-center justify-between gap-3 px-3">
        <Link
          className="arena-brand-link flex h-full min-w-0 shrink-0 items-center rounded-md text-left focus:outline-none"
          data-testid="arena-brand-link"
          to="/games"
        >
          <img
            alt={brandLabel}
            className="arena-brand-logo h-[var(--arena-nav-height)] w-auto max-w-[16rem] shrink-0 object-contain"
            data-testid="arena-brand-logo"
            src={brandLogoSrc}
          />
        </Link>
        <nav
          aria-label="页面功能"
          className="arena-nav-actions flex w-auto shrink-0 flex-nowrap items-center justify-end gap-1.5"
          data-testid="arena-nav-actions"
        >
          <div className="contents" data-testid="arena-nav-primary-action">
            {primaryAction}
          </div>
          <div className="contents" data-testid="arena-nav-secondary-action">
            {secondaryAction}
          </div>
        </nav>
      </div>
    </header>
  );
}
```

- [ ] **Step 4: Export `ArenaGlobalNav`**

Modify `apps/web/src/app/navigation/index.ts`:

```ts
export { ArenaGlobalNav } from "./ArenaGlobalNav";
export { ArenaNavButton } from "./ArenaNavButton";
export { useArenaNavSurface } from "./useArenaNavSurface";
export type {
  ArenaNavBrandMode,
  ArenaNavButtonSize,
  ArenaNavButtonTone,
  ArenaNavButtonVariant,
  ArenaNavDensity,
  ArenaNavSlot,
  ArenaNavSurface,
  ArenaNavTone,
} from "./arenaNav.types";
```

- [ ] **Step 5: Run the focused test and verify it passes**

Run:

```bash
pnpm --dir apps/web exec vitest run src/app/navigation/ArenaGlobalNav.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add apps/web/src/app/navigation/ArenaGlobalNav.test.tsx apps/web/src/app/navigation/ArenaGlobalNav.tsx apps/web/src/app/navigation/index.ts
git commit -m "feat: add arena global navigation"
```

---

### Task 3: Command Navigation Shell

**Files:**
- Create: `apps/web/src/app/navigation/ArenaCommandNav.test.tsx`
- Create: `apps/web/src/app/navigation/ArenaCommandNav.tsx`
- Modify: `apps/web/src/app/navigation/index.ts`

- [ ] **Step 1: Write failing command navigation tests**

Create `apps/web/src/app/navigation/ArenaCommandNav.test.tsx`:

```tsx
import { act, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { ArenaCommandNav } from "./ArenaCommandNav";
import { ArenaNavButton } from "./ArenaNavButton";

function setScrollY(value: number) {
  Object.defineProperty(window, "scrollY", {
    configurable: true,
    value,
  });
}

function renderNav(ui: ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

afterEach(() => {
  setScrollY(0);
});

describe("ArenaCommandNav", () => {
  it("renders live command context and actions with compact navigation metadata", () => {
    renderNav(
      <ArenaCommandNav
        actions={<ArenaNavButton to="/games">返回大厅</ArenaNavButton>}
        commands={<button type="button">暂停</button>}
        context={<span>实时状态</span>}
      />,
    );

    const nav = screen.getByTestId("arena-command-nav");

    expect(nav).toHaveAttribute("data-variant", "command");
    expect(nav).toHaveAttribute("data-density", "compact");
    expect(nav).toHaveAttribute("data-tone", "nocturne");
    expect(nav).toHaveAttribute("data-surface", "transparent");
    expect(screen.getByTestId("arena-command-context")).toHaveTextContent(
      "实时状态",
    );
    expect(within(screen.getByTestId("arena-command-controls")).getByRole(
      "button",
      { name: "暂停" },
    )).toBeInTheDocument();
    expect(within(screen.getByTestId("arena-command-actions")).getByRole(
      "link",
      { name: "返回大厅" },
    )).toHaveClass("gothic-button");
    expect(screen.getByTestId("arena-command-brand-logo")).toHaveClass(
      "h-[var(--arena-nav-height)]",
      "w-auto",
    );
  });

  it("uses the same light frosted surface after scrolling", () => {
    setScrollY(0);
    renderNav(<ArenaCommandNav />);

    const nav = screen.getByTestId("arena-command-nav");

    act(() => {
      setScrollY(10);
      window.dispatchEvent(new Event("scroll"));
    });

    expect(nav).toHaveAttribute("data-surface", "frosted");
    expect(nav).toHaveClass(
      "bg-slate-950/[0.08]",
      "backdrop-blur-xl",
      "border-white/10",
    );
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
pnpm --dir apps/web exec vitest run src/app/navigation/ArenaCommandNav.test.tsx
```

Expected: FAIL because `ArenaCommandNav` does not exist.

- [ ] **Step 3: Implement `ArenaCommandNav`**

Create `apps/web/src/app/navigation/ArenaCommandNav.tsx`:

```tsx
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import brandLogoSrc from "../../assets/langrensha-arena-nav-logo.png";
import type { ArenaNavDensity, ArenaNavTone } from "./arenaNav.types";
import { useArenaNavSurface } from "./useArenaNavSurface";

type ArenaCommandNavProps = {
  actions?: ReactNode;
  brandLabel?: string;
  className?: string;
  commands?: ReactNode;
  context?: ReactNode;
  density?: ArenaNavDensity;
  tone?: ArenaNavTone;
};

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function surfaceClass(surface: ReturnType<typeof useArenaNavSurface>) {
  return surface === "frosted"
    ? "border-white/10 bg-slate-950/[0.08] shadow-[0_12px_40px_rgba(0,0,0,0.12)] backdrop-blur-xl"
    : "border-transparent bg-transparent shadow-none";
}

export function ArenaCommandNav({
  actions,
  brandLabel = "狼人杀竞技场",
  className,
  commands,
  context,
  density = "compact",
  tone = "nocturne",
}: ArenaCommandNavProps) {
  const surface = useArenaNavSurface();

  return (
    <header
      className={cx(
        "arena-command-nav fixed inset-x-0 top-0 z-50 h-[var(--arena-nav-height)] min-h-[var(--arena-nav-height)] w-full border-b text-amber-50 transition-[background-color,border-color,box-shadow,backdrop-filter] duration-200",
        surfaceClass(surface),
        className,
      )}
      data-density={density}
      data-surface={surface}
      data-testid="arena-command-nav"
      data-tone={tone}
      data-variant="command"
    >
      <div className="arena-command-nav-inner mx-auto flex h-full w-full max-w-none items-center justify-between gap-3 overflow-x-auto px-3">
        <div className="arena-command-primary flex min-w-0 flex-1 items-center gap-3">
          <Link
            className="arena-command-brand-link flex h-full min-w-0 shrink-0 items-center rounded-md text-left focus:outline-none"
            data-testid="arena-command-brand-link"
            to="/games"
          >
            <img
              alt={brandLabel}
              className="arena-command-brand-logo h-[var(--arena-nav-height)] w-auto max-w-[16rem] shrink-0 object-contain"
              data-testid="arena-command-brand-logo"
              src={brandLogoSrc}
            />
          </Link>
          <div
            className="arena-command-context min-w-0 flex-1"
            data-testid="arena-command-context"
          >
            {context}
          </div>
        </div>
        <nav
          aria-label="实时对局功能"
          className="arena-command-action-region flex w-auto shrink-0 flex-nowrap items-center gap-2"
          data-testid="arena-command-action-region"
        >
          <div className="contents" data-testid="arena-command-controls">
            {commands}
          </div>
          <div className="contents" data-testid="arena-command-actions">
            {actions}
          </div>
        </nav>
      </div>
    </header>
  );
}
```

- [ ] **Step 4: Export `ArenaCommandNav`**

Modify `apps/web/src/app/navigation/index.ts`:

```ts
export { ArenaCommandNav } from "./ArenaCommandNav";
export { ArenaGlobalNav } from "./ArenaGlobalNav";
export { ArenaNavButton } from "./ArenaNavButton";
export { useArenaNavSurface } from "./useArenaNavSurface";
export type {
  ArenaNavBrandMode,
  ArenaNavButtonSize,
  ArenaNavButtonTone,
  ArenaNavButtonVariant,
  ArenaNavDensity,
  ArenaNavSlot,
  ArenaNavSurface,
  ArenaNavTone,
} from "./arenaNav.types";
```

- [ ] **Step 5: Run the focused test and verify it passes**

Run:

```bash
pnpm --dir apps/web exec vitest run src/app/navigation/ArenaCommandNav.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add apps/web/src/app/navigation/ArenaCommandNav.test.tsx apps/web/src/app/navigation/ArenaCommandNav.tsx apps/web/src/app/navigation/index.ts
git commit -m "feat: add arena command navigation"
```

---

### Task 4: Tokens, Content Offset, And Legacy History Nav CSS Cleanup

**Files:**
- Modify: `apps/web/src/styles/index.css`
- Modify: `apps/web/src/app/AppTheme.tsx`

- [ ] **Step 1: Add the navigation token test through existing focused nav tests**

Before implementation, run:

```bash
pnpm --dir apps/web exec vitest run src/app/navigation/ArenaGlobalNav.test.tsx src/app/navigation/ArenaCommandNav.test.tsx
```

Expected: PASS because class assertions do not need CSS variables to exist in jsdom. This step records the current safety net before CSS changes.

- [ ] **Step 2: Add arena navigation CSS tokens**

Modify the `:root` block in `apps/web/src/styles/index.css` to include these lines after `--app-top-nav-height: 56px;`:

```css
  --arena-nav-height: var(--app-top-nav-height);
  --arena-nav-logo-size: var(--arena-nav-height);
```

The beginning of the file should read:

```css
@import "tailwindcss";

:root {
  --app-top-nav-height: 56px;
  --arena-nav-height: var(--app-top-nav-height);
  --arena-nav-logo-size: var(--arena-nav-height);

  color: #e2e8f0;
  font-family: "Inter", "Segoe UI", sans-serif;
}
```

- [ ] **Step 3: Switch app content offset to the new token**

Modify `apps/web/src/app/AppTheme.tsx` so the content layer uses the arena token:

```tsx
import type { ReactNode } from "react";

import siteBackground from "../assets/werewolf-site-background.png";

type AppThemeProps = {
  children: ReactNode;
};

export function AppTheme({ children }: AppThemeProps) {
  return (
    <div className="app-theme relative isolate min-h-screen overflow-x-hidden text-slate-50">
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 z-0 bg-cover bg-center bg-no-repeat"
        data-testid="site-background"
        style={{
          backgroundImage: `linear-gradient(180deg, rgba(2, 6, 13, 0.26) 0%, rgba(2, 6, 13, 0.58) 48%, rgba(2, 6, 13, 0.82) 100%), url(${siteBackground})`,
          backgroundPosition: "center top",
        }}
      />
      <div className="site-content-layer relative z-10 min-h-screen pt-[var(--arena-nav-height)]">
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Remove migrated history navigation overrides**

In `apps/web/src/styles/index.css`, remove only these navigation-specific blocks:

```css
.history-top-nav {
  background:
    linear-gradient(90deg, rgb(15 23 42 / 8%), rgb(2 6 13 / 5%)),
    linear-gradient(180deg, rgb(255 255 255 / 8%), transparent 70%);
  backdrop-filter: blur(18px) saturate(130%);
}

.history-top-nav .app-top-nav-inner {
  padding-inline: 1.5rem;
}
```

Also remove the nested responsive selectors that target `.history-top-nav`:

```css
  .history-top-nav .app-top-nav-inner {
    padding-inline: 0.75rem;
  }
```

and:

```css
  .history-top-nav .app-top-nav-inner {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
  }

  .history-top-nav .app-top-nav-primary {
    min-width: 0;
  }

  .history-top-nav .app-top-nav-actions {
    min-width: 0;
    justify-self: end;
  }
```

Keep the non-navigation history page styles such as `.history-page-shell`, `.history-page-header`, `.history-board`, and pagination classes.

- [ ] **Step 5: Run CSS and nav checks**

Run:

```bash
git diff --check -- apps/web/src/styles/index.css apps/web/src/app/AppTheme.tsx
pnpm --dir apps/web exec vitest run src/app/navigation/ArenaGlobalNav.test.tsx src/app/navigation/ArenaCommandNav.test.tsx
```

Expected: `git diff --check` has no output and tests PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add apps/web/src/styles/index.css apps/web/src/app/AppTheme.tsx
git commit -m "style: add arena navigation tokens"
```

---

### Task 5: Migrate Lobby, History, And Replay Pages

**Files:**
- Modify: `apps/web/src/pages/GamesPage.tsx`
- Modify: `apps/web/src/pages/GameHistoryPage.tsx`
- Modify: `apps/web/src/pages/GameDetailPage.tsx`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`
- Modify: `apps/web/src/pages/GameHistoryPage.test.tsx`
- Modify: `apps/web/src/pages/GameDetailPage.test.tsx`

- [ ] **Step 1: Update page tests to expect new global nav**

In each of the three page tests, replace assertions that target `app-top-nav` or `app-brand-logo` with new assertions targeting `arena-global-nav` and `arena-brand-logo`.

For `apps/web/src/pages/GamesPage.test.tsx`, the navigation assertions should include:

```tsx
expect(screen.getByTestId("arena-global-nav")).toHaveAttribute(
  "data-variant",
  "global",
);
expect(screen.getByTestId("arena-global-nav")).toHaveAttribute(
  "data-surface",
  "transparent",
);
expect(screen.getByTestId("arena-global-nav")).toHaveClass(
  "h-[var(--arena-nav-height)]",
  "min-h-[var(--arena-nav-height)]",
  "bg-transparent",
  "border-transparent",
);
expect(screen.getByTestId("arena-brand-logo")).toHaveClass(
  "h-[var(--arena-nav-height)]",
  "w-auto",
);
expect(screen.getByRole("link", { name: "狼人杀竞技场" })).toHaveAttribute(
  "href",
  "/games",
);
expect(screen.getByRole("link", { name: "对局历史" })).toHaveAttribute(
  "href",
  "/games/history",
);
expect(screen.getByRole("link", { name: "对局历史" })).toHaveClass(
  "gothic-button",
);
expect(screen.getByRole("button", { name: "新建对局" })).toHaveClass(
  "gothic-button",
);
```

For `apps/web/src/pages/GameHistoryPage.test.tsx`, the navigation assertions should include:

```tsx
const topNav = screen.getByTestId("arena-global-nav");

expect(topNav).toHaveAttribute("data-tone", "ornate");
expect(topNav).toHaveAttribute("data-surface", "transparent");
expect(topNav).not.toHaveClass("history-top-nav");
expect(screen.getByRole("button", { name: "刷新列表" })).toHaveClass(
  "gothic-button",
);
expect(screen.getByRole("link", { name: "返回大厅" })).toHaveClass(
  "gothic-button",
);
```

For `apps/web/src/pages/GameDetailPage.test.tsx`, the navigation assertions should include:

```tsx
expect(screen.getByTestId("arena-global-nav")).toHaveAttribute(
  "data-variant",
  "global",
);
expect(screen.getByTestId("arena-global-nav")).toHaveAttribute(
  "data-surface",
  "transparent",
);
expect(screen.getByRole("button", { name: "刷新复盘" })).toHaveClass(
  "gothic-button",
);
expect(screen.getByRole("link", { name: "返回大厅" })).toHaveClass(
  "gothic-button",
);
```

- [ ] **Step 2: Run the focused page tests and verify they fail**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/GamesPage.test.tsx src/pages/GameHistoryPage.test.tsx src/pages/GameDetailPage.test.tsx
```

Expected: FAIL because the pages still render `AppTopNav`.

- [ ] **Step 3: Migrate `GamesPage`**

Modify `apps/web/src/pages/GamesPage.tsx` to use the new navigation module:

```tsx
import { useRef } from "react";

import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
import { GamesWorkspace } from "./components/GamesWorkspace";

export function GamesPage() {
  const createFormRef = useRef<HTMLDivElement>(null);
  const focusCreateForm = () => {
    createFormRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    createFormRef.current
      ?.querySelector<HTMLElement>(
        "button, input, [tabindex]:not([tabindex='-1'])",
      )
      ?.focus();
  };

  return (
    <>
      <ArenaGlobalNav
        primaryAction={
          <ArenaNavButton intent="primary" onClick={focusCreateForm}>
            新建对局
          </ArenaNavButton>
        }
        secondaryAction={
          <ArenaNavButton to="/games/history">对局历史</ArenaNavButton>
        }
      />
      <GamesWorkspace createFormRef={createFormRef} />
    </>
  );
}
```

- [ ] **Step 4: Migrate `GameHistoryPage` navigation**

In `apps/web/src/pages/GameHistoryPage.tsx`, replace the `Button` and `AppTopNav` imports with:

```tsx
import { Callout, Heading } from "../components/ui";
import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
```

Replace the `<AppTopNav ... />` block with:

```tsx
      <ArenaGlobalNav
        primaryAction={
          <ArenaNavButton
            color="red"
            disabled={isFetching}
            loading={isFetching && !isPending}
            onClick={refreshSessions}
          >
            刷新列表
          </ArenaNavButton>
        }
        secondaryAction={<ArenaNavButton to="/games">返回大厅</ArenaNavButton>}
        tone="ornate"
      />
```

Keep the existing history page body unchanged.

- [ ] **Step 5: Migrate `GameDetailPage` navigation**

In `apps/web/src/pages/GameDetailPage.tsx`, replace the `Button` and `AppTopNav` imports with:

```tsx
import { Callout, Text } from "../components/ui";
import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
```

Replace the `topNav` constant with:

```tsx
  const topNav = (
    <ArenaGlobalNav
      primaryAction={
        <ArenaNavButton
          color="gray"
          disabled={isFetching}
          loading={isFetching && !isPending}
          onClick={() => void refetch()}
        >
          刷新复盘
        </ArenaNavButton>
      }
      secondaryAction={<ArenaNavButton to="/games">返回大厅</ArenaNavButton>}
    />
  );
```

- [ ] **Step 6: Run the focused page tests and verify they pass**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/GamesPage.test.tsx src/pages/GameHistoryPage.test.tsx src/pages/GameDetailPage.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add apps/web/src/pages/GamesPage.tsx apps/web/src/pages/GameHistoryPage.tsx apps/web/src/pages/GameDetailPage.tsx apps/web/src/pages/GamesPage.test.tsx apps/web/src/pages/GameHistoryPage.test.tsx apps/web/src/pages/GameDetailPage.test.tsx
git commit -m "feat: migrate standard pages to arena nav"
```

---

### Task 6: Migrate Live Page To Command Navigation

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Update live page tests to expect command nav**

In `apps/web/src/pages/LiveGamePage.test.tsx`, replace navigation assertions that target `app-top-nav` with assertions like:

```tsx
const topNav = screen.getByTestId("arena-command-nav");

expect(topNav).toHaveAttribute("data-variant", "command");
expect(topNav).toHaveAttribute("data-density", "compact");
expect(topNav).toHaveAttribute("data-tone", "nocturne");
expect(topNav).toHaveAttribute("data-surface", "transparent");
expect(topNav).toHaveClass(
  "h-[var(--arena-nav-height)]",
  "min-h-[var(--arena-nav-height)]",
  "bg-transparent",
  "border-transparent",
);
expect(screen.getByTestId("arena-command-brand-logo")).toHaveClass(
  "h-[var(--arena-nav-height)]",
  "w-auto",
);
expect(screen.getByTestId("arena-command-context")).toBeInTheDocument();
expect(screen.getByTestId("arena-command-controls")).toBeInTheDocument();
expect(screen.getByTestId("arena-command-actions")).toBeInTheDocument();
```

Where the test covers terminal live state, keep assertions for text actions and update them to expect gothic classes:

```tsx
expect(screen.getByRole("button", { name: "继续对局" })).toHaveClass(
  "gothic-button",
);
expect(screen.getByRole("link", { name: "查看完整复盘" })).toHaveClass(
  "gothic-button",
);
```

- [ ] **Step 2: Run the focused live test and verify it fails**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx
```

Expected: FAIL because `LiveGamePage` still renders `AppTopNav`.

- [ ] **Step 3: Update live page imports**

In `apps/web/src/pages/LiveGamePage.tsx`, remove the `AppTopNav` import and add:

```tsx
import { ArenaCommandNav, ArenaNavButton } from "../app/navigation";
```

Keep the existing `Button` import because the icon-only return action still uses the component-library button.

- [ ] **Step 4: Split live controls and actions**

Replace the current `topNavActions` constant with:

```tsx
  const topNavCommands = run ? (
    <LiveDirectorControls
      backlogCount={director.backlogCount}
      isCatchingUp={director.isCatchingUp}
      isPaused={director.isPaused}
      onCatchUpToLatest={director.catchUpToLatest}
      onSpeedChange={director.setSpeed}
      onTogglePaused={director.togglePaused}
      speed={director.speed}
      variant="nav"
    />
  ) : null;
  const topNavActions = (
    <>
      {canResumeRun && run ? (
        <ArenaNavButton
          disabled={resumeMutation.isPending}
          intent="primary"
          loading={resumeMutation.isPending}
          onClick={() => resumeMutation.mutate(run.session_id)}
        >
          继续对局
        </ArenaNavButton>
      ) : null}
      {terminalEvent && run ? (
        <ArenaNavButton to={`/games/${run.session_id}`}>
          查看完整复盘
        </ArenaNavButton>
      ) : null}
      <Button
        asChild
        className="live-command-exit h-10 w-10 px-0 text-lg"
        color="gray"
        highContrast
        size="2"
        variant="surface"
      >
        <Link aria-label="返回大厅" to="/games">
          <span className="sr-only">返回大厅</span>
          <span aria-hidden="true">↪</span>
        </Link>
      </Button>
    </>
  );
```

- [ ] **Step 5: Replace all live `AppTopNav` render sites**

In the pending, error, and success branches, replace:

```tsx
        <AppTopNav
          actions={topNavActions}
          context={topNavContext}
          density="compact"
          tone="nocturne"
          variant="command"
        />
```

with:

```tsx
        <ArenaCommandNav
          actions={topNavActions}
          commands={topNavCommands}
          context={topNavContext}
        />
```

- [ ] **Step 6: Run the focused live test and verify it passes**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit Task 6**

```bash
git add apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat: migrate live page to arena command nav"
```

---

### Task 7: Full Test Pass And Visual Browser Verification

**Files:**
- No expected source changes unless verification exposes a defect.

- [ ] **Step 1: Run all web unit tests**

Run:

```bash
pnpm --dir apps/web exec vitest run
```

Expected: PASS for all test files.

- [ ] **Step 2: Run web build**

Run:

```bash
pnpm build:web
```

Expected: build completes successfully.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Start or reuse the local web server**

If no Vite server is running, start one:

```bash
pnpm --dir apps/web dev --host 127.0.0.1 --port 5174
```

Expected: the app is available at `http://127.0.0.1:5174`.

- [ ] **Step 5: Capture top-of-page screenshots**

Open these routes and capture the top navigation at scroll position `0`:

```bash
LIVE_RUN_ID="$(curl -sS -X POST http://127.0.0.1:5174/api/v1/games/session_20260513_001143_012a3961/resume | node -e 'let data = ""; process.stdin.on("data", chunk => data += chunk); process.stdin.on("end", () => console.log(JSON.parse(data).run_id));')"
printf '%s\n' \
  "http://127.0.0.1:5174/games" \
  "http://127.0.0.1:5174/games/history" \
  "http://127.0.0.1:5174/games/session_20260424_050950_66ea9f38" \
  "http://127.0.0.1:5174/games/live/${LIVE_RUN_ID}"
```

Expected visual result: navigation is transparent and borderless, logo height matches the navigation height, and text buttons use the gothic component style.

- [ ] **Step 6: Capture scrolled screenshots**

On each route, scroll at least `16px` down and capture the top navigation again.

Expected visual result: navigation gains only a subtle frosted transparent glass surface, a light border, and no layout shift.

- [ ] **Step 7: Commit verification fixes if any were needed**

If visual verification required source fixes, commit only those files:

```bash
git status --short
git add apps/web/src/app/navigation apps/web/src/pages/GamesPage.tsx apps/web/src/pages/GameHistoryPage.tsx apps/web/src/pages/GameDetailPage.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/styles/index.css apps/web/src/app/AppTheme.tsx
git commit -m "fix: refine arena navigation visuals"
```

If no fixes were needed, do not create a verification-only commit.

---

## Self-Review Checklist

- Spec coverage:
  - New navigation module: Tasks 1-3.
  - No `AppTopNav` modification: file structure and every task exclude `AppTopNav.tsx`.
  - Logo height tied to nav height: Tasks 2-3 tests and implementations.
  - Transparent top and frosted scroll state: Tasks 2-3 tests and `useArenaNavSurface`.
  - Text buttons through component library: Task 1 and page migrations.
  - Four pages migrated: Tasks 5-6.
  - Browser screenshots: Task 7.
- Completeness scan: every task has exact files, commands, and expected outcomes.
- Type consistency:
  - `ArenaNavTone`, `ArenaNavDensity`, and `ArenaNavSurface` are defined before components use them.
  - `primaryAction` and `secondaryAction` belong to `ArenaGlobalNav`.
  - `context`, `commands`, and `actions` belong to `ArenaCommandNav`.
  - `ArenaNavButton` is used only for text navigation actions; icon-only live exit remains a component-library `Button`.
