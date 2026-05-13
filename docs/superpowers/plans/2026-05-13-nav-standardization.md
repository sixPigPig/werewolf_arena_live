# Navigation Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize the global navigation bar around stable slots and explicit variants while keeping live-game command controls flexible.

**Architecture:** `AppTopNav` remains the single exported navigation component, but its API moves from page-specific booleans to variant, density, brand, context, actions, and utility action slots. Navigation height, brand sizing, and page content offset become named CSS/Tailwind contracts instead of repeated literals. Pages provide their own actions through slots, while `AppTopNav` owns layout, spacing, focus, and responsive behavior.

**Tech Stack:** React, TypeScript, React Router, Tailwind utility classes, Vitest, Testing Library.

---

### Task 1: Lock Navigation API Contracts With Tests

**Files:**
- Create: `apps/web/src/app/AppTopNav.test.tsx`
- Modify: existing page tests only where their expectations reference removed page-specific props.

- [ ] **Step 1: Write failing tests for standard slots and variants**

Create `apps/web/src/app/AppTopNav.test.tsx` with tests that render:
- default global navigation with a full brand logo and `data-variant="global"`
- command navigation with `variant="command"`, `density="compact"`, context content, primary actions, and utility actions
- compact brand rendering when `brand="compact"`

- [ ] **Step 2: Run the new test and verify it fails**

Run: `pnpm --dir apps/web exec vitest run src/app/AppTopNav.test.tsx`

Expected: FAIL because `variant`, `density`, `brand`, `utilityActions`, CSS variable height classes, and data attributes are not implemented yet.

### Task 2: Refactor AppTopNav Around Standard Slots

**Files:**
- Modify: `apps/web/src/app/AppTopNav.tsx`
- Modify: `apps/web/src/app/AppTheme.tsx`
- Modify: `apps/web/src/styles/index.css`

- [ ] **Step 1: Replace page-specific props**

Remove `layout`, `showHistoryLink`, and `showLobbyBack`. Add:

```ts
type AppTopNavProps = {
  actions?: ReactNode;
  brand?: "full" | "compact";
  className?: string;
  context?: ReactNode;
  density?: "regular" | "compact";
  projectName?: string;
  tone?: "default" | "nocturne";
  utilityActions?: ReactNode;
  variant?: "global" | "command";
};
```

- [ ] **Step 2: Add stable layout tokens**

Use `h-[var(--app-top-nav-height)] min-h-[var(--app-top-nav-height)]` for the shell, `pt-[var(--app-top-nav-height)]` for the content offset, and `--app-top-nav-height: 56px` in `:root`.

- [ ] **Step 3: Add brand variants**

Render the full horizontal brand by default. Render the square logo asset for `brand="compact"`. Keep the link accessible with `alt={projectName}` on the visible image.

- [ ] **Step 4: Verify the new test passes**

Run: `pnpm --dir apps/web exec vitest run src/app/AppTopNav.test.tsx`

Expected: PASS.

### Task 3: Migrate Pages and Remove CSS Residue

**Files:**
- Modify: `apps/web/src/pages/GamesPage.tsx`
- Modify: `apps/web/src/pages/GameDetailPage.tsx`
- Modify: `apps/web/src/pages/GameHistoryPage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/*.test.tsx`
- Modify: `apps/web/src/styles/index.css`

- [ ] **Step 1: Move built-in navigation links to page actions**

Replace `showHistoryLink` and `showLobbyBack` with explicit `Button asChild` action nodes in the calling pages.

- [ ] **Step 2: Rename command usage**

Replace `layout="command"` with `variant="command" density="compact"` in live pages. Keep the full brand unless a specific live layout later opts into `brand="compact"`.

- [ ] **Step 3: Remove obsolete project-name CSS**

Delete `.app-project-name` responsive rules because the text wordmark no longer exists.

- [ ] **Step 4: Run related tests**

Run: `pnpm --dir apps/web exec vitest run src/app/AppTopNav.test.tsx src/pages/HomePage.test.tsx src/pages/GamesPage.test.tsx src/pages/GameDetailPage.test.tsx src/pages/GameHistoryPage.test.tsx src/pages/LiveGamePage.test.tsx`

Expected: PASS.

### Task 4: Full Verification

**Files:**
- No additional source files.

- [ ] **Step 1: Run full tests**

Run: `pnpm --dir apps/web exec vitest run`

Expected: all tests pass.

- [ ] **Step 2: Run production build**

Run: `pnpm build:web`

Expected: Vite build completes successfully.

- [ ] **Step 3: Check git diff hygiene**

Run: `git diff --check`

Expected: no output and exit code 0.
