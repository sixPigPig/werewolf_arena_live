# Admin Rule Sets UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the missing Admin Web “内容资产 → 游戏规则” entry and a complete structured rule-management workflow backed by the existing versioned rule-set Admin API.

**Architecture:** Add a self-contained `features/rule-sets` frontend module following the existing player-profile repository pattern. Runtime mode uses strict API parsers and CSRF-protected requests; preview mode uses an in-memory repository with the same interfaces. Routes and navigation enforce read permission, while each mutation additionally checks its existing granular rule permission. The browser performs only safe form validation and interaction gating; server validation remains authoritative.

**Tech Stack:** React 19, TypeScript 6, React Router 7, TanStack Query 5, Vitest, Testing Library, Vite, ESLint, existing FastAPI Admin rule-set API.

## Global Constraints

- Use the approved design in `docs/superpowers/specs/2026-07-13-admin-rule-sets-ui-design.md`.
- Do not add a raw JSON editor or expose compiled snapshots, revision UUIDs, SQL, raw errors, players, or private game data.
- Do not duplicate backend rule compilation or content-hash logic in TypeScript.
- Source all enum choices and numeric constraints from `GET /api/v1/admin/rule-set-options`.
- Preserve the existing Problem Details, CSRF, RBAC, lock-version, audit, no-store, and fail-closed contracts.
- Every production behavior starts with a failing test and a witnessed expected failure.
- Preserve the user's untracked `.codex/` directory and unrelated working-tree changes.

---

### Task 1: Strict rule-set contracts and API client

**Files:**
- Create: `apps/admin-web/src/features/rule-sets/types.ts`
- Create: `apps/admin-web/src/features/rule-sets/parsers.ts`
- Create: `apps/admin-web/src/features/rule-sets/contracts.test.ts`
- Create: `apps/admin-web/src/features/rule-sets/api.ts`
- Create: `apps/admin-web/src/features/rule-sets/api.test.ts`
- Create: `apps/admin-web/src/features/rule-sets/query-keys.ts`
- Create: `apps/admin-web/src/features/rule-sets/list-state.ts`
- Create: `apps/admin-web/src/features/rule-sets/list-state.test.ts`

**Interfaces:**
- Consumes: `adminApiFetch`, `AdminApiError`, and the existing Admin API paths under `/api/v1/admin`.
- Produces: strict DTO types, parser functions, request functions, query keys, and URL list-state helpers used by all later tasks.

- [ ] **Step 1: Write failing parser contract tests**

Create fixtures and tests asserting that `parseAdminRuleSet`, `parseAdminRuleSetDetail`, `parseAdminRuleSetList`, `parseRuleSetOptions`, and `parseRuleSetValidation` accept exact valid payloads. Add negative cases for unknown status/state, missing positive lock versions, malformed pagination, malformed role counts, and forbidden keys `compiled_snapshot` on rule detail, `rule_set_snapshot`, `players`, `sql`, and `raw_error` anywhere outside the validation DTO.

The exported domain core must be:

```ts
export type RuleSetStatus = "draft" | "published" | "archived";
export type RuleRevisionState = "draft" | "published" | "superseded";
export type RuleRoleId =
  | "werewolf"
  | "villager"
  | "seer"
  | "guard"
  | "witch"
  | "hunter"
  | "idiot";

export type RuleSetConfig = {
  name: string;
  description: string;
  complexity: string;
  estimated_duration: string;
  rule_tags: string[];
  role_counts: Record<RuleRoleId, number>;
  win_condition: "wolves_gte_others" | "slaughter_side";
  sheriff_enabled: boolean;
  sheriff_vote_weight: number;
  speech_policy: "sequential" | "sheriff_directed";
  werewolf_self_explosion_enabled: boolean;
  sheriff_badge_bomb_policy: "none" | "double";
};
```

The detail type must distinguish aggregate usage from revision usage, and validation is the only type allowed to contain `compiled_snapshot`; the UI never renders or persists that field.

- [ ] **Step 2: Run parser tests and verify RED**

Run:

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/contracts.test.ts
```

Expected: FAIL because the rule-set types and parsers do not exist.

- [ ] **Step 3: Implement strict types and parsers**

Implement exact-enum, exact-number, positive/non-negative integer, boolean, nullable string/date, array, pagination, config, revision, usage, warning, options, and validation parsers. Reuse the existing `AdminApiError` shape with:

```ts
code: "admin_invalid_rule_set_response"
title: "规则接口响应无效"
status: 502
```

Reject sensitive unexpected keys recursively before returning a DTO. Permit `compiled_snapshot` only at validation response root, parse it as `Record<string, unknown> | null`, and ensure no component receives it by exposing a UI validation type that omits the field.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run the Task 1 parser command again. Expected: all contract tests pass.

- [ ] **Step 5: Write failing API client tests**

Mock `adminApiFetch` and assert exact paths, methods, CSRF header, and bodies for:

```text
GET    /api/v1/admin/rule-set-options
GET    /api/v1/admin/rule-sets?page=&page_size=&q=&status=&player_count=&sort=
GET    /api/v1/admin/rule-sets/{id}
POST   /api/v1/admin/rule-sets
PATCH  /api/v1/admin/rule-sets/{id}/draft
POST   /api/v1/admin/rule-sets/{id}/validate
POST   /api/v1/admin/rule-sets/{id}/publish
POST   /api/v1/admin/rule-sets/{id}/archive
POST   /api/v1/admin/rule-sets/{id}/restore
POST   /api/v1/admin/rule-sets/{id}/set-default
POST   /api/v1/admin/rule-sets/{id}/duplicate
```

Assert every path segment uses `encodeURIComponent`, GET requests accept `AbortSignal`, and writes include `Content-Type` plus `X-CSRF-Token`.

- [ ] **Step 6: Run API tests and verify RED**

Run:

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/api.test.ts
```

Expected: FAIL because `api.ts` is missing.

- [ ] **Step 7: Implement API functions and query keys**

Export typed functions for every endpoint. Use request shapes matching the backend schemas exactly:

```ts
export type UpdateRuleSetDraftRequest = {
  expected_rule_set_lock_version: number;
  expected_revision_lock_version: number | null;
  display_order: number;
  config: RuleSetConfig;
};

export type PublishRuleSetRequest = {
  expected_rule_set_lock_version: number;
  expected_revision_lock_version: number;
  reason: string;
};
```

Define `ruleSetKeys.all`, `lists`, `list(params)`, `details`, `detail(id)`, and `options`.

- [ ] **Step 8: Write RED list-state tests, implement, and verify GREEN**

Test and implement canonical parsing/serialization for page, page size, query, status, player count, sort field, and direction. Invalid values fall back to page `1`, page size `20`, sort `display_order`, direction `asc`; filter changes reset page to `1`.

Run:

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/contracts.test.ts src/features/rule-sets/api.test.ts src/features/rule-sets/list-state.test.ts
```

Expected: all Task 1 tests pass.

- [ ] **Step 9: Commit Task 1**

```bash
git add apps/admin-web/src/features/rule-sets
git commit -m "feat(admin): add rule set frontend contracts"
```

---

### Task 2: Form model and preview repository

**Files:**
- Create: `apps/admin-web/src/features/rule-sets/form.ts`
- Create: `apps/admin-web/src/features/rule-sets/form.test.ts`
- Create: `apps/admin-web/src/features/rule-sets/test-fixtures.ts`
- Create: `apps/admin-web/src/features/rule-sets/preview-repository.ts`
- Create: `apps/admin-web/src/features/rule-sets/preview-repository.test.ts`
- Create: `apps/admin-web/src/features/rule-sets/repository.ts`

**Interfaces:**
- Consumes: Task 1 DTOs/API/query contracts and `useAdminSession()` runtime mode/CSRF token.
- Produces: deterministic form transforms and a runtime/preview repository with one interface for pages.

- [ ] **Step 1: Write failing form tests**

Cover:

- new-rule defaults derived from server options;
- detail-to-form mapping preferring `draft_revision.config`, otherwise `published_revision.config`;
- trimmed scalar fields and comma-separated tag parsing;
- role counts as non-negative integers and player-count calculation;
- ID pattern, text lengths, tag count/length, display order, role count, and total-player 6–12 validation;
- sheriff-off normalization to `sheriff_vote_weight: 1` and `sheriff_badge_bomb_policy: "none"`;
- API warning `path` mapping to a field plus form summary;
- dirty comparison using cleaned values, not display-only strings.

- [ ] **Step 2: Run form tests and verify RED**

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/form.test.ts
```

Expected: FAIL because `form.ts` is missing.

- [ ] **Step 3: Implement the pure form model**

Export:

```ts
export type RuleSetFormInput = {
  id: string;
  display_order: number;
  config: RuleSetConfig;
};

export type RuleSetFormErrors = Partial<
  Record<
    | "id"
    | "display_order"
    | "name"
    | "description"
    | "complexity"
    | "estimated_duration"
    | "rule_tags"
    | "role_counts"
    | "win_condition"
    | "sheriff_vote_weight"
    | "speech_policy"
    | "sheriff_badge_bomb_policy"
    | "form",
    string
  >
>;
```

Implement `defaultRuleSetInput(options)`, `inputFromRuleSet(detail, options)`, `cleanRuleSetInput(input, options)`, `validateRuleSetInput(input, options)`, `playerCount(input)`, `roleSummary(input, options)`, and `formErrorsFromApi(problem)`.

- [ ] **Step 4: Run form tests and verify GREEN**

Run the Task 2 form command again. Expected: all tests pass.

- [ ] **Step 5: Write failing preview repository tests**

Use four official-style fixtures covering published default, published non-default, draft, and archived. Verify list filtering/sorting/pagination, detail usage/history, create, duplicate, update lock conflicts, validation success/error, publish, set-default, archive-with-replacement, restore, reason length, and immutable history revisions.

- [ ] **Step 6: Run preview repository tests and verify RED**

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/preview-repository.test.ts
```

Expected: FAIL because preview repository functions are missing.

- [ ] **Step 7: Implement preview and runtime repositories**

The preview repository must clone every returned value, increment rule/revision lock versions consistently, create a new immutable published revision on publish, supersede the previous published revision, keep exactly one published default, and reset deterministically between tests.

`useRuleSetRepository()` must expose:

```ts
{
  isPreview,
  list,
  get,
  getOptions,
  create,
  updateDraft,
  validate,
  publish,
  archive,
  restore,
  setDefault,
  duplicate,
}
```

Preview mode calls in-memory functions; connected mode calls Task 1 API functions with the current CSRF token.

- [ ] **Step 8: Verify Task 2 and commit**

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/form.test.ts src/features/rule-sets/preview-repository.test.ts
cd ../..
git add apps/admin-web/src/features/rule-sets
git commit -m "feat(admin): add rule set form repository"
```

Expected: all Task 2 tests pass and the commit contains no page or route code.

---

### Task 3: Navigation, routes, and rule list

**Files:**
- Create: `apps/admin-web/src/features/rule-sets/RuleSetsPage.tsx`
- Create: `apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx`
- Modify: `apps/admin-web/src/app/admin-navigation.ts`
- Modify: `apps/admin-web/src/routes/lazy-pages.tsx`
- Modify: `apps/admin-web/src/routes/definitions.tsx`
- Modify: `apps/admin-web/src/app/App.test.tsx`

**Interfaces:**
- Consumes: Task 1 list state/query keys, Task 2 repository, existing session/permission and route-shell components.
- Produces: permission-gated navigation/routes and a complete read/list/duplicate entry point.

- [ ] **Step 1: Write failing navigation and route tests**

Add `rules.read`, `rules.write`, `rules.publish`, `rules.archive`, and `rules.set_default` to the expected frontend permission union in the test. Assert:

- “内容资产 → 游戏规则” links to `/content/rules` when `rules.read` or preview wildcard is present;
- `/content/rules` renders the rule list;
- `/content/rules/new` and `/content/rules/:ruleSetId` resolve through lazy routes;
- a connected session without `rules.read` sees 403 on direct access;
- existing player, voice, game, run, overview, and security routes still resolve.

- [ ] **Step 2: Run route tests and verify RED**

```bash
cd apps/admin-web
pnpm test --run src/app/App.test.tsx src/features/rule-sets/RuleSetsFlow.test.tsx
```

Expected: FAIL because permissions, navigation, routes, and pages are missing.

- [ ] **Step 3: Add permission, navigation, and lazy routes**

Add the five permission literals to `AdminPermission`, the approved nav item, lazy imports/route wrappers, and route definitions. Put `content/rules/new` before `content/rules/:ruleSetId` for unambiguous matching. Require `rules.read` at route level.

- [ ] **Step 4: Write failing list interaction tests**

In `RuleSetsFlow.test.tsx`, verify:

- heading and total count;
- default/status/revision/player/role summary rendering;
- search submit, status/player count/sort/page-size filters, clear filters, and pagination update the URL;
- loading, empty, and repository-error retry states;
- read-only users see no create/duplicate buttons;
- `rules.write` users can open new and duplicate flows;
- duplicate requires valid new ID/name, calls the repository with source lock version, and navigates to the new detail.

- [ ] **Step 5: Run list tests and verify RED**

Run the Task 3 command again. Expected: route tests may pass, list interactions fail because the page is incomplete.

- [ ] **Step 6: Implement `RuleSetsPage`**

Follow the existing player list layout and accessibility conventions. Use TanStack Query with `keepPreviousData`, server options for status/player filters, URL list state, explicit retry, semantic list/table labels, text status badges, and permission-gated actions. Keep duplicate dialog local to the list page because it creates a new aggregate and then navigates.

- [ ] **Step 7: Verify Task 3 and commit**

```bash
cd apps/admin-web
pnpm test --run src/app/App.test.tsx src/features/rule-sets/RuleSetsFlow.test.tsx
cd ../..
git add apps/admin-web/src/app/admin-navigation.ts apps/admin-web/src/routes apps/admin-web/src/app/App.test.tsx apps/admin-web/src/features/rule-sets/RuleSetsPage.tsx apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx
git commit -m "feat(admin): add rule set navigation and list"
```

Expected: route/list tests pass.

---

### Task 4: Structured editor, save, and server validation

**Files:**
- Create: `apps/admin-web/src/features/rule-sets/RuleSetEditorPage.tsx`
- Modify: `apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx`

**Interfaces:**
- Consumes: Task 1 types/queries, Task 2 form/repository, Task 3 routes.
- Produces: create/edit form with dirty protection, server validation, preview, usage, and history display.

- [ ] **Step 1: Write failing editor rendering and form tests**

Cover new and existing routes. Assert all approved structured fields render; role inputs follow server option order; player count and role summary update; rule ID becomes read-only after creation; sheriff-off disables/normalizes dependent controls; read-only users can inspect but cannot edit.

- [ ] **Step 2: Run focused editor tests and verify RED**

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/RuleSetsFlow.test.tsx -t "rule editor"
```

Expected: FAIL because `RuleSetEditorPage` is missing.

- [ ] **Step 3: Implement loading, error, and structured form rendering**

Load options and detail in parallel, show 404-specific copy, 503/repository retry, status/default/revision summary, aggregate usage, operation warnings, and at most 50 history revisions with per-revision game/live usage. Do not render revision IDs, raw config JSON, or validation `compiled_snapshot`.

- [ ] **Step 4: Write failing save and dirty-navigation tests**

Verify invalid local input blocks the repository call; new save creates and navigates; existing save sends both lock versions; success resets dirty baseline and invalidates list/detail queries; edit after validation invalidates the validation result; browser/unload and route blockers protect unsaved changes; conflict keeps the local draft and offers explicit reload.

- [ ] **Step 5: Run save tests and verify RED**

Run the focused flow test with `-t "save rule draft|unsaved rule|rule conflict"`. Expected: FAIL because save/dirty/conflict behavior is missing.

- [ ] **Step 6: Implement create/update and conflict behavior**

Use `useBlocker`, `useBeforeUnload`, a JSON baseline of `cleanRuleSetInput`, one pending-action state, field/form errors, Problem Details mapping, and explicit reload. Never overwrite local input after a 409/412 conflict.

- [ ] **Step 7: Write failing validation-gate tests**

Verify validate is disabled before save, sends the current revision lock, maps server errors by path, renders warnings, content-hash prefix and rule text on success, never renders compiled snapshot, and disables publish after any form change until save plus re-validation.

- [ ] **Step 8: Implement validation and preview state**

Store only:

```ts
type RuleSetValidationView = {
  valid: boolean;
  errors: RuleSetWarning[];
  warnings: RuleSetWarning[];
  content_hash: string | null;
  rule_text_preview: string | null;
  revision_lock_version: number;
};
```

Discard `compiled_snapshot` immediately in the repository/parser boundary exposed to components.

- [ ] **Step 9: Verify Task 4 and commit**

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/RuleSetsFlow.test.tsx src/features/rule-sets/form.test.ts
cd ../..
git add apps/admin-web/src/features/rule-sets/RuleSetEditorPage.tsx apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx
git commit -m "feat(admin): add structured rule set editor"
```

Expected: editor/save/validation tests pass.

---

### Task 5: Publish, default, archive, and restore workflows

**Files:**
- Create: `apps/admin-web/src/features/rule-sets/RuleSetTransitionDialog.tsx`
- Modify: `apps/admin-web/src/features/rule-sets/RuleSetEditorPage.tsx`
- Modify: `apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx`

**Interfaces:**
- Consumes: current aggregate/revision locks, validated-revision state, rule repository mutations, granular permissions.
- Produces: complete lifecycle management without direct API usage.

- [ ] **Step 1: Write failing permission and transition-dialog tests**

Assert each action requires its exact permission, all dialogs have accessible title/description/cancel, reasons are trimmed and constrained by server options, pending actions prevent duplicate submit, and closing a dialog preserves the editor draft.

- [ ] **Step 2: Run transition tests and verify RED**

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/RuleSetsFlow.test.tsx -t "publish rule|default rule|archive rule|restore rule"
```

Expected: FAIL because transition dialogs/actions are missing.

- [ ] **Step 3: Implement publish**

Enable only for an unchanged, saved, server-validated current draft and `rules.publish`. Send both current lock versions plus reason. On success, clear validation, replace detail data, invalidate list/detail queries, and announce success.

- [ ] **Step 4: Implement set-default**

Require `rules.set_default` and a published non-default rule. Resolve the current published default from a repository list query, send its lock version as `previous_default_expected_lock_version`, and handle a default changed concurrently as a non-destructive conflict.

- [ ] **Step 5: Implement archive with replacement**

Require `rules.archive`. For a non-default rule, send null replacement fields. For the current default, load published candidates excluding the current rule, require a selection, and send replacement ID plus its lock version. If no candidate exists, disable confirmation and explain that another rule must be published first.

- [ ] **Step 6: Implement restore**

Require `rules.archive`, send the current aggregate lock and reason, then refresh detail/list. The restored lifecycle and editability are determined from the server response, not assumed in the component.

- [ ] **Step 7: Add conflict/error/success assertions and verify GREEN**

Test 409/412 for every transition, 422 reason errors, 503 retry copy, success announcements, cache refresh, exact request bodies, no duplicate requests, and no raw error leakage.

Run:

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/RuleSetsFlow.test.tsx
```

Expected: the complete rule workflow passes.

- [ ] **Step 8: Commit Task 5**

```bash
git add apps/admin-web/src/features/rule-sets/RuleSetTransitionDialog.tsx apps/admin-web/src/features/rule-sets/RuleSetEditorPage.tsx apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx
git commit -m "feat(admin): add rule set lifecycle controls"
```

---

### Task 6: Styling, accessibility, documentation, and full verification

**Files:**
- Modify: `apps/admin-web/src/styles/index.css`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/admin-deployment-runbook.md`
- Modify: `apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx`

**Interfaces:**
- Consumes: complete Tasks 1–5 UI.
- Produces: production-ready responsive presentation, documented entry, and verified release evidence.

- [ ] **Step 1: Add failing accessibility assertions**

Assert every form control has an accessible name, errors use `aria-describedby` or an equivalent association, statuses include text, async success/error uses live regions, dialog focus enters a meaningful control and returns on close, and every workflow is keyboard-operable.

- [ ] **Step 2: Run flow tests and verify RED where styling/ARIA is missing**

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets/RuleSetsFlow.test.tsx
```

Expected: accessibility assertions fail on the missing associations or states.

- [ ] **Step 3: Add scoped responsive styles and ARIA fixes**

Use `.rule-set-*` class names and existing Admin color/spacing tokens. Desktop uses list rows and a two-column editor/summary layout; narrow screens stack the summary after the form and use controlled horizontal scrolling for history. Do not introduce a new dependency or global reset.

- [ ] **Step 4: Document the actual Admin entry**

Update README, architecture, and runbook to state that authorized operators manage rules at “内容资产 → 游戏规则” and that publish/default/archive actions remain versioned, reasoned, audited, and server-validated. Do not claim raw JSON editing or automatic fallback.

- [ ] **Step 5: Run frontend focused and full verification**

```bash
cd apps/admin-web
pnpm test --run src/features/rule-sets src/app/App.test.tsx
pnpm test --run
pnpm run build
pnpm run lint
```

Expected: all commands exit 0 without unhandled React warnings.

- [ ] **Step 6: Run backend rule API regression**

```bash
cd apps/api
.venv/bin/python -m pytest -q tests/test_admin_rule_sets.py tests/test_rule_set_service.py tests/test_rule_set_repository.py tests/test_rule_set_validation.py tests/test_rule_set_snapshots.py
```

Expected: all selected backend tests pass.

- [ ] **Step 7: Run repository hygiene checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files are changed before the final commit. Preserve `.codex/` as untracked and untouched.

- [ ] **Step 8: Commit documentation and presentation**

```bash
git add apps/admin-web/src/styles/index.css README.md docs/architecture.md docs/admin-deployment-runbook.md apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx
git commit -m "docs(admin): document rule management entry"
```

- [ ] **Step 9: Independent final review and verification report**

Review the immutable implementation range against the approved design. Fix every Critical, Important, and applicable Minor finding with a new failing regression test, rerun the focused and full verification commands, and report exact test/build/lint results plus the final commit range.
