# Arena Navigation Redesign

## Purpose

Replace the current navigation usage with a newly named navigation system instead of extending `AppTopNav` further. The new system must make the global navigation standard explicit while preserving a separate command-oriented navigation shape for the live game page.

## Scope

The redesign covers the lobby, history, replay, and live pages. `AppTopNav` stays in place as the legacy component and is not modified as part of this rewrite. Pages migrate to new navigation components once those components and tests exist.

## New Components

- `ArenaGlobalNav`: standard page navigation for lobby, history, replay, and other non-command pages.
- `ArenaCommandNav`: dense live-page command navigation for status, rules, playback controls, and page actions.
- `ArenaNavButton`: a small wrapper around the component-library `Button` that enforces the navigation text-button standard.
- `arenaNav.types.ts`: shared action, tone, density, brand, and surface types.

## Visual Requirements

- Navigation height remains controlled by the global navigation height token.
- The brand logo uses an absolute square size equal to the navigation height. It must not rely on the logo image's natural rendered height.
- When the page is at the top and has no scroll offset, the navigation is visually transparent and has no border.
- After the page scrolls, the navigation gains only a light frosted-glass surface: very transparent background, subtle blur, and a light border.
- The frosted state should be driven by scroll state in the new navigation system, not by each page manually adding classes.
- Text actions in navigation use the component-library `Button` through `ArenaNavButton`, with the gothic skin applied by default.
- Icon-only command controls may use dedicated compact command styling when needed, but they must not force ordinary page navigation to inherit live-page density.

## Architecture

`ArenaGlobalNav` owns the shared shell: fixed position, height, brand link, transparent-at-top behavior, frosted-on-scroll behavior, and primary/secondary action placement. Pages pass semantic action data or explicit action elements into controlled slots, but they do not recreate the shell layout.

`ArenaCommandNav` owns the live-page exception. It reuses the same brand sizing and scroll surface rules, but exposes a context slot for live status/rules and a command slot for director controls. This keeps the high-density live page flexible without letting command-specific layout leak into normal pages.

`ArenaNavButton` centralizes button defaults for navigation: gothic skin, compact size, consistent link wrapping, and accessible labels. Page code should not repeat `skin="gothic"` for normal text actions.

## Page Mapping

- Lobby uses `ArenaGlobalNav` with primary action `新建对局` and secondary action `对局历史`.
- History uses `ArenaGlobalNav` with nocturne/ornate tone, primary action `刷新列表`, and secondary action `返回大厅`.
- Replay uses `ArenaGlobalNav` with primary action `刷新复盘` and secondary action `返回大厅`.
- Live uses `ArenaCommandNav` with live status/rule context, director controls, optional `继续对局`, optional `查看完整复盘`, and icon-only return-to-lobby.

## CSS And State Rules

The new components should keep most structural styling in component classes. Shared CSS should be limited to global tokens and genuinely global media behavior. Existing history-page navigation overrides should be removed from page-level usage during migration and represented through component props instead.

Scroll detection should be implemented once in the navigation layer. The component should initialize to transparent, update to frosted when `window.scrollY > 0`, and clean up its listener on unmount. The implementation should avoid layout shift when the surface changes.

## Testing Requirements

- Unit tests lock `ArenaGlobalNav` height, brand size, top transparency, scrolled frosted state, no border at top, and action rendering.
- Unit tests lock `ArenaCommandNav` context rendering, command action rendering, compact density, and shared brand/surface behavior.
- Page tests verify lobby, history, replay, and live pages use the new navigation components and keep expected navigation actions.
- A regression test verifies ordinary navigation text actions go through `ArenaNavButton` or component-library `Button` styling rather than ad hoc classes.
- Browser verification captures lobby, history, replay, and live pages after migration, checking transparent top state and frosted scrolled state.

## Non-Goals

- Do not delete `AppTopNav` in this pass.
- Do not redesign the page bodies.
- Do not change routing, data fetching, or live game behavior.
- Do not introduce a new visual theme outside the navigation surface.

## Acceptance Criteria

- New navigation code is created under a new `app/navigation` module.
- `AppTopNav` remains unchanged during the rewrite.
- Lobby, history, replay, and live pages render through the new navigation system.
- Logo rendered height and width are both tied to the navigation height token.
- Top-of-page navigation is transparent and borderless.
- Scrolled navigation is lightly frosted and still highly transparent.
- Navigation text buttons share component-library styling without repeated page-level button styling.
- Tests and browser screenshots cover the four migrated pages.
