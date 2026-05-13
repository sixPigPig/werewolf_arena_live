# Lobby Console Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the `/games` lobby into a compact gothic control console with a top create-run bar, horizontal official rule cards, and the existing selected-rule detail panel preserved below.

**Architecture:** Keep the existing `GamesPage -> GamesWorkspace -> CreateGameRunForm` flow and move only the visual title into `CreateGameRunForm`. Use component class hooks plus CSS in `index.css` for the new console and rule panel, while preserving current query, selection, validation, submit payload, and navigation behavior.

**Tech Stack:** React 19, React Router 7, TanStack Query 5, Vitest, Testing Library, Tailwind 4 CSS utilities plus project CSS.

---

## File Structure

- Modify `apps/web/src/pages/GamesPage.test.tsx`: add assertions for the new lobby console structure and preserved rule detail placement.
- Modify `apps/web/src/pages/components/GamesWorkspace.tsx`: remove the standalone page heading and leave the workspace as the full-width shell and scroll target wrapper.
- Modify `apps/web/src/features/games/components/CreateGameRunForm.tsx`: restructure the form into top console, rules panel, and selected details while keeping state and submit logic unchanged.
- Modify `apps/web/src/styles/index.css`: add `lobby-*` classes for panels, responsive grids, compact fields, gothic rule cards, selected details, and mobile behavior.

## Task 1: Lock the Lobby Console Structure With a Failing Test

**Files:**
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Update the first lobby test expectations**

In `renders the lobby without the game history list`, replace the current create module class expectation:

```ts
expect(screen.getByTestId("games-create-module")).toHaveClass(
  "glass-panel",
);
```

with:

```ts
const createModule = screen.getByTestId("games-create-module");
expect(createModule).toHaveClass(
  "games-create-module",
  "lobby-console-form",
);
expect(createModule).not.toHaveClass("glass-panel");

const consoleBar = within(createModule).getByTestId("lobby-console-bar");
expect(
  within(consoleBar).getByRole("heading", { name: "狼人杀对局大厅" }),
).toBeInTheDocument();
expect(within(consoleBar).getByLabelText("随机种子")).toBeInTheDocument();
expect(within(consoleBar).getByLabelText("最大轮数")).toBeInTheDocument();
expect(
  within(consoleBar).getByRole("combobox", { name: "演示慢速" }),
).toBeInTheDocument();
expect(
  within(consoleBar).getByRole("button", { name: "发起对局" }),
).toHaveClass("gothic-button");

const rulesPanel = within(createModule).getByTestId("lobby-rules-panel");
expect(within(rulesPanel).getByText("官方规则")).toBeInTheDocument();
expect(
  within(rulesPanel).getByRole("radiogroup", { name: "官方规则" }),
).toHaveClass("lobby-rule-grid");
```

Keep the existing `screen.getByRole("heading", { name: "狼人杀对局大厅" })` assertion near the top of the test. It should continue to pass after the heading moves inside the form.

- [ ] **Step 2: Add a detail placement assertion**

In the same test, after `const officialRuleCards = await screen.findByRole("radiogroup", { name: "官方规则" });`, add:

```ts
expect(screen.getByTestId("lobby-rules-panel")).toContainElement(
  officialRuleCards,
);
expect(screen.getByTestId("games-create-module")).toContainElement(
  screen.getByTestId("selected-rule-details"),
);
```

- [ ] **Step 3: Run the focused test and verify it fails for the new structure**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL because `lobby-console-form`, `lobby-console-bar`, `lobby-rules-panel`, and `lobby-rule-grid` do not exist yet, and the submit button is not gothic inside the form.

## Task 2: Restructure the Lobby Components

**Files:**
- Modify: `apps/web/src/pages/components/GamesWorkspace.tsx`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`

- [ ] **Step 1: Simplify the workspace shell**

Replace `apps/web/src/pages/components/GamesWorkspace.tsx` with:

```tsx
import { CreateGameRunForm } from "../../features/games/components/CreateGameRunForm";
import type { RefObject } from "react";

type GamesWorkspaceProps = {
  createFormRef: RefObject<HTMLDivElement | null>;
};

export function GamesWorkspace({ createFormRef }: GamesWorkspaceProps) {
  return (
    <main
      className="games-workspace-module lobby-page-shell mx-auto w-full max-w-none px-4 py-5 sm:px-6 lg:px-8"
      data-testid="games-workspace-module"
    >
      <div ref={createFormRef}>
        <CreateGameRunForm />
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Remove `Card` from the create form imports**

At the top of `apps/web/src/features/games/components/CreateGameRunForm.tsx`, remove `Card` from the UI import list:

```tsx
import {
  Badge,
  Button,
  Callout,
  Flex,
  RadioCards,
  SelectField,
  Text,
  TextField,
} from "../../../components/ui";
```

- [ ] **Step 3: Replace the form wrapper and top controls**

In `CreateGameRunForm`, replace the current `return (` block from `<Card asChild size="2">` through the closing `</Card>` with this structure, keeping the existing submit handler body exactly as shown:

```tsx
return (
  <form
    className="games-create-module lobby-console-form"
    data-testid="games-create-module"
    noValidate
    onSubmit={(event) => {
      event.preventDefault();
      const parsedMaxRounds = Number(maxRounds);
      if (
        !maxRounds ||
        !Number.isInteger(parsedMaxRounds) ||
        parsedMaxRounds < 1 ||
        parsedMaxRounds > 20
      ) {
        setValidationError("最大轮数必须是 1 到 20 的整数");
        return;
      }

      setValidationError(null);
      mutation.mutate({
        rule_set_id: selectedRuleSetId,
        seed: seed ? Number(seed) : null,
        max_rounds: parsedMaxRounds,
        event_pacing: eventPacing,
      });
    }}
  >
    <section className="lobby-console-bar" data-testid="lobby-console-bar">
      <div className="lobby-console-title-block">
        <h1 className="lobby-console-title">狼人杀对局大厅</h1>
      </div>
      <div className="lobby-console-controls" data-testid="lobby-console-controls">
        <label className="lobby-console-field lobby-console-field-seed">
          <span className="lobby-console-field-label">随机种子</span>
          <TextField.Root
            className="lobby-console-input"
            inputMode="numeric"
            placeholder="可留空"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
          />
        </label>
        <label className="lobby-console-field lobby-console-field-rounds">
          <span className="lobby-console-field-label">最大轮数</span>
          <TextField.Root
            className="lobby-console-input"
            min={1}
            max={20}
            required
            type="number"
            value={maxRounds}
            onChange={(event) => {
              setMaxRounds(event.target.value);
              setValidationError(null);
            }}
          />
        </label>
        <div className="lobby-console-field lobby-console-field-pacing">
          <span className="lobby-console-field-label" id="event-pacing-label">
            演示慢速
          </span>
          <SelectField
            aria-labelledby="event-pacing-label"
            className="lobby-console-select"
            value={eventPacing}
            onChange={(event) =>
              setEventPacing(event.target.value as EventPacingMode)
            }
          >
            <option value="off">关闭</option>
            <option value="standard">标准演示</option>
            <option value="slow">慢速讲解</option>
          </SelectField>
        </div>
        <Button
          className="lobby-console-launch"
          disabled={isSubmitDisabled}
          intent="warning"
          loading={mutation.isPending}
          size="1"
          skin="gothic"
          type="submit"
        >
          发起对局
        </Button>
      </div>
    </section>

    <fieldset className="lobby-rules-panel" data-testid="lobby-rules-panel">
      <legend className="lobby-rules-legend">
        <span aria-hidden="true" className="lobby-rules-legend-mark" />
        官方规则
      </legend>
      {ruleSetsQuery.isPending ? (
        <p className="lobby-rules-status">正在读取官方规则...</p>
      ) : null}
      {ruleSetsQuery.isError ? (
        <p className="lobby-rules-error">无法读取官方规则</p>
      ) : null}
      {ruleSets.length > 0 ? (
        <div className="lobby-rules-content">
          <RadioCards.Root
            aria-label="官方规则"
            className="lobby-rule-grid"
            highContrast
            onValueChange={setSelectedRuleSetId}
            value={selectedRuleSetId}
            variant="surface"
          >
            {ruleSets.map(renderRuleCard)}
          </RadioCards.Root>
          {selectedRuleSet ? <SelectedRuleDetails rule={selectedRuleSet} /> : null}
        </div>
      ) : null}
    </fieldset>

    {validationError ? (
      <Callout.Root className="lobby-form-callout" color="red" size="1" variant="soft">
        <Callout.Text>{validationError}</Callout.Text>
      </Callout.Root>
    ) : null}
    {mutation.isError ? (
      <Callout.Root className="lobby-form-callout" color="red" size="1" variant="soft">
        <Callout.Text>无法发起对局</Callout.Text>
      </Callout.Root>
    ) : null}
  </form>
);
```

- [ ] **Step 4: Run the focused test and verify the structure still needs rule-card classes**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL only on rule card visual class assertions or CSS-independent expectations that are not implemented yet. Submit payload and selected-rule behavior should still pass.

## Task 3: Convert Rule Cards and Details to the New Class Hooks

**Files:**
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`

- [ ] **Step 1: Replace `renderRuleCard` markup**

Replace the body of `renderRuleCard` with:

```tsx
const roleSummary = formatRoleSummary(rule);
const isSelected = selectedRuleSetId === rule.id;

return (
  <RadioCards.Item
    aria-label={rule.name}
    className={[
      "lobby-rule-card",
      isSelected ? "lobby-rule-card-selected" : "",
    ].join(" ")}
    key={rule.id}
    value={rule.id}
  >
    <span aria-hidden="true" className="lobby-rule-card-glint" />
    <div className="lobby-rule-card-body">
      <span
        aria-hidden="true"
        className={[
          "lobby-rule-emblem",
          isSelected ? "lobby-rule-emblem-selected" : "",
        ].join(" ")}
      >
        {getRuleEmblem(rule)}
      </span>
      <div className="lobby-rule-copy">
        <Text as="span" className="lobby-rule-name" size="3" weight="bold">
          {rule.name}
        </Text>
        <Text as="span" className="lobby-rule-meta" size="2">
          {rule.player_count} 人 · {rule.complexity ?? "标准"} ·{" "}
          {rule.estimated_duration ?? "中"}
        </Text>
        <Text as="span" className="lobby-rule-roles" size="2">
          {roleSummary}
        </Text>
        {rule.rule_tags && rule.rule_tags.length > 0 ? (
          <Flex className="lobby-rule-tags" gap="1" wrap="wrap">
            {rule.rule_tags.map((tag) => (
              <Badge className="lobby-rule-tag" color="gray" key={tag} variant="surface">
                {tag}
              </Badge>
            ))}
          </Flex>
        ) : null}
      </div>
    </div>
  </RadioCards.Item>
);
```

- [ ] **Step 2: Replace selected rule details classes**

In `SelectedRuleDetails`, replace the `<section>` class with:

```tsx
className="lobby-rule-details"
```

Replace the decorative background glyph class with:

```tsx
className="lobby-rule-details-glyph"
```

Replace the header wrapper class with:

```tsx
className="lobby-rule-details-header"
```

Replace the details emblem class with:

```tsx
className="lobby-rule-details-emblem"
```

Replace the title wrapper `<div className="min-w-0">` with:

```tsx
<div className="lobby-rule-details-title-block">
```

Replace the `<h3>` class with:

```tsx
className="lobby-rule-details-title"
```

Replace the description `<p>` class with:

```tsx
className="lobby-rule-details-description"
```

Replace the `<dl>` class with:

```tsx
className="lobby-rule-details-list"
```

Replace each row class with:

```tsx
className="lobby-rule-details-row"
```

Replace the `<dt>` class with:

```tsx
className="lobby-rule-details-label"
```

Replace the `<dd>` class with:

```tsx
className="lobby-rule-details-value"
```

- [ ] **Step 3: Run the focused test**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
```

Expected: PASS for behavior and structure. Visual polish still needs CSS.

## Task 4: Add the Lobby Console CSS

**Files:**
- Modify: `apps/web/src/styles/index.css`

- [ ] **Step 1: Add page, panel, and control CSS**

Insert this CSS before `.gothic-button`:

```css
.lobby-page-shell {
  min-height: calc(100svh - var(--arena-nav-height, var(--app-top-nav-height, 56px)));
}

.lobby-console-form {
  display: flex;
  width: min(92rem, 100%);
  flex-direction: column;
  gap: 0.62rem;
  margin: 0 auto;
}

.lobby-console-bar,
.lobby-rules-panel,
.lobby-rule-details {
  position: relative;
  border: 1px solid rgb(185 147 92 / 44%);
  border-radius: 0.35rem;
  background:
    linear-gradient(180deg, rgb(6 11 15 / 88%), rgb(1 5 10 / 78%)),
    radial-gradient(circle at 50% 0%, rgb(224 178 103 / 10%), transparent 42%);
  box-shadow:
    inset 0 1px 0 rgb(255 230 184 / 12%),
    inset 0 0 28px rgb(0 0 0 / 52%),
    0 14px 34px rgb(0 0 0 / 26%);
}

.lobby-console-bar::before,
.lobby-rules-panel::before,
.lobby-rule-details::before {
  position: absolute;
  inset: 0.32rem;
  content: "";
  border: 1px solid rgb(185 147 92 / 18%);
  border-radius: 0.22rem;
  pointer-events: none;
}

.lobby-console-bar {
  display: grid;
  grid-template-columns: minmax(12rem, 1fr) minmax(0, 4.35fr);
  align-items: center;
  gap: 1rem;
  min-height: 3.75rem;
  padding: 0.48rem 0.78rem;
}

.lobby-console-title-block,
.lobby-console-controls,
.lobby-rules-content,
.lobby-rule-card-body,
.lobby-rule-details-header,
.lobby-rule-details-list {
  position: relative;
  z-index: 1;
}

.lobby-console-title {
  margin: 0;
  color: #f0dfc8;
  font-family: Georgia, "Times New Roman", "Noto Serif SC", serif;
  font-size: 1.35rem;
  font-weight: 800;
  line-height: 1.1;
  text-shadow:
    0 1px 0 rgb(0 0 0 / 72%),
    0 0 18px rgb(238 190 111 / 18%);
}

.lobby-console-controls {
  display: grid;
  grid-template-columns:
    minmax(9.5rem, 0.95fr)
    minmax(8rem, 0.72fr)
    minmax(13rem, 1.35fr)
    minmax(8.5rem, auto);
  align-items: end;
  gap: 0.72rem;
}

.lobby-console-field {
  display: flex;
  min-width: 0;
  flex-direction: row;
  align-items: center;
  gap: 0.48rem;
  color: #e7d2ad;
  font-family: Georgia, "Times New Roman", "Noto Serif SC", serif;
  font-size: 0.86rem;
  font-weight: 800;
  white-space: nowrap;
}

.lobby-console-field-label {
  display: inline-flex;
  align-items: center;
  min-height: 2.1rem;
  border: 1px solid rgb(185 147 92 / 34%);
  border-radius: 0.18rem;
  background: rgb(10 13 17 / 70%);
  padding: 0 0.74rem;
  color: #e8c982;
  text-shadow: 0 1px 0 rgb(0 0 0 / 78%);
}

.lobby-console-input,
.lobby-console-select {
  width: 100%;
  min-width: 0;
  height: 2.1rem;
  border-color: rgb(134 146 158 / 42%) !important;
  border-radius: 0.18rem !important;
  background: rgb(3 8 13 / 78%) !important;
  color: #e8eef4 !important;
  font-family: "Inter", "Segoe UI", sans-serif;
  font-size: 0.9rem;
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 6%),
    inset 0 -1px 0 rgb(0 0 0 / 56%);
}

.lobby-console-select option {
  background: #050910;
  color: #e8eef4;
}

.lobby-console-launch {
  justify-self: end;
}

.lobby-rules-panel {
  min-width: 0;
  margin: 0;
  padding: 1.8rem 0.78rem 0.78rem;
}

.lobby-rules-legend {
  position: relative;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  margin-left: 0.28rem;
  padding: 0 0.4rem;
  color: #e8c982;
  font-family: Georgia, "Times New Roman", "Noto Serif SC", serif;
  font-size: 0.92rem;
  font-weight: 800;
  text-shadow: 0 1px 0 rgb(0 0 0 / 78%);
}

.lobby-rules-legend-mark {
  width: 0.72rem;
  height: 0.72rem;
  border: 1px solid rgb(232 201 130 / 72%);
  transform: rotate(45deg);
}

.lobby-rules-content {
  display: flex;
  flex-direction: column;
  gap: 0.78rem;
}

.lobby-rules-status,
.lobby-rules-error,
.lobby-form-callout {
  position: relative;
  z-index: 1;
  margin-top: 0.5rem;
}

.lobby-rules-status {
  color: #c7d0da;
  font-size: 0.9rem;
}

.lobby-rules-error {
  color: #fca5a5;
  font-size: 0.9rem;
}
```

- [ ] **Step 2: Add rule card and details CSS**

Insert this CSS after the block from Step 1 and before `.gothic-button`:

```css
.lobby-rule-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.62rem;
}

.lobby-rule-card {
  position: relative;
  min-height: 8.15rem;
  overflow: hidden;
  border-color: rgb(134 146 158 / 42%) !important;
  border-radius: 0.25rem !important;
  background:
    linear-gradient(180deg, rgb(8 15 20 / 84%), rgb(2 7 12 / 88%)),
    radial-gradient(circle at 18% 35%, rgb(130 153 166 / 12%), transparent 34%);
  padding: 0.82rem !important;
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 7%),
    inset 0 -1px 0 rgb(0 0 0 / 54%);
}

.lobby-rule-card::before,
.lobby-rule-card::after {
  position: absolute;
  width: 0.62rem;
  height: 0.62rem;
  content: "";
  border-color: rgb(185 147 92 / 42%);
  pointer-events: none;
}

.lobby-rule-card::before {
  top: 0.2rem;
  left: 0.2rem;
  border-top: 1px solid;
  border-left: 1px solid;
}

.lobby-rule-card::after {
  right: 0.2rem;
  bottom: 0.2rem;
  border-right: 1px solid;
  border-bottom: 1px solid;
}

.lobby-rule-card:hover {
  border-color: rgb(232 201 130 / 62%) !important;
  filter: brightness(1.08);
}

.lobby-rule-card-selected {
  border-color: rgb(232 201 130 / 82%) !important;
  background:
    linear-gradient(180deg, rgb(31 28 18 / 86%), rgb(5 8 12 / 90%)),
    radial-gradient(circle at 18% 35%, rgb(238 190 111 / 18%), transparent 36%);
  box-shadow:
    0 0 0 1px rgb(232 201 130 / 24%),
    0 0 22px rgb(238 190 111 / 16%),
    inset 0 1px 0 rgb(255 230 184 / 13%),
    inset 0 -1px 0 rgb(0 0 0 / 54%);
}

.lobby-rule-card-glint {
  position: absolute;
  top: 0;
  right: 0.8rem;
  left: 0.8rem;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgb(232 201 130 / 46%), transparent);
  opacity: 0;
}

.lobby-rule-card-selected .lobby-rule-card-glint,
.lobby-rule-card:hover .lobby-rule-card-glint {
  opacity: 1;
}

.lobby-rule-card-body {
  display: flex;
  height: 100%;
  min-width: 0;
  align-items: center;
  gap: 0.82rem;
}

.lobby-rule-emblem {
  display: grid;
  width: 3.4rem;
  height: 3.4rem;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid rgb(180 192 203 / 42%);
  border-radius: 999px;
  background:
    radial-gradient(circle at 50% 35%, rgb(238 190 111 / 18%), transparent 48%),
    radial-gradient(circle, rgb(28 35 42 / 86%), rgb(5 8 12 / 92%));
  color: #d8e0e7;
  font-family: Georgia, "Times New Roman", "Noto Serif SC", serif;
  font-size: 1.35rem;
  font-weight: 800;
  box-shadow:
    inset 0 0 0 0.25rem rgb(0 0 0 / 28%),
    0 8px 16px rgb(0 0 0 / 30%);
}

.lobby-rule-emblem-selected {
  border-color: rgb(232 201 130 / 72%);
  color: #f0dfc8;
  box-shadow:
    inset 0 0 0 0.25rem rgb(0 0 0 / 26%),
    0 0 18px rgb(238 190 111 / 20%);
}

.lobby-rule-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.24rem;
}

.lobby-rule-name {
  overflow-wrap: anywhere;
  color: #f0dfc8;
  font-family: Georgia, "Times New Roman", "Noto Serif SC", serif;
  font-size: 1.05rem;
  line-height: 1.28;
}

.lobby-rule-meta {
  color: #c7d0da;
  line-height: 1.25;
}

.lobby-rule-roles {
  overflow-wrap: anywhere;
  color: #e5edf4;
  line-height: 1.35;
}

.lobby-rule-tags {
  margin-top: 0.16rem;
}

.lobby-rule-tag {
  border-color: rgb(232 201 130 / 35%);
  border-radius: 0.22rem;
  background: rgb(6 10 15 / 42%);
  color: #efd9b5;
}

.lobby-rule-details {
  overflow: hidden;
  padding: 1rem 1.1rem;
}

.lobby-rule-details-glyph {
  position: absolute;
  right: 1.6rem;
  bottom: 0.8rem;
  display: block;
  width: 7rem;
  height: 7rem;
  border: 1px solid rgb(232 201 130 / 9%);
  border-radius: 999px;
  color: rgb(240 223 200 / 5%);
  font-family: Georgia, "Times New Roman", "Noto Serif SC", serif;
  font-size: 4rem;
  line-height: 7rem;
  text-align: center;
}

.lobby-rule-details-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.lobby-rule-details-emblem {
  display: grid;
  width: 3rem;
  height: 3rem;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid rgb(232 201 130 / 54%);
  border-radius: 999px;
  background: rgb(238 190 111 / 10%);
  color: #f0dfc8;
  font-family: Georgia, "Times New Roman", "Noto Serif SC", serif;
  font-size: 1.35rem;
}

.lobby-rule-details-title-block {
  min-width: 0;
}

.lobby-rule-details-title {
  margin: 0;
  overflow-wrap: anywhere;
  color: #f0dfc8;
  font-family: Georgia, "Times New Roman", "Noto Serif SC", serif;
  font-size: 1.35rem;
  font-weight: 800;
  line-height: 1.35;
}

.lobby-rule-details-description {
  margin: 0.2rem 0 0;
  color: #c7d0da;
  font-size: 0.9rem;
}

.lobby-rule-details-list {
  margin: 0.82rem 0 0;
  border-top: 1px solid rgb(232 201 130 / 12%);
}

.lobby-rule-details-row {
  display: grid;
  grid-template-columns: 7.5rem minmax(0, 1fr);
  gap: 0.75rem;
  padding: 0.48rem 0;
  border-bottom: 1px solid rgb(232 201 130 / 10%);
}

.lobby-rule-details-label {
  color: #e8c982;
  font-size: 0.88rem;
  font-weight: 800;
}

.lobby-rule-details-value {
  color: #eef4f8;
  font-size: 0.9rem;
  line-height: 1.55;
}
```

- [ ] **Step 3: Add responsive CSS**

Insert this CSS after the rule details block:

```css
@media (max-width: 1180px) {
  .lobby-console-bar {
    grid-template-columns: 1fr;
    gap: 0.7rem;
  }

  .lobby-console-controls {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .lobby-console-launch {
    justify-self: stretch;
  }

  .lobby-rule-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .lobby-console-form {
    gap: 0.75rem;
  }

  .lobby-console-bar,
  .lobby-rules-panel,
  .lobby-rule-details {
    border-radius: 0.28rem;
  }

  .lobby-console-controls,
  .lobby-rule-grid,
  .lobby-rule-details-row {
    grid-template-columns: 1fr;
  }

  .lobby-console-field {
    flex-direction: column;
    align-items: stretch;
    white-space: normal;
  }

  .lobby-console-field-label {
    min-height: auto;
    padding: 0.32rem 0.55rem;
  }

  .lobby-rule-card {
    min-height: 7.4rem;
  }

  .lobby-rule-details-glyph {
    display: none;
  }
}
```

- [ ] **Step 4: Run the focused test**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx
```

Expected: PASS.

## Task 5: Build and Browser-Verify the Lobby

**Files:**
- No source file changes expected.

- [ ] **Step 1: Run the web build**

Run:

```bash
pnpm --dir apps/web build
```

Expected: exit code 0.

- [ ] **Step 2: Start the dev server**

Run:

```bash
pnpm --dir apps/web dev -- --host 127.0.0.1
```

Expected: Vite prints a local URL, usually `http://127.0.0.1:5173/`.

- [ ] **Step 3: Open `/games` in the browser**

Use the in-app browser at:

```text
http://127.0.0.1:5173/games
```

Expected desktop visual result:

- Top lobby panel is a single compact control bar.
- The heading, seed, max rounds, pacing select, and launch button are in the same bordered panel.
- Official rules are inside a second bordered panel.
- Rule cards render as four columns on a wide viewport.
- Selected rule details are still visible below the card grid.

- [ ] **Step 4: Check a mobile viewport**

Set the browser viewport near `390x844`.

Expected mobile visual result:

- Top controls stack without text overlap.
- Rule cards become one column.
- Selected rule details remain below the cards.
- The launch button remains visible and readable.

## Task 6: Commit the Implementation

**Files:**
- Stage: `apps/web/src/pages/GamesPage.test.tsx`
- Stage: `apps/web/src/pages/components/GamesWorkspace.tsx`
- Stage: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Stage: `apps/web/src/styles/index.css`
- Stage: `docs/superpowers/plans/2026-05-14-lobby-console-redesign.md`

- [ ] **Step 1: Review the diff**

Run:

```bash
git diff --stat
git diff -- apps/web/src/pages/GamesPage.test.tsx apps/web/src/pages/components/GamesWorkspace.tsx apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/styles/index.css
```

Expected: only lobby page tests, lobby workspace, create form, CSS, and this plan changed.

- [ ] **Step 2: Stage files**

Run:

```bash
git add apps/web/src/pages/GamesPage.test.tsx apps/web/src/pages/components/GamesWorkspace.tsx apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/styles/index.css docs/superpowers/plans/2026-05-14-lobby-console-redesign.md
```

- [ ] **Step 3: Commit**

Run:

```bash
git commit -m "feat(web): redesign lobby console"
```

Expected: commit succeeds after focused tests, build, and browser verification pass.

## Self-Review

- Spec coverage: tasks cover top console, horizontal rule cards, preserved selected details, unchanged submit behavior, responsive behavior, tests, build, and browser verification.
- Placeholder scan: no deferred steps or undefined implementation notes remain.
- Type consistency: class names used in tests, JSX, and CSS match: `lobby-console-form`, `lobby-console-bar`, `lobby-rules-panel`, `lobby-rule-grid`, `lobby-rule-details`.
