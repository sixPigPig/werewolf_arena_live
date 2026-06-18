# Mobile Rule Confirm Start Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the mobile game homepage require rule confirmation before quick start or custom start, and let custom start skip rule selection when launched with a confirmed rule.

**Architecture:** Keep the flow inside existing mobile page components. `GameHomePage` owns rule selection and confirmation for the homepage, while `CustomGamePage` reads an optional `ruleSetId` query parameter and initializes its wizard once rule sets load.

**Tech Stack:** React 19, React Router 7, TanStack Query, TypeScript, Vitest, Testing Library.

---

## File Structure

- Modify `apps/mobile-web/src/pages/GameHomePage.tsx`: add rule-set query, selected/confirmed rule state, rule confirmation UI, quick start with confirmed rule, and custom-start link with `ruleSetId`.
- Modify `apps/mobile-web/src/pages/GameHomePage.test.tsx`: mock `listRuleSets()` and cover homepage rule confirmation behavior.
- Modify `apps/mobile-web/src/pages/CustomGamePage.tsx`: read `ruleSetId` with React Router, initialize rule and step after rule sets load, preserve existing no-param behavior.
- Modify `apps/mobile-web/src/pages/CustomGamePage.test.tsx`: render with configurable route and cover query-driven rule initialization.
- Optionally modify `apps/mobile-web/src/styles/index.css`: add compact summary/action styling only if the existing `mobile-card`, `mobile-choice-row`, and `mobile-home-actions` classes are not enough.

### Task 1: Homepage Rule Confirmation Tests

**Files:**
- Modify: `apps/mobile-web/src/pages/GameHomePage.test.tsx`
- Test: `apps/mobile-web/src/pages/GameHomePage.test.tsx`

- [ ] **Step 1: Write the failing tests**

Add `listRuleSets` to the `gamesApi` import and mock:

```ts
import { createGameRun, listGames, listRuleSets } from "../api/gamesApi";
```

```ts
vi.mock("../api/gamesApi", () => ({
  createGameRun: vi.fn(),
  listGames: vi.fn(),
  listRuleSets: vi.fn(),
}));
```

In `beforeEach`, reset and resolve rule sets:

```ts
vi.mocked(listRuleSets).mockReset();
vi.mocked(listRuleSets).mockResolvedValue({
  rule_sets: [
    {
      id: "classic_8",
      version: "1",
      name: "经典 8 人",
      player_count: 8,
      role_summary: "狼人 2 · 好人 6",
    },
    {
      id: "classic_12_seer_witch_hunter_idiot",
      version: "1",
      name: "经典 12 人",
      player_count: 12,
      role_summary: "预女猎白",
    },
  ],
});
```

Add this test:

```ts
it("starts a quick game only after confirming the selected rule", async () => {
  vi.mocked(createGameRun).mockResolvedValue({
    ...gameRunFixture,
    rule_set_id: "classic_8",
    rule_set: {
      id: "classic_8",
      version: "1",
      name: "经典 8 人",
      player_count: 8,
      roles: [],
    },
  });

  renderGameHomePage();

  await screen.findByRole("radio", { name: /经典 8 人/ });

  expect(
    screen.queryByRole("button", { name: "快速开局" }),
  ).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("radio", { name: /经典 8 人/ }));
  await userEvent.click(screen.getByRole("button", { name: "确认规则" }));
  await userEvent.click(screen.getByRole("button", { name: "快速开局" }));

  expect(createGameRun).toHaveBeenCalledWith({
    max_rounds: 8,
    player_configs: [],
    rule_set_id: "classic_8",
  });
  await waitFor(() => {
    expect(navigateMock).toHaveBeenCalledWith("/live/run_mobile_1");
  });
});
```

Add this test:

```ts
it("links custom start to the confirmed rule", async () => {
  renderGameHomePage();

  await screen.findByRole("radio", { name: /经典 8 人/ });
  await userEvent.click(screen.getByRole("radio", { name: /经典 8 人/ }));
  await userEvent.click(screen.getByRole("button", { name: "确认规则" }));

  expect(screen.getByRole("link", { name: "自定义开局" })).toHaveAttribute(
    "href",
    "/custom-game?ruleSetId=classic_8",
  );
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GameHomePage.test.tsx
```

Expected: FAIL because `GameHomePage` does not call `listRuleSets()`, does not render rule radios, and still renders the old one-click start.

### Task 2: Homepage Rule Confirmation Implementation

**Files:**
- Modify: `apps/mobile-web/src/pages/GameHomePage.tsx`
- Test: `apps/mobile-web/src/pages/GameHomePage.test.tsx`

- [ ] **Step 1: Implement the minimal homepage behavior**

Update imports:

```ts
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createGameRun, listGames, listRuleSets } from "../api/gamesApi";
```

Remove:

```ts
const quickStartRuleSetId = "classic_12_seer_witch_hunter_idiot";
```

Inside `GameHomePage`, add rule query and state before the mutation:

```ts
const [selectedRuleSetId, setSelectedRuleSetId] = useState("");
const [confirmedRuleSetId, setConfirmedRuleSetId] = useState("");

const ruleSetsQuery = useQuery({
  queryKey: ["rule-sets"],
  queryFn: listRuleSets,
});

const ruleSets = useMemo(
  () => ruleSetsQuery.data?.rule_sets ?? [],
  [ruleSetsQuery.data?.rule_sets],
);
const activeRule = useMemo(
  () =>
    ruleSets.find((ruleSet) => ruleSet.id === selectedRuleSetId) ??
    ruleSets[0],
  [ruleSets, selectedRuleSetId],
);
const confirmedRule = useMemo(
  () =>
    ruleSets.find((ruleSet) => ruleSet.id === confirmedRuleSetId) ?? null,
  [ruleSets, confirmedRuleSetId],
);
```

Replace the hero copy and action area with:

```tsx
<div className="mobile-hero-panel">
  <p className="mobile-kicker">大厅</p>
  <h2>先确认今晚规则</h2>
  <p>选定规则后，可以直接快速开局，也可以带着规则进入自定义阵容。</p>

  {!confirmedRule ? (
    <>
      {ruleSetsQuery.isLoading ? <p>正在读取规则预设...</p> : null}
      {ruleSetsQuery.isError ? (
        <StatusBanner title="规则读取失败" tone="error">
          <p>规则预设暂时无法加载，请稍后再试。</p>
        </StatusBanner>
      ) : null}
      {!ruleSetsQuery.isLoading && !ruleSetsQuery.isError && ruleSets.length === 0 ? (
        <p>暂无可用规则预设。</p>
      ) : null}
      {ruleSets.map((ruleSet) => (
        <label className="mobile-choice-row" key={ruleSet.id}>
          <input
            checked={activeRule?.id === ruleSet.id}
            name="home-rule-set"
            onChange={() => {
              setSelectedRuleSetId(ruleSet.id);
            }}
            type="radio"
          />
          <span>
            <strong>{ruleSet.name}</strong>
            <span>
              {ruleSet.player_count} 人
              {ruleSet.role_summary ? ` · ${ruleSet.role_summary}` : ""}
            </span>
          </span>
        </label>
      ))}
      <MobileButton
        disabled={!activeRule || createRunMutation.isPending}
        onClick={() => {
          if (activeRule) {
            setConfirmedRuleSetId(activeRule.id);
          }
        }}
        tone="primary"
      >
        确认规则
      </MobileButton>
    </>
  ) : (
    <>
      <div className="mobile-list-row">
        <div>
          <strong>{confirmedRule.name}</strong>
          <p>
            {confirmedRule.player_count} 人
            {confirmedRule.role_summary ? ` · ${confirmedRule.role_summary}` : ""}
          </p>
        </div>
        <MobileButton
          disabled={createRunMutation.isPending}
          onClick={() => {
            setConfirmedRuleSetId("");
          }}
        >
          更换规则
        </MobileButton>
      </div>
      <div className="mobile-home-actions">
        <MobileButton
          disabled={createRunMutation.isPending}
          onClick={() => {
            createRunMutation.mutate({
              max_rounds: 8,
              player_configs: [],
              rule_set_id: confirmedRule.id,
            });
          }}
          tone="primary"
        >
          {createRunMutation.isPending ? "开局中..." : "快速开局"}
        </MobileButton>
        <Link
          className="mobile-link-button"
          to={`/custom-game?ruleSetId=${encodeURIComponent(confirmedRule.id)}`}
        >
          自定义开局
        </Link>
      </div>
    </>
  )}

  {createRunMutation.isError ? (
    <StatusBanner title="开局失败" tone="error">
      <p>{mutationErrorMessage(createRunMutation.error)}</p>
    </StatusBanner>
  ) : null}
</div>
```

- [ ] **Step 2: Run homepage tests to verify they pass**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GameHomePage.test.tsx
```

Expected: PASS for the new homepage rule confirmation tests and existing recent-game test.

### Task 3: Custom Game Query Parameter Tests

**Files:**
- Modify: `apps/mobile-web/src/pages/CustomGamePage.test.tsx`
- Test: `apps/mobile-web/src/pages/CustomGamePage.test.tsx`

- [ ] **Step 1: Write the failing tests**

Change the render helper to accept a route:

```ts
function renderCustomGamePage(route = "/custom-game") {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <CustomGamePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
```

Add this test:

```ts
it("starts at player selection when a valid ruleSetId is provided", async () => {
  renderCustomGamePage("/custom-game?ruleSetId=classic_12");

  expect(
    await screen.findByRole("heading", { name: "玩家选择" }),
  ).toBeInTheDocument();
  expect(screen.getByText("第 2 步 / 共 4 步")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("checkbox", { name: /夜鸦/ }));
  await userEvent.click(screen.getByRole("button", { name: "下一步" }));
  await userEvent.click(screen.getByRole("button", { name: "下一步" }));
  await userEvent.click(screen.getByRole("button", { name: "确认开局" }));

  expect(createGameRun).toHaveBeenCalledWith(
    expect.objectContaining({
      player_configs: [{ seat: 1, profile_id: "p1" }],
      rule_set_id: "classic_12",
    }),
  );
});
```

Add this no-param guard test:

```ts
it("starts at rule selection without a ruleSetId parameter", async () => {
  renderCustomGamePage();

  expect(
    await screen.findByRole("heading", { name: "规则预设" }),
  ).toBeInTheDocument();
  expect(screen.getByText("第 1 步 / 共 4 步")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/CustomGamePage.test.tsx
```

Expected: FAIL for the valid `ruleSetId` test because `CustomGamePage` does not read the URL query parameter yet.

### Task 4: Custom Game Query Parameter Implementation

**Files:**
- Modify: `apps/mobile-web/src/pages/CustomGamePage.tsx`
- Test: `apps/mobile-web/src/pages/CustomGamePage.test.tsx`

- [ ] **Step 1: Implement query-driven initialization**

Update imports:

```ts
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
```

Inside `CustomGamePage`, after `const navigate = useNavigate();`, add:

```ts
const [searchParams] = useSearchParams();
const ruleSetIdFromQuery = searchParams.get("ruleSetId") ?? "";
const didInitializeRuleSetFromQuery = useRef(false);
```

After `ruleSets` is declared, add:

```ts
useEffect(() => {
  if (
    didInitializeRuleSetFromQuery.current ||
    !ruleSetIdFromQuery ||
    ruleSets.length === 0
  ) {
    return;
  }

  didInitializeRuleSetFromQuery.current = true;
  const queryRule = ruleSets.find((ruleSet) => ruleSet.id === ruleSetIdFromQuery);

  if (!queryRule) {
    return;
  }

  setSelectedRuleSetId(queryRule.id);
  setSelectedProfileIds((current) => current.slice(0, queryRule.player_count));
  setStep(1);
}, [ruleSetIdFromQuery, ruleSets]);
```

- [ ] **Step 2: Run custom page tests to verify they pass**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/CustomGamePage.test.tsx
```

Expected: PASS for the new query-parameter tests and existing wizard tests.

### Task 5: Full Mobile Verification

**Files:**
- Verify: `apps/mobile-web/src/pages/GameHomePage.tsx`
- Verify: `apps/mobile-web/src/pages/CustomGamePage.tsx`
- Verify: `apps/mobile-web/src/pages/GameHomePage.test.tsx`
- Verify: `apps/mobile-web/src/pages/CustomGamePage.test.tsx`

- [ ] **Step 1: Run focused tests**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GameHomePage.test.tsx src/pages/CustomGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run all mobile tests**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run:

```bash
pnpm --dir apps/mobile-web lint
```

Expected: PASS with no ESLint errors.

- [ ] **Step 4: Run build**

Run:

```bash
pnpm --dir apps/mobile-web build
```

Expected: PASS, including TypeScript project build and Vite production build.

- [ ] **Step 5: Review git diff**

Run:

```bash
git diff -- apps/mobile-web/src/pages/GameHomePage.tsx apps/mobile-web/src/pages/GameHomePage.test.tsx apps/mobile-web/src/pages/CustomGamePage.tsx apps/mobile-web/src/pages/CustomGamePage.test.tsx
```

Expected: diff only includes rule confirmation flow, query-parameter initialization, and tests for those behaviors.

- [ ] **Step 6: Commit implementation**

Run:

```bash
git add apps/mobile-web/src/pages/GameHomePage.tsx apps/mobile-web/src/pages/GameHomePage.test.tsx apps/mobile-web/src/pages/CustomGamePage.tsx apps/mobile-web/src/pages/CustomGamePage.test.tsx
git commit -m "feat: confirm mobile rules before starting"
```

Expected: commit succeeds after tests, lint, and build pass.
