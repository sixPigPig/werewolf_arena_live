# Mobile Live Record Playback Design

## Goal

Allow mobile users to import a saved game record into the existing live theater experience and play it like a live broadcast. The feature should keep the current mobile replay summary page, while adding a more immersive historical playback path that reuses the live arena UI.

## User Decisions

- Entry points: add both a direct "live replay" entry from game history and an "import to live page" entry from the mobile replay page.
- Default playback start: historical live replay starts from the first event and auto-plays forward.
- Preferred architecture: extract the mobile live theater UI into a reusable component, then feed it either live SSE events or saved playback events.

## Scope

In scope:

- Add a mobile route for historical live playback, for example `/games/:gameId/live-replay`.
- Add a "直播回放" action to each history card.
- Add a "导入直播页播放" action to the mobile replay page.
- Reuse the existing mobile live theater visuals, seat layout, phase selector, pause, speed, and latest controls.
- Support resume from failed resumable records.
- Preserve current real-time live behavior and current replay summary behavior.

Out of scope:

- Changing backend playback payload shape.
- Migrating or importing external replay files.
- Replacing the existing text summary replay page.
- Adding a scrubber timeline beyond the existing phase selector and director controls.
- Desktop playback changes, since the desktop app already has a playback-stage pattern.

## Current State

`apps/mobile-web/src/pages/LivePage.tsx` owns both data loading and the mobile live theater UI. It reads active run metadata through `getGameRun`, consumes live events through `useGameRunEvents`, derives spectator and god-view state, and renders the full-screen arena.

`apps/mobile-web/src/pages/PlaybackPage.tsx` reads `getGamePlayback` and renders a compact summary with round details. It does not reuse the live theater.

The backend and `@werewolf-arena/game-client` already expose `GamePlayback.events` as `LiveGameEvent[]`, which is the same event shape consumed by the live director, phase bar, spectator state, and god-view derivation helpers. That means mobile historical playback can be a frontend composition change, not a backend change.

## Architecture

Extract the presentational theater from `LivePage` into a reusable mobile component, tentatively:

`apps/mobile-web/src/components/MobileLiveTheater.tsx`

This component will not fetch data. It receives already-derived playback state and callbacks:

- current event
- director controls from `useLiveDirector`
- god-view state
- live status label
- phase segments
- run-like display metadata
- terminal event
- back action
- phase selection action
- optional resume action

`LivePage` remains the active-run container. It keeps `getGameRun`, `useGameRunEvents`, live-specific connection state, terminal-start behavior, and resume mutation. After deriving state, it renders `MobileLiveTheater`.

Add `LiveReplayPage` as the historical container. It calls `getGamePlayback(gameId)`, passes `playback.events` into `useLiveDirector` with `startAtLatestTerminal: false`, filters visible events by `director.currentEventId`, derives spectator and god-view state from visible events, and renders the same `MobileLiveTheater`.

The route boundary keeps the two modes clear:

- `/games/:gameId/live`: active run playback from SSE.
- `/games/:gameId/live-replay`: saved record playback from `getGamePlayback`.
- `/games/:gameId/replay`: existing text summary replay.

## Data Flow

Active live flow:

1. `LivePage` reads the run through `getGameRun(gameId)`.
2. `LivePage` subscribes to `useGameRunEvents(gameId)`.
3. `useLiveDirector(events, { resetKey: gameId, startAtLatestTerminal })` chooses the current event.
4. Visible stage events are derived from live events and the current director event.
5. Shared helpers derive phase segments, spectator state, god-view state, and nav status.
6. `MobileLiveTheater` renders the arena.

Historical live replay flow:

1. `LiveReplayPage` reads the record through `getGamePlayback(gameId)`.
2. `LiveReplayPage` uses `playback.events` as the event source.
3. `useLiveDirector(events, { resetKey: gameId, startAtLatestTerminal: false })` starts at the first event.
4. Visible events are `events.filter(event => event.id <= director.currentEventId)`.
5. Shared helpers derive phase segments, spectator state, god-view state, and a local playback status.
6. `MobileLiveTheater` renders the same arena in replay mode.

For display metadata, `LiveReplayPage` can build a small run-like object from playback data:

- `run_id`: `playback_${playback.session_id}`
- `session_id`: `playback.session_id`
- `status`: `completed` for complete records, `failed` for partial failed records when a failed terminal event is visible, otherwise `running`
- `rule_set`: `playback.rule_set`
- `winner`: winner from the terminal event payload when present
- timestamps and `event_count` from the event list

## User Interface

History cards will show:

- "继续对局" when `session.resumable === true`
- "直播回放" linking to `/games/:sessionId/live-replay`
- "查看复盘" linking to `/games/:sessionId/replay`

The mobile replay summary page will keep its current overview and round details. Its header or primary action area will include "导入直播页播放", linking to `/games/:gameId/live-replay`.

The historical live replay page will look like the mobile live page, with the existing gothic arena background and full-screen theater. The title board should use the rule name when available and a playback-oriented status label, such as "历史回放", "回放中", "已完成", or "对局失败".

The bottom control deck remains familiar:

- pause or continue
- 1x or 2x speed
- latest
- resume only for failed resumable records
- link back to the text replay page when appropriate

## Error Handling

Loading states:

- Active live page keeps "正在读取实时对局..."
- Historical live replay uses "正在准备历史播放台..."
- Replay summary keeps "正在读取复盘..."

Error states:

- Active live page keeps "无法读取实时对局"
- Historical live replay shows "无法读取历史回放"
- Replay summary keeps "无法读取复盘"
- Resume failures show "无法继续对局"

Empty playback events should not crash the page. The theater can render its shell and display the existing waiting state: no current player, "等待玩家行动", and "等待事件".

## Testing

Mobile history tests should verify:

- Completed sessions expose both "直播回放" and "查看复盘".
- Resumable sessions still expose "继续对局".
- The "直播回放" link points to `/games/:sessionId/live-replay`.

Mobile replay summary tests should verify:

- The page still renders the existing summary content.
- "导入直播页播放" links to `/games/:gameId/live-replay`.

New historical live replay tests should verify:

- `LiveReplayPage` calls `getGamePlayback(gameId)`.
- Playback starts from `game_started` rather than the terminal event.
- Pause hides future speaker deltas, matching live-page behavior.
- Phase selection is rendered and can seek by phase.
- Completed records do not show "继续对局".
- Failed resumable records show "继续对局" and call `resumeGameRun(session_id)`.

Existing live-page tests should continue to pass after extraction, proving the shared theater did not change active live behavior.

## Implementation Notes

- Prefer moving presentational functions from `LivePage.tsx` into `MobileLiveTheater.tsx` with the smallest API that supports both containers.
- Keep live-specific event-source behavior in `LivePage`; keep playback-specific fetch behavior in `LiveReplayPage`.
- Avoid changing shared `@werewolf-arena/game-client` helpers unless a type boundary requires a small exported type.
- Keep CSS class names stable where possible so existing live-page style tests remain meaningful.
- Do not introduce a new visual theme for replay mode; the purpose is to make records feel playable in the live arena.

## Risks

- `LivePage.tsx` currently mixes presentation and data loading, so extraction must be narrow and test-guided.
- Historical playback has no SSE connection state; status labels should be derived locally and not pretend to have a live network connection.
- If a saved record lacks early setup events, the theater may have incomplete player seating until later events appear. The page should still remain stable.
