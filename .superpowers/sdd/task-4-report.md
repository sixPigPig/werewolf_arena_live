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

### Remaining evidence concern

- The reviewer-requested exhaustive exact-body/invalidation matrix was not fully expanded in this fix commit: exact cleaned create JSON, both update-lock bodies including the null draft lock branch, direct query invalidation spies, every individual editable-field validation invalidation category, invalid validation response/path association, and dedicated editor 404/503 cases remain represented only partially or indirectly by existing repository/parser/form/flow tests. No RED evidence is claimed for those unadded cases.
- The earlier save/dirty/conflict tranche was not destructively removed and replayed, so its original report limitation remains: those tests first ran green after the initial implementation.
