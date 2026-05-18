# Player Creation Flow Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build three autonomous improvements for the virtual player creation flow: starter templates, visible readiness plus duplicate-name protection, and save-and-continue creation.

**Architecture:** Keep the backend unchanged. Put reusable creation logic in a pure frontend helper module, then have `VirtualPlayerLibrary` own state transitions and `VirtualPlayerEditor` render the new controls.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, existing gothic UI components and CSS.

---

## File Map

- Create: `apps/web/src/features/games/playerProfileCreation.ts`
  - Starter templates.
  - Preset application.
  - Unique name generation.
  - Duplicate-name detection.
  - Creation readiness checklist.
- Create: `apps/web/src/features/games/playerProfileCreation.test.ts`
  - Unit tests for helper behavior.
- Modify: `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`
  - Build fresh template-backed drafts.
  - Pass readiness and template props to the editor.
  - Add save-and-continue behavior.
  - Generate duplicate-safe copy names.
- Modify: `apps/web/src/features/games/components/VirtualPlayerEditor.tsx`
  - Render starter template choices.
  - Render readiness chips and duplicate-name alert.
  - Render save-and-continue button only for new profiles.
- Modify: `apps/web/src/pages/PlayersPage.test.tsx`
  - Cover starter template application, duplicate-name blocking, and save-and-continue.
- Modify: `apps/web/src/styles/index.css`
  - Style template buttons, readiness chips, and responsive action layout.

## Task 1: Pure Creation Logic

**Files:**
- Create: `apps/web/src/features/games/playerProfileCreation.ts`
- Create: `apps/web/src/features/games/playerProfileCreation.test.ts`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```ts
expect(applyPlayerCreationPreset(baseDraft, "pressure-attacker")).toMatchObject({
  strategy_profile: "pressure_attacker",
  personality_id: "aggressive",
  tags: ["强压", "提问"],
});
expect(nextAvailableProfileName("冷静的阿夜", profiles)).toBe("冷静的阿夜 2");
expect(getPlayerProfileCreationReadiness(draft, profiles).canSave).toBe(false);
```

- [ ] **Step 2: Run red test**

Run: `pnpm --dir apps/web test -- --run src/features/games/playerProfileCreation.test.ts`

Expected: fail because the module does not exist.

- [ ] **Step 3: Implement helper module**

Create the preset list and pure functions. Keep returned arrays copied so callers cannot mutate shared preset data.

- [ ] **Step 4: Run green test**

Run: `pnpm --dir apps/web test -- --run src/features/games/playerProfileCreation.test.ts`

Expected: pass.

## Task 2: Editor Integration

**Files:**
- Modify: `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`
- Modify: `apps/web/src/features/games/components/VirtualPlayerEditor.tsx`
- Modify: `apps/web/src/styles/index.css`
- Modify: `apps/web/src/pages/PlayersPage.test.tsx`

- [ ] **Step 1: Write failing component tests**

Add tests that assert:

```ts
await userEvent.click(screen.getByRole("button", { name: "新建虚拟玩家" }));
await userEvent.click(screen.getByRole("button", { name: "高压进攻" }));
expect(screen.getByLabelText("一句话简介")).toHaveValue("用连续提问制造压力，快速逼出视角漏洞。");

await userEvent.clear(screen.getByLabelText("虚拟玩家昵称"));
await userEvent.type(screen.getByLabelText("虚拟玩家昵称"), "Alpha 阿夜");
expect(screen.getByRole("alert")).toHaveTextContent("已有同名虚拟玩家");
expect(screen.getByRole("button", { name: "保存虚拟玩家" })).toBeDisabled();
```

- [ ] **Step 2: Run red component test**

Run: `pnpm --dir apps/web test -- --run src/pages/PlayersPage.test.tsx`

Expected: fail because the controls do not exist.

- [ ] **Step 3: Implement editor UI**

Wire helper output into `VirtualPlayerLibrary`, pass template and readiness props into `VirtualPlayerEditor`, then render the controls.

- [ ] **Step 4: Style the controls**

Add CSS under the existing virtual player editor section. Ensure mobile layout stacks cleanly and button text cannot overflow.

- [ ] **Step 5: Run green component test**

Run: `pnpm --dir apps/web test -- --run src/pages/PlayersPage.test.tsx`

Expected: pass.

## Task 3: Batch Creation Flow

**Files:**
- Modify: `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`
- Modify: `apps/web/src/features/games/components/VirtualPlayerEditor.tsx`
- Modify: `apps/web/src/pages/PlayersPage.test.tsx`

- [ ] **Step 1: Write failing save-and-continue test**

Add a test that clicks “保存并继续新建”, verifies one POST request was sent with the selected template fields, and verifies the editor remains open with a non-empty next draft.

- [ ] **Step 2: Run red test**

Run: `pnpm --dir apps/web test -- --run src/pages/PlayersPage.test.tsx`

Expected: fail because the button does not exist.

- [ ] **Step 3: Implement save-and-continue**

Let `saveDraft({ continueCreating: true })` reset to a fresh template-backed draft after successful creation. Do not show the button during edit mode.

- [ ] **Step 4: Run green test**

Run: `pnpm --dir apps/web test -- --run src/pages/PlayersPage.test.tsx`

Expected: pass.

## Task 4: Final Verification

**Files:**
- No new files unless a failure reveals a focused fix.

- [ ] **Step 1: Run targeted web tests**

Run: `pnpm --dir apps/web test -- --run src/features/games/playerProfileCreation.test.ts src/pages/PlayersPage.test.tsx`

Expected: pass.

- [ ] **Step 2: Run full web test suite**

Run: `pnpm test:web`

Expected: pass.

- [ ] **Step 3: Build frontend**

Run: `pnpm build:web`

Expected: pass.

- [ ] **Step 4: Inspect diff**

Run: `git diff -- docs/superpowers/specs/2026-05-18-player-creation-flow-optimization-design.md docs/superpowers/plans/2026-05-18-player-creation-flow-optimization.md apps/web/src/features/games apps/web/src/pages/PlayersPage.test.tsx apps/web/src/styles/index.css`

Expected: changes are scoped to the documented feature.
