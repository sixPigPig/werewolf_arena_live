**Findings**

- No actionable P0, P1, or P2 differences remain.
- [P3] Existing Admin chrome is slightly wider and taller than the generated source.
  Location: global sidebar and top navigation.
  Evidence: the source uses an approximately 234 px sidebar and 50 px top bar; the existing product shell renders at approximately 258 px and 64 px in the normalized capture.
  Impact: the content canvas is slightly narrower, but all primary controls and the complete public-information section remain above the fold.
  Resolution: accepted as an intentional existing-product constraint; the task-specific content was compacted without changing global navigation behavior.

**Required Fidelity Surfaces**

- Fonts and typography: retained the product's existing Chinese/system font stack, Ant Design optical weights, compact table type, and source-like heading hierarchy. No clipping or unintended wrapping remains.
- Spacing and layout rhythm: phase scrubber, event/state split, causal chain, public-information grid, radii, borders, and section gaps match the source composition. The final capture has no player-table or causal-chain horizontal scrollbar.
- Colors and visual tokens: uses the source's white/slate surfaces, blue active controls, green alive state, red danger state, and subtle blue selection treatment through existing Admin tokens.
- Image quality and asset fidelity: the screen contains no photographic or generated raster assets. Product logo and Ant Design icons remain the existing source-quality assets; no custom SVG, emoji, placeholder, or CSS illustration was introduced.
- Copy and content: source labels and hierarchy are preserved in Chinese. Player identities, actions, targets, results, speeches, votes, and system messages come from the real persisted game rather than the illustrative mock data.

**Open Questions**

- None blocking. The generated mock's illustrative check target/result differs from the real game; the implementation intentionally displays the persisted fact: 4号唐梨查验1号贺峥为好人阵营.

**Implementation Checklist**

- [x] Merge round digest and omniscient state into one historical fact scrubber.
- [x] Reconstruct player life state at the selected record sequence.
- [x] Show authoritative private actions, incoming effects, public speech, votes, and judge messages at the cursor.
- [x] Support follow-live, historical review, return-latest, moment/final state, adjacent-event navigation, and diagnostic drawer.
- [x] Verify production build, lint, tests, browser interactions, and console.

**Comparison History**

1. Initial P2 findings:
   - The player roster and causal chain produced horizontal scrollbars at the target desktop width.
   - Ability stage selection preferred passive close-eye narration over the authoritative ability result.
   Fixes:
   - Reduced the roster minimum width, allowed dense cells to wrap, and made causal steps wrap.
   - Added semantic stage priority so result/decision facts outrank wake/sleep narration, then resolved the persisted activation actor, target, and result.
2. Second P2 finding:
   - Existing page-header density pushed the public-information summary below the target first fold.
   Fixes:
   - Reduced task-page top padding, metric row gap, panel margin, and panel internal rhythm while preserving the Admin shell.
3. Post-fix evidence:
   - Full-view comparison: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/design-comparison-source-left-implementation-right.png`
   - Focused event/roster comparison: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/design-comparison-focus-event-roster.png`

**Evidence**

- Source visual truth: `/Users/fanqiedanhuatang/.codex/generated_images/019fb331-4160-7a02-a45d-050eb6961ea0/call_KO0rZeXzsFLeHWmxcwptEBzB.png`
- Browser-rendered implementation: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/omniscient-history-final-1487x1058.png`
- Source pixels: 1487 x 1058.
- Implementation pixels: 1487 x 1058.
- CSS viewport requested: 1502 x 1069 at device scale 1; the in-app browser content capture normalized to 1487 x 1058, exactly matching the source pixels.
- State: authenticated development Admin, light theme, real game `v2_game_0027bccb8e6c4859`, historical first-night seer-result cursor.
- Focused comparison was required because dense table text and event-result alignment were not legible enough in the full-view pair.
- Primary interactions tested: historical stage selection, moment/final state toggle, return to latest, adjacent fact navigation, and diagnostic drawer open/close.
- Console checked: no task-introduced error. The existing Ant Design cssVar `App` development warning remains unchanged.

**Follow-up Polish**

- If the global Admin shell is redesigned later, its sidebar and top-bar dimensions can be brought to the generated source without changing this panel.

## 2026-07-30 AntD Table / Complete Facts Correction

**Findings**

- No actionable P0, P1, or P2 differences remain for the four annotated areas.
- The roster is now an Ant Design `Table` with `size="small"` and all five columns visible at the desktop comparison width.
- The current-event and omniscient-state panels render at the same measured height: `746.609375 px` each.
- The selected persisted model request contains 45 public-timeline facts; all 45 render in source `record_seq` order with 44 sibling connectors between them.
- The fact list is constrained to a 240 px viewport with 6,798 px of scroll content, so the full request does not expand the page or the right roster.
- The public-speech list is constrained to a 150 px viewport with 410 px of scroll content. Speech text uses `white-space: pre-wrap` and `text-overflow: clip`; no ellipsis transform remains.

**Implementation Verification**

- [x] Ant Design table confirmed by runtime class `ant-table-small`.
- [x] 12 player data rows rendered with no horizontal table overflow at the comparison viewport.
- [x] Left and right main panels are equal height.
- [x] Current event speech is complete and independently scrollable.
- [x] Public speech entries retain the complete persisted text and scroll vertically.
- [x] Causal facts come from the selected request's persisted `request_payload.public_timeline.events`, not an event-derived five-item summary.
- [x] `history.timeline` remains available in the raw model request; the causal-chain presentation no longer duplicates player speech bodies.
- [x] Down arrows are siblings between fact cards, never children of the preceding fact card.

**Comparison Evidence**

- Annotated reference: `/var/folders/02/1d84m8gn0m7dr08p6kk2jlyw0000gn/T/codex-clipboard-d197a85c-57b9-4358-9d0b-e26de9f93419.png`
- Main-grid implementation: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/omniscient-main-grid.png`
- Complete-speech implementation: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/omniscient-public-speeches.png`
- Browser state: authenticated development Admin, light theme, real game `v2_game_2bfb8db828ef4443`, selected 4号唐梨白天发言 request.
- The reference and both implementation captures were inspected together in one comparison input.

final result: passed

## 2026-07-31 Phase Steps / Expandable Action Table

**Findings**

- No actionable P0, P1, or P2 differences remain for the annotated phase-progress and action-timeline regions.
- The phase rail now uses the native Ant Design vertical `Steps` component and preserves each phase's persisted step/model-request counts and terminal status.
- The action timeline now uses the native Ant Design `Table` with a 680 px vertical viewport. Every row can expand to show the action lifecycle, while the action label still opens the complete request-detail drawer.
- The reference contains illustrative actors and 136 readable steps; the verified implementation intentionally renders the real persisted game with 65 readable steps.

**Required Fidelity Surfaces**

- Fonts and typography: retained the existing Admin system font stack and compact hierarchy. Step titles, counts, table headers, actions, statuses, and monospace timestamps remain readable without unintended wrapping.
- Spacing and layout rhythm: the phase rail keeps the source-like narrow proportion; the table fills the remaining workspace; the final desktop capture has no unnecessary horizontal scrollbar.
- Colors and visual tokens: native Ant Design blue step progress, green success state, white/slate surfaces, borders, hover states, and selected-row treatment remain aligned with the existing Admin theme.
- Image quality and asset fidelity: this region has no raster content. All visible controls use the existing Ant Design icon set; no custom SVG, emoji, placeholder, or CSS illustration was introduced.
- Copy and content: Chinese labels and the seven source columns are preserved. Actor, audience, status, model/template source, duration, phase count, and lifecycle values come from persisted facts.

**Interaction And Responsive Verification**

- [x] Clicking “第 1 夜” filters the table from 65 rows to 15; clicking it again restores all 65 rows.
- [x] Expanding “法官 / 开场播报” exposes one visible “动作生命周期” region.
- [x] Clicking the action label still opens the complete request-detail drawer; closing it returns to zero open dialogs.
- [x] At a 1536 x 900 requested viewport, the table body has `clientWidth = scrollWidth = 978 px`.
- [x] At a 1024 x 900 requested viewport, the page has no document-level horizontal overflow; the 900 px table scroll width is contained inside its 726 px body.
- [x] Browser console contains no task-introduced runtime exception. The existing global Ant Design cssVar `App` development warning remains.

**Comparison History**

1. Initial P2 finding:
   - At the 1536 px desktop viewport, the first Ant Design Table column widths plus the expansion column exceeded the available table body by approximately 30 px, producing an unnecessary horizontal scrollbar.
   Fix:
   - Reduced the seven data-column widths and the table's horizontal scroll target from 980 px to 900 px.
2. Post-fix evidence:
   - The desktop table body measures `978 px` for both client and scroll width.
   - The same-screen source/implementation comparison shows the intended Steps rail, seven-column table, compact density, and vertical table scrolling without desktop horizontal overflow.

**Evidence**

- Source visual truth: `/var/folders/02/1d84m8gn0m7dr08p6kk2jlyw0000gn/T/codex-clipboard-41ef330f-5087-4e71-87d3-aa4c794557b0.png`
- Browser-rendered implementation: `/private/tmp/v2-steps-expandable-table-implementation.png`
- Same-input comparison: `/private/tmp/v2-steps-expandable-table-comparison.png`
- Source pixels: 3138 x 1624.
- Implementation region pixels: 1213 x 804.
- CSS viewport requested: 1536 x 900 at device scale 1; the in-app browser content capture measured 1521 x 891.
- Density normalization: the full source was proportionally downsampled to 1213 px wide and vertically centered beside the native 1213 x 804 implementation crop. The comparison judges component structure and region proportions; persisted row content is intentionally different.
- State: authenticated development Admin, light theme, real game `v2_game_0027bccb8e6c4859`, all phase filters cleared, action rows collapsed.
- Full-view comparison evidence: the same-input comparison above covers the complete task-target region.
- Focused comparison was not required because the complete task-target region is readable at the implementation's native 1213 x 804 resolution. The expanded lifecycle state was verified separately through the browser and targeted component test.
- Primary interactions tested: phase select/toggle, action-row expand, request-detail drawer open, and drawer close.

**Follow-up Polish**

- None required for this change.

final result: passed

## 2026-07-30 Private Knowledge Ownership / Localization

**Root Cause**

- The persisted private knowledge was correct. The Admin presentation incorrectly treated every `werewolf.attack` activation decision target as if that target player privately knew “被袭击”.
- In the verified game, first-night discussion activations proposed several different targets before the final team result. Those proposals are private wolf decisions, not knowledge granted to the proposed targets.
- Durable `v2_knowledge_facts` already records the correct owner for werewolf resolution, seer investigation, and witch attack observation facts.

**Findings**

- No actionable P0, P1, or P2 differences remain for the annotated table.
- “当前私有信息” now projects only persisted player-owned knowledge facts visible at the selected `record_seq`.
- Players 7, 8, and 9 no longer receive inferred “被袭击” knowledge. Their current private-information cells correctly show “暂无私有信息”.
- Werewolves see the resolved first- and second-night attack targets; the seer sees the owned investigation result; the witch sees the two owned attack observations.
- `witch_poison` renders as “女巫毒杀”. A runtime scan of the roster's status, private-information, and recent-action columns found no remaining snake_case tokens.
- Six players with no recorded action display `--`; the former “尚未执行角色技能” text is absent.
- Historical first-night attack review contains no second-night facts and no leaked attack knowledge for players 7, 8, or 9.

**Implementation Verification**

- [x] Private information is sourced from `knowledge_facts`, not reverse-inferred from ability targets.
- [x] Knowledge facts respect owner scope, source activation visibility, and selected timeline sequence.
- [x] Technical projection/action-commit facts are not duplicated as player-facing private information.
- [x] Known role, ability, team, death-cause, and knowledge-fact values render in Chinese.
- [x] No-action cells use `--`.
- [x] Targeted tests, TypeScript, ESLint, production build, browser interactions, and runtime DOM checks pass.

**Comparison Evidence**

- Annotated reference: `/var/folders/02/1d84m8gn0m7dr08p6kk2jlyw0000gn/T/codex-clipboard-c1e6e1e2-d14e-4fe5-94ff-a7f09e98085c.png`
- Corrected real-page capture: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/omniscient-private-info-wide.png`
- Browser state: authenticated development Admin, light theme, real game `v2_game_2bfb8db828ef4443`, latest 4号唐梨白天发言 cursor.
- The annotated reference and corrected implementation were inspected together in one comparison input.

final result: passed

## 2026-07-30 Native Small / Speech Body Removal

**Findings**

- No actionable P0, P1, or P2 differences remain for the latest annotated correction.
- The roster keeps Ant Design `Table size="small"` and no longer overrides the component's header/body padding or font size.
- Runtime computed styles are Ant Design's native small values: `8px` padding on all table-cell sides and `14px` table text.
- All 45 persisted public-timeline facts remain in source `record_seq` order with 44 sibling connectors.
- The 18 `player_statement` fact cards render zero body paragraphs. Each card retains only its sequence, fact type, temporal context, and authority label.
- The main event and roster panels remain equal height at `796.6171875 px`; the roster has 12 rows and no horizontal overflow.

**Implementation Verification**

- [x] Runtime class remains `ant-table-small`.
- [x] No `.ant-table-thead > th` or `.ant-table-tbody > td` size override remains in the task stylesheet.
- [x] Player-statement speech remains in the persisted model request and public-speech history, but is not duplicated in the causal chain.
- [x] Non-speech facts retain their concise fact summaries.
- [x] Causal-chain vertical scrolling and between-card arrow placement remain intact.
- [x] Targeted tests, TypeScript, ESLint, production build, and browser DOM checks pass.

**Comparison Evidence**

- Annotated reference: `/var/folders/02/1d84m8gn0m7dr08p6kk2jlyw0000gn/T/codex-clipboard-80f0d66f-c2c8-42e7-a9e8-273b1bdef20d.png`
- Native-small roster capture: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/omniscient-native-small-no-speech.png`
- Causal-chain capture: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/omniscient-cause-no-speech.png`
- Browser state: authenticated development Admin, light theme, real game `v2_game_2bfb8db828ef4443`, selected 4号唐梨白天发言 request.
- The annotated reference and the corrected real-page capture were inspected together in one comparison input.

final result: passed

## 2026-07-30 Private Knowledge History Modal / Causal Height Cleanup

**Findings**

- No actionable P0, P1, or P2 differences remain for the four annotated areas.
- The inactive information icon beside “此刻发生了什么” and the non-interactive three-color roster legend are removed.
- The causal container no longer stretches into unused space. On the verified real record it measures `308.140625 px`; its fact viewport remains `240 px` high with `3,452 px` of scroll content.
- The current-event and omniscient-state cards still match at `928.421875 px`, preserving the previously requested equal-height layout.
- Each populated private-information cell displays only its latest persisted fact and an Ant Design link button with the total history count.
- The “全部私有信息” modal lists every fact for the selected player in persisted chronological order and closes normally.

**Implementation Verification**

- [x] Information icon runtime count is zero.
- [x] Bottom legend runtime count is zero.
- [x] Real table cells show only the latest fact, including `第2夜获知：1号 贺峥被袭击` for the witch.
- [x] “查看 1号 贺峥的全部私有信息（2条）” opens a dialog containing both first- and second-night facts.
- [x] Dialog close returns the page to zero open dialogs.
- [x] Empty recent-action cells remain `--`.
- [x] Targeted Vitest: 13 passed.
- [x] TypeScript, focused ESLint, production build, browser interactions, and runtime measurements pass.

**Comparison Evidence**

- Annotated reference: `/var/folders/02/1d84m8gn0m7dr08p6kk2jlyw0000gn/T/codex-clipboard-e71f407c-b061-4866-8d8a-f060d14808c3.png`
- Same logical viewport (`1515 x 805`) corrected page: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/omniscient-same-viewport-closed.png`
- Modal-open evidence: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/omniscient-private-modal-and-compact-cause.png`
- Browser state: authenticated development Admin, light theme, real game `v2_game_2bfb8db828ef4443`, latest 4号唐梨白天发言 cursor.
- The annotated reference and same-viewport implementation were inspected together in one comparison input.

final result: passed

## 2026-07-31 Causal Panel Remaining-Space Fill

**Findings**

- The blank region below the causal chain was caused by shrinking the causal container to its former `240 px` list viewport while the left card still matched the roster card's full height.
- The causal container now consumes the left card's remaining height, while size containment prevents its 45 facts from increasing the main grid row.
- At the matched `1515 x 805` viewport, the left and right cards remain equal at `928.421875 px`.
- The causal container ends `15 px` above the card edge, accounting only for the intended `14 px` bottom margin and card border; no additional blank region remains.
- The fact viewport expands to `435 px` and retains `3,452 px` of independently scrollable content.

**Implementation Verification**

- [x] 45 fact cards and 44 between-card connectors remain rendered.
- [x] Causal fact list keeps `overflow-y: auto`.
- [x] Main grid height remains driven by the roster rather than the full fact list.
- [x] TypeScript and production build pass.

**Comparison Evidence**

- Annotated reference: `/var/folders/02/1d84m8gn0m7dr08p6kk2jlyw0000gn/T/codex-clipboard-9cf76700-56fb-491c-b589-5a967d3c5cb2.png`
- Corrected real-page capture: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/30/019fb331-4160-7a02-a45d-050eb6961ea0/omniscient-cause-fill-remaining-space.png`
- Browser state: authenticated development Admin, light theme, real game `v2_game_2bfb8db828ef4443`, latest 4号唐梨白天发言 cursor.
- The reference and corrected implementation were inspected together in one comparison input.

final result: passed
