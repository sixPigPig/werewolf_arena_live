# Live V2 Phase 1 Design QA

## Comparison target

- Source visual truth: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/26/019f9eda-d2e7-70c0-bc22-e128180d7740/werewolf-live-viewing-modes.html`
- Rendered implementation: `http://127.0.0.1:5174/v2/games/v2_game_c7f26eea82b74329/live`
- Implementation screenshot: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/26/019f9eda-d2e7-70c0-bc22-e128180d7740/phase-1-entry-390x844.png`
- Full-view comparison: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/26/019f9eda-d2e7-70c0-bc22-e128180d7740/phase-1-comparison-1600x1050.png`
- Viewport and density:
  - Mobile implementation captures: 390 × 844 CSS px, 390 × 844 image px, device scale factor 1.
  - Full-view source and implementation captures: 1280 × 900 CSS px, 1280 × 900 image px, device scale factor 1.
  - Comparison board: 1600 × 1050 CSS px and image px, device scale factor 1.
- State:
  - Waiting game, before WebSocket connection, default `director` selection.
  - Waiting game with `challenge` selected.
  - Existing non-running `finalizing` game connected to the director projection, showing a real public-stage scene without starting a model run.

The source is a flow prototype rather than a pixel-level mobile mock. The comparison therefore treats its information architecture, mode hierarchy, scene boundaries, and no-replay rule as the source truth while retaining the existing Mobile Live V2 gothic theater as the visual system.

## Findings

- No actionable P0, P1, or P2 findings remain.
- The implementation preserves the prototype's primary hierarchy: `导演全知` is the recommended default, `推理挑战` is an explicit opt-in, and the selected mode is confirmed by the entry CTA and stage header.
- The director scene banner makes the active context visible without replacing the established stage, portraits, subtitle area, or live-state rhythm.
- Private role information is contextual: the active speaker receives a compact role badge and ability targets receive a temporary highlight; the permanent public roster remains role-free.
- The two Phase 1 modes are intentionally shown instead of the source prototype's full four-mode roadmap. Player Follow is deferred, and the credentialed analysis entry is intentionally absent from the mobile live page.

## Required fidelity surfaces

- Fonts and typography: The implementation keeps the product's existing serif display face for theatrical titles and subtitles, with compact sans-serif utility copy. Mode titles, descriptions, and CTA weights remain legible at 390 px with no clipping.
- Spacing and layout rhythm: The selection panel fits within the live stage above the persistent subtitle panel at both 390 × 844 and the existing `max-height: 760px` breakpoint. The two mode cards share one rhythm and the selected-state inset accent does not shift layout.
- Colors and visual tokens: Director mode reuses the existing gold live-stage tokens for selection and introduces violet only for contextual director cues and private targets. Contrast is sufficient against the dark gothic backgrounds.
- Image quality and asset fidelity: Existing production arena, castle, portrait, and frame assets are reused at their native crops. Lucide icons are used for mode and scene affordances; no placeholder, emoji, CSS-drawn, or custom SVG assets were introduced.
- Copy and content: Entry copy states the no-replay behavior before connection. Director and challenge descriptions clearly state the information boundary. The connected scene names match the flow prototype (`公共舞台`, `狼人房间`, `预言家查验`, `女巫用药`, `守卫行动`, `黎明公布`).

## Full-view comparison evidence

The combined comparison confirms that the source's default mode, public-entry framing, stage loop, and contextual scene preview have been translated into the existing mobile theater. The implementation deliberately compresses the flow map into a two-choice entry panel, then exposes the current flow node as a compact in-stage director banner.

## Focused region evidence

- Entry selector: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/26/019f9eda-d2e7-70c0-bc22-e128180d7740/phase-1-entry-390x844.png`
- Challenge selected: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/26/019f9eda-d2e7-70c0-bc22-e128180d7740/phase-1-challenge-390x844.png`
- Connected director scene: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/26/019f9eda-d2e7-70c0-bc22-e128180d7740/phase-1-director-scene-390x844.png`

These focused captures were necessary because the source is a wide flow map while the implementation is a narrow mobile stage. They verify selection affordance, copy wrapping, director context, active role badge, cast visibility, subtitle hierarchy, and persistent navigation at the intended viewport.

## Comparison history

### Pass 1

- [P2] A historical in-progress presentation stored a fenced JSON model response in `subtitle_text`, so the connected director scene rendered protocol-shaped text instead of audience speech.
- Evidence: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/26/019f9eda-d2e7-70c0-bc22-e128180d7740/phase-1-director-scene-before-subtitle-fix-390x844.png`
- Fix: Added a narrow display-only normalizer that extracts a non-empty `speech` field from complete or truncated fenced JSON while leaving ordinary subtitles unchanged.

### Pass 2

- Post-fix evidence: `/Users/fanqiedanhuatang/.codex/visualizations/2026/07/26/019f9eda-d2e7-70c0-bc22-e128180d7740/phase-1-director-scene-390x844.png`
- The same stored presentation now renders natural Chinese speech. No remaining P0/P1/P2 differences were found.

## Primary interactions and runtime checks

- Switched from default Director mode to Challenge mode and verified the selected state, header label, privacy copy, and CTA update.
- Connected Director mode to a real persisted scene and verified scene banner, active speaker, role badge, deaths, and normalized subtitle.
- Verified the page produced no browser console warnings or errors.
- Automated coverage verifies the director WebSocket/ready contract, public/private event merge, challenge fail-closed behavior, no replay, cancellation, ability target context, and JSON subtitle normalization.

## Open questions

- A fresh full private-night scene was not started during visual QA to avoid consuming a waiting game. The private scene state is covered by component/protocol tests; a future real-match acceptance run can add that visual capture without changing the Phase 1 design.

## Implementation checklist

- [x] Default Director mode and explicit Challenge mode.
- [x] Dedicated directed snapshot, WebSocket, and ready contract.
- [x] Director-only scene-change events.
- [x] Public plus private presentation merge for Director.
- [x] Strict public projection and fail-closed handling for Challenge.
- [x] Contextual role and target treatment without a permanent identity table.
- [x] No-replay and cancellation semantics retained.
- [x] Mobile build, bundle budget, API tests, UI tests, browser interaction, and console checks passed.

## Follow-up polish

- P3: Capture a real `狼人房间` or `预言家查验` browser frame during the next intentionally started match to enrich the visual regression set.

final result: passed
