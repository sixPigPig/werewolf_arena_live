# Mobile Live Action Visibility Implementation Plan

> **For agentic workers:** Implement task by task with test-first changes. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make night actions, day votes, vote tallies, and resolved outcomes unmistakable on the shared mobile live/live-replay theater through a phase-aware center card, persistent event rail, and accessible event sheet.

**Architecture:** Keep `LivePage` and `LiveReplayPage` as director/event boundaries, enrich meaningful God View event lines in `@werewolf-arena/game-client`, add a mobile-only pure focus-presentation model, and compose the new action stage and event rail inside `MobileLiveTheater`. Use only director-visible `stageEvents`; preserve the existing playback clock and key cue durations.

**Tech Stack:** React 19, TypeScript 6, TanStack Query 5, React Router 7, Vite 8, Vitest 4, Testing Library, Playwright 1.61, CSS, pnpm workspaces.

## Global Constraints

- The canonical design is `docs/superpowers/specs/2026-07-13-mobile-live-action-visibility-design.md`.
- Do not change backend APIs, database schema, game-engine rules, SSE/WebSocket contracts, replay payloads, voice payloads, visual assets, or the omniscient role-reveal policy.
- All live UI must derive from events at or before `director.currentEventId`; never read future events into the rail or focus card.
- Preserve speech, subtitle, voice, pause, speed, latest, phase seek, replay/resume, failure, and terminal behavior.
- Do not add a second timer for result visibility. Preserve the existing key cue durations in `liveDirector`.
- Keep new mobile CSS under `mobile-live-*` selectors and do not change shared button contracts globally.
- Use semantic user-visible assertions. Avoid new brittle whole-file CSS string tests where component or browser assertions are possible.
- Do not stage unrelated worktree changes or audit artifacts.

## Target File Structure

- Modify `packages/game-client/src/live/liveGodView.ts`
- Modify `packages/game-client/src/live/liveGodView.test.ts`
- Modify `packages/game-client/src/live/liveDirector.test.ts`
- Create `apps/mobile-web/src/components/mobileLiveActionModel.ts`
- Create `apps/mobile-web/src/components/mobileLiveActionModel.test.ts`
- Create `apps/mobile-web/src/components/MobileLiveActionStage.tsx`
- Create `apps/mobile-web/src/components/MobileLiveActionStage.test.tsx`
- Create `apps/mobile-web/src/components/MobileLiveEventRail.tsx`
- Create `apps/mobile-web/src/components/MobileLiveEventRail.test.tsx`
- Modify `apps/mobile-web/src/components/MobileLiveTheater.tsx`
- Modify `apps/mobile-web/src/pages/LivePage.tsx`
- Modify `apps/mobile-web/src/pages/LivePage.test.tsx`
- Modify `apps/mobile-web/src/pages/LiveReplayPage.tsx`
- Modify `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`
- Modify `apps/mobile-web/src/styles/index.css`
- Create `apps/mobile-web/e2e/mobile-live-actions.spec.ts`
- Modify `apps/mobile-web/e2e/support/mobile-api-fixtures.ts` only if shared playback fixtures reduce duplication.
- Modify `docs/mobile-web-production-design.md`

---

### Task 1: Enrich Meaningful God View Event Lines

**Files:**

- Modify: `packages/game-client/src/live/liveGodView.ts`
- Test: `packages/game-client/src/live/liveGodView.test.ts`

- [ ] **Step 1: Add failing tests for parsed action moments**

Add focused tests proving `eventLines` contains stable event IDs and readable text for:

- `1号 刀票 → 7号` from each `werewolf_kill_vote`, including revote rounds.
- `最终狼刀 → 7号` from the separate `remove`/`eliminate` consensus result.
- `女巫救 7号` and `女巫未使用解药`.
- `女巫毒 5号` and `女巫未使用毒药`.
- `守卫守护 7号`.
- `预言家查验 8号` without exposing private/raw fields beyond the existing God View contract.
- `8号 → 1号` for a parsed vote.

Use fixtures with two different voters choosing the same target and assert that both event IDs remain present.

- [ ] **Step 2: Add failing tests for result summaries**

Cover:

- Weighted vote result text with `2.5票` formatting.
- Tied highest vote text.
- Exile result.
- Witch save, poison, guard save, peaceful night, and night death causal text.
- No `model_thinking_tick`, `model_response_delta`, raw payload dump, prompt, or private summary in `eventLines`.

- [ ] **Step 3: Run the focused shared tests**

```bash
pnpm --dir packages/game-client test -- --run src/live/liveGodView.test.ts
```

Expected: new assertions fail because `eventLineFor` currently omits `action_parsed` details and uses generic vote/night update text.

- [ ] **Step 4: Implement minimal event-line enrichment**

Inside `liveGodView.ts`:

- Add an `action_parsed` branch to `eventLineFor`.
- Reuse normalized action names and parsed choices; do not stringify arbitrary payloads.
- Add small formatting helpers for vote counts and top/tied tallies.
- Update `stateUpdatedReplayText` to prefer explicit exile, night resolution, and ballot summaries.
- Keep the existing `GodViewEventLine` shape and public exports stable.
- Keep event IDs as identity; do not deduplicate distinct votes by text.

- [ ] **Step 5: Re-run the focused shared tests**

```bash
pnpm --dir packages/game-client test -- --run src/live/liveGodView.test.ts
```

Expected: PASS.

- [ ] **Step 6: Protect key director result durations**

Add or update `liveDirector.test.ts` assertions showing vote ballot, exile, peaceful night, and night death state updates remain key, non-compressible 6,000ms cues before playback speed is applied.

```bash
pnpm --dir packages/game-client test -- --run src/live/liveDirector.test.ts
```

Expected: PASS without production duration changes unless the tests reveal a regression.

---

### Task 2: Add the Pure Mobile Focus-Presentation Model

**Files:**

- Create: `apps/mobile-web/src/components/mobileLiveActionModel.ts`
- Create: `apps/mobile-web/src/components/mobileLiveActionModel.test.ts`

- [ ] **Step 1: Write the model contract and failing tests**

Define `MobileLiveFocusKind`, `MobileLiveFocusTone`, and `MobileLiveFocusPresentation` exactly as required by the design.

Test `deriveMobileLiveFocusPresentation(currentEvent, godViewState)` for:

- Waiting and phase start.
- Existing speech presentation.
- Werewolf team action with no arbitrary single actor.
- Guard, seer, witch save, witch poison, and `skip`.
- Vote request, parsed vote, weighted tally, tie, and exile.
- Skill triggers and terminal result.
- Missing actor/choice fallback text.
- Complete accessible sentences.

- [ ] **Step 2: Add failing tests for active non-speech actor selection**

Test a helper such as `getActiveTheaterPlayer(state)` with players whose `stageStatus.kind` is:

- `preparing-speech`.
- `speaking`.
- `voting`.
- `acting`.
- `summarizing`.
- `resolved` or `out`, which must not become the active actor.

- [ ] **Step 3: Run the model tests**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/mobileLiveActionModel.test.ts
```

Expected: FAIL because the model does not exist.

- [ ] **Step 4: Implement the pure model**

Implementation rules:

- Consume only `currentEvent` and `GodViewState`.
- Normalize names by matching both exact player name and existing seat/name strings without inventing identities.
- Use `godViewState.nightActions`, `nightResolution`, `vote.tallies`, `totalVotes`, and player vote fields for resolved copy.
- Render fractional votes without trailing `.0`.
- Prioritize explicit exile/skill/terminal results over generic phase copy.
- Return data only; no React state, DOM reads, timers, or class names.

- [ ] **Step 5: Re-run the model tests**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/mobileLiveActionModel.test.ts
```

Expected: PASS.

---

### Task 3: Build the Phase-Aware Center Action Stage

**Files:**

- Create: `apps/mobile-web/src/components/MobileLiveActionStage.tsx`
- Create: `apps/mobile-web/src/components/MobileLiveActionStage.test.tsx`
- Modify: `apps/mobile-web/src/components/MobileLiveTheater.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Add failing component tests**

Cover:

- Speech still renders the existing portrait, name, `公开发言`, and speaker avatar.
- Night action renders actor/team, action, target or `未使用`, and phase.
- Vote action renders voter, arrow-equivalent text, target, and tally progress.
- Vote result renders top three totals and tie text.
- Night result renders peaceful night, save/protect, poison, or death.
- Unknown/malformed action renders a readable fallback instead of only `?`.
- The region exposes one atomic polite status message.
- Decorative icons remain hidden from assistive technology.

- [ ] **Step 2: Run the component test**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/MobileLiveActionStage.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement `MobileLiveActionStage`**

- Reuse the current `.mobile-live-center-stage` footprint.
- Keep the existing presenter image path for a single active player.
- Use existing Lucide icons for team/action/result states without a single actor.
- Apply tone and focus-kind modifier classes.
- Keep target/result text visible at 320px; use a two-line clamp rather than the current unconditional single-line ellipsis for action detail.
- Add visible text labels beside tone icons.

- [ ] **Step 4: Replace `LiveCenterStage` composition**

In `MobileLiveTheater`:

- Derive the focus presentation with the pure model.
- Replace the generic non-speech content with `MobileLiveActionStage`.
- Use the active-player helper for action, vote, and summarize actor portraits.
- Preserve `LiveSeatColumn`, subtitle placement, and control-deck props.

- [ ] **Step 5: Add seat action/target modifiers**

Derive classes and visible badges for:

- Acting/voting actor.
- Current action target.
- Saved/protected target.
- Poison/attack target.
- Current and final received vote count.

Do not replace the existing night-death or exile markers. Add textual `aria-label` content for every new state.

- [ ] **Step 6: Re-run focused component and page tests**

```bash
pnpm --dir apps/mobile-web test -- --run \
  src/components/MobileLiveActionStage.test.tsx \
  src/pages/LivePage.test.tsx \
  src/pages/LiveReplayPage.test.tsx
```

Expected: PASS after updating obsolete generic-stage expectations to semantic action/result expectations. Existing speech/subtitle tests remain green.

---

### Task 4: Build the Persistent Event Rail

**Files:**

- Create: `apps/mobile-web/src/components/MobileLiveEventRail.tsx`
- Create: `apps/mobile-web/src/components/MobileLiveEventRail.test.tsx`
- Modify: `apps/mobile-web/src/components/MobileLiveTheater.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Add failing rail tests**

Cover:

- Empty state `等待首个关键事件` and disabled `全部`.
- Latest meaningful moments render in event order.
- Current moment has `aria-current="true"`.
- The rail uses `role="log"`, polite additions, and does not include future supplied events outside its props.
- Duplicate text with different event IDs remains distinct.
- `全部` accessible name includes the moment count.
- Opening the sheet moves focus inside it.
- Escape and close restore focus to `全部`.
- Tab and Shift+Tab remain inside the sheet.
- The provided background becomes inert while open and is restored on close.
- Selecting an event calls `onSelectEvent(event.id)` and closes the sheet.

- [ ] **Step 2: Run the rail tests**

```bash
pnpm --dir apps/mobile-web test -- --run src/components/MobileLiveEventRail.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the collapsed rail**

- Render a fixed-height, horizontally scrollable chip row.
- Keep the `全部` trigger outside the scrolling container.
- Follow the latest moment only while the user remains at the end.
- When the user scrolls away, show a non-blocking new-event indicator instead of forcing scroll.
- Respect reduced motion and do not move focus.

- [ ] **Step 4: Implement the grouped event sheet**

- Group by round/phase from the event-line time and current God View context available in the component props. If the event-line shape lacks grouping information, add the smallest backward-compatible optional `round` and `phase` fields to `GodViewEventLine` and protect them in shared tests.
- Render vote totals and voter lists from `godViewState.vote` when the selected group is the current vote result.
- Render ordered night actions and `nightResolution` for the current night result.
- Follow `LobbyModal` focus/inert semantics without importing or modifying lobby components.
- Keep event ingestion live while the sheet is open and preserve the user's scroll position.

- [ ] **Step 5: Integrate the rail into the theater grid**

Add the rail after `.mobile-live-seat-stage` and before `.mobile-live-control-deck`.

Update `.mobile-live-theater` rows to:

```css
grid-template-rows: auto minmax(...) minmax(0, 1fr) auto auto;
```

Add short-height rules that keep the rail to one row and shrink only decorative sky/portrait dimensions. Do not shrink text below 12px or common targets below 44px.

- [ ] **Step 6: Re-run rail and theater tests**

```bash
pnpm --dir apps/mobile-web test -- --run \
  src/components/MobileLiveEventRail.test.tsx \
  src/components/MobileLiveActionStage.test.tsx \
  src/pages/LivePage.test.tsx \
  src/pages/LiveReplayPage.test.tsx
```

Expected: PASS.

---

### Task 5: Wire Event Seek Through Live and Replay

**Files:**

- Modify: `apps/mobile-web/src/components/MobileLiveTheater.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`
- Modify: `apps/mobile-web/src/pages/LiveReplayPage.tsx`
- Modify: `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`

- [ ] **Step 1: Add failing live-page tests**

Use a visible event sequence containing night action and vote moments. Assert:

- The rail contains only events through the mocked director current ID.
- Selecting an older rail row calls the director seek function with that event ID.
- A future latest event or speaker delta is absent while paused or behind backlog.
- Catching up to latest subsequently exposes the newer moment.

- [ ] **Step 2: Add failing replay-page tests**

Assert:

- Saved playback renders the same rail and focus card.
- Selecting an event seeks the replay director.
- Replay without saved voice still renders action and result moments.
- Phase seek and event seek coexist.

- [ ] **Step 3: Add the theater event-seek prop**

Extend `MobileLiveTheaterProps` with:

```ts
onSelectEvent: (eventId: number) => void;
```

Pass `director.seekToEventId` from both page controllers.

- [ ] **Step 4: Keep all derivation on visible state**

- `LivePage` continues using its existing guarded `stageEvents` computation.
- `LiveReplayPage` continues filtering all events by `currentEventId`.
- Do not pass `allEvents` or newest SSE events to the rail except through already-visible derived state.

- [ ] **Step 5: Run both page suites**

```bash
pnpm --dir apps/mobile-web test -- --run \
  src/pages/LivePage.test.tsx \
  src/pages/LiveReplayPage.test.tsx
```

Expected: PASS.

---

### Task 6: Add Motion, Reduced-Motion, and Responsive Rules

**Files:**

- Modify: `apps/mobile-web/src/styles/index.css`
- Update tests only where user-visible behavior requires coverage.

- [ ] **Step 1: Add tone and transition rules**

Implement scoped classes for:

- Focus-card kinds and tones.
- Actor/target/vote-count seat badges.
- Rail chip tones and current state.
- Sheet backdrop, frame, grouped headers, and rows.
- One short action-enter transition, one target pulse, and numeric vote transition.

- [ ] **Step 2: Add reduced-motion overrides**

Inside the existing `prefers-reduced-motion` strategy, disable:

- Action translate/pulse.
- Target pulse.
- Numeric rolling.
- Glow cycling.
- Smooth rail auto-scroll.

Do not hide state changes.

- [ ] **Step 3: Protect short screens**

At `max-height: 860px` and `max-height: 700px`:

- Keep the rail one line.
- Reduce only decorative sky/portrait space.
- Preserve controls, subtitle, action title, target/result, and `全部` target.
- Ensure the event sheet uses internal scrolling.

- [ ] **Step 4: Remove or rewrite brittle CSS-string expectations**

Keep small contract tests only when they protect structural requirements that JSDOM cannot compute. Move geometry, target size, overflow, and reduced-motion verification to Playwright.

---

### Task 7: Add Deterministic Mobile Browser Coverage

**Files:**

- Create: `apps/mobile-web/e2e/mobile-live-actions.spec.ts`
- Modify: `apps/mobile-web/e2e/support/mobile-api-fixtures.ts` if shared fixture types are useful.

- [ ] **Step 1: Add deterministic saved-playback fixtures**

Create compact 8-player and 12-player playback payloads containing:

- Game start and night phase.
- Werewolf target.
- Witch save and poison/skip examples.
- Day phase and short speech state.
- Three parsed votes.
- Weighted or tied vote state update.
- Explicit exile state update.
- Saved voices empty, proving action UI does not depend on audio.

Keep event IDs monotonic and payloads identical to production contracts.

- [ ] **Step 2: Add semantic browser scenarios**

Cover:

- Night action actor/target/result.
- Per-voter vote display.
- Complete tally and exile reveal.
- Event rail and grouped sheet.
- Selecting a sheet event and returning to latest.
- Phase selector, subtitles, and controls still work.

Use deterministic playback and Playwright clock control or explicit director cue advancement. Do not use broad real-time sleeps.

- [ ] **Step 3: Add responsive geometry assertions**

Run at the configured:

- 320×568 small-mobile viewport.
- 390×844 iOS mobile viewport.
- 412×915 Android mobile viewport.

Assert:

- `document.documentElement.scrollWidth <= window.innerWidth`.
- Rail, subtitle, and control rectangles do not intersect.
- The action title and target/result are visible.
- Common rail/sheet targets are at least 44×44px.
- The sheet covers the usable width, scrolls internally, makes background inert, and restores focus.

- [ ] **Step 4: Add reduced-motion browser assertion**

Emulate `prefers-reduced-motion: reduce` and assert the action/target elements compute to no nonessential animation while updated text remains visible.

- [ ] **Step 5: Run the focused browser spec**

```bash
pnpm --dir apps/mobile-web build
pnpm --dir apps/mobile-web exec playwright test e2e/mobile-live-actions.spec.ts
```

Expected: PASS in all configured mobile projects.

---

### Task 8: Documentation and Full Verification

**Files:**

- Modify: `docs/mobile-web-production-design.md`
- All changed source and test files.

- [ ] **Step 1: Update production design documentation**

Add the live theater contract:

- Phase-aware action focus.
- Persistent meaningful event rail.
- Accessible event sheet and event seek.
- Director-visible event boundary.
- Key result durations.
- No dependence on voice playback.

- [ ] **Step 2: Run the shared package suite**

```bash
pnpm --dir packages/game-client test -- --run
```

Expected: PASS.

- [ ] **Step 3: Run the full mobile verification matrix**

```bash
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web lint
pnpm --dir apps/mobile-web build
pnpm --dir apps/mobile-web exec playwright test \
  e2e/mobile-navigation.spec.ts \
  e2e/lobby-redesign.spec.ts \
  e2e/mobile-live-actions.spec.ts
```

Expected:

- Unit and component tests PASS.
- Lint PASS.
- TypeScript, Vite production build, and bundle budget PASS.
- Existing navigation/lobby browser coverage remains green.
- New live-action browser coverage passes in all configured mobile viewports.

- [ ] **Step 4: Run repository checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and only intended files in the diff. Do not stage unrelated files or external audit screenshots.

---

## Final Review Checklist

- [ ] Every acceptance criterion in `docs/superpowers/specs/2026-07-13-mobile-live-action-visibility-design.md` is satisfied.
- [ ] Night actions show actor/team, action, target/skip, and resolution.
- [ ] Votes show voter, target, progress, final tally, tie state, and exile result.
- [ ] The rail contains meaningful director-visible events only.
- [ ] The event sheet is focus-contained, background-isolated, dismissible, and seekable.
- [ ] Future SSE/replay events do not leak through the new UI.
- [ ] Speech, subtitles, voice, pause, speed, latest, phase seek, replay/resume, errors, and terminal state remain intact.
- [ ] No backend, database, payload, rule, or asset contract changed.
- [ ] Responsive and reduced-motion browser checks pass.
