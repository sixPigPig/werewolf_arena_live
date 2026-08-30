# Mobile Live Subtitles Design

## Goal

Add subtitles to the mobile live theater so judge lines and each player's public speech appear as colored captions. The captions must show speech only: no model status, debug events, parsed private actions, vote choices, or generic event labels.

Scope is limited to `apps/mobile-web`. Desktop live already has a narrative panel and is out of scope for this change.

## Current Context

The mobile live experience is shared by:

- `apps/mobile-web/src/pages/LivePage.tsx` for live runs.
- `apps/mobile-web/src/pages/LiveReplayPage.tsx` for saved live playback.
- `apps/mobile-web/src/components/MobileLiveTheater.tsx` for the common theater UI.

Both pages already derive:

- `stageEvents`, the events visible at the current director position.
- `spectatorState`, derived from visible events.
- `godViewState`, derived from visible events and spectator state.
- `director.currentCue`, which points to the current director cue.

The shared client package already provides `deriveLiveNarrativeState`, which classifies director cues into judge, player-speaking, vote, death, terminal, and fallback narrative states. This should be reused instead of duplicating event interpretation in mobile UI code.

## Approved UX

Use a lower-third subtitle style in the center stage:

- Place the subtitle under the current presenter details in `LiveCenterStage`.
- Keep it inside the center column so it does not cover the left/right seat columns.
- Use a dark translucent gothic HUD surface consistent with the current live theater.
- Show a speaker label and speech text.
- Use gold styling for the judge.
- Use a deterministic player color by seat number so each player differs from the judge and from nearby players.

Subtitle examples:

- Judge: `法官 请阿青发言。`
- Player: `阿青 我先听后置位发言，重点看谁在跟风。`

## Speech Rules

Create a small mobile subtitle view model, for example:

```ts
type MobileLiveSubtitle = {
  speakerName: string;
  text: string;
  tone: "judge" | "player";
  colorIndex: number;
};
```

Build this from `deriveLiveNarrativeState`:

- For `cue.kind === "player-speaking"`, show `cue.speechText.trim()` when non-empty.
- For judge captions, show `cue.judgeLine.trim()` only for judge-like narrative states that are actual spoken public narration:
  - `cue.kind === "judge"`
  - `cue.kind === "player-thinking"` when `cue.action` is a public speech action: `debate`, `sheriff_speech`, or `sheriff_pk_speech`
- Do not show subtitles for:
  - `vote`
  - `death`
  - `terminal`
  - `player-action`
  - `fallback`
  - empty or whitespace-only text

This keeps captions limited to what a spectator would hear as speech.

## Data Flow

In both mobile pages:

1. Keep deriving `stageEvents`, `spectatorState`, and `godViewState` as today.
2. Derive a `narrativeState` with:

```ts
deriveLiveNarrativeState({
  cue: director.currentCue,
  events: stageEvents,
  godViewState,
  spectatorState,
});
```

3. Convert `narrativeState` to `MobileLiveSubtitle | null`.
4. Pass `subtitle` into `MobileLiveTheater`.
5. Pass it from `MobileLiveTheater` into `LiveCenterStage`.

`MobileLiveTheater` remains the shared rendering component for live and replay. The pages own data derivation, matching the existing pattern for `godViewState`.

## Color Rules

Use CSS classes instead of inline colors:

- Judge: `mobile-live-subtitle-judge`.
- Players: `mobile-live-subtitle-player-0` through `mobile-live-subtitle-player-7`.

Player color index should be deterministic:

- Prefer the matching player seat number from `godViewState.players`.
- Use `(seatNumber - 1) % 8`.
- Fall back to hashing the speaker name if seat number is missing.

The palette should be readable on the existing dark live background and avoid a one-note palette:

- teal
- sky
- violet
- rose
- amber
- emerald
- blue
- pink

Judge gold remains separate from the player palette.

## Layout

Add a subtitle element inside `LiveCenterStage` after the existing event label and before the optional phase label.

Expected structure:

```tsx
{subtitle ? <LiveSubtitle subtitle={subtitle} /> : null}
```

The subtitle element should:

- Have `role="status"` or an accessible label so screen readers can identify live speech.
- Limit itself to two lines on normal screens.
- Use wrapping for long Chinese text without resizing the entire theater.
- Stay within the center stage width.
- Compress on short screens without overlapping controls.

No new card should wrap the theater. This is a small HUD element inside the existing stage.

## Error Handling

If narrative derivation cannot find a speaker, still show a player subtitle when `cue.speechText` exists:

- `speakerName` falls back to `cue.actor`, then `当前玩家`.
- `colorIndex` falls back to the speaker-name hash.

If no valid speech text exists, return `null` and render no subtitle.

## Tests

Add or update mobile tests for:

- Live page shows a player subtitle for a public `model_response_delta`.
- Live page shows a judge subtitle for a speech prompt.
- Live page does not show subtitles for non-speech events such as vote/death/terminal/action parsing.
- Judge and player subtitles use different color classes.
- Replay page gets the same subtitle behavior through the shared theater component.

Style tests should assert the lower-third classes and color class definitions exist in `apps/mobile-web/src/styles/index.css`.

## Out Of Scope

- Desktop live page subtitle redesign.
- Backend event schema changes.
- Persisting subtitle tracks separately from live events.
- Showing private night action text as captions.
- Adding user controls for subtitle visibility.
