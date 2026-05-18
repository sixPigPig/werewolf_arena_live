# Live Nav Status Integration

## Purpose

The live game navigation should show one clear spectator-facing status instead of asking the user to combine separate connection and playback labels. The new status is display-only and must not change the meaning of existing connection, run, director, stage, timeline, or player states.

## Scope

This change covers only the live page navigation at `/games/live/:runId`.

In scope:

- Derive a navigation-specific status from the existing live connection state, game run status, and director playback state.
- Replace the current separate navigation labels for connection and run status with one compact status readout.
- Keep the existing playback controls: pause/resume, catch up, and speed.
- Preserve current non-navigation uses of the same underlying states.

Out of scope:

- Changing SSE connection behavior in `useGameRunEvents`.
- Changing game run status values such as `queued`, `running`, `completed`, or `failed`.
- Changing director playback mechanics in `useLiveDirector`.
- Changing player-level status labels such as waiting, thinking, streaming, acted, or out.
- Redesigning the live stage, timeline, or God view panels.

## Status Model

Create a navigation-only derived status, tentatively named `LiveNavStatus`. It should be produced by a pure helper such as `deriveLiveNavStatus(...)` so the priority and label rules are testable outside React rendering.

The user-facing states are:

- `connecting`: shown as `连接中`.
- `live`: shown as `直播中`.
- `catchingUp`: shown as `追播中`.
- `paused`: shown as `已暂停`.
- `ended`: shown as `已结束`.
- `interrupted`: shown as `异常中断`.

Priority order:

1. `interrupted`: run failed, terminal failure event, or connection error while the run is not normally ended.
2. `ended`: run completed or terminal completion event.
3. `paused`: director is paused.
4. `connecting`: connection is idle or connecting while the run is not terminal.
5. `catchingUp`: director backlog is greater than zero.
6. `live`: connected or otherwise running with no backlog.

## Display Rules

The navigation should render one compact status group in the live nav context. Suggested copy:

- `直播中 · 1x`
- `追播中 · 落后 8 条 · 2x`
- `已暂停 · 落后 2 条`
- `连接中`
- `异常中断 · 连接异常`
- `已结束 · 已完成`

The status group may include a small icon or colored dot, but it should remain compact enough for the existing command navigation height. The existing session id and rule-set summary may remain near the status group as long as they do not recreate separate connection/run status labels.

## Component Boundaries

Keep the underlying states intact:

- `useGameRunEvents` continues to own `ConnectionState`.
- `GameRun.status` continues to represent backend run lifecycle.
- `useLiveDirector` continues to own playback state such as `isPaused`, `backlogCount`, `isCatchingUp`, and `speed`.
- Stage and timeline components continue consuming director state directly.

Preferred implementation shape:

- Add a pure helper near live UI code, for example under `apps/web/src/features/games/liveNavStatus.ts`.
- Update `LiveStatusStrip` or introduce a focused live nav status component to render the derived status.
- Pass director playback fields from `LiveGamePage` into that nav status renderer.

## Error Handling

Unknown connection or run states should not crash rendering. The derived helper should fall back to a readable label using the raw value when needed, while known states use the localized labels above.

Connection `closed` is normal when the run is completed. If the run is still active and connection closes unexpectedly, the navigation should prefer a degraded/interrupted message over `直播中`.

## Testing

Add focused tests for the pure derived status helper:

- connection idle/connecting maps to `连接中`.
- open connection with running run and no backlog maps to `直播中`.
- backlog greater than zero maps to `追播中`.
- paused director maps to `已暂停` even when backlog exists.
- completed run maps to `已结束`.
- failed run or connection error maps to `异常中断`.

Update live page or component tests to verify the navigation renders one combined status and no longer shows separate connection/run labels in the nav context.

## Acceptance Criteria

- The live navigation displays one combined spectator status.
- The combined status follows the priority order in this spec.
- Playback controls remain available and unchanged.
- Existing stage, timeline, and player status behavior is unchanged.
- Tests cover the derived status priority and the live nav rendering.
