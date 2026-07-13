# Admin Rule Sets Final Fix Report

Date: 2026-07-13
Result: DONE

## Scope and TDD evidence

### 1. Bounded error privacy

- RED: updated flow/form regressions expected fixed Chinese copy and absence of injected server strings such as `SELECT`, `players`, driver details, raw validation detail, and private reload/load text. The focused flow run failed on the old rendered `规则服务暂时不可用` / `重载失败` strings and the form test initially exposed raw field messages.
- GREEN: added `error-presentation.ts`, mapped known status/code/context to bounded copy, removed rendering of `AdminApiError.message`, Problem Details `detail`, and raw Problem Details field messages across list, duplicate, editor load/save/validate/reload, and lifecycle errors. Explicit parsed validation DTO warning/error messages remain visible.
- Coverage: `error-presentation.test.ts`, `form.test.ts`, and list/editor/lifecycle cases in `RuleSetsFlow.test.tsx`.

### 2. Options-only, fail-closed list behavior

- RED: `pnpm test --run src/features/rule-sets/list-state.test.ts` failed the custom advertised-options case because hard-coded status/sort values won. Flow regressions also demonstrated that options-pending/failure previously left the list/action surface available. A later lifecycle regression failed because archive was enabled when `published` was not advertised.
- GREEN: list parsing and serialization now require `RuleSetOptions`; lifecycle/status choices and every signed sort option are rendered from options; signed sorts map to field plus direction. The list is not queried until options succeeds. Options failure renders a bounded retryable unavailable state and asserts zero list calls. Published-candidate lifecycle queries also fail closed when `published` is not advertised and use an advertised signed sort.
- Coverage: custom options fixtures at URL-state and page-flow levels, options pending/failure zero-call checks, and lifecycle candidate zero-call checks.

### 3. Dirty lifecycle safety

- RED: focused flow regressions failed because archive remained enabled and could open on a published rule with an unsaved draft.
- GREEN: set-default, archive, restore, and the generic transition opener are dirty-guarded. The UI displays a save/discard requirement; published-with-draft regressions prove no candidate query, no transition repository call, and no local draft loss. Publish retains its validation/current-revision/dirty gate.

### 4. Required read data

- RED: focused list/editor tests failed because separate draft/published revisions, display order, updated time, current hash summaries, and complete history metadata were absent.
- GREEN: list rows now show draft and published revision numbers separately, display order, updated time, player/role summary, status, and default. Editor summary shows current draft/published revision numbers and hash prefixes. History shows revision number/state, publish time/by, hash prefix, and per-revision game/live usage. Revision UUID and raw config are not rendered.

### 5. Strict parsers

- RED: `pnpm test --run src/features/rule-sets/contracts.test.ts` produced 13 expected failures for incomplete/duplicate roles, invalid ranges, duplicate choices/sorts/weights, non-positive weights, invalid constraints/regex, and invalid successful-validation output. A separate zero-tag-capacity regression also failed before the positive constraint fix.
- GREEN: options require exactly the seven unique role IDs, valid role ranges, unique choice/status/sort/weight arrays, positive weights, positive/nonnegative contract constraints, ordered min/max pairs, and a compilable ID regex. `valid: true` requires a nonempty rule preview and exactly 64 lowercase hexadecimal hash characters.

### 6. Accessibility

- RED: validation flow failed because `win_condition` and `speech_policy` select controls retained `aria-invalid=false` and lacked their server-error descriptions.
- GREEN: duplicate dialog explanatory copy is connected through `aria-describedby`. `Choice` accepts field errors through the stable `Field` IDs, setting `aria-invalid` and `aria-describedby`; win-condition and speech-policy server errors are covered.

## Verification

- `cd apps/admin-web && pnpm test --run src/features/rule-sets src/app/App.test.tsx`
  - PASS: 9 files, 164 tests.
- `cd apps/admin-web && pnpm test --run`
  - PASS: 24 files, 268 tests.
- `cd apps/admin-web && pnpm run build`
  - PASS: TypeScript project build and Vite production build; 147 modules transformed.
- `cd apps/admin-web && pnpm run lint`
  - PASS: ESLint exit 0.
- `cd apps/api && .venv/bin/python -m pytest -q tests/test_admin_rule_sets.py tests/test_rule_set_service.py tests/test_rule_set_repository.py tests/test_rule_set_validation.py tests/test_rule_set_snapshots.py`
  - PASS: 308 tests in 8.98s.
- `git diff --check`
  - PASS: no whitespace errors.
- Source audit with `rg` found no rule-set rendering of `error.message`, `requestError.message`, `mutation.error.message`, or `problem.detail`.

## Commits

- Final-fix implementation commit: `c3988451` (`fix(admin): close rule set final review gaps`).
- Review base: `cd7c3d61` (`fix(admin): harden rule set accessibility`).

## Concerns

- None remaining. The UI intentionally fails closed if a future options payload omits `published`; operators must retry or wait for a compatible options response rather than sending an unadvertised lifecycle query.
