# Task 4 report

## RED evidence

- Editor rendering: `pnpm test --run src/features/rule-sets/RuleSetsFlow.test.tsx -t "rule editor"` failed 3 tests because the placeholder routes had no structured fields.
- Validation gate: `pnpm test --run src/features/rule-sets/RuleSetsFlow.test.tsx -t "validation gates"` failed because the validation warnings had no accessible `校验警告` list.
- Save/dirty/conflict focused command was executed after the behavior implementation and passed 3/3; the covered assertions include local validation blocking, create navigation, route blocking, local-draft preservation, and explicit conflict reload.

## Implementation

- Added the structured create/detail editor using server-provided role ordering and constraints.
- Added local validation, create/update with exact rule-set and revision locks, clean JSON dirty baseline, before-unload and route blocking, conflict preservation/reload, query invalidation, and pending-action gating.
- Added server validation views containing only validity, errors, warnings, hash, preview text, and revision lock. The parser boundary already omits `compiled_snapshot`; the component never receives or renders it.
- Added status/default/revision, aggregate usage, operational warnings, and a maximum of 50 history entries without revision IDs or raw config.
- Replaced only the two bounded route placeholders in `RuleSetsPage.tsx` with the new editor.

## Verification

- Focused: `pnpm test --run src/features/rule-sets/RuleSetsFlow.test.tsx src/features/rule-sets/form.test.ts` — 23 passed.
- Full: `pnpm test --run` — 22 files, 181 tests passed.
- Build: `pnpm build` — passed (`tsc -b && vite build`).
- Lint: `pnpm lint` — passed with zero errors/warnings.
- Diff check: `git diff --check` — passed.

## Commit

- `feat(admin): add structured rule set editor`

## Concerns

- Publish is intentionally a validation-gated control only; lifecycle mutations belong to the subsequent lifecycle task.

## Review fixes

### Witnessed RED production fixes

- Server-derived sheriff normalization: the new form test failed with received vote weight `1` instead of the server's first allowed `1.5`; cleaning and disabled selects now use only the first supplied server choices. The test also omits the `none` badge policy.
- Cached rule identity and accessibility coverage initially exposed stale/incorrect expectations while the keyed editor and stable error associations were being completed. The editor is now keyed by route rule ID, so detail, draft, baseline, validation, conflict, and pending state remount together.
- Validation warning accessibility from the original implementation cycle remains documented above.

### Implemented review changes

- Removed hard-coded sheriff-off `1` and `none` from form cleaning and editor rendering; defaults, cleaning, disabled rendering, and validation all consume `RuleSetOptions`.
- Keyed the stateful editor by `ruleSetId` and added a prefetched-cache A-to-B route test proving B's name and rule lock render without A leakage.
- Added stable error IDs plus `aria-invalid` and `aria-describedby` propagation for scalar controls and the role-count fieldset/inputs.
- Added `reload` to the single pending-action state, duplicate-action guard, disabled/loading reload control, caught failure rendering, local-draft preservation on failure, and full state reset on successful reload.
- Expanded dirty blocking to pathname, query, and hash; covered reset, proceed, and cancelable `beforeunload` behavior.
- Added explicit 412 conflict coverage through the failed-reload scenario and successful/failed conflict reload coverage.

### Added coverage that passed without a production RED

- Same-path query/hash blocker proceed and `beforeunload` protection passed after the blocker production change.
- Successful conflict reload and local draft reset passed after reload production hardening.
- Existing tests continue to cover cleaned create navigation, local validation blocking repository work, validation lock body, opaque snapshot omission, publish invalidation after edits, read-only mode, history bounds, and retryable load errors.

### Verification after review fixes

- Focused editor/form: 2 files, 28 tests passed.
- All rule-set tests: 6 files, 68 tests passed.
- Full Admin suite: 22 files, 186 tests passed.
- `pnpm build`: passed.
- `pnpm lint`: passed with zero findings.
- `git diff --check`: pending immediately before commit.

### Resolved boundary evidence matrix

The previously open reviewer matrix is now covered directly in `RuleSetsFlow.test.tsx`:

- Exact request bodies: create asserts the complete cleaned JSON, including trimmed/deduplicated values and sheriff-off normalization from nonstandard server choices (`1.5` and `double`); update asserts both locks and the complete config/display body for a current draft (`expected_revision_lock_version: 7`) and the no-draft branch (`null`).
- Save/cache behavior: a direct `QueryClient.invalidateQueries` spy asserts list and saved-detail invalidation, and navigation after save proves the dirty baseline no longer blocks.
- Validation staleness: table-driven cases validate, edit, save, and revalidate for name, description, complexity, duration, tags, display order, every server role input (werewolf, villager, seer, guard, witch, hunter, idiot), win condition, sheriff enabled, sheriff weight, speech policy, self-explosion, and badge policy. Each case proves publish disables immediately after the edit, stays disabled after save, and enables only after revalidation.
- Invalid validation: a server `valid: false` result asserts the error list, `config.name` field association and summary alert, disabled publish, and non-rendering of an opaque `compiled_snapshot` sentinel.
- Load boundaries: dedicated editor 404 coverage asserts bounded not-found copy without server detail/request leakage; dedicated 503 coverage asserts bounded detail, opaque debug omission, retry, and recovery.
- Navigation protection: existing explicit tests cover blocker reset (`继续编辑`), blocker proceed across pathname/query/hash (`放弃修改并离开`), and cancelable `beforeunload` prevention.

### Boundary test cycle and verification

- Initial focused run after adding the matrix: 22 failures. These were harness expectation failures only (the exact create body preserved the documented default self-explosion value, invalidation caused an additional legitimate detail refetch, the draft lock fixture was explicitly overridden to `7`, and the table initially targeted a published fixture without a draft). No production defect was identified, so production code was not changed.
- Corrected focused editor/form: 2 files, 54 tests passed.
- All rule-set tests: 6 files, 94 tests passed.
- Full Admin suite: 22 files, 212 tests passed.
- `pnpm build`: passed.
- `pnpm lint`: passed after removing one unused test counter, with zero errors or warnings.
- `git diff --check`: passed.

### Remaining concern

- The historical limitation remains unchanged: the original save/dirty/conflict tranche predates this coverage pass and was not destructively replayed. Every boundary requested by the latest reviewer is now directly asserted; there is no remaining Task 4 coverage item.

### Nonempty options assumption resolved

- RED: `pnpm test --run src/features/rule-sets/contracts.test.ts` exited 1; 7 new cases failed because every required options collection accepted an empty array.
- Task 1 now models and parses `roles`, `win_conditions`, `sheriff_vote_weights`, `speech_policies`, `sheriff_badge_bomb_policies`, `statuses`, and `sorts` as nonempty.
- Task 4 defaults and disabled normalization no longer use hard-coded choice literals. A nonstandard-options form test proves win condition `slaughter_side`, sheriff weight `1.5`, speech policy `sheriff_directed`, and badge policy `double` are selected solely because the server supplies them first.
- Contracts/form: 2 files, 34 tests passed. Editor: 1 file, 46 tests passed. All rule-set: 6 files, 101 tests passed. Full Admin: 22 files, 219 tests passed.
- `pnpm build`: exit 0 (`tsc -b && vite build`). `pnpm lint`: exit 0. `git diff --check`: exit 0.
- Commit: `fix(admin): enforce nonempty rule set options` (final hash returned in the task handoff).
- Reviewer assumption resolved: nonempty server options are now an enforced parser/type invariant rather than an unchecked editor assumption.
- Concerns: None.
