# 可配置规则集 Admin Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在 Admin Web 中提供规则列表、受限草稿编辑、编译预览、修订历史和高风险生命周期操作，并保证 preview 只读、409 不覆盖脏表单、只有 Super Admin 能影响新对局。

**Architecture:** 新增 features/rule-sets 垂直切片，复用 player-profiles 的类型/parser/API/repository/query/list-state/editor/dialog模式。真实模式调用 Admin API；preview repository 只返回固定只读 fixtures，所有写方法稳定拒绝，页面同时隐藏写入口。

**Tech Stack:** React 19、TypeScript 6、React Router 7、TanStack Query 5、Vitest、Testing Library、Playwright、axe、Tailwind/CSS。

## Global Constraints

- Requires completed backend contract: docs/superpowers/plans/2026-07-12-rule-catalog-admin-api.md。
- 页面不提供原始 JSON、action 顺序、任意 prompt 或新角色编辑器。
- player_count 只由七个 role_counts 求和显示，不能直接编辑。
- 表单选项和限制只来自 GET /api/v1/admin/rule-set-options。
- 409 必须保留 draft、baseline 和用户输入；只有用户明确确认重新加载才覆盖。
- Preview mode 只能读 fixtures，不能模拟保存、发布、归档、恢复或设默认成功。
- Content Editor 只能创建/编辑/校验草稿；发布、归档、恢复、设默认仅 Super Admin。
- 前端权限只控制交互；后端权限仍是安全边界。
- 生命周期原因 3–500 字，dialog 必须 trap focus、Escape 关闭、关闭后恢复焦点。
- 列表筛选、分页和排序必须进入 URL。
- 页面覆盖 loading、empty、error、forbidden 和 partial-warning 状态。
- Admin Playwright 现有构建固定 preview，因此浏览器 E2E 只验证只读 UI/导航/响应式/可访问性，不伪造真实发布成功。

---

## File Structure

- Create apps/admin-web/src/features/rule-sets/types.ts：Admin 规则、修订、配置、请求和响应类型。
- Create parsers.ts：对服务端 unknown JSON 的严格运行时解析。
- Create api.ts：Admin list/detail/options/create/update/validate/transition/duplicate 调用。
- Create query-keys.ts、list-state.ts：Query keys 和 URL 状态。
- Create repository.ts：真实/preview 选择与 CSRF 注入。
- Create preview-repository.ts、preview-repository.test.ts：只读 fixtures 和稳定写拒绝。
- Create contracts.test.ts：parser/API/URL contract tests。
- Create RuleSetsPage.tsx：列表、筛选、分页、告警和状态。
- Create form.ts：输入清洗、派生人数和客户端可即时验证的约束。
- Create RuleSetEditorPage.tsx：基础、阵容、玩法、编译预览、修订历史五区。
- Create RuleSetTransitionDialog.tsx：原因确认和影响说明。
- Create RuleSetsFlow.test.tsx：编辑、权限、409、dialog 和 dirty navigation。
- Modify app/admin-navigation.ts、routes/definitions.tsx、routes/lazy-pages.tsx：导航和路由。
- Modify styles/index.css：规则列表/editor/dialog 响应式样式。
- Modify app/App.test.tsx、features/auth/AuthFlow.test.tsx：导航与 deep-link guard。
- Modify e2e/admin-workspace.spec.ts：preview keyboard、axe 和窄屏验收。

## Backend JSON Names Used by This Plan

~~~typescript
type RuleRoleCounts = {
  werewolf: number;
  villager: number;
  seer: number;
  guard: number;
  witch: number;
  hunter: number;
  idiot: number;
};

type RuleSetDraftInput = {
  name: string;
  description: string;
  complexity: string;
  estimated_duration: string;
  rule_tags: string[];
  role_counts: RuleRoleCounts;
  win_condition: "wolves_gte_others" | "slaughter_side";
  sheriff_enabled: boolean;
  sheriff_vote_weight: 1 | 1.5 | 2;
  speech_policy: "sequential" | "sheriff_directed";
  werewolf_self_explosion_enabled: boolean;
  sheriff_badge_bomb_policy: "none" | "double";
};
~~~

Stable entity concurrency field is lock_version. Draft revision concurrency field is also lock_version. Do not rename either to a generic form version in request JSON.

---

### Task 1: Add Strict Types, Parsers, API and URL State

**Files:**
- Create: apps/admin-web/src/features/rule-sets/types.ts
- Create: apps/admin-web/src/features/rule-sets/parsers.ts
- Create: apps/admin-web/src/features/rule-sets/api.ts
- Create: apps/admin-web/src/features/rule-sets/query-keys.ts
- Create: apps/admin-web/src/features/rule-sets/list-state.ts
- Create: apps/admin-web/src/features/rule-sets/contracts.test.ts

**Interfaces:**
- Consumes: Admin endpoints and field names from backend plan.
- Produces: all frontend DTOs and repository-ready functions.

- [ ] **Step 1: Write failing contract tests**

~~~typescript
it("strictly parses rule detail and revision metadata", () => {
  const detail = parseAdminRuleSetDetail(ruleSetDetailFixture());
  expect(detail.id).toBe("classic_8");
  expect(detail.published_revision?.revision_no).toBe(1);
  expect(detail.published_revision?.content_hash).toHaveLength(64);
});

it("rejects unknown roles and malformed managed metadata", () => {
  const payload = ruleSetDetailFixture();
  payload.draft_revision.config.role_counts.future_role = 1;
  expect(() => parseAdminRuleSetDetail(payload)).toThrow(AdminApiError);
});

it("serializes both stable and revision expected versions", async () => {
  await updateAdminRuleSetDraft(
    "classic_8",
    {
      expected_rule_set_lock_version: 3,
      expected_revision_lock_version: 2,
      display_order: 1,
      config: ruleDraftInputFixture(),
    },
    "csrf-token",
  );
  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining("/api/v1/admin/rule-sets/classic_8/draft"),
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"expected_revision_lock_version":2'),
    }),
  );
});
~~~

Also test list q/status/player_count/page/page_size/signed sort URL round-trip, validation response errors/warnings/compiled snapshot/hash/text, and extra top-level fields rejection.

- [ ] **Step 2: Run and verify missing modules**

~~~bash
pnpm --dir apps/admin-web exec vitest run \
  src/features/rule-sets/contracts.test.ts
~~~

Expected: module resolution FAILS for features/rule-sets.

- [ ] **Step 3: Define exact types**

~~~typescript
export type RuleSetStatus = "draft" | "published" | "archived";
export type RuleRevisionState = "draft" | "published" | "superseded";
export type RuleSetSortField =
  | "display_order" | "updated_at" | "name" | "created_at";

export type AdminRuleRevision = {
  id: string;
  rule_set_id: string;
  revision_no: number;
  state: RuleRevisionState;
  schema_version: number;
  content_hash: string | null;
  lock_version: number;
  config: RuleSetDraftInput | null;
  player_count: number;
  role_summary: string;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  published_by: string | null;
};

export type AdminRuleSetDetail = {
  id: string;
  status: RuleSetStatus;
  is_default: boolean;
  display_order: number;
  lock_version: number;
  draft_revision: AdminRuleRevision | null;
  published_revision: AdminRuleRevision | null;
  revisions: AdminRuleRevision[];
  usage: { game_count: number; live_count: number };
  warnings: RuleValidationIssue[];
  created_at: string;
  updated_at: string;
};
~~~

Add list params/result, options, validation response and exact create/update/validate/archive/transition/default/duplicate requests. DEFAULT_RULE_SET_INPUT contains all seven role keys.

- [ ] **Step 4: Implement strict parsers**

Use helpers requireRecord、requireExactKeys、requireString、requireInteger、requireBoolean、requireStringArray and oneOf. Every nested role/config/revision object rejects unknown fields. Parse timestamps as non-empty strings but do not reinterpret time zones. Convert malformed backend payloads to an AdminApiError with code admin_rule_set_contract_invalid.

- [ ] **Step 5: Implement API and list state**

API paths:

~~~text
/api/v1/admin/rule-set-options
/api/v1/admin/rule-sets
/api/v1/admin/rule-sets/{id}/draft
/api/v1/admin/rule-sets/{id}/validate
/api/v1/admin/rule-sets/{id}/publish
/api/v1/admin/rule-sets/{id}/archive
/api/v1/admin/rule-sets/{id}/restore
/api/v1/admin/rule-sets/{id}/set-default
/api/v1/admin/rule-sets/{id}/duplicate
~~~

All writes use adminApiFetch with Content-Type and X-CSRF-Token. list-state defaults page=1、page_size=20、sort=updated_at、direction=desc and drops empty filters. Query keys begin with ["admin", "rule-sets"].

- [ ] **Step 6: Verify and commit**

~~~bash
pnpm --dir apps/admin-web exec vitest run \
  src/features/rule-sets/contracts.test.ts
pnpm --dir apps/admin-web lint
git add apps/admin-web/src/features/rule-sets/types.ts \
  apps/admin-web/src/features/rule-sets/parsers.ts \
  apps/admin-web/src/features/rule-sets/api.ts \
  apps/admin-web/src/features/rule-sets/query-keys.ts \
  apps/admin-web/src/features/rule-sets/list-state.ts \
  apps/admin-web/src/features/rule-sets/contracts.test.ts
git commit -m "feat(admin): add rule set client contracts"
~~~

---

### Task 2: Add Read-Only Preview, List, Navigation and Routes

**Files:**
- Create: apps/admin-web/src/features/rule-sets/preview-repository.ts
- Create: apps/admin-web/src/features/rule-sets/preview-repository.test.ts
- Create: apps/admin-web/src/features/rule-sets/repository.ts
- Create: apps/admin-web/src/features/rule-sets/RuleSetsPage.tsx
- Modify: apps/admin-web/src/app/admin-navigation.ts
- Modify: apps/admin-web/src/routes/definitions.tsx
- Modify: apps/admin-web/src/routes/lazy-pages.tsx
- Modify: apps/admin-web/src/app/App.test.tsx
- Modify: apps/admin-web/src/features/auth/AuthFlow.test.tsx
- Modify: apps/admin-web/src/styles/index.css

**Interfaces:**
- Consumes: Task 1 contract layer.
- Produces: /content/rules read route and repository used by editor.

- [ ] **Step 1: Write failing preview/list/route tests**

~~~typescript
it("renders revisioned read-only preview inventory without API requests", async () => {
  renderAdminAt("/content/rules", { mode: "preview" });
  expect(await screen.findByRole("heading", { name: "规则集" })).toBeVisible();
  expect(screen.getByText("经典 8 人局")).toBeVisible();
  expect(screen.queryByRole("button", { name: "新建规则" })).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

it("guards rule deep links with rules.read", async () => {
  renderAdminAt("/content/rules/classic_8", {
    permissions: ["overview.read"],
  });
  expect(await screen.findByRole("heading", { name: "无权访问" })).toBeVisible();
});
~~~

Add URL filter/pagination/sort, loading、empty、retryable error、partial-warning counts and navigation item tests.

- [ ] **Step 2: Run and verify route/navigation failures**

~~~bash
pnpm --dir apps/admin-web exec vitest run \
  src/features/rule-sets/preview-repository.test.ts \
  src/app/App.test.tsx src/features/auth/AuthFlow.test.tsx
~~~

- [ ] **Step 3: Implement a read-only preview repository**

Provide fixed published、draft、archived fixtures with revision metadata. list/get/getOptions return structuredClone values. All writes reject with one stable AdminApiError:

~~~typescript
function previewWriteRejected(): Promise<never> {
  return Promise.reject(
    new AdminApiError({
      problem: {
        type: "about:blank",
        title: "预览模式只读",
        status: 403,
        detail: "预览模式不能修改或发布规则。",
        code: "admin_preview_read_only",
        request_id: null,
      },
    }),
  );
}
~~~

useRuleSetRepository exposes isPreview and real/preview methods. The UI must still hide writes even though preview session currently has wildcard permissions.

- [ ] **Step 4: Build the list page**

Use URL state as Query input. Columns show name/ID、status、default、current revision、player count/role summary、draft indicator、updated actor/time、game count and warning count. Add semantic table/list behavior, accessible labels and explicit loading/empty/error/forbidden/partial-warning regions.

- [ ] **Step 5: Add permissions, navigation and routes**

Extend AdminPermission with rules.read、rules.write、rules.publish、rules.archive、rules.set_default. Add 内容资产 → 规则集 at /content/rules. Add routes:

~~~tsx
/content/rules
/content/rules/new
/content/rules/:ruleSetId
~~~

List/detail require rules.read; new requires rules.write. Add lazy RuleSetsRoute and RuleSetEditorRoute.

- [ ] **Step 6: Verify and commit**

~~~bash
pnpm --dir apps/admin-web exec vitest run \
  src/features/rule-sets/preview-repository.test.ts \
  src/app/App.test.tsx src/features/auth/AuthFlow.test.tsx
pnpm --dir apps/admin-web lint
git add apps/admin-web/src/features/rule-sets \
  apps/admin-web/src/app/admin-navigation.ts \
  apps/admin-web/src/routes/definitions.tsx \
  apps/admin-web/src/routes/lazy-pages.tsx \
  apps/admin-web/src/app/App.test.tsx \
  apps/admin-web/src/features/auth/AuthFlow.test.tsx \
  apps/admin-web/src/styles/index.css
git commit -m "feat(admin): add rule set inventory"
~~~

---

### Task 3: Add Restricted Draft Editor and Compile Preview

**Files:**
- Create: apps/admin-web/src/features/rule-sets/form.ts
- Create: apps/admin-web/src/features/rule-sets/RuleSetEditorPage.tsx
- Create: apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx
- Modify: apps/admin-web/src/styles/index.css

**Interfaces:**
- Consumes: Task 2 repository and backend options/validation.
- Produces: create/edit/validate UI with dirty-navigation protection.

- [ ] **Step 1: Write failing form/editor tests**

Add exact tests:

~~~text
focuses the first invalid field when creating a draft
derives player_count from role counts and has no player_count input
normalizes tags and enforces special role maximums
shows server errors by path
renders compiled actions hash snapshot summary and rule text
does not expose raw JSON action-order or arbitrary prompt inputs
blocks route changes and beforeunload while dirty
saves both stable and revision expected lock versions
~~~

- [ ] **Step 2: Run and verify missing editor/form**

~~~bash
pnpm --dir apps/admin-web exec vitest run \
  src/features/rule-sets/RuleSetsFlow.test.tsx
~~~

- [ ] **Step 3: Implement deterministic form helpers**

~~~typescript
export function derivePlayerCount(input: RuleSetDraftInput) {
  return Object.values(input.role_counts).reduce(
    (total, count) => total + count,
    0,
  );
}

export function cleanRuleSetInput(input: RuleSetDraftInput): RuleSetDraftInput {
  return {
    ...input,
    name: input.name.normalize("NFKC").trim(),
    description: input.description.normalize("NFKC").trim(),
    complexity: input.complexity.normalize("NFKC").trim(),
    estimated_duration: input.estimated_duration.normalize("NFKC").trim(),
    rule_tags: Array.from(
      new Set(input.rule_tags.map((item) => item.normalize("NFKC").trim()).filter(Boolean)),
    ),
    role_counts: { ...input.role_counts },
  };
}
~~~

validateRuleSetInput mirrors immediate structural/combination checks for UX but does not replace POST validate. formErrorsFromApi maps paths such as role_counts.werewolf and sheriff_vote_weight to exact controls.

- [ ] **Step 4: Build five editor sections**

1. 基础信息：ID only on create, name/description/complexity/duration/tags/display order。
2. 阵容：seven supported roles, count controls, derived total and 6–12 hint。
3. 玩法：win condition、sheriff、weight、speech、self-explosion、badge policy。
4. 编译预览：validation errors/warnings、derived actions、hash、snapshot summary、rule text。
5. 修订历史：number/state/hash/publisher/time/reason, no edit action on published history。

Use options response for labels/limits. No JSON textarea.

- [ ] **Step 5: Add save/validate and dirty navigation behavior**

~~~typescript
const baseline = useRef(JSON.stringify(cleanRuleSetInput(initialInput)));
const isDirty =
  JSON.stringify(cleanRuleSetInput(draft)) !== baseline.current;

const blocker = useBlocker(({ currentLocation, nextLocation }) =>
  !allowNavigation.current &&
  isDirty &&
  currentLocation.pathname !== nextLocation.pathname
);
~~~

Create saves a draft then navigates to its detail. Update sends both lock versions and display_order. Validate sends the exact expected draft revision. Only a successful save updates baseline/cache and invalidates lists.

Because the backend validates a persisted draft, disable the 编译预览 action while isDirty is true and show “请先保存草稿，再生成编译预览”。This prevents presenting a preview for content the server has not stored.

- [ ] **Step 6: Verify and commit**

~~~bash
pnpm --dir apps/admin-web exec vitest run \
  src/features/rule-sets/RuleSetsFlow.test.tsx
pnpm --dir apps/admin-web lint
git add apps/admin-web/src/features/rule-sets/form.ts \
  apps/admin-web/src/features/rule-sets/RuleSetEditorPage.tsx \
  apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx \
  apps/admin-web/src/styles/index.css
git commit -m "feat(admin): edit and validate rule set drafts"
~~~

---

### Task 4: Preserve Dirty Forms on Conflict and Add High-Risk Actions

**Files:**
- Create: apps/admin-web/src/features/rule-sets/RuleSetTransitionDialog.tsx
- Modify: apps/admin-web/src/features/rule-sets/RuleSetEditorPage.tsx
- Modify: apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx
- Modify: apps/admin-web/src/styles/index.css

**Interfaces:**
- Consumes: editor state and transition API.
- Produces: safe publish/archive/restore/default/duplicate interactions.

- [ ] **Step 1: Write failing conflict/permission/dialog tests**

~~~text
keeps dirty form content and baseline on 409
reloads server revision only after explicit confirmation
content editor can edit but cannot publish archive restore or set default
super admin publishes with a 3-500 character reason
default archive requires replacement selection and shows both affected IDs
lifecycle actions are disabled while dirty
dialog traps focus closes with Escape and restores trigger focus
successful mutation updates detail then invalidates lists
~~~

- [ ] **Step 2: Run and verify missing high-risk flow**

~~~bash
pnpm --dir apps/admin-web exec vitest run \
  src/features/rule-sets/RuleSetsFlow.test.tsx \
  -t "409|content editor|super admin|focus|default"
~~~

- [ ] **Step 3: Implement exact permission gates**

~~~typescript
const isSuperAdmin = session?.user.role === "super_admin";
const canWrite =
  !repository.isPreview &&
  hasAdminPermission(permissions, "rules.write");
const canPublish =
  !repository.isPreview &&
  isSuperAdmin &&
  hasAdminPermission(permissions, "rules.publish");
const canArchive =
  !repository.isPreview &&
  isSuperAdmin &&
  hasAdminPermission(permissions, "rules.archive");
const canSetDefault =
  !repository.isPreview &&
  isSuperAdmin &&
  hasAdminPermission(permissions, "rules.set_default");
~~~

Restore uses canArchive. Read routes stay permission-based and do not require Super Admin role.

- [ ] **Step 4: Keep 409 state untouched**

~~~typescript
function handleMutationError(error: unknown) {
  const apiError = asRuleSetAdminError(error);
  if (apiError.status === 409) {
    setConflict(apiError);
    setTransitionAction(null);
    return;
  }
  if (apiError.status === 422) {
    const nextErrors = formErrorsFromApi(apiError.fieldErrors);
    setFormErrors(nextErrors);
    focusFirstInvalidRuleField(nextErrors);
    return;
  }
  setRequestError(apiError);
}
~~~

Do not set draft、detail cache、baseline or auto-invalidate on conflict. The conflict alertdialog offers 复制本地内容 and 重新加载最新版本; only the second explicitly refetches and resets baseline.

- [ ] **Step 5: Implement accessible reason/impact dialogs**

Publish、archive、restore、set-default use a role=alertdialog with 3–500 validation. Archive of default requires a replacement published rule and sends both expected lock versions. Set-default names previous/next default. Duplicate asks new stable ID/name but does not require lifecycle reason. Disable every transition while dirty or pending.

- [ ] **Step 6: Verify and commit**

~~~bash
pnpm --dir apps/admin-web exec vitest run \
  src/features/rule-sets/RuleSetsFlow.test.tsx
pnpm --dir apps/admin-web lint
git add apps/admin-web/src/features/rule-sets/RuleSetTransitionDialog.tsx \
  apps/admin-web/src/features/rule-sets/RuleSetEditorPage.tsx \
  apps/admin-web/src/features/rule-sets/RuleSetsFlow.test.tsx \
  apps/admin-web/src/styles/index.css
git commit -m "feat(admin): protect rule set lifecycle actions"
~~~

---

### Task 5: Add Preview Browser Accessibility and Final Gates

**Files:**
- Modify: apps/admin-web/e2e/admin-workspace.spec.ts
- Modify: apps/admin-web/src/app/App.test.tsx
- Modify: apps/admin-web/src/styles/index.css

**Interfaces:**
- Consumes: completed rule feature.
- Produces: preview-only browser QA and build evidence.

- [ ] **Step 1: Add failing Playwright scenarios**

Add scenarios:

~~~text
规则列表通过键盘导航并保持 axe 基线
preview 规则模块保持只读
窄屏侧栏可进入规则页并自动收起
规则列表和详情在 320/768/1440 宽度无横向溢出
编译预览与修订历史具有可访问标题
~~~

Assert no publish/archive/default/create buttons in preview, rather than mocking success.

- [ ] **Step 2: Build and run the focused browser suite**

~~~bash
pnpm --dir apps/admin-web run build:e2e
pnpm --dir apps/admin-web exec playwright test \
  e2e/admin-workspace.spec.ts --project=desktop-chromium
~~~

Expected before final CSS/semantics: new rule scenarios FAIL on navigation, overflow or accessibility assertions.

- [ ] **Step 3: Fix semantic and responsive gaps**

Use existing Admin shell breakpoints. Form labels must bind to controls; validation summary uses role=alert; asynchronous status uses aria-live=polite; modal error uses aria-live=assertive. Keep primary actions visible without fixed overlays at 320px.

- [ ] **Step 4: Run all Admin gates**

~~~bash
pnpm --dir apps/admin-web lint
pnpm --dir apps/admin-web test -- --run
pnpm --dir apps/admin-web build
pnpm --dir apps/admin-web run build:e2e
pnpm --dir apps/admin-web exec playwright test \
  e2e/admin-workspace.spec.ts --project=desktop-chromium
~~~

- [ ] **Step 5: Commit browser QA**

~~~bash
git add apps/admin-web/e2e/admin-workspace.spec.ts \
  apps/admin-web/src/app/App.test.tsx \
  apps/admin-web/src/styles/index.css
git commit -m "test(admin): cover rule set accessibility"
~~~

## Plan Completion Gate

~~~bash
pnpm --dir apps/admin-web lint
pnpm --dir apps/admin-web test -- --run
pnpm --dir apps/admin-web build
~~~

Expected: all gates PASS。人工核对 preview 绝无写入口、Content Editor 无高风险入口、409 不覆盖本地输入、列表状态可复制 URL 复现。
