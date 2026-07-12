# Mobile Lobby Redesign Design

**Date:** 2026-07-12
**Status:** Approved
**Surface:** `apps/mobile-web` `/games`

## Context

The mobile lobby currently exposes rule selection, lineup construction, game settings, automatic fill, lineup clearing, launch status, and primary navigation in one highly decorated viewport. The functional order is sound, but every section uses similar visual weight. At the supported 320×568 viewport, the fixed action bar and tab bar occupy 141px, overlap the second seat row and settings area in the initial view, and force seat labels down to approximately 8.5px.

The player drawer compounds the problem: it occupies 78svh, leaves the lobby interactive behind it, presents only two poster-size player cards per view, and uses separate search, favorite, strategy, favorite-button, and confirmation controls.

The redesign keeps the existing Gothic visual identity, public APIs, lineup behavior, and game-creation request contract. It changes information hierarchy, interaction density, component boundaries, and accessibility behavior.

## Goals

1. Make the lobby answer three questions immediately: which rules are active, who is playing, and whether the game can start.
2. Make lineup construction the primary visual task.
3. Remove duplicate rule controls and reduce persistent bottom actions to one primary button.
4. Replace the non-modal player drawer with an accessible full-screen player picker that supports efficient scanning.
5. Preserve all existing game-creation, lineup, favorite, filtering, refresh, and validation semantics.
6. Eliminate content overlap at 320×568 without shrinking readable text or touch targets.
7. Split the 1,562-line `GamesPage.tsx` into focused lobby components without introducing unrelated application-wide refactors.

## Non-Goals

- No backend changes.
- No changes to `@werewolf-arena/game-client` public contracts.
- No new or regenerated visual assets.
- No redesign of live play, replay, history, player encyclopedia, or the shared tab bar.
- No application-wide design-token or stylesheet migration.
- No change to the global viewport zoom policy in this lobby project; that remains a separate accessibility task because it affects every mobile route.
- No screenshot-baseline test suite.

## Considered Approaches

### 1. Single-page progressive disclosure — chosen

Keep rule selection, lineup construction, settings, and launch on one route. Show only the current rule, make the lineup dominant, move infrequent settings behind disclosure, and open rule/player collections only when requested.

This preserves repeat-use efficiency and current navigation while removing the largest sources of visual and interaction density.

### 2. Three-step wizard — rejected

Split the flow into rule, lineup, and launch steps. This creates the cleanest individual screens but adds navigation state, back behavior, and more actions for repeat users.

### 3. Styling-only reduction — rejected

Keep the current structure and reduce borders, type compression, and fixed-bar styling. This has lower engineering risk but does not solve duplicate rule controls, inefficient player scanning, or the non-modal drawer contract.

## Information Architecture

The lobby remains one page, ordered as follows.

### 1. Compact brand header

Keep the existing lobby hero asset and background, but reduce the hero's vertical footprint. It remains the page-level identity, not an interactive section.

### 2. Current rule summary

The default page shows one compact summary containing:

- Rule name.
- Player count.
- Role or complexity summary.
- One `更换规则` action.

The existing horizontal three-card viewport and the second set of pagination-dot buttons are removed from the default lobby.

`更换规则` opens an `aria-modal` bottom-sheet rule picker with a maximum height of 80svh. Rules appear as compact two-column cards, and the sheet scrolls internally when required. The picker presents all available rules once, preserves the existing selected-rule artwork and unknown-rule text fallback, isolates the lobby behind it, and applies the selected rule through the existing rule-change behavior.

### 3. Lineup section

The lineup is the page's visual center. It retains a four-column grid at all supported widths and shows a visible two-digit seat number in every state.

- Empty: `01 · 待选择`.
- Filled: `01 · 暗巷观星`.

The section header contains:

- Current selected/required count.
- `智能补齐` secondary action.
- A more-actions menu containing `清空阵容`.

`智能补齐` opens a compact action panel with the existing `收藏补齐` and `随机补齐` choices. It is not part of the fixed launch bar and must not overlap settings or launch status.

`清空阵容` retains destructive confirmation. The confirmation is explicit and does not share the primary launch position.

### 4. Advanced settings

Seed and maximum rounds move into a native `<details>` disclosure, closed by default.

The closed summary reads `高级设置 · 随机种子 / 8轮`, substituting the current values when they change. Opening the disclosure reveals the existing numeric inputs and preserves maximum-round validation from 1 through 20.

If launch validation finds an invalid maximum-round value, the disclosure opens, the error is shown inline, and focus moves to the invalid field.

### 5. Launch bar

The fixed launch bar contains launch progress and exactly one full-width button.

- Incomplete lineup: button text `还差 N 位`, disabled.
- Ready lineup: button text `开始对局`, enabled.
- Create request in progress: button text `发起中…`, disabled.

The fixed bar contains no fill or clear actions. It respects the tab bar, safe-area inset, and scroll padding without overlapping the second lineup row or advanced-settings summary at 320×568.

## Full-Screen Player Picker

Clicking a seat opens a full-screen modal player picker.

### Layout

- Header: current seat, close action, and selection progress.
- Persistent search field.
- One filter action that manages favorite and strategy criteria.
- A compact single-column player list.
- Sticky confirmation area.

Each player row contains:

- Avatar.
- Display name.
- Strategy label.
- Favorite action.
- Current seat assignment, when assigned.
- Selected state.

At 320×568, at least five player rows intersect the initial list viewport when the fixture contains eight or more players.

### Selection behavior

1. Opening a seat initializes the pending candidate from that seat's current profile.
2. Selecting a row changes the pending candidate but does not mutate the lineup immediately.
3. `确认并下一位` commits the candidate and advances to the next empty seat while keeping the picker open.
4. On the final empty seat, the action reads `完成阵容`; committing closes the picker and returns focus to the originating or final seat control.
5. Closing before confirmation does not mutate the active seat.
6. Selecting a profile assigned elsewhere presents the existing move semantics as an explicit `移动到当前座位` confirmation; it does not reject the profile as a duplicate.
7. Refreshing the player list can invalidate the pending profile. When that happens, the confirmation action is disabled and the user is told to select another player.

### Filtering and favorites

- Search remains available at all times.
- Favorite and strategy filters are reached through one filter action instead of two persistent side-by-side controls.
- The filter action's accessible name describes active filters.
- Favorite updates keep the existing optimistic-cache update, rollback, pending state, and guest-session recovery behavior.
- If favorite state is unavailable, players remain selectable and the favorite control is disabled with a readable status message.

### Modal accessibility

- The picker uses `role="dialog"` and `aria-modal="true"`.
- The lobby content becomes `inert` while the picker is open.
- The shared tab bar is hidden and cannot receive focus while the picker is open.
- Initial focus moves to the search field.
- Tab and Shift+Tab remain inside the picker.
- Escape closes the picker.
- Closing restores focus to the seat that opened the picker.
- The close, favorite, filter, menu, and confirmation targets are at least 44×44 CSS pixels.
- The modal covers the usable viewport at every supported mobile width.

The rule picker follows the same modal isolation and focus-restoration contract.

## Component Architecture

`GamesPage.tsx` remains the composition and data-controller root. It owns queries, mutations, cross-component state, derived lineup state, validation, and navigation.

Add the following lobby-scoped modules under `apps/mobile-web/src/components/lobby/`:

### `LobbyRuleSummary.tsx`

Renders the selected rule summary and raises `onOpenPicker`.

### `LobbyRulePicker.tsx`

Renders the modal rule collection, unknown-rule fallback, selected state, and modal focus behavior. It raises the selected rule ID without owning lineup resizing.

### `LobbyLineupSection.tsx`

Renders numbered seats, selected/required progress, smart-fill entry, and the clear action. It consumes controlled profile maps and raises seat, fill, and clear callbacks.

### `LobbyAdvancedSettings.tsx`

Owns the presentation of the native disclosure and controlled seed/round fields. Validation state and values remain controlled by `GamesPage`.

### `LobbyLaunchBar.tsx`

Renders the derived launch summary and the single launch button. It does not build the API request.

### `LobbyPlayerPicker.tsx`

Owns picker-only search/filter state, pull-to-refresh gesture state, list scrolling, focus trapping, and compact player-row presentation. Candidate selection remains controlled so a refreshed catalog can invalidate it safely.

### `lobbyModel.ts`

Contains lobby-local pure functions for:

- Moving or assigning profiles to seats.
- Finding the next empty seat.
- Normalizing configs for submission.
- Building launch status.
- Filtering players and formatting strategy/description text.

These helpers remain lobby-local. They are not replaced with `game-client.applyProfileToSeat` because that helper rejects duplicates while the lobby intentionally moves an existing profile between seats.

## State Ownership

`GamesPage` retains:

- `selectedRuleSetId`.
- `playerConfigs`.
- `seed` and `maxRounds`.
- Validation, shortage, and create-error state.
- Active seat and controlled pending profile ID.
- Rule, public profile, and favorite queries.
- Create-game mutation and navigation.
- Favorite optimistic mutation, rollback, pending IDs, and cache invalidation.
- Rule-change lineup resizing and invalid-profile cleanup.
- Create-request normalization and payload construction.

`LobbyPlayerPicker` owns:

- Search input.
- Favorite filter.
- Strategy filter.
- Pull-to-refresh distance and gesture refs.
- List scroll state.

The existing fill-popover open state and rule-carousel scroll refs are removed. Clear confirmation moves to the lineup action surface. Lobby-content refs are used only when required for modal inert/focus coordination.

## Data Flow

1. React Query loads rule sets, public player profiles, and favorite IDs.
2. `GamesPage` merges profile and favorite data, removes invalid profile references, resizes the lineup for the selected rule, and derives profile-by-seat and launch status.
3. Controlled child components render this state and raise semantic callbacks.
4. Rule selection calls the existing rule-change behavior, including active-seat clamping and lineup resizing.
5. Player confirmation calls the lobby-local move/assign helper and advances to the next empty seat when requested.
6. Smart fill uses the existing favorite-only or random fill logic.
7. Launch validates settings and lineup completeness, then submits the unchanged create request shape:
   - `rule_set_id`.
   - Nullable numeric `seed`.
   - Integer `max_rounds` from 1 through 20.
   - Sorted, normalized `player_configs`.
8. Successful creation navigates to `/games/:runId/live`.

## Error and Recovery Behavior

### Rule query failure

The rule summary area shows a readable error and retry action. Lineup and launch remain unavailable until a rule is loaded.

### Player query failure

The current lineup remains visible. Opening the player picker shows a retry state. Launch remains unavailable when the configured lineup references unavailable profiles.

### Favorite query or mutation failure

Profile selection remains usable. Favorite controls disable when the authoritative favorite state is unavailable. Failed optimistic mutations roll back and show a status message.

### Empty search or filter result

The picker shows an explicit empty state and a clear-filters action.

### Invalid maximum rounds

Advanced settings open automatically, the field shows the error, and focus moves to the invalid input.

### Create request failure

The lineup and settings remain intact. A launch error appears immediately above the launch bar, and the launch action becomes available for retry after the request settles.

### Create request in progress

Rule changes, lineup mutations, fill, clear, settings edits, and duplicate launch submission are disabled until the request settles.

## Visual Rules

- Keep the existing black-blue canvas, warm gold accents, hero, rule art, avatars, and launch-button assets.
- Use at most one high-decoration surface per screen region.
- Treat lineup content and picker rows as lower-contrast deep panels so the selected rule and primary action retain hierarchy.
- Use the spacing scale 4, 8, 12, 16, and 24px.
- Keep visible body, seat, filter, and status text at 12px or larger at the 320px viewport.
- Keep common interactive targets at 44×44 CSS pixels or larger.
- Scope all lobby styling under lobby-specific selectors in `apps/mobile-web/src/styles/index.css` during this project. Do not alter shared `.mobile-button` or `.mobile-action-bar` contracts globally.

## Testing Strategy

### Pure model tests

Add `apps/mobile-web/src/components/lobby/lobbyModel.test.ts` for profile moves, next-empty-seat logic, filtering, config normalization, and launch-state derivation.

### Component and page tests

Update `apps/mobile-web/src/pages/GamesPage.test.tsx` and add focused component tests where a component owns meaningful behavior.

Tests cover:

- One rule summary and no duplicate pagination controls.
- Rule-picker selection and lineup resizing.
- Visible two-digit seat numbers in empty and filled states.
- Default-closed advanced settings and updated summary.
- One launch-bar button and correct incomplete/ready/pending states.
- Smart-fill entry outside the fixed launch bar.
- Destructive clear confirmation.
- Player search, combined filters, favorite optimistic update and rollback.
- Candidate confirmation, next-empty-seat advance, final completion, cross-seat moves, stale candidates, and close-without-commit.
- Modal inert state, focus entry, focus trap, Escape close, and focus restoration.
- Existing create payload, validation, error, and navigation behavior.

Existing tests that assert the obsolete three-column bar, click-through drawer, two-card snap layout, exact CSS declarations, or obsolete PNG assets are removed or rewritten around user-visible behavior.

### Browser tests

Add `apps/mobile-web/e2e/lobby-redesign.spec.ts` and shared lobby API fixtures containing at least two rules, eight profiles, favorite state, and a captured create request.

Run the existing Playwright projects at:

- 320×568.
- 390×844.
- 412×915.

Browser assertions cover:

- No horizontal overflow.
- No intersection between the second seat row, settings summary, fixed launch bar, and tab bar at 320×568.
- Seat text computed size of at least 12px.
- Common target boxes of at least 44×44px.
- Exactly one fixed launch action.
- Modal viewport coverage and background isolation.
- At least five initially visible player rows at 320×568 with eight fixture profiles.
- Rule switching, smart fill, continuous player selection, advanced-setting edits, and the final create payload.

Geometry and computed styles are asserted in a real browser. No new screenshot baselines or brittle CSS-string tests are added.

## Acceptance Criteria

1. The default lobby presents one rule summary, one lineup, one advanced-settings summary, and one fixed launch button.
2. The default lobby contains no rule pagination dots and no rule-card carousel.
3. Every seat displays a two-digit visible seat number in empty and filled states.
4. The fixed launch bar contains exactly one button and no fill or clear controls.
5. Smart fill and clear remain available from the lineup section.
6. Advanced settings are closed by default and preserve seed/round values and validation.
7. The player picker is full-screen, modal, keyboard-contained, background-isolated, and focus-restoring.
8. At least five player rows are initially scannable at 320×568 with eight profiles.
9. Search, favorite/strategy filtering, favorites, refresh, continuous selection, profile moves, smart fill, destructive clear, and launch behavior remain functional.
10. At 320×568, content does not intersect the fixed launch bar or tab bar, visible lobby text is at least 12px, and common targets are at least 44×44px.
11. The game-creation API payload and success navigation remain unchanged.
12. Mobile unit tests, lint, production build, and all configured Playwright lobby scenarios pass.

## Delivery Boundaries

Implementation should be delivered as independently reviewable vertical slices:

1. Protect and extract lobby domain behavior with semantic tests.
2. Replace the rule carousel with the summary and modal picker.
3. Rebuild the numbered lineup hierarchy and move fill/clear actions.
4. Replace the drawer with the full-screen accessible player picker.
5. Collapse advanced settings and simplify the launch bar.
6. Remove obsolete lobby selectors/assets references and replace brittle tests.
7. Complete responsive, focus, build, lint, and E2E verification.

Each slice must leave the lobby runnable and testable. The implementation plan will define the exact test-first steps and commit boundaries.
