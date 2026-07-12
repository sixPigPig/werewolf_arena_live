# 可配置规则集共享客户端与 Mobile 切换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 拆清规则目录项与历史快照契约，使 Mobile 显式选择默认 published revision、在开局提交 revision 前置条件，并安全处理 revision 更新、规则下架和人数变化。

**Architecture:** packages/game-client 增加严格规则 contract parser，并让 ApiError 暴露 public problem code/current_rule_set。GamesPage 保存用户选中的完整 RuleSetCatalogItem，而非只保存 ID；目录刷新不会无提示替换选中 revision，冲突通过显式 reconcile 和可访问确认对话框处理。

**Tech Stack:** TypeScript 6、React 19、TanStack Query 5、Vitest、Testing Library、Playwright、FastAPI TestClient。

## Global Constraints

- Requires completed runtime API contract: docs/superpowers/plans/2026-07-12-rule-runtime-snapshots.md。
- RuleSetCatalogItem 用于当前 published 目录；RuleSetSnapshot 用于 Live、History、Replay 和历史 state，两者不能继续混用。
- Catalog item 的 revision_id、revision_no、schema_version、content_hash、is_default、roles 必填。
- Legacy RuleSetSnapshot 的 managed metadata 可为空/缺失，version=2026.04 必须继续可读。
- Mobile 优先 is_default=true，不依赖数组第一项表达默认。
- 开局必须提交选中项 expected_rule_revision_id。
- 同 ID 新 revision 不得因 query 刷新自动覆盖当前选择或裁剪阵容。
- 人数不变的 revision 更新保留阵容；人数变化必须用户确认后才 resize。
- rule_set_unavailable 取消旧选择并候选新默认；人数变化仍需确认。
- 冲突待处理时禁止开局，取消 dialog 只能延后处理，不能继续提交旧 revision。
- 未知规则没有专属图片时保持当前文字 fallback。
- Live、History、Playback 页面继续只读保存 snapshot，不查询当前目录。
- 目录 staleTime 保持 15 秒；revision precondition 提供最终一致性。
- Admin preview E2E 不承担真实发布链路；跨端业务闭环由 API 集成测试验证。

---

## File Structure

- Modify packages/game-client/src/types.ts：RuleSetContent、RuleSetCatalogItem、RuleSetSnapshot 和请求字段。
- Create packages/game-client/src/rules/ruleContracts.ts：严格 catalog/snapshot/problem parser。
- Create packages/game-client/src/rules/ruleContracts.test.ts。
- Modify packages/game-client/src/api/client.ts、client.test.ts：解析错误 body/code/current rule。
- Modify packages/game-client/src/api/listRuleSets.ts、createGameRun.ts、endpoints.test.ts。
- Modify packages/game-client/src/index.ts：导出新类型/parser。
- Modify apps/mobile-web/src/pages/GamesPage.tsx、GamesPage.test.tsx：完整选择状态和 reconcile。
- Modify components/lobby/LobbyRuleSummary.tsx、LobbyRulePicker.tsx：目录类型。
- Create components/lobby/RuleCatalogConflictDialog.tsx、RuleCatalogConflictDialog.test.tsx。
- Modify e2e/support/mobile-api-fixtures.ts、e2e/lobby-redesign.spec.ts。
- Create apps/api/tests/test_rule_set_end_to_end.py：真实 Admin/API 生命周期闭环。
- Modify docs/mobile-web-production-design.md、docs/admin-deployment-runbook.md：客户端兼容期与告警。
- Modify .github/workflows/ci.yml only if current release-check does not execute the new unit/type/build gates; do not duplicate existing jobs.

---

### Task 1: Split Shared Rule Contracts and Parse Public Problems

**Files:**
- Modify: packages/game-client/src/types.ts:3-34,45-53,203-212,554-580,620-627
- Create: packages/game-client/src/rules/ruleContracts.ts
- Create: packages/game-client/src/rules/ruleContracts.test.ts
- Modify: packages/game-client/src/api/client.ts
- Modify: packages/game-client/src/api/client.test.ts
- Modify: packages/game-client/src/api/listRuleSets.ts
- Modify: packages/game-client/src/api/endpoints.test.ts
- Modify: packages/game-client/src/index.ts

**Interfaces:**
- Consumes: public catalog/problem response from runtime plan.
- Produces: RuleSetCatalogItem、RuleSetSnapshot and ApiError.code/currentRuleSet.

- [ ] **Step 1: Write failing type/parser/error tests**

~~~typescript
it("parses a managed catalog item separately from a legacy snapshot", () => {
  const catalog = parseRuleSetCatalogResponse({
    rule_sets: [managedCatalogFixture()],
  });
  const legacy = parseRuleSetSnapshot(legacySnapshotFixture());
  expect(catalog.rule_sets[0].revision_id).toBe("revision-1");
  expect(catalog.rule_sets[0].is_default).toBe(true);
  expect(legacy.version).toBe("2026.04");
  expect(legacy.revision_id).toBeUndefined();
});

it("exposes revision conflict details from FastAPI public problems", async () => {
  fetchMock.mockResolvedValue(
    jsonResponse(409, {
      detail: {
        code: "rule_revision_changed",
        message: "Rule revision changed.",
        current_rule_set: managedCatalogFixture(),
      },
    }),
  );
  await expect(createGameRun({
    rule_set_id: "classic_8",
    expected_rule_revision_id: "old-revision",
  })).rejects.toMatchObject({
    status: 409,
    code: "rule_revision_changed",
    currentRuleSet: expect.objectContaining({ revision_id: "revision-1" }),
  });
});
~~~

Also test malformed catalog fields, unknown roles, partial managed snapshot metadata, empty/non-JSON error bodies and request serialization.

- [ ] **Step 2: Run and verify missing types/parser**

~~~bash
pnpm --dir packages/game-client exec vitest run \
  src/rules/ruleContracts.test.ts \
  src/api/client.test.ts src/api/endpoints.test.ts
~~~

Expected: missing RuleSetCatalogItem/RuleSetSnapshot/module or ApiError field failures.

- [ ] **Step 3: Define exact shared types**

~~~typescript
export type RuleSetContent = {
  id: string;
  version: string;
  name: string;
  description: string;
  player_count: number;
  roles: RoleSpecSummary[];
  night_actions: string[];
  day_actions: string[];
  win_condition: string;
  reveal_policy: string;
  complexity: string;
  estimated_duration: string;
  role_summary: string;
  sheriff_enabled: boolean;
  sheriff_vote_weight: number;
  speech_policy: "sequential" | "sheriff_directed";
  speech_rounds: number;
  rule_tags: string[];
  werewolf_self_explosion_enabled: boolean;
  sheriff_badge_bomb_policy: "none" | "double";
};

export type ManagedRuleSetSnapshot = RuleSetContent & {
  revision_id: string;
  revision_no: number;
  schema_version: number;
  content_hash: string;
};

export type RuleSetCatalogItem = ManagedRuleSetSnapshot & {
  is_default: boolean;
};

export type LegacyRuleSetSnapshot = Partial<RuleSetContent> & {
  id: string;
  revision_id?: null;
  revision_no?: null;
  schema_version?: number;
  content_hash?: null;
};

export type RuleSetSnapshot = ManagedRuleSetSnapshot | LegacyRuleSetSnapshot;
~~~

RuleSetsResponse contains RuleSetCatalogItem[]. GameRun、GameSessionSummary、RawGameState、GamePlayback and replay adapters use RuleSetSnapshot. CreateGameRunRequest adds expected_rule_revision_id?: string.

- [ ] **Step 4: Add strict parsers**

parseRuleSetCatalogItem requires all managed fields and a 64-character lowercase hex hash. parseRuleSetSnapshot uses a discriminated rule: a string revision_id requires the complete managed runtime shape, while a legacy object requires only a non-empty id and validates each known optional field that is present. Legacy parsing tolerates and ignores unknown historical fields so an older client can still render bounded fallback text; managed/catalog parsing remains strict. parseRuleSetCatalogResponse rejects extra top-level fields. Keep stable role/team/model/category strings open for historical snapshots, but validate role/count whenever roles are present.

- [ ] **Step 5: Preserve and expose error bodies**

~~~typescript
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly currentRuleSet: RuleSetCatalogItem | null;

  constructor(
    status: number,
    options: {
      code?: string | null;
      currentRuleSet?: RuleSetCatalogItem | null;
      cause?: unknown;
    } = {},
  ) {
    super("Request failed with status " + status, { cause: options.cause });
    this.name = "ApiError";
    this.status = status;
    this.code = options.code ?? null;
    this.currentRuleSet = options.currentRuleSet ?? null;
  }
}
~~~

apiFetch reads the body once before checking response.ok. For errors, normalize body.detail when it is an object, otherwise use top-level body; parse code and current_rule_set defensively. Invalid current_rule_set yields null rather than hiding the HTTP error.

- [ ] **Step 6: Verify, typecheck and commit**

~~~bash
pnpm --dir packages/game-client exec vitest run \
  src/rules/ruleContracts.test.ts \
  src/api/client.test.ts src/api/endpoints.test.ts
pnpm --dir packages/game-client typecheck
git add packages/game-client/src/types.ts \
  packages/game-client/src/rules \
  packages/game-client/src/api/client.ts \
  packages/game-client/src/api/client.test.ts \
  packages/game-client/src/api/listRuleSets.ts \
  packages/game-client/src/api/endpoints.test.ts \
  packages/game-client/src/index.ts
git commit -m "feat(client): split rule catalog and snapshot contracts"
~~~

---

### Task 2: Select the Explicit Default and Submit Its Revision

**Files:**
- Modify: apps/mobile-web/src/pages/GamesPage.tsx:49-86,155-190,241-281,361-405
- Modify: apps/mobile-web/src/pages/GamesPage.test.tsx
- Modify: apps/mobile-web/src/components/lobby/LobbyRuleSummary.tsx
- Modify: apps/mobile-web/src/components/lobby/LobbyRulePicker.tsx

**Interfaces:**
- Consumes: RuleSetCatalogItem and CreateGameRunRequest from Task 1.
- Produces: stable explicit selection and revision-aware create request.

- [ ] **Step 1: Write failing default/revision tests**

~~~text
selects is_default even when it is not the first item
keeps an explicit user selection ahead of a later default
submits selected expected_rule_revision_id
renders an empty published catalog as empty not retry error
keeps unknown-rule image fallback
does not replace selected revision during background refetch
~~~

- [ ] **Step 2: Run and verify first-item/no-revision behavior**

~~~bash
pnpm --dir apps/mobile-web exec vitest run \
  src/pages/GamesPage.test.tsx \
  -t "is_default|expected_rule_revision_id|empty published|background refetch"
~~~

- [ ] **Step 3: Store the complete selected catalog item**

~~~typescript
function preferredRuleSet(
  ruleSets: RuleSetCatalogItem[],
  selected: RuleSetCatalogItem | null,
) {
  if (selected) return selected;
  return (
    ruleSets.find((rule) => rule.is_default) ??
    ruleSets[0] ??
    null
  );
}
~~~

Replace selectedRuleSetId state with selectedRuleSet: RuleSetCatalogItem | null. Initialize only when no explicit selection exists. User picker stores the complete item. A query refetch does not silently swap the object to a newer revision.

- [ ] **Step 4: Submit the exact revision**

~~~typescript
createGameRunMutation.mutate({
  rule_set_id: selectedRuleSet.id,
  expected_rule_revision_id: selectedRuleSet.revision_id,
  seed: seed ? Number(seed) : null,
  max_rounds: parsedMaxRounds,
  player_configs: normalizedPlayerConfigs,
});
~~~

Disable launch when catalog is successfully empty. Keep retry only for query errors. Update Lobby props from RuleSetSummary to RuleSetCatalogItem.

- [ ] **Step 5: Verify and commit**

~~~bash
pnpm --dir apps/mobile-web exec vitest run \
  src/pages/GamesPage.test.tsx
pnpm --dir apps/mobile-web lint
git add apps/mobile-web/src/pages/GamesPage.tsx \
  apps/mobile-web/src/pages/GamesPage.test.tsx \
  apps/mobile-web/src/components/lobby/LobbyRuleSummary.tsx \
  apps/mobile-web/src/components/lobby/LobbyRulePicker.tsx
git commit -m "feat(mobile): launch the explicit default rule revision"
~~~

---

### Task 3: Handle Revision Changes and Rule Unavailability

**Files:**
- Create: apps/mobile-web/src/components/lobby/RuleCatalogConflictDialog.tsx
- Create: apps/mobile-web/src/components/lobby/RuleCatalogConflictDialog.test.tsx
- Modify: apps/mobile-web/src/pages/GamesPage.tsx
- Modify: apps/mobile-web/src/pages/GamesPage.test.tsx
- Modify: apps/mobile-web/src/styles/index.css

**Interfaces:**
- Consumes: ApiError.code/currentRuleSet and existing resizeLineupForPlayerCount().
- Produces: explicit pending reconciliation state and accessible confirmation.

- [ ] **Step 1: Write failing conflict tests**

~~~text
refreshes catalog after rule_revision_changed
preserves lineup when only revision changes
keeps assignments until player-count change is confirmed
falls back to new default after rule_set_unavailable
keeps launch disabled after dialog cancel until conflict resolved
returns focus to launch after cancel or confirm
announces updates with aria-live
~~~

- [ ] **Step 2: Run and verify generic create error behavior**

~~~bash
pnpm --dir apps/mobile-web exec vitest run \
  src/pages/GamesPage.test.tsx \
  src/components/lobby/RuleCatalogConflictDialog.test.tsx
~~~

Expected: dialog module missing and GamesPage only shows a generic launch error.

- [ ] **Step 3: Add explicit pending reconciliation**

~~~typescript
type PendingRuleReconciliation = {
  reason: "revision_changed" | "unavailable";
  previous: RuleSetCatalogItem;
  candidate: RuleSetCatalogItem;
  playerCountChanged: boolean;
};
~~~

Mutation onError rules:

1. rule_revision_changed: invalidate/refetch ["rule-sets"]; prefer error.currentRuleSet when valid, otherwise find same ID in refreshed catalog。
2. rule_set_unavailable: refetch and choose refreshed is_default, then first item, then null。
3. same player count: immediately set candidate, preserve playerConfigs and announce。
4. changed count: keep previous selection/configs, set pending state, disable launch。
5. no candidate: clear selection and show published catalog empty/unavailable state。

- [ ] **Step 4: Build the accessible dialog**

~~~tsx
<div
  role="alertdialog"
  aria-modal="true"
  aria-labelledby="rule-change-title"
  aria-describedby="rule-change-description"
>
~~~

Trap Tab, focus confirm on open, Escape/cancel closes and returns focus but retains a blocking banner/button to reopen. Confirm calls resizeLineupForPlayerCount, updates selection, clears pending state and announces dropped seat assignments.

- [ ] **Step 5: Prevent accidental mutation during refetch**

A background catalog refetch that no longer contains the selected revision must enter the same reconciliation path instead of replacing selection. Compare both ID and revision_id. Do not resize until explicit confirmation.

- [ ] **Step 6: Verify and commit**

~~~bash
pnpm --dir apps/mobile-web exec vitest run \
  src/pages/GamesPage.test.tsx \
  src/components/lobby/RuleCatalogConflictDialog.test.tsx
pnpm --dir apps/mobile-web lint
git add apps/mobile-web/src/components/lobby/RuleCatalogConflictDialog.tsx \
  apps/mobile-web/src/components/lobby/RuleCatalogConflictDialog.test.tsx \
  apps/mobile-web/src/pages/GamesPage.tsx \
  apps/mobile-web/src/pages/GamesPage.test.tsx \
  apps/mobile-web/src/styles/index.css
git commit -m "feat(mobile): reconcile changed rule revisions"
~~~

---

### Task 4: Add Mobile Browser Contract and Accessibility Coverage

**Files:**
- Modify: apps/mobile-web/e2e/support/mobile-api-fixtures.ts
- Modify: apps/mobile-web/e2e/lobby-redesign.spec.ts
- Modify: apps/mobile-web/src/pages/GamesPage.test.tsx

**Interfaces:**
- Consumes: completed Mobile flow.
- Produces: browser evidence at 320/390/412 widths.

- [ ] **Step 1: Update all rule fixtures**

Every catalog fixture includes revision_id、revision_no、version、schema_version、content_hash、is_default and roles. Historical run/replay fixtures use RuleSetSnapshot and may retain version=2026.04 without managed metadata.

- [ ] **Step 2: Add failing Playwright scenarios**

~~~text
mobile uses a non-first explicit default and revision precondition
unknown managed rule keeps text fallback
revision conflict with same count preserves lineup
revision conflict with new count requires keyboard-confirmable alertdialog
rule unavailable selects the new default
320 390 and 412 widths have no horizontal overflow
~~~

Intercept POST /api/v1/games/runs and assert both rule_set_id and expected_rule_revision_id.

- [ ] **Step 3: Run focused browser tests**

~~~bash
pnpm --dir apps/mobile-web build
pnpm --dir apps/mobile-web exec playwright test \
  e2e/lobby-redesign.spec.ts
~~~

Expected before fixture/flow completion: request or conflict assertions FAIL.

- [ ] **Step 4: Fix final semantic/responsive issues**

Keep the launch bar usable with the dialog/banner at 320px, no horizontal overflow, visible focus rings, bound labels and aria-live messages. Do not introduce an image requirement for custom rule IDs.

- [ ] **Step 5: Run gates and commit**

~~~bash
pnpm --dir apps/mobile-web lint
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web build
pnpm --dir apps/mobile-web exec playwright test \
  e2e/lobby-redesign.spec.ts
git add apps/mobile-web/e2e/support/mobile-api-fixtures.ts \
  apps/mobile-web/e2e/lobby-redesign.spec.ts \
  apps/mobile-web/src/pages/GamesPage.test.tsx
git commit -m "test(mobile): cover revision-aware rule selection"
~~~

---

### Task 5: Prove the Cross-End Lifecycle and Finish Rollout Docs

**Files:**
- Create: apps/api/tests/test_rule_set_end_to_end.py
- Modify: docs/mobile-web-production-design.md
- Modify: docs/admin-deployment-runbook.md
- Inspect/modify: .github/workflows/ci.yml only when a required unit/type/build command is absent

**Interfaces:**
- Consumes: completed backend Admin/runtime and shared/Mobile contracts.
- Produces: business acceptance evidence and deployment sequence.

- [ ] **Step 1: Write the failing API lifecycle integration test**

Using FastAPI TestClient, SQLite, a Super Admin dev session and patched background target:

~~~python
def test_rule_lifecycle_is_consistent_across_admin_catalog_and_runs(
    rule_api_context: RuleApiContext,
) -> None:
    created = create_rule_draft(rule_api_context, rule_id="custom_8")
    published = publish_rule(rule_api_context, created, reason="上线新规则")
    set_default(rule_api_context, published, reason="切换大厅默认")

    catalog = rule_api_context.client.get("/api/v1/games/rule-sets").json()
    selected = next(item for item in catalog["rule_sets"] if item["id"] == "custom_8")
    assert selected["is_default"] is True

    first_run = create_run(
        rule_api_context,
        rule_id="custom_8",
        revision_id=selected["revision_id"],
    )
    old_snapshot = first_run["rule_set"]

    next_revision = edit_and_publish_next_revision(
        rule_api_context, published, name="自定义 8 人局 v2"
    )
    second_run = create_run(
        rule_api_context,
        rule_id="custom_8",
        revision_id=next_revision["published_revision"]["id"],
    )

    assert first_run["rule_set"] == old_snapshot
    assert second_run["rule_set"]["revision_no"] == 2
    assert second_run["rule_set"]["name"] == "自定义 8 人局 v2"

    catalog_after_publish = rule_api_context.client.get(
        "/api/v1/games/rule-sets"
    ).json()["rule_sets"]
    classic = next(item for item in catalog_after_publish if item["id"] == "classic_8")
    set_default_by_catalog_item(
        rule_api_context, classic, reason="恢复经典规则为默认"
    )
    archive_rule(rule_api_context, next_revision, reason="停止新建对局")
    unavailable = create_run_response(
        rule_api_context,
        rule_id="custom_8",
        revision_id=second_run["rule_set"]["revision_id"],
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "rule_set_unavailable"
~~~

Add Content Editor publish denial, stale revision current_rule_set response, old checkpoint restore after archive, and DB unavailable 503 without static fallback.

- [ ] **Step 2: Run and verify the missing integration module or behavior**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_rule_set_end_to_end.py -q
~~~

- [ ] **Step 3: Complete the fixture without bypassing security**

Reuse real Admin dev login/session cookie and X-CSRF-Token; do not override require_admin_permission or require_admin_csrf. Override only database session, background execution and nondeterministic IDs when an exact assertion needs them.

- [ ] **Step 4: Document compatibility and rollout**

Document:

- old clients may omit expected revision only during the measured compatibility window;
- new Mobile always submits it;
- rule_revision_changed and rule_set_unavailable UX;
- catalog empty behavior;
- exact rollout order: migrations → v1/v2 backend → Admin → shared client/Mobile → source switch;
- rollback application only, not data-lossy catalog downgrade;
- alert on sustained legacy no-revision creates before ending compatibility.

- [ ] **Step 5: Verify CI coverage**

Current root Makefile release-check must cover API pytest/Ruff/Alembic check、game-client typecheck/tests、Mobile lint/tests/build、Admin lint/tests/build. Change ci.yml only if one is absent; browser E2E remains its existing explicit job.

- [ ] **Step 6: Run the complete release gate**

~~~bash
make release-check
pnpm --dir apps/admin-web run build:e2e
pnpm --dir apps/admin-web exec playwright test \
  e2e/admin-workspace.spec.ts --project=desktop-chromium
pnpm --dir apps/mobile-web exec playwright test \
  e2e/lobby-redesign.spec.ts
~~~

Expected: all unit、lint、typecheck、build、Alembic and focused browser gates PASS.

- [ ] **Step 7: Commit final acceptance work**

~~~bash
git add apps/api/tests/test_rule_set_end_to_end.py \
  docs/mobile-web-production-design.md \
  docs/admin-deployment-runbook.md
git commit -m "test: prove configurable rule lifecycle end to end"
~~~

If Step 5 changed .github/workflows/ci.yml, stage that file in a separate git add command before the commit.

## Plan Completion Gate

~~~bash
make release-check
~~~

Expected: PASS。最终验收同时满足：非首项默认规则被选中、POST 含 revision、409 不丢阵容、人数变化先确认、旧 Live/replay/checkpoint 保持旧 revision、归档只阻止新局、数据库异常不使用静态目录。
