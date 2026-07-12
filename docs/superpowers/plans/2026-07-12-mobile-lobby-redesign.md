# Mobile Lobby Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the mobile game lobby as a single-page progressive flow with one rule summary, a dominant numbered lineup, disclosed advanced settings, one launch action, and an accessible full-screen player picker.

**Architecture:** Keep `GamesPage` as the React Query/controller boundary and move lobby-only pure logic plus presentation into focused modules under `src/components/lobby`. Preserve the existing public APIs, favorite mutation lifecycle, lineup resize/move semantics, and create-game payload while replacing the current rule carousel, click-through player drawer, and three-column fixed action bar.

**Tech Stack:** React 19, TypeScript 6, TanStack Query 5, React Router 7, Vite 8, Vitest 4, Testing Library, Playwright 1.61, CSS, pnpm workspaces.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-07-12-mobile-lobby-redesign-design.md`; every task must preserve its acceptance criteria.
- Do not change the backend, `@werewolf-arena/game-client` public contracts, global viewport metadata, shared tab-bar behavior outside lobby modal states, or visual asset files.
- Preserve rule-change lineup resizing, invalid-profile cleanup, seat clamping, cross-seat profile moves, continuous empty-seat advance, close-without-commit, favorite optimistic update/rollback, favorite-session recovery, pull-to-refresh, two-step destructive clear, max-round validation, create payload, and success navigation.
- Keep lobby CSS scoped under lobby-specific selectors in `apps/mobile-web/src/styles/index.css`; do not change shared `.mobile-button` or `.mobile-action-bar` semantics globally.
- At 320×568, visible lobby text must compute to at least 12px and common controls must measure at least 44×44 CSS pixels.
- At 320×568, the second seat row, advanced-settings summary, fixed launch bar, and tab bar must not intersect.
- Use semantic behavior tests for React logic and real Playwright geometry for size/overlap requirements; do not add screenshot baselines or new PNG-pixel assertions.
- Follow test-first order within each task and make only the task's listed commit after its tests pass.

---

## File Structure

- Create `apps/mobile-web/src/components/lobby/lobbyModel.ts`: lobby-local pure lineup, filtering, label, and normalization functions.
- Create `apps/mobile-web/src/components/lobby/lobbyModel.test.ts`: pure-function contract tests.
- Create `apps/mobile-web/src/components/lobby/LobbyModal.tsx`: shared inert/focus/Escape modal foundation.
- Create `apps/mobile-web/src/components/lobby/LobbyModal.test.tsx`: modal accessibility contract.
- Create `apps/mobile-web/src/components/lobby/lobbyRuleAssets.ts`: existing rule-card asset lookup only.
- Create `apps/mobile-web/src/components/lobby/LobbyRuleSummary.tsx`: current-rule summary and retry/change actions.
- Create `apps/mobile-web/src/components/lobby/LobbyRulePicker.tsx`: modal bottom-sheet rule selection.
- Create `apps/mobile-web/src/components/lobby/LobbyLineupSection.tsx`: numbered seats, smart fill, and clear menu.
- Create `apps/mobile-web/src/components/lobby/LobbyLineupSection.test.tsx`: lineup behavior and semantics.
- Create `apps/mobile-web/src/components/lobby/LobbyAdvancedSettings.tsx`: default-closed seed/round disclosure.
- Create `apps/mobile-web/src/components/lobby/LobbyAdvancedSettings.test.tsx`: disclosure, summary, and error-focus tests.
- Create `apps/mobile-web/src/components/lobby/LobbyLaunchBar.tsx`: progress, error, and single launch action.
- Create `apps/mobile-web/src/components/lobby/LobbyLaunchBar.test.tsx`: incomplete/ready/pending/error states.
- Create `apps/mobile-web/src/components/lobby/LobbyPlayerPicker.tsx`: full-screen player search, filters, favorites, refresh, selection, and confirmation UI.
- Create `apps/mobile-web/src/components/lobby/LobbyPlayerPicker.test.tsx`: modal, filtering, favorite, empty, and confirmation behavior.
- Create `apps/mobile-web/e2e/support/mobile-api-fixtures.ts`: shared deterministic mobile API fixtures.
- Create `apps/mobile-web/e2e/lobby-redesign.spec.ts`: responsive and end-to-end lobby coverage.
- Modify `apps/mobile-web/src/pages/GamesPage.tsx`: retain controller/data ownership and compose the new lobby components.
- Modify `apps/mobile-web/src/pages/GamesPage.test.tsx`: replace obsolete visual contracts while retaining query/mutation/integration coverage.
- Modify `apps/mobile-web/src/app/App.test.tsx`: replace fixed old lobby-padding/type selectors with new semantic contracts.
- Modify `apps/mobile-web/src/styles/index.css`: add scoped component styles and remove obsolete carousel/drawer/three-action selectors.
- Modify `apps/mobile-web/e2e/mobile-navigation.spec.ts`: reuse the shared API fixture installer.

---

### Task 1: Protect and Extract Lobby Domain Logic

**Files:**
- Create: `apps/mobile-web/src/components/lobby/lobbyModel.ts`
- Create: `apps/mobile-web/src/components/lobby/lobbyModel.test.ts`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx:1206-1514`
- Test: `apps/mobile-web/src/pages/GamesPage.test.tsx`

**Interfaces:**
- Consumes: `PlayerConfig`, `PlayerProfileFavoritesResponse`, and `PublicPlayerProfileWithFavorite` from `@werewolf-arena/game-client`.
- Produces: `LineupLaunchStatus`, `ProfileFilters`, `upsertSeatProfile`, `normalizePlayerConfigs`, `buildLineupLaunchStatus`, `clampSeat`, `findNextEmptySeat`, `hasNextEmptySeat`, `filterProfiles`, `updateFavoriteProfileIds`, `getStrategyFilterOptions`, `formatStrategyLabel`, `getProfileDescription`, `getProfileCardDescriptionLines`, `splitProfileCardDescription`, `getProfileSeatStatusLabel`, `getProfileChoiceAriaLabel`, and `getConfirmProfileButtonLabel`.

- [ ] **Step 1: Write the failing pure-model tests**

Create `apps/mobile-web/src/components/lobby/lobbyModel.test.ts` with a complete profile factory and these contract cases:

```ts
import { describe, expect, it } from "vitest";

import type {
  PlayerConfig,
  PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";
import {
  buildLineupLaunchStatus,
  filterProfiles,
  findNextEmptySeat,
  normalizePlayerConfigs,
  upsertSeatProfile,
} from "./lobbyModel";

function buildProfile(
  id: string,
  overrides: Partial<PublicPlayerProfileWithFavorite> = {},
): PublicPlayerProfileWithFavorite {
  return {
    id,
    display_name: id,
    model: "test-model",
    personality_id: "balanced",
    personality_text: "沉稳控场",
    appearance_id: "default",
    avatar_image_url: "",
    short_description: "先盘逻辑再站边",
    background_story: "",
    speaking_style: "",
    catchphrases: [],
    strategy_profile: "analysis",
    risk_tolerance: 3,
    bluffing_tendency: 3,
    trust_tendency: 3,
    leadership_tendency: 3,
    talkativeness: 3,
    example_messages: [],
    display_order: 1,
    featured: false,
    tags: ["逻辑"],
    is_favorite: false,
    ...overrides,
  };
}

describe("lobbyModel", () => {
  it("moves an already assigned profile to the requested seat", () => {
    const configs: PlayerConfig[] = [
      { seat: 1, profile_id: "profile-a" },
      { seat: 2, profile_id: "profile-b" },
    ];

    expect(upsertSeatProfile(configs, 2, "profile-a")).toEqual([
      { seat: 2, profile_id: "profile-a" },
    ]);
  });

  it("normalizes configured seats into sorted API payload entries", () => {
    expect(
      normalizePlayerConfigs(
        [
          { seat: 3, profile_id: "outside" },
          { seat: 2, model: "  model-b  " },
          { seat: 1, profile_id: "profile-a", name: "ignored" },
        ],
        2,
      ),
    ).toEqual([
      { seat: 1, profile_id: "profile-a" },
      { seat: 2, model: "model-b" },
    ]);
  });

  it("reports a disabled remaining-seat label until the lineup is full", () => {
    const profiles = [buildProfile("profile-a"), buildProfile("profile-b")];

    expect(buildLineupLaunchStatus([], profiles, 2)).toMatchObject({
      assignedCount: 0,
      emptySeatCount: 2,
      ctaLabel: "还差 2 位",
      canLaunch: false,
    });
    expect(
      buildLineupLaunchStatus(
        [
          { seat: 1, profile_id: "profile-a" },
          { seat: 2, profile_id: "profile-b" },
        ],
        profiles,
        2,
      ),
    ).toMatchObject({ ctaLabel: "开始对局", canLaunch: true });
  });

  it("wraps next-empty-seat search after the active seat", () => {
    expect(
      findNextEmptySeat(
        [
          { seat: 2, profile_id: "profile-b" },
          { seat: 3, profile_id: "profile-c" },
        ],
        3,
        2,
      ),
    ).toBe(1);
  });

  it("filters by search, favorite, and strategy together", () => {
    const profiles = [
      buildProfile("alpha", { is_favorite: true, strategy_profile: "analysis" }),
      buildProfile("beta", { strategy_profile: "aggressive" }),
    ];

    expect(
      filterProfiles(profiles, {
        favoriteFilter: "favorite",
        search: "逻辑",
        strategy: "analysis",
      }).map((profile) => profile.id),
    ).toEqual(["alpha"]);
  });
});
```

- [ ] **Step 2: Run the model test and verify it fails**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/lobbyModel.test.ts
```

Expected: FAIL because `./lobbyModel` does not exist.

- [ ] **Step 3: Move the pure helpers into `lobbyModel.ts`**

Move the existing implementations from `GamesPage.tsx:1206-1514` into the new module, export the public contracts, and keep `hasPlayerConfig` inside this module. Use these exact public types and update the incomplete launch label:

```ts
import {
  hasPlayerConfig,
  type PlayerConfig,
  type PlayerProfileFavoritesResponse,
  type PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";

export type LineupLaunchStatus = {
  assignedCount: number;
  emptySeatCount: number;
  profileShortageCount: number;
  summaryText: string;
  ctaLabel: string;
  canLaunch: boolean;
};

export type ProfileFilters = {
  favoriteFilter: "all" | "favorite";
  search: string;
  strategy: string;
};

export function upsertSeatProfile(
  configs: PlayerConfig[],
  seat: number,
  profileId: string,
): PlayerConfig[] {
  return configs
    .filter(
      (config) => config.seat !== seat && config.profile_id !== profileId,
    )
    .concat({ seat, profile_id: profileId })
    .sort((left, right) => left.seat - right.seat);
}
```

In `buildLineupLaunchStatus`, keep the existing counts and `summaryText`, but set `ctaLabel` with this exact branch logic:

```ts
const ctaLabel =
  playerCount === 0
    ? "等待规则"
    : emptySeatCount > 0
      ? `还差 ${emptySeatCount} 位`
      : "开始对局";
```

Return that `ctaLabel` in every status branch. Export the remaining moved functions without changing their current behavior.

- [ ] **Step 4: Replace local helper declarations with imports**

In `GamesPage.tsx`, import the moved functions from `../components/lobby/lobbyModel` and delete their old local declarations. Keep rule-image lookup in `GamesPage` until Task 3.

```ts
import {
  buildLineupLaunchStatus,
  clampSeat,
  filterProfiles,
  findNextEmptySeat,
  getConfirmProfileButtonLabel,
  getProfileCardDescriptionLines,
  getProfileChoiceAriaLabel,
  getProfileSeatStatusLabel,
  getStrategyFilterOptions,
  normalizePlayerConfigs,
  updateFavoriteProfileIds,
  upsertSeatProfile,
} from "../components/lobby/lobbyModel";
```

- [ ] **Step 5: Run the focused tests and verify they pass**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/lobbyModel.test.ts src/pages/GamesPage.test.tsx
```

Expected: PASS; existing page behavior remains unchanged except tests that assert the old incomplete `ctaLabel` must now expect `还差 N 位`.

- [ ] **Step 6: Commit the protected domain extraction**

```bash
git add apps/mobile-web/src/components/lobby/lobbyModel.ts apps/mobile-web/src/components/lobby/lobbyModel.test.ts apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/pages/GamesPage.test.tsx
git commit -m "refactor(mobile): extract lobby domain model"
```

---

### Task 2: Add the Accessible Lobby Modal Foundation

**Files:**
- Create: `apps/mobile-web/src/components/lobby/LobbyModal.tsx`
- Create: `apps/mobile-web/src/components/lobby/LobbyModal.test.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

**Interfaces:**
- Consumes: a background ref, restore-focus ref, optional initial-focus ref, label ID, close callback, class name, and children.
- Produces: a mounted `role="dialog"`, `aria-modal="true"` layer that marks the background inert, traps Tab, handles Escape, restores focus, and exposes `.mobile-lobby-modal-layer` for tab-bar hiding.

- [ ] **Step 1: Write the failing modal accessibility test**

Create `LobbyModal.test.tsx`:

```tsx
import { useRef, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LobbyModal } from "./LobbyModal";

function ModalHarness() {
  const [isOpen, setIsOpen] = useState(false);
  const backgroundRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const initialFocusRef = useRef<HTMLInputElement | null>(null);

  return (
    <main>
      <div ref={backgroundRef}>
        <button ref={triggerRef} onClick={() => setIsOpen(true)} type="button">
          打开选择器
        </button>
      </div>
      {isOpen ? (
        <LobbyModal
          backgroundRef={backgroundRef}
          className="test-dialog"
          initialFocusRef={initialFocusRef}
          labelledBy="test-dialog-title"
          onClose={() => setIsOpen(false)}
          restoreFocusRef={triggerRef}
        >
          <h2 id="test-dialog-title">测试选择器</h2>
          <input aria-label="搜索" ref={initialFocusRef} />
          <button onClick={() => setIsOpen(false)} type="button">
            完成
          </button>
        </LobbyModal>
      ) : null}
    </main>
  );
}

describe("LobbyModal", () => {
  it("isolates the background, traps focus, closes on Escape, and restores focus", async () => {
    const user = userEvent.setup();
    render(<ModalHarness />);
    const trigger = screen.getByRole("button", { name: "打开选择器" });

    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "测试选择器" });
    const search = screen.getByRole("textbox", { name: "搜索" });
    const done = screen.getByRole("button", { name: "完成" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(trigger.parentElement).toHaveAttribute("inert");
    expect(search).toHaveFocus();

    await user.tab({ shift: true });
    expect(done).toHaveFocus();
    await user.tab();
    expect(search).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(trigger.parentElement).not.toHaveAttribute("inert");
  });
});
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/LobbyModal.test.tsx
```

Expected: FAIL because `LobbyModal` does not exist.

- [ ] **Step 3: Implement `LobbyModal`**

Create the component with this public contract and focusable selector:

```tsx
import {
  type ReactNode,
  type RefObject,
  useEffect,
  useRef,
} from "react";

type LobbyModalProps = {
  backgroundRef: RefObject<HTMLElement | null>;
  children: ReactNode;
  className: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
  labelledBy: string;
  onClose: () => void;
  restoreFocusRef: RefObject<HTMLElement | null>;
};

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function getFocusableElements(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter((element) => !element.hidden && element.tabIndex >= 0);
}

export function LobbyModal({
  backgroundRef,
  children,
  className,
  initialFocusRef,
  labelledBy,
  onClose,
  restoreFocusRef,
}: LobbyModalProps) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    const background = backgroundRef.current as
      | (HTMLElement & { inert?: boolean })
      | null;
    if (!dialog || !background) return;

    background.inert = true;
    background.setAttribute("inert", "");
    const frame = window.requestAnimationFrame(() => {
      (initialFocusRef?.current ?? getFocusableElements(dialog)[0] ?? dialog).focus();
    });

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = getFocusableElements(dialog);
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      } else if (!(active instanceof Node) || !dialog.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleKeyDown);
      background.inert = false;
      background.removeAttribute("inert");
      const restoreTarget = restoreFocusRef.current;
      if (restoreTarget && document.contains(restoreTarget)) restoreTarget.focus();
    };
  }, [backgroundRef, initialFocusRef, restoreFocusRef]);

  return (
    <div className="mobile-lobby-modal-layer">
      <div aria-hidden="true" className="mobile-lobby-modal-backdrop" />
      <section
        aria-labelledby={labelledBy}
        aria-modal="true"
        className={["mobile-lobby-modal", className].join(" ")}
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        {children}
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Add the modal-layer CSS contract**

Add scoped styles that make the layer fixed and hide the shared tab bar only while a lobby modal exists:

```css
.mobile-lobby-modal-layer {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  width: 100%;
  height: 100svh;
  place-items: end center;
}

.mobile-lobby-modal-backdrop {
  position: absolute;
  inset: 0;
  background: rgb(0 0 0 / 72%);
}

.mobile-lobby-modal {
  position: relative;
  z-index: 1;
  width: min(100%, 480px);
  box-sizing: border-box;
  color: #f4e8d2;
}

.mobile-app-shell:has(.mobile-lobby-modal-layer) .mobile-tab-bar {
  display: none;
}
```

- [ ] **Step 5: Run the modal test and lint**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/LobbyModal.test.tsx
pnpm --dir apps/mobile-web lint
```

Expected: both commands PASS.

- [ ] **Step 6: Commit the modal foundation**

```bash
git add apps/mobile-web/src/components/lobby/LobbyModal.tsx apps/mobile-web/src/components/lobby/LobbyModal.test.tsx apps/mobile-web/src/styles/index.css
git commit -m "feat(mobile): add accessible lobby modal"
```

---

### Task 3: Replace the Rule Carousel with a Summary and Modal Picker

**Files:**
- Create: `apps/mobile-web/src/components/lobby/lobbyRuleAssets.ts`
- Create: `apps/mobile-web/src/components/lobby/LobbyRuleSummary.tsx`
- Create: `apps/mobile-web/src/components/lobby/LobbyRulePicker.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx:20-28,309-352,650-753`
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx:619-799`
- Modify: `apps/mobile-web/src/styles/index.css:381-531`

**Interfaces:**
- Consumes: `RuleSetSummary[]`, selected rule ID, query state/refetch, lobby background ref, change-button restore ref, select callback, and close callback.
- Produces: `LobbyRuleSummary` with one persistent change action and `LobbyRulePicker` with one modal selection target per rule.

- [ ] **Step 1: Replace the old carousel tests with failing summary/picker tests**

In `GamesPage.test.tsx`, remove tests that require the three-card horizontal viewport and colored pagination dots. Add:

```tsx
it("shows one current rule summary and changes rules in a modal picker", async () => {
  const user = userEvent.setup();
  gameClientMocks.listRuleSets.mockResolvedValue({
    rule_sets: [classicRuleSet, starterRuleSet],
  });
  renderGamesPage();

  const summary = await screen.findByRole("region", { name: "当前规则" });
  expect(within(summary).getByText("经典 8 人")).toBeVisible();
  expect(within(summary).getByText("测试阵容")).toBeVisible();
  expect(screen.queryByRole("group", { name: "规则选择指示" })).not.toBeInTheDocument();

  await user.click(within(summary).getByRole("button", { name: "更换规则" }));
  const picker = screen.getByRole("dialog", { name: "选择规则" });
  expect(picker).toHaveAttribute("aria-modal", "true");
  await user.click(
    within(picker).getByRole("button", { name: "选择规则 新手 6 人快局" }),
  );

  expect(screen.queryByRole("dialog", { name: "选择规则" })).not.toBeInTheDocument();
  expect(within(summary).getByText("新手 6 人快局")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "选择 6 号座位，当前为 请选择" }),
  ).toBeVisible();
});

it("retries a failed rule query from the summary", async () => {
  const user = userEvent.setup();
  gameClientMocks.listRuleSets
    .mockRejectedValueOnce(new Error("rules unavailable"))
    .mockResolvedValueOnce({ rule_sets: [starterRuleSet] });
  renderGamesPage();

  await user.click(await screen.findByRole("button", { name: "重新加载规则" }));

  expect(await screen.findByText("新手 6 人快局")).toBeVisible();
  expect(gameClientMocks.listRuleSets).toHaveBeenCalledTimes(2);
});
```

- [ ] **Step 2: Run the page test and verify it fails**

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL because the current page has no `当前规则` region or modal rule picker.

- [ ] **Step 3: Move the existing rule image lookup**

Create `lobbyRuleAssets.ts` and move the current imports/map from `GamesPage.tsx:20-28,1516-1551` into it. Export this exact function:

```ts
export function getLobbyRuleCardImage(
  ruleSetId: string,
  isSelected: boolean,
): string | null {
  const images = ruleCardImagesById[ruleSetId];
  if (!images) return null;
  return isSelected ? images.selected : images.unselected;
}
```

Delete the obsolete rule-tone lookup; the new page has no pagination dots.

- [ ] **Step 4: Implement `LobbyRuleSummary`**

Use this controlled contract and semantic structure:

```tsx
import type { RefObject } from "react";
import type { RuleSetSummary } from "@werewolf-arena/game-client";

type LobbyRuleSummaryProps = {
  changeButtonRef: RefObject<HTMLButtonElement | null>;
  disabled: boolean;
  isError: boolean;
  isLoading: boolean;
  onOpenPicker: () => void;
  onRetry: () => void;
  ruleSet: RuleSetSummary | null;
};

export function LobbyRuleSummary({
  changeButtonRef,
  disabled,
  isError,
  isLoading,
  onOpenPicker,
  onRetry,
  ruleSet,
}: LobbyRuleSummaryProps) {
  return (
    <section aria-label="当前规则" className="mobile-lobby-rule-summary">
      <div className="mobile-lobby-rule-summary-copy">
        <span>当前规则</span>
        <h2 id="mobile-current-rule-title">{ruleSet?.name ?? "等待规则"}</h2>
        <p>
          {ruleSet
            ? `${ruleSet.player_count} 人 · ${ruleSet.role_summary ?? ruleSet.complexity ?? "自定义规则"}`
            : isLoading
              ? "正在读取规则"
              : "暂时无法读取规则"}
        </p>
      </div>
      {isError ? (
        <button onClick={onRetry} type="button">重新加载规则</button>
      ) : (
        <button
          disabled={!ruleSet || disabled}
          onClick={onOpenPicker}
          ref={changeButtonRef}
          type="button"
        >
          更换规则
        </button>
      )}
    </section>
  );
}
```

- [ ] **Step 5: Implement `LobbyRulePicker`**

Use `LobbyModal`, focus the selected rule, and close immediately after selection:

```tsx
import { type RefObject, useRef } from "react";
import type { RuleSetSummary } from "@werewolf-arena/game-client";

import { LobbyModal } from "./LobbyModal";
import { getLobbyRuleCardImage } from "./lobbyRuleAssets";

type LobbyRulePickerProps = {
  backgroundRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  onSelect: (ruleSetId: string) => void;
  restoreFocusRef: RefObject<HTMLElement | null>;
  ruleSets: RuleSetSummary[];
  selectedRuleSetId: string | null;
};

export function LobbyRulePicker({
  backgroundRef,
  onClose,
  onSelect,
  restoreFocusRef,
  ruleSets,
  selectedRuleSetId,
}: LobbyRulePickerProps) {
  const selectedRuleRef = useRef<HTMLButtonElement | null>(null);

  return (
    <LobbyModal
      backgroundRef={backgroundRef}
      className="mobile-lobby-rule-dialog"
      initialFocusRef={selectedRuleRef}
      labelledBy="mobile-rule-picker-title"
      onClose={onClose}
      restoreFocusRef={restoreFocusRef}
    >
      <header className="mobile-lobby-modal-header">
        <h2 id="mobile-rule-picker-title">选择规则</h2>
        <button aria-label="关闭规则选择" onClick={onClose} type="button">×</button>
      </header>
      <div aria-label="可用规则" className="mobile-lobby-rule-grid" role="group">
        {ruleSets.map((ruleSet) => {
          const isSelected = ruleSet.id === selectedRuleSetId;
          const image = getLobbyRuleCardImage(ruleSet.id, isSelected);
          return (
            <button
              aria-label={`选择规则 ${ruleSet.name}`}
              aria-pressed={isSelected}
              className="mobile-lobby-rule-option"
              key={ruleSet.id}
              onClick={() => {
                onSelect(ruleSet.id);
                onClose();
              }}
              ref={isSelected ? selectedRuleRef : undefined}
              type="button"
            >
              {image ? <img alt="" aria-hidden="true" src={image} /> : null}
              <strong>{ruleSet.name}</strong>
              <span>{ruleSet.player_count} 人</span>
              <small>{ruleSet.role_summary ?? ruleSet.complexity ?? "自定义规则"}</small>
            </button>
          );
        })}
      </div>
    </LobbyModal>
  );
}
```

- [ ] **Step 6: Integrate the summary and picker in `GamesPage`**

Add `isRulePickerOpen`, `rulePickerTriggerRef`, stable `openRulePicker`/`closeRulePicker` callbacks, and render `LobbyRulePicker` as a sibling of `.mobile-lobby-content`. Simplify `handleRuleSetChange` to accept only `ruleSetId`; delete `ruleScrollRef`, `ruleCardRefs`, `scrollRuleCardIntoView`, the carousel JSX, and the dot JSX.

Use these exact composition calls:

```tsx
<LobbyRuleSummary
  changeButtonRef={rulePickerTriggerRef}
  disabled={createGameRunMutation.isPending}
  isError={ruleSetsQuery.isError}
  isLoading={ruleSetsQuery.isPending}
  onOpenPicker={openRulePicker}
  onRetry={() => void ruleSetsQuery.refetch()}
  ruleSet={selectedRuleSet}
/>
```

```tsx
{isRulePickerOpen ? (
  <LobbyRulePicker
    backgroundRef={lobbyContentRef}
    onClose={closeRulePicker}
    onSelect={handleRuleSetChange}
    restoreFocusRef={rulePickerTriggerRef}
    ruleSets={ruleSets}
    selectedRuleSetId={selectedRuleSet?.id ?? null}
  />
) : null}
```

- [ ] **Step 7: Add scoped rule-summary and bottom-sheet styles**

Ensure `.mobile-lobby-rule-dialog` has `max-height: 80svh`, internal overflow, and a two-column `.mobile-lobby-rule-grid`. Make every rule option and close action at least 44px in both dimensions. Keep the existing card images but remove the unused page-carousel and dot selectors.

- [ ] **Step 8: Run focused tests and commit**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/LobbyModal.test.tsx src/pages/GamesPage.test.tsx
pnpm --dir apps/mobile-web lint
git add apps/mobile-web/src/components/lobby/lobbyRuleAssets.ts apps/mobile-web/src/components/lobby/LobbyRuleSummary.tsx apps/mobile-web/src/components/lobby/LobbyRulePicker.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/styles/index.css
git commit -m "feat(mobile): simplify lobby rule selection"
```

Expected: tests and lint PASS; the commit contains only the rule slice.

---

### Task 4: Make the Numbered Lineup the Primary Work Area

**Files:**
- Create: `apps/mobile-web/src/components/lobby/LobbyLineupSection.tsx`
- Create: `apps/mobile-web/src/components/lobby/LobbyLineupSection.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx:69-72,297-307,354-425,755-928`
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx:919-1150,1834-1875`
- Modify: `apps/mobile-web/src/styles/index.css:532-884`

**Interfaces:**
- Consumes: player count, selected profiles by seat, active seat, launch status, fill availability, favorite availability, busy state, and controlled seat/fill/clear callbacks.
- Produces: four-column visible two-digit seats, a section-local smart-fill menu, and a section-local two-step clear action.

- [ ] **Step 1: Write the failing lineup component tests**

Create `LobbyLineupSection.test.tsx` with these cases:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LobbyLineupSection } from "./LobbyLineupSection";

const emptyStatus = {
  assignedCount: 0,
  emptySeatCount: 8,
  profileShortageCount: 0,
  summaryText: "已选 0/8 · 可自动补齐",
  ctaLabel: "还差 8 位",
  canLaunch: false,
};

describe("LobbyLineupSection", () => {
  it("renders visible two-digit seat numbers and opens the requested seat", async () => {
    const user = userEvent.setup();
    const onSelectSeat = vi.fn();
    render(
      <LobbyLineupSection
        activeSeat={1}
        canFillSeats
        favoritesAvailable
        isBusy={false}
        launchStatus={emptyStatus}
        onClear={vi.fn()}
        onFill={vi.fn()}
        onSelectSeat={onSelectSeat}
        playerCount={8}
        profilesBySeat={new Map()}
      />,
    );

    expect(screen.getByText("01")).toBeVisible();
    expect(screen.getByText("08")).toBeVisible();
    const seat = screen.getByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    });
    await user.click(seat);
    expect(onSelectSeat).toHaveBeenCalledWith(1, seat);
  });

  it("keeps fill and destructive clear outside the fixed launch bar", async () => {
    const user = userEvent.setup();
    const onFill = vi.fn();
    const onClear = vi.fn();
    render(
      <LobbyLineupSection
        activeSeat={1}
        canFillSeats
        favoritesAvailable
        isBusy={false}
        launchStatus={emptyStatus}
        onClear={onClear}
        onFill={onFill}
        onSelectSeat={vi.fn()}
        playerCount={8}
        profilesBySeat={new Map()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "智能补齐" }));
    const fillMenu = screen.getByRole("menu", { name: "智能补齐方式" });
    await user.click(within(fillMenu).getByRole("menuitem", { name: "收藏补齐" }));
    expect(onFill).toHaveBeenCalledWith({ favoritesOnly: true });

    await user.click(screen.getByRole("button", { name: "阵容更多操作" }));
    await user.click(screen.getByRole("menuitem", { name: "清空阵容" }));
    expect(onClear).not.toHaveBeenCalled();
    await user.click(screen.getByRole("menuitem", { name: "确认清空阵容" }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the component test and verify it fails**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/LobbyLineupSection.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the controlled lineup component**

Use this public contract:

```tsx
import { useEffect, useState } from "react";
import {
  resolveAvatarImageUrl,
  type PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";
import type { LineupLaunchStatus } from "./lobbyModel";

type FillOptions = { favoritesOnly?: boolean };

type LobbyLineupSectionProps = {
  activeSeat: number;
  canFillSeats: boolean;
  favoritesAvailable: boolean;
  isBusy: boolean;
  launchStatus: LineupLaunchStatus;
  onClear: () => void;
  onFill: (options?: FillOptions) => void;
  onSelectSeat: (seat: number, trigger: HTMLButtonElement) => void;
  playerCount: number;
  profilesBySeat: ReadonlyMap<number, PublicPlayerProfileWithFavorite | null>;
};
```

Keep ephemeral menus inside the component:

```tsx
const [openMenu, setOpenMenu] = useState<"fill" | "more" | null>(null);
const [isClearConfirming, setIsClearConfirming] = useState(false);

useEffect(() => {
  if (!isClearConfirming) return;
  const timeout = window.setTimeout(() => setIsClearConfirming(false), 3000);
  return () => window.clearTimeout(timeout);
}, [isClearConfirming]);
```

Render seat content with a separate visible number and name:

```tsx
{Array.from({ length: playerCount }, (_, index) => index + 1).map((seat) => {
  const profile = profilesBySeat.get(seat) ?? null;
  const displayName = profile?.display_name ?? "待选择";
  const avatar = profile ? resolveAvatarImageUrl(profile) : "";
  return (
    <button
      aria-label={`选择 ${seat} 号座位，当前为 ${displayName}`}
      aria-pressed={activeSeat === seat}
      className="mobile-lobby-seat-card"
      disabled={isBusy}
      key={seat}
      onClick={(event) => onSelectSeat(seat, event.currentTarget)}
      type="button"
    >
      {avatar ? <img alt="" aria-hidden="true" src={avatar} /> : null}
      <span className="mobile-lobby-seat-number">
        {String(seat).padStart(2, "0")}
      </span>
      <strong>{displayName}</strong>
    </button>
  );
})}
```

Render `智能补齐` and `阵容更多操作` as 44px buttons in the section header, followed by these in-flow menus:

```tsx
<div className="mobile-lobby-lineup-actions">
  <button
    aria-expanded={openMenu === "fill"}
    disabled={!canFillSeats || isBusy}
    onClick={() => setOpenMenu((menu) => menu === "fill" ? null : "fill")}
    type="button"
  >
    智能补齐
  </button>
  <button
    aria-expanded={openMenu === "more"}
    disabled={isBusy}
    onClick={() => setOpenMenu((menu) => menu === "more" ? null : "more")}
    type="button"
  >
    阵容更多操作
  </button>
</div>
{openMenu === "fill" ? (
  <div aria-label="智能补齐方式" className="mobile-lobby-lineup-menu" role="menu">
    <button
      disabled={!favoritesAvailable}
      onClick={() => {
        onFill({ favoritesOnly: true });
        setOpenMenu(null);
      }}
      role="menuitem"
      type="button"
    >
      收藏补齐
    </button>
    <button
      onClick={() => {
        onFill();
        setOpenMenu(null);
      }}
      role="menuitem"
      type="button"
    >
      随机补齐
    </button>
  </div>
) : null}
{openMenu === "more" ? (
  <div aria-label="阵容操作" className="mobile-lobby-lineup-menu" role="menu">
    <button
      onClick={() => {
        if (!isClearConfirming) {
          setIsClearConfirming(true);
          return;
        }
        onClear();
        setIsClearConfirming(false);
        setOpenMenu(null);
      }}
      role="menuitem"
      type="button"
    >
      {isClearConfirming ? "确认清空阵容" : "清空阵容"}
    </button>
  </div>
) : null}
```

- [ ] **Step 4: Integrate the component and remove duplicate page actions**

Replace the current lineup JSX with:

```tsx
{selectedRuleSet ? (
  <LobbyLineupSection
    activeSeat={safeActiveSeat}
    canFillSeats={canFillSeats}
    favoritesAvailable={favoritesAvailable}
    isBusy={createGameRunMutation.isPending}
    launchStatus={launchStatus}
    onClear={handleClearSeats}
    onFill={fillEmptySeats}
    onSelectSeat={openProfileDrawer}
    playerCount={playerCount}
    profilesBySeat={selectedProfilesBySeat}
  />
) : null}
```

Delete `isFillOptionsOpen`, page-level `isClearConfirming`, their timeout effect, and the old fill/clear buttons. Simplify `handleClearSeats` to clear immediately because the component owns confirmation:

```ts
function handleClearSeats() {
  setPlayerConfigs([]);
  setShortage(false);
  setValidationError(null);
}
```

Leave the current launch status and launch button in the fixed bar until Task 5.

- [ ] **Step 5: Add scoped lineup styles and update page tests**

Keep four columns, but make the seat number and name at least 12px computed at 320px. Style section-local menus so they participate in document flow below the header instead of floating over settings. Rewrite page tests to assert user-visible labels and callbacks; remove CSS assertions requiring three fixed-bar columns or the obsolete fill flyout.

- [ ] **Step 6: Run focused tests and commit**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/LobbyLineupSection.test.tsx src/pages/GamesPage.test.tsx
pnpm --dir apps/mobile-web lint
git add apps/mobile-web/src/components/lobby/LobbyLineupSection.tsx apps/mobile-web/src/components/lobby/LobbyLineupSection.test.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/styles/index.css
git commit -m "feat(mobile): promote lobby lineup workflow"
```

Expected: tests and lint PASS; fill and clear exist only in the lineup section.

---

### Task 5: Disclose Advanced Settings and Reduce the Fixed Bar to One Action

**Files:**
- Create: `apps/mobile-web/src/components/lobby/LobbyAdvancedSettings.tsx`
- Create: `apps/mobile-web/src/components/lobby/LobbyAdvancedSettings.test.tsx`
- Create: `apps/mobile-web/src/components/lobby/LobbyLaunchBar.tsx`
- Create: `apps/mobile-web/src/components/lobby/LobbyLaunchBar.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx:634-648,826-928`
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx:842-917,935-1150`
- Modify: `apps/mobile-web/src/app/App.test.tsx:164-212`
- Modify: `apps/mobile-web/src/styles/index.css:688-884,3422-3440`

**Interfaces:**
- Consumes: controlled seed/round values, field error, busy state, launch status, create error, launch-disabled state, and callbacks.
- Produces: a default-closed native disclosure and a fixed bar with exactly one launch button.

- [ ] **Step 1: Write failing advanced-settings tests**

Create `LobbyAdvancedSettings.test.tsx`:

```tsx
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LobbyAdvancedSettings } from "./LobbyAdvancedSettings";

function AdvancedHarness({
  error = null,
  initialMaxRounds = "8",
}: {
  error?: string | null;
  initialMaxRounds?: string;
}) {
  const [seed, setSeed] = useState("");
  const [maxRounds, setMaxRounds] = useState(initialMaxRounds);

  return (
    <LobbyAdvancedSettings
      disabled={false}
      maxRounds={maxRounds}
      maxRoundsError={error}
      onMaxRoundsChange={setMaxRounds}
      onSeedChange={setSeed}
      seed={seed}
    />
  );
}

describe("LobbyAdvancedSettings", () => {
  it("starts closed and exposes controlled settings after expansion", async () => {
    const user = userEvent.setup();
    render(<AdvancedHarness />);

    const details = screen.getByText("高级设置 · 随机种子 / 8轮").closest("details");
    expect(details).not.toHaveAttribute("open");
    await user.click(screen.getByText("高级设置 · 随机种子 / 8轮"));
    await user.type(screen.getByRole("spinbutton", { name: "种子" }), "42");
    await user.clear(screen.getByRole("spinbutton", { name: "最大轮数" }));
    await user.type(screen.getByRole("spinbutton", { name: "最大轮数" }), "10");

    expect(screen.getByRole("spinbutton", { name: "种子" })).toHaveValue(42);
    expect(screen.getByRole("spinbutton", { name: "最大轮数" })).toHaveValue(10);
    expect(screen.getByText("高级设置 · 种子 42 / 10轮")).toBeVisible();
  });

  it("opens and focuses maximum rounds when validation fails", () => {
    render(
      <AdvancedHarness
        error="最大轮数必须是 1 到 20 的整数"
        initialMaxRounds="0"
      />,
    );

    const input = screen.getByRole("spinbutton", { name: "最大轮数" });
    expect(input.closest("details")).toHaveAttribute("open");
    expect(input).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent("最大轮数必须是 1 到 20 的整数");
  });
});
```

- [ ] **Step 2: Write failing launch-bar tests**

Create `LobbyLaunchBar.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LobbyLaunchBar } from "./LobbyLaunchBar";

const incomplete = {
  assignedCount: 5,
  emptySeatCount: 3,
  profileShortageCount: 0,
  summaryText: "已选 5/8 · 可自动补齐",
  ctaLabel: "还差 3 位",
  canLaunch: false,
};

describe("LobbyLaunchBar", () => {
  it("renders one disabled remaining-seat action", () => {
    render(
      <LobbyLaunchBar
        error={null}
        isLaunchDisabled
        isPending={false}
        onLaunch={vi.fn()}
        status={incomplete}
      />,
    );

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "还差 3 位" })).toBeDisabled();
  });

  it("shows pending and create-error states without losing progress", () => {
    render(
      <LobbyLaunchBar
        error="无法发起对局"
        isLaunchDisabled
        isPending
        onLaunch={vi.fn()}
        status={{
          assignedCount: 8,
          emptySeatCount: 0,
          profileShortageCount: 0,
          summaryText: "已选 8/8 · 阵容已就绪",
          ctaLabel: "开始对局",
          canLaunch: true,
        }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("无法发起对局");
    expect(screen.getByRole("button", { name: "发起中…" })).toBeDisabled();
    expect(screen.getByText("已选 8/8 · 阵容已就绪")).toBeVisible();
  });
});
```

- [ ] **Step 3: Run both tests and verify they fail**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/LobbyAdvancedSettings.test.tsx src/components/lobby/LobbyLaunchBar.test.tsx
```

Expected: FAIL because both components are missing.

- [ ] **Step 4: Implement `LobbyAdvancedSettings`**

Use refs to open/focus on validation failure and keep the summary derived from controlled values:

```tsx
import { useEffect, useRef } from "react";

type LobbyAdvancedSettingsProps = {
  disabled: boolean;
  maxRounds: string;
  maxRoundsError: string | null;
  onMaxRoundsChange: (value: string) => void;
  onSeedChange: (value: string) => void;
  seed: string;
};

export function LobbyAdvancedSettings({
  disabled,
  maxRounds,
  maxRoundsError,
  onMaxRoundsChange,
  onSeedChange,
  seed,
}: LobbyAdvancedSettingsProps) {
  const detailsRef = useRef<HTMLDetailsElement | null>(null);
  const roundsRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!maxRoundsError) return;
    if (detailsRef.current) detailsRef.current.open = true;
    roundsRef.current?.focus();
  }, [maxRoundsError]);

  const seedSummary = seed ? `种子 ${seed}` : "随机种子";
  const roundsSummary = maxRounds ? `${maxRounds}轮` : "轮数未设置";

  return (
    <details className="mobile-lobby-advanced" ref={detailsRef}>
      <summary>
        高级设置 · {seedSummary} / {roundsSummary}
      </summary>
      <div className="mobile-lobby-settings-grid">
        <label className="mobile-lobby-field">
          <span>种子</span>
          <input
            disabled={disabled}
            inputMode="numeric"
            onChange={(event) => onSeedChange(event.target.value)}
            placeholder="随机"
            type="number"
            value={seed}
          />
        </label>
        <label className="mobile-lobby-field">
          <span>最大轮数</span>
          <input
            aria-describedby={maxRoundsError ? "mobile-max-rounds-error" : undefined}
            aria-invalid={Boolean(maxRoundsError)}
            disabled={disabled}
            inputMode="numeric"
            max={20}
            min={1}
            onChange={(event) => onMaxRoundsChange(event.target.value)}
            ref={roundsRef}
            type="number"
            value={maxRounds}
          />
        </label>
      </div>
      {maxRoundsError ? (
        <p id="mobile-max-rounds-error" role="alert">{maxRoundsError}</p>
      ) : null}
    </details>
  );
}
```

- [ ] **Step 5: Implement `LobbyLaunchBar`**

```tsx
import type { LineupLaunchStatus } from "./lobbyModel";

type LobbyLaunchBarProps = {
  error: string | null;
  isLaunchDisabled: boolean;
  isPending: boolean;
  onLaunch: () => void;
  status: LineupLaunchStatus;
};

export function LobbyLaunchBar({
  error,
  isLaunchDisabled,
  isPending,
  onLaunch,
  status,
}: LobbyLaunchBarProps) {
  return (
    <div className="mobile-lobby-launch-region">
      {error ? <p role="alert">{error}</p> : null}
      <div className="mobile-lobby-launch-bar">
        <span aria-live="polite">{status.summaryText}</span>
        <button
          className="mobile-button mobile-button-primary mobile-lobby-launch-button"
          disabled={isLaunchDisabled}
          onClick={onLaunch}
          type="button"
        >
          {isPending ? "发起中…" : status.ctaLabel}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Integrate both components**

Replace the always-open settings section with:

```tsx
<LobbyAdvancedSettings
  disabled={createGameRunMutation.isPending}
  maxRounds={maxRounds}
  maxRoundsError={validationError}
  onMaxRoundsChange={(value) => {
    setMaxRounds(value);
    setValidationError(null);
  }}
  onSeedChange={setSeed}
  seed={seed}
/>
```

Replace the remaining fixed action-bar JSX with:

```tsx
<LobbyLaunchBar
  error={
    createGameRunMutation.isError
      ? "无法发起对局"
      : shortage
        ? "玩家库玩家不足"
        : null
  }
  isLaunchDisabled={isLaunchDisabled}
  isPending={createGameRunMutation.isPending}
  onLaunch={handleSubmit}
  status={launchStatus}
/>
```

Remove the old top-level max-round/create/shortage banners that now belong to these components. Keep rule and profile query failures in their own surfaces.

Replace the old pending-clear test in `GamesPage.test.tsx` with this full pending-state contract:

```tsx
it("locks lobby mutations while game creation is pending", async () => {
  const user = userEvent.setup();
  gameClientMocks.createGameRun.mockReturnValue(new Promise(() => undefined));
  renderGamesPage();

  await user.click(await screen.findByRole("button", { name: "智能补齐" }));
  await user.click(screen.getByRole("menuitem", { name: "随机补齐" }));
  await user.click(screen.getByText("高级设置 · 随机种子 / 8轮"));
  await user.click(screen.getByRole("button", { name: "开始对局" }));

  expect(screen.getByRole("button", { name: "发起中…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "更换规则" })).toBeDisabled();
  expect(screen.getAllByRole("button", { name: /选择 \d+ 号座位/ })[0]).toBeDisabled();
  expect(screen.getByRole("spinbutton", { name: "种子" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "阵容更多操作" })).toBeDisabled();
});
```

- [ ] **Step 7: Replace old fixed-bar and form CSS contracts**

Style `.mobile-lobby-launch-region` above the tab bar with one status row and one full-width button. Reserve only the computed height required by that bar in `.mobile-lobby-page`; remove the old `repeat(3, ...)`, fill-flyout, and clear-button rules. Keep the settings summary and inputs at 44px minimum target height. Remove the old `App.test.tsx` assertions that lock `+128px` lobby padding and 12px source declarations; Task 8 will verify actual computed values at 320px.

- [ ] **Step 8: Run focused tests and commit**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/LobbyAdvancedSettings.test.tsx src/components/lobby/LobbyLaunchBar.test.tsx src/pages/GamesPage.test.tsx src/app/App.test.tsx
pnpm --dir apps/mobile-web lint
git add apps/mobile-web/src/components/lobby/LobbyAdvancedSettings.tsx apps/mobile-web/src/components/lobby/LobbyAdvancedSettings.test.tsx apps/mobile-web/src/components/lobby/LobbyLaunchBar.tsx apps/mobile-web/src/components/lobby/LobbyLaunchBar.test.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/app/App.test.tsx apps/mobile-web/src/styles/index.css
git commit -m "feat(mobile): simplify lobby settings and launch"
```

Expected: tests and lint PASS; the fixed launch region exposes exactly one button.

---

### Task 6: Replace the Poster Drawer with a Full-Screen Compact Player Picker

**Files:**
- Create: `apps/mobile-web/src/components/lobby/LobbyPlayerPicker.tsx`
- Create: `apps/mobile-web/src/components/lobby/LobbyPlayerPicker.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx:7-17,69-88,236-295,354-509,931-1201`
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx:1152-1832,1877-1900,2218-2637`
- Modify: `apps/mobile-web/src/styles/index.css:886-1652`

**Interfaces:**
- Consumes: active seat, full profile list, pending candidate ID, profile-to-seat map, favorite availability/pending/error state, refresh state/callback, confirm label/state, lobby background ref, and trigger restore ref.
- Produces: a full-screen `LobbyModal` with persistent search, one persistent filter entry, compact rows, favorite actions, refresh behavior, a controlled pending candidate, and one confirmation action.

- [ ] **Step 1: Write failing player-picker component tests**

Create `LobbyPlayerPicker.test.tsx` with these imports, a complete profile factory, and the stateful harness:

```tsx
import { useRef, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PublicPlayerProfileWithFavorite } from "@werewolf-arena/game-client";

import { LobbyPlayerPicker } from "./LobbyPlayerPicker";

function buildProfile(
  id: string,
  overrides: Partial<PublicPlayerProfileWithFavorite> = {},
): PublicPlayerProfileWithFavorite {
  return {
    id,
    display_name: id,
    model: "test-model",
    personality_id: "balanced",
    personality_text: "沉稳控场",
    appearance_id: "default",
    avatar_image_url: "",
    short_description: "先盘逻辑再站边",
    background_story: "",
    speaking_style: "",
    catchphrases: [],
    strategy_profile: "analysis",
    risk_tolerance: 3,
    bluffing_tendency: 3,
    trust_tendency: 3,
    leadership_tendency: 3,
    talkativeness: 3,
    example_messages: [],
    display_order: 1,
    featured: false,
    tags: ["逻辑"],
    is_favorite: false,
    ...overrides,
  };
}

function PickerHarness() {
  const [isOpen, setIsOpen] = useState(true);
  const [pendingProfileId, setPendingProfileId] = useState<string | null>(null);
  const backgroundRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const profiles = [
    buildProfile("alpha", { display_name: "暗巷观星", is_favorite: true }),
    buildProfile("beta", { display_name: "狼啸听风", strategy_profile: "aggressive" }),
  ];

  return (
    <main>
      <div ref={backgroundRef}>
        <button ref={triggerRef} type="button">1号座位</button>
      </div>
      {isOpen ? (
        <LobbyPlayerPicker
          activeSeat={1}
          assignedSeatByProfileId={new Map([["beta", 2]])}
          backgroundRef={backgroundRef}
          canConfirm={pendingProfileId !== null}
          confirmLabel="确认选择"
          favoriteUpdateError={null}
          favoritesAvailable
          isRefreshing={false}
          onClose={() => setIsOpen(false)}
          onConfirm={vi.fn()}
          onPendingProfileIdChange={setPendingProfileId}
          onRefresh={vi.fn().mockResolvedValue(undefined)}
          onToggleFavorite={vi.fn()}
          pendingFavoriteProfileIds={new Set()}
          pendingProfileId={pendingProfileId}
          playerCount={2}
          profiles={profiles}
          profilesError={false}
          restoreFocusRef={triggerRef}
        />
      ) : null}
    </main>
  );
}
```

Add these assertions:

```tsx
it("opens as an isolated full-screen searchable picker", async () => {
  const user = userEvent.setup();
  render(<PickerHarness />);

  const dialog = screen.getByRole("dialog", { name: "玩家卡牌库" });
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(screen.getByRole("searchbox", { name: "搜索玩家" })).toHaveFocus();
  expect(screen.getByRole("button", { name: "筛选玩家，当前 全部玩家、全部策略" })).toBeVisible();

  await user.type(screen.getByRole("searchbox", { name: "搜索玩家" }), "观星");
  expect(screen.getByRole("button", { name: "为 1 号座位候选 暗巷观星" })).toBeVisible();
  expect(screen.queryByText("狼啸听风")).not.toBeInTheDocument();
});

it("shows assignment state and controls a pending candidate", async () => {
  const user = userEvent.setup();
  render(<PickerHarness />);

  expect(screen.getByText("已在 2 号座位")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "为 1 号座位候选 暗巷观星" }));
  expect(screen.getByRole("button", { name: "确认选择" })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "为 1 号座位候选 暗巷观星" }),
  ).toHaveAttribute("aria-pressed", "true");
});

it("closes on Escape without committing", async () => {
  const user = userEvent.setup();
  render(<PickerHarness />);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "玩家卡牌库" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "1号座位" })).toHaveFocus();
});
```

- [ ] **Step 2: Run the picker test and verify it fails**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/LobbyPlayerPicker.test.tsx
```

Expected: FAIL because `LobbyPlayerPicker` does not exist.

- [ ] **Step 3: Define the player-picker public contract**

Create `LobbyPlayerPicker.tsx` with this exact props type:

```tsx
import {
  type RefObject,
  useMemo,
  useRef,
  useState,
} from "react";
import { LoaderCircle, Star, StarCheck } from "lucide-react";
import {
  resolveAvatarImageUrl,
  type PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";

import { MobileBottomSelect } from "../MobileBottomSelect";
import { LobbyModal } from "./LobbyModal";
import {
  filterProfiles,
  formatStrategyLabel,
  getProfileChoiceAriaLabel,
  getProfileSeatStatusLabel,
  getStrategyFilterOptions,
} from "./lobbyModel";

type LobbyPlayerPickerProps = {
  activeSeat: number;
  assignedSeatByProfileId: ReadonlyMap<string, number>;
  backgroundRef: RefObject<HTMLElement | null>;
  canConfirm: boolean;
  confirmLabel: string;
  favoriteUpdateError: string | null;
  favoritesAvailable: boolean;
  isRefreshing: boolean;
  onClose: () => void;
  onConfirm: () => void;
  onPendingProfileIdChange: (profileId: string | null) => void;
  onRefresh: () => Promise<unknown>;
  onToggleFavorite: (profile: PublicPlayerProfileWithFavorite) => void;
  pendingFavoriteProfileIds: ReadonlySet<string>;
  pendingProfileId: string | null;
  playerCount: number;
  profiles: PublicPlayerProfileWithFavorite[];
  profilesError: boolean;
  restoreFocusRef: RefObject<HTMLElement | null>;
};
```

- [ ] **Step 4: Implement local search, combined filter entry, and refresh state**

Inside the component, own only picker-local state:

```tsx
const [search, setSearch] = useState("");
const [favoriteFilter, setFavoriteFilter] = useState<"all" | "favorite">("all");
const [strategyFilter, setStrategyFilter] = useState("all");
const [isFilterPanelOpen, setIsFilterPanelOpen] = useState(false);
const searchRef = useRef<HTMLInputElement | null>(null);
const listRef = useRef<HTMLDivElement | null>(null);
const pullStartRef = useRef<number | null>(null);
const pullDistanceRef = useRef(0);
const [pullDistance, setPullDistance] = useState(0);
const appliedFavoriteFilter = favoritesAvailable ? favoriteFilter : "all";
const filteredProfiles = useMemo(
  () => filterProfiles(profiles, {
    favoriteFilter: appliedFavoriteFilter,
    search,
    strategy: strategyFilter,
  }),
  [appliedFavoriteFilter, profiles, search, strategyFilter],
);
const strategyOptions = useMemo(
  () => getStrategyFilterOptions(profiles),
  [profiles],
);
```

Inside `LobbyModal`, render a `<label className="mobile-profile-search">` containing visible text `搜索玩家` and an `<input aria-label="搜索玩家" ref={searchRef} type="search" value={search} onChange={(event) => setSearch(event.target.value)} />`. Pass `searchRef` as `initialFocusRef`.

Move the current pull handlers from `GamesPage.tsx:444-509` into this component. Replace the query-specific refresh call with this exact completion branch:

```tsx
if (pullDistanceRef.current >= 64) {
  void onRefresh().finally(() => {
    pullStartRef.current = null;
    pullDistanceRef.current = 0;
    setPullDistance(0);
  });
}
```

Render the refresh state at the top of `.mobile-profile-picker-list` so `LoaderCircle`, `isRefreshing`, and `pullDistance` are observable:

```tsx
<div aria-live="polite" className="mobile-profile-refresh-status">
  {isRefreshing ? <LoaderCircle aria-hidden="true" /> : null}
  <span>
    {isRefreshing
      ? "正在刷新玩家"
      : pullDistance >= 64
        ? "松开刷新玩家"
        : ""}
  </span>
</div>
```

Expose one persistent filter button:

```tsx
<button
  aria-expanded={isFilterPanelOpen}
  aria-label={`筛选玩家，当前 ${
    appliedFavoriteFilter === "favorite" ? "只看收藏" : "全部玩家"
  }、${strategyFilter === "all" ? "全部策略" : formatStrategyLabel(strategyFilter)}`}
  className="mobile-profile-filter-trigger"
  onClick={() => setIsFilterPanelOpen((open) => !open)}
  type="button"
>
  筛选
</button>
```

When expanded, render the two values inside one grouped panel; these controls are not mounted while the panel is closed:

```tsx
{isFilterPanelOpen ? (
  <div aria-label="玩家筛选" className="mobile-profile-filter-panel" role="group">
    <MobileBottomSelect
      disabled={!favoritesAvailable}
      label="收藏"
      onChange={setFavoriteFilter}
      options={[
        { label: "全部玩家", value: "all" },
        { label: "只看收藏", value: "favorite" },
      ]}
      value={appliedFavoriteFilter}
    />
    <MobileBottomSelect
      label="策略"
      onChange={setStrategyFilter}
      options={[
        { label: "全部策略", value: "all" },
        ...strategyOptions.map((strategy) => ({
          label: formatStrategyLabel(strategy),
          value: strategy,
        })),
      ]}
      value={strategyFilter}
    />
  </div>
) : null}
```

- [ ] **Step 5: Implement compact player rows and one confirmation action**

Use `LobbyModal` with `searchRef` as initial focus. For every filtered profile render a non-nested pair of controls:

```tsx
const seatStatusLabel = getProfileSeatStatusLabel(
  assignedSeatByProfileId.get(profile.id),
  activeSeat,
);
const avatarUrl = resolveAvatarImageUrl(profile);

return <article className="mobile-profile-row" key={profile.id}>
  <button
    aria-label={getProfileChoiceAriaLabel(
      activeSeat,
      profile,
      seatStatusLabel,
    )}
    aria-pressed={pendingProfileId === profile.id}
    className="mobile-profile-row-select"
    onClick={() => onPendingProfileIdChange(profile.id)}
    type="button"
  >
    {avatarUrl ? (
      <img alt="" aria-hidden="true" src={avatarUrl} />
    ) : (
      <span aria-hidden="true" className="mobile-profile-row-avatar-fallback" />
    )}
    <span className="mobile-profile-row-copy">
      <strong>{profile.display_name}</strong>
      <small>{formatStrategyLabel(profile.strategy_profile)}</small>
      {seatStatusLabel ? <em>{seatStatusLabel}</em> : null}
    </span>
  </button>
  <button
    aria-label={`${profile.is_favorite ? "取消收藏" : "收藏"} ${profile.display_name}`}
    disabled={!favoritesAvailable || pendingFavoriteProfileIds.has(profile.id)}
    onClick={() => onToggleFavorite(profile)}
    type="button"
  >
    {profile.is_favorite ? <StarCheck aria-hidden="true" /> : <Star aria-hidden="true" />}
  </button>
</article>;
```

Use `.mobile-lobby-modal-header` for the header containing `玩家卡牌库`, `当前选择：N号座位`, `已选 X/Y`, and the close button; derive `X` from `assignedSeatByProfileId.size` and `Y` from `playerCount`. Use `.mobile-profile-picker-list` for the scrollable list and `.mobile-profile-picker-footer` for the sticky confirmation area. Render profile-query failure with `重新加载玩家`, favorite degradation/error as `role="status"`/`role="alert"`, and an empty result with a `清除筛选` action that resets search and both filters. Render one footer button using `confirmLabel`, `canConfirm`, and `onConfirm`.

- [ ] **Step 6: Integrate the full-screen picker in `GamesPage`**

Rename `isProfileDrawerOpen` to `isPlayerPickerOpen`, add `playerPickerTriggerRef`, and store the clicked seat button in `openProfileDrawer`. Remove picker-local search/filter/pull refs and state from the page. Replace the drawer JSX with:

```tsx
{isPlayerPickerOpen ? (
  <LobbyPlayerPicker
    activeSeat={safeActiveSeat}
    assignedSeatByProfileId={assignedSeatByProfileId}
    backgroundRef={lobbyContentRef}
    canConfirm={pendingProfile !== null}
    confirmLabel={getConfirmProfileButtonLabel(
      pendingProfile,
      pendingAssignedSeat,
      safeActiveSeat,
    )}
    favoriteUpdateError={favoriteUpdateError}
    favoritesAvailable={favoritesAvailable}
    isRefreshing={isProfileDataFetching}
    onClose={closeProfileDrawer}
    onConfirm={() => confirmPendingProfile()}
    onPendingProfileIdChange={setPendingProfileId}
    onRefresh={() => Promise.all([
      playerProfilesQuery.refetch(),
      favoritesQuery.refetch(),
    ])}
    onToggleFavorite={handleToggleProfileFavorite}
    pendingFavoriteProfileIds={pendingFavoriteProfileIds}
    pendingProfileId={pendingProfileId}
    playerCount={playerCount}
    profiles={profiles}
    profilesError={playerProfilesQuery.isError}
    restoreFocusRef={playerPickerTriggerRef}
  />
) : null}
```

At this task boundary, confirmation keeps the existing single-seat commit/close behavior. Task 7 changes it to automatic next-empty-seat progression.

- [ ] **Step 7: Add full-screen compact-list styles and replace obsolete tests**

Set the picker dialog to `height: 100svh`, with header/search/filter/footer outside the scrollable list. Use compact single-column rows sized so five rows intersect the 320×568 initial list viewport. Give close, filter, favorite, refresh, and confirm controls 44px minimum boxes. Delete tests that require `78svh`, transparent click-through behavior, two poster cards, 100% snap rows, 30px close controls, or three footer columns. Preserve and adapt search, favorite rollback, refresh, stale-candidate, avatar, and close-without-commit tests.

- [ ] **Step 8: Run focused tests and commit**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/lobby/LobbyModal.test.tsx src/components/lobby/LobbyPlayerPicker.test.tsx src/pages/GamesPage.test.tsx
pnpm --dir apps/mobile-web lint
git add apps/mobile-web/src/components/lobby/LobbyPlayerPicker.tsx apps/mobile-web/src/components/lobby/LobbyPlayerPicker.test.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/styles/index.css
git commit -m "feat(mobile): add full-screen lobby player picker"
```

Expected: tests and lint PASS; the old non-modal drawer is no longer rendered.

---

### Task 7: Integrate Continuous Selection, Move Semantics, and Remove Obsolete Lobby Contracts

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx:60-604,606-1204`
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx:1901-2151,2638-2797`
- Modify: `apps/mobile-web/src/components/lobby/LobbyPlayerPicker.tsx`
- Modify: `apps/mobile-web/src/components/lobby/LobbyPlayerPicker.test.tsx`
- Modify: `apps/mobile-web/src/styles/index.css:247-1652`

**Interfaces:**
- Consumes: `upsertSeatProfile`, `findNextEmptySeat`, pending profile and assignment state, active seat, and player-picker controlled callbacks.
- Produces: one-button `确认并下一位`/`完成阵容`/`移动到 N 号座位` behavior, modal focus that stays inside during advance, and a `GamesPage` containing controller logic rather than obsolete presentation state.

- [ ] **Step 1: Rewrite the page tests for automatic progression**

Replace the old separate `确认选择`/`确认并下一位` and outside-seat-focus tests with:

```tsx
it("confirms through empty seats and closes only after completing the lineup", async () => {
  const user = userEvent.setup();
  renderGamesPage();

  await user.click(
    await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  );
  await user.click(
    screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
  );
  await user.click(screen.getByRole("button", { name: "确认并下一位" }));

  const picker = screen.getByRole("dialog", { name: "玩家卡牌库" });
  expect(within(picker).getByText("当前选择：2号座位")).toBeVisible();
  expect(screen.getByRole("searchbox", { name: "搜索玩家" })).toHaveFocus();

  await user.click(
    within(picker).getByRole("button", { name: "为 2 号座位候选 白石" }),
  );
  await user.click(within(picker).getByRole("button", { name: "完成阵容" }));

  expect(screen.queryByRole("dialog", { name: "玩家卡牌库" })).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "选择 1 号座位，当前为 阿青" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "选择 2 号座位，当前为 白石" }),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "开始对局" })).toBeEnabled();
});

it("moves an occupied profile and continues with the next empty seat", async () => {
  const user = userEvent.setup();
  renderGamesPage();

  await user.click(await screen.findByRole("button", {
    name: "选择 1 号座位，当前为 待选择",
  }));
  await user.click(screen.getByRole("button", { name: "为 1 号座位候选 阿青" }));
  await user.click(screen.getByRole("button", { name: "确认并下一位" }));
  await user.click(screen.getByRole("button", { name: "为 2 号座位候选 阿青" }));

  expect(screen.getByRole("button", { name: "移动到 2 号座位" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "移动到 2 号座位" }));
  await user.keyboard("{Escape}");

  expect(
    screen.getByRole("button", { name: "选择 1 号座位，当前为 待选择" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "选择 2 号座位，当前为 阿青" }),
  ).toBeVisible();
});
```

Retain and update the existing stale-candidate and close-without-commit tests so their button labels use `待选择`, the new full-screen picker, and its single confirmation action.

- [ ] **Step 2: Run the page test and verify the new progression test fails**

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL because Task 6 still closes after a single confirmation and still labels the single action `确认选择`.

- [ ] **Step 3: Derive the one-button confirmation state**

In `GamesPage`, derive the next lineup and next empty seat without committing them:

```ts
const pendingNextConfigs = pendingProfile
  ? upsertSeatProfile(
      visiblePlayerConfigs,
      safeActiveSeat,
      pendingProfile.id,
    )
  : null;
const nextEmptySeatAfterConfirm = pendingNextConfigs
  ? findNextEmptySeat(
      pendingNextConfigs,
      playerCount,
      safeActiveSeat,
    )
  : undefined;
const playerPickerConfirmLabel = !pendingProfile
  ? "请选择玩家"
  : pendingAssignedSeat && pendingAssignedSeat !== safeActiveSeat
    ? `移动到 ${safeActiveSeat} 号座位`
    : nextEmptySeatAfterConfirm
      ? "确认并下一位"
      : "完成阵容";
```

Pass `playerPickerConfirmLabel` into `LobbyPlayerPicker` and keep `canConfirm={pendingProfile !== null}`.

- [ ] **Step 4: Replace the optional confirmation modes with one continuous handler**

Use this exact controller behavior:

```ts
function confirmPendingProfile() {
  if (!pendingProfile) return;

  const nextConfigs = upsertSeatProfile(
    visiblePlayerConfigs,
    safeActiveSeat,
    pendingProfile.id,
  );
  const nextEmptySeat = findNextEmptySeat(
    nextConfigs,
    playerCount,
    safeActiveSeat,
  );

  setValidationError(null);
  setShortage(false);
  setPlayerConfigs(nextConfigs);
  setPendingProfileId(null);

  if (nextEmptySeat) {
    setActiveSeat(nextEmptySeat);
    return;
  }

  setIsPlayerPickerOpen(false);
}
```

Do not focus or scroll an inert seat while the modal remains open.

- [ ] **Step 5: Reset search and focus inside the picker when the active seat advances**

Add this effect inside `LobbyPlayerPicker`:

```tsx
useEffect(() => {
  setSearch("");
  const frame = window.requestAnimationFrame(() => searchRef.current?.focus());
  return () => window.cancelAnimationFrame(frame);
}, [activeSeat]);
```

Keep favorite and strategy filters applied across seats; only the seat-specific search and pending candidate reset.

- [ ] **Step 6: Remove obsolete page state, helpers, selectors, and brittle tests**

Delete:

- `ruleScrollRef`, `ruleCardRefs`, `seatButtonRefs`, and `focusSeatAndScrollRowToTop`.
- Page-owned player search/filter/pull state moved into `LobbyPlayerPicker`.
- `mobile-lobby-page-drawer-open` and all old drawer, poster-card, snap-row, three-column footer, rule-dot, page-carousel, fill-flyout, and three-action-bar selectors.
- Unused old button-asset imports and `expectLobbyButtonBackgroundAssets`.
- PNG decoding helpers from `GamesPage.test.tsx` when no remaining test references them.
- `getConfirmProfileButtonLabel` and poster-only description-splitting exports if no new component consumes them.

In the same scoped CSS pass, reduce `.mobile-lobby-hero` to a compact brand strip while preserving `mobile-lobby-hero-banner.png`. Keep high-decoration artwork on the current-rule surface and primary launch action only; render lineup, advanced settings, menus, and player rows as lower-contrast deep panels using the approved 4/8/12/16/24px spacing scale.

Retain tests for rule resizing, profile invalidation, favorite optimistic update/rollback/concurrency, favorite-session recovery, create payload, create failure, shortage, search without tags, stale pending candidate, cross-seat moves, and close-without-commit.

- [ ] **Step 7: Run the complete mobile unit suite and build**

```bash
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web build
pnpm --dir apps/mobile-web lint
```

Expected: all commands PASS; no test requires the old carousel, click-through drawer, poster snap layout, or three fixed actions.

- [ ] **Step 8: Commit the integrated lobby controller cleanup**

```bash
git add apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/components/lobby/LobbyPlayerPicker.tsx apps/mobile-web/src/components/lobby/LobbyPlayerPicker.test.tsx apps/mobile-web/src/styles/index.css
git commit -m "refactor(mobile): complete lobby progressive flow"
```

---

### Task 8: Add Deterministic Responsive E2E Coverage and Final Verification

**Files:**
- Create: `apps/mobile-web/e2e/support/mobile-api-fixtures.ts`
- Create: `apps/mobile-web/e2e/lobby-redesign.spec.ts`
- Modify: `apps/mobile-web/e2e/mobile-navigation.spec.ts:1-72`
- Modify: `apps/mobile-web/src/styles/index.css`
- Test: all mobile tests, lint, build, and configured Playwright projects.

**Interfaces:**
- Consumes: Playwright `Page`, two deterministic rule summaries, eight deterministic public profiles, favorite state, and captured create requests.
- Produces: a reusable fixture installer and browser assertions for hierarchy, modal behavior, geometry, target size, text size, continuous selection, advanced settings, and create payload.

- [ ] **Step 1: Create the shared mobile API fixture installer**

Create `e2e/support/mobile-api-fixtures.ts` with deterministic data and request capture:

```ts
import type { Page } from "@playwright/test";
import type {
  CreateGameRunRequest,
  PublicPlayerProfile,
  RuleSetSummary,
} from "@werewolf-arena/game-client";

export const mobileRuleSets: RuleSetSummary[] = [
  {
    id: "classic_8",
    version: "e2e",
    name: "经典 8 人局",
    player_count: 8,
    role_summary: "2 狼人 / 1 预言家 / 1 守卫 / 4 村民",
    roles: [],
  },
  {
    id: "starter_6",
    version: "e2e",
    name: "新手 6 人快局",
    player_count: 6,
    role_summary: "1 狼人 / 1 预言家 / 1 守卫 / 3 村民",
    roles: [],
  },
];

const profileNames = [
  "暗巷观星",
  "暗牌验心",
  "票台换票",
  "狼啸听风",
  "警徽定狼",
  "警徽低语",
  "雾灯守灯",
  "守夜潜行",
];

export const mobileProfiles: PublicPlayerProfile[] = profileNames.map(
  (displayName, index) => ({
    id: `profile-${index + 1}`,
    display_name: displayName,
    model: "e2e-model",
    personality_id: "balanced",
    personality_text: "沉稳控场",
    appearance_id: "default",
    avatar_image_url: "",
    short_description: "先盘逻辑再给站边",
    background_story: "",
    speaking_style: "",
    catchphrases: [],
    strategy_profile: index % 2 === 0 ? "analysis" : "balanced",
    risk_tolerance: 3,
    bluffing_tendency: 3,
    trust_tendency: 3,
    leadership_tendency: 3,
    talkativeness: 3,
    example_messages: [],
    display_order: index + 1,
    featured: false,
    tags: index % 2 === 0 ? ["逻辑"] : ["均衡"],
  }),
);

type MobileApiFixtureOptions = {
  favoriteProfileIds?: string[];
  profiles?: PublicPlayerProfile[];
  ruleSets?: RuleSetSummary[];
};

export async function installMobileApiFixtures(
  page: Page,
  options: MobileApiFixtureOptions = {},
) {
  const favoriteProfileIds = new Set(options.favoriteProfileIds ?? ["profile-1"]);
  const profiles = options.profiles ?? mobileProfiles;
  const ruleSets = options.ruleSets ?? mobileRuleSets;
  const createRequests: CreateGameRunRequest[] = [];

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === "/api/v1/public/session") {
      await route.fulfill({
        json: {
          viewer: { kind: "guest" },
          csrf_token: "mobile-e2e-csrf",
          session_expires_at: "2099-01-01T00:00:00Z",
        },
      });
      return;
    }

    if (path === "/api/v1/public/me/favorite-player-profiles") {
      await route.fulfill({ json: { profile_ids: [...favoriteProfileIds] } });
      return;
    }

    if (path.startsWith("/api/v1/public/me/favorite-player-profiles/")) {
      const profileId = decodeURIComponent(path.split("/").at(-1) ?? "");
      const isFavorite = request.method() === "PUT";
      if (isFavorite) favoriteProfileIds.add(profileId);
      else favoriteProfileIds.delete(profileId);
      await route.fulfill({ json: { profile_id: profileId, is_favorite: isFavorite } });
      return;
    }

    if (path === "/api/v1/public/player-profiles") {
      await route.fulfill({
        json: {
          items: profiles,
          pagination: { page: 1, page_size: 100, total: profiles.length, pages: 1 },
        },
      });
      return;
    }

    if (path === "/api/v1/games/rule-sets") {
      await route.fulfill({ json: { rule_sets: ruleSets } });
      return;
    }

    if (path === "/api/v1/games/runs" && request.method() === "POST") {
      const body = request.postDataJSON() as CreateGameRunRequest;
      createRequests.push(body);
      await route.fulfill({
        json: {
          run_id: "run-e2e",
          session_id: "session-e2e",
          villager_model: "e2e-model",
          werewolf_model: "e2e-model",
          seed: body.seed ?? null,
          max_rounds: body.max_rounds ?? 8,
          winner: null,
          status: "queued",
          created_at: "2026-07-12T00:00:00Z",
          started_at: null,
          completed_at: null,
          error: null,
          event_count: 0,
          player_configs: body.player_configs ?? [],
        },
      });
      return;
    }

    if (path === "/api/v1/games") {
      await route.fulfill({ json: { sessions: [] } });
      return;
    }

    await route.fulfill({ status: 404, json: { detail: `Unhandled fixture: ${path}` } });
  });

  return { createRequests };
}
```

- [ ] **Step 2: Refactor navigation E2E to reuse the fixture**

Delete the local fixture function and `emptyProfilePage` from `mobile-navigation.spec.ts`. Import `installMobileApiFixtures` and keep:

```ts
test.beforeEach(async ({ page }) => {
  await installMobileApiFixtures(page);
});
```

Run the existing navigation spec after the refactor:

```bash
pnpm --dir apps/mobile-web build
pnpm --dir apps/mobile-web exec playwright test e2e/mobile-navigation.spec.ts --project=small-mobile
```

Expected: PASS.

- [ ] **Step 3: Add hierarchy, rule-change, and continuous-picker E2E coverage**

Create `lobby-redesign.spec.ts` with a fresh fixture per test and add:

```ts
import { expect, test } from "@playwright/test";

import { installMobileApiFixtures } from "./support/mobile-api-fixtures";

test("lobby exposes one rule summary and one fixed launch action", async ({ page }) => {
  await installMobileApiFixtures(page);
  await page.goto("/games");

  const summary = page.getByRole("region", { name: "当前规则" });
  await expect(summary).toContainText("经典 8 人局");
  await expect(page.getByRole("group", { name: "规则选择指示" })).toHaveCount(0);
  await expect(page.locator(".mobile-lobby-rule-scroll")).toHaveCount(0);
  await expect(page.locator(".mobile-lobby-launch-bar").getByRole("button")).toHaveCount(1);

  await summary.getByRole("button", { name: "更换规则" }).click();
  const picker = page.getByRole("dialog", { name: "选择规则" });
  await picker.getByRole("button", { name: "选择规则 新手 6 人快局" }).click();
  await expect(summary).toContainText("新手 6 人快局");
  await expect(
    page.getByRole("button", { name: "选择 6 号座位，当前为 待选择" }),
  ).toBeVisible();
});

test("player confirmation advances inside the same modal", async ({ page }) => {
  await installMobileApiFixtures(page);
  await page.goto("/games");

  await page.getByRole("button", {
    name: "选择 1 号座位，当前为 待选择",
  }).click();
  const picker = page.getByRole("dialog", { name: "玩家卡牌库" });
  await picker.getByRole("button", {
    name: "为 1 号座位候选 暗巷观星",
  }).click();
  await picker.getByRole("button", { name: "确认并下一位" }).click();

  await expect(picker.getByText("当前选择：2号座位")).toBeVisible();
  await expect(picker.getByRole("searchbox", { name: "搜索玩家" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", {
    name: "选择 1 号座位，当前为 暗巷观星",
  })).toBeVisible();
});
```

- [ ] **Step 4: Add the 320×568 geometry and modal accessibility test**

```ts
test("small lobby has readable non-overlapping content and an isolated picker", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "small-mobile", "320x568 geometry contract");
  await installMobileApiFixtures(page);
  await page.goto("/games");

  const secondRowSeat = page.locator(".mobile-lobby-seat-card").nth(4);
  const launchBar = page.locator(".mobile-lobby-launch-region");
  const advanced = page.locator(".mobile-lobby-advanced");
  const [seatBox, launchBox] = await Promise.all([
    secondRowSeat.boundingBox(),
    launchBar.boundingBox(),
  ]);
  expect(seatBox).not.toBeNull();
  expect(launchBox).not.toBeNull();
  expect((seatBox?.y ?? 0) + (seatBox?.height ?? 0)).toBeLessThanOrEqual(
    launchBox?.y ?? 0,
  );

  await advanced.scrollIntoViewIfNeeded();
  const [advancedBox, launchBoxAfterScroll] = await Promise.all([
    advanced.boundingBox(),
    launchBar.boundingBox(),
  ]);
  expect((advancedBox?.y ?? 0) + (advancedBox?.height ?? 0)).toBeLessThanOrEqual(
    launchBoxAfterScroll?.y ?? 0,
  );
  expect(
    await secondRowSeat.locator("strong").evaluate((element) =>
      Number.parseFloat(getComputedStyle(element).fontSize),
    ),
  ).toBeGreaterThanOrEqual(12);

  const firstSeat = page.getByRole("button", {
    name: "选择 1 号座位，当前为 待选择",
  });
  await firstSeat.click();
  const dialog = page.getByRole("dialog", { name: "玩家卡牌库" });
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".mobile-lobby-content")).toHaveAttribute("inert", "");
  await expect(page.getByRole("navigation", { name: "移动端主导航" })).toBeHidden();

  const visibleRows = await page.locator(".mobile-profile-row").evaluateAll((rows) =>
    rows.filter((row) => {
      const rect = row.getBoundingClientRect();
      return rect.bottom > 0 && rect.top < window.innerHeight;
    }).length,
  );
  expect(visibleRows).toBeGreaterThanOrEqual(5);

  const targetSelectors = [
    ".mobile-lobby-modal-header button",
    ".mobile-profile-filter-trigger",
    ".mobile-profile-row > button:last-child",
    ".mobile-profile-picker-footer button",
  ];
  for (const selector of targetSelectors) {
    const box = await page.locator(selector).first().boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(firstSeat).toBeFocused();
});
```

- [ ] **Step 5: Add settings, smart-fill, and create-payload E2E coverage**

```ts
test("smart fill and advanced settings produce the preserved create payload", async ({ page }) => {
  const { createRequests } = await installMobileApiFixtures(page);
  await page.goto("/games");

  await page.getByRole("button", { name: "智能补齐" }).click();
  await page.getByRole("menuitem", { name: "随机补齐" }).click();
  const launch = page.locator(".mobile-lobby-launch-bar").getByRole("button");
  await expect(launch).toHaveAccessibleName("开始对局");

  await page.getByText("高级设置 · 随机种子 / 8轮").click();
  await page.getByRole("spinbutton", { name: "种子" }).fill("42");
  await page.getByRole("spinbutton", { name: "最大轮数" }).fill("10");
  await launch.click();

  await expect.poll(() => createRequests.length).toBe(1);
  expect(createRequests[0]).toMatchObject({
    rule_set_id: "classic_8",
    seed: 42,
    max_rounds: 10,
  });
  expect(createRequests[0].player_configs).toHaveLength(8);
  expect(createRequests[0].player_configs?.map((config) => config.seat)).toEqual([
    1, 2, 3, 4, 5, 6, 7, 8,
  ]);
});
```

- [ ] **Step 6: Run the new E2E spec first at 320×568**

```bash
pnpm --dir apps/mobile-web build
pnpm --dir apps/mobile-web exec playwright test e2e/lobby-redesign.spec.ts --project=small-mobile
```

Expected: PASS. If a geometry assertion fails, adjust only lobby-scoped spacing, fixed-bar height, scroll padding, type size, or target size; do not weaken the numeric contract.

- [ ] **Step 7: Run the complete verification matrix**

```bash
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web lint
pnpm --dir apps/mobile-web build
pnpm --dir apps/mobile-web exec playwright test e2e/mobile-navigation.spec.ts e2e/lobby-redesign.spec.ts
git diff --check
git status --short
```

Expected:

- Unit/component tests PASS.
- Lint PASS.
- Production build and mobile bundle check PASS.
- Both E2E files PASS in `small-mobile`, `ios-mobile`, and `android-mobile` projects.
- `git diff --check` prints nothing.
- `git status --short` contains only the intended Task 8 files before commit; pre-existing `.codex/` audit artifacts remain untracked and must not be staged.

- [ ] **Step 8: Commit the responsive acceptance suite**

```bash
git add apps/mobile-web/e2e/support/mobile-api-fixtures.ts apps/mobile-web/e2e/lobby-redesign.spec.ts apps/mobile-web/e2e/mobile-navigation.spec.ts apps/mobile-web/src/styles/index.css
git commit -m "test(mobile): verify redesigned lobby flow"
```

---

## Final Review Checklist

- [ ] Compare the implementation against every acceptance criterion in `docs/superpowers/specs/2026-07-12-mobile-lobby-redesign-design.md`.
- [ ] Confirm `GamesPage.tsx` contains queries, mutations, derived state, validation, and composition rather than the removed carousel/drawer presentation.
- [ ] Confirm no backend, `game-client`, global viewport, or asset file changed.
- [ ] Confirm the working tree does not stage `.codex/` audit artifacts.
- [ ] Confirm all eight task commits exist in order and each commit was made only after its focused tests passed.
