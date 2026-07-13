# Mobile Live Action Visibility Design

**Date:** 2026-07-13

**Status:** Ready for implementation

**Surface:** `apps/mobile-web` `/games/:runId/live` and `/games/:sessionId/live-replay`

## Context

The mobile spectator theater already communicates the current round, day/night phase, player seats, identities, speech focus, subtitles, playback position, and terminal state. It does not visibly communicate the most important game mechanics with the same clarity:

- A night action can show a generic prompt such as `选择是否救人`, while the actor, target, submitted choice, and resolved effect remain absent from the stage.
- A day vote can show `投票席：8号` and `已投票`, while the selected target, current tally, leading target, and final ballot remain absent.
- A resolved exile or night death is mainly visible as a small seat marker after the fact. There is no dedicated result reveal and no persistent event record.

This is primarily a presentation gap, not a missing-data problem. `deriveGodViewState` already exposes night actions, night resolution, deaths, vote targets, vote tallies, event lines, replay marks, and skill triggers. `MobileLiveTheater` currently renders only the sky banner, seat columns, center stage, subtitles, and playback controls.

The chosen direction combines three layers:

1. A phase-aware action focus card in the existing center stage.
2. A compact, persistent event rail immediately below the seat stage.
3. Short result emphasis for night and vote resolution.

The design keeps the existing Gothic arena, player-seat layout, phase selector, subtitles, voice behavior, and playback controls.

## Goals

1. Let a viewer understand the current night action or vote within one glance.
2. Show actor, action, target, progress, and result when those facts become available.
3. Preserve recent meaningful actions so they do not disappear when the director advances.
4. Make the full ballot and night sequence available without permanently crowding the 320–480px mobile viewport.
5. Apply the same presentation to live viewing and saved live replay.
6. Preserve director pause, speed, catch-up, phase seek, voice, and subtitle behavior.
7. Make dynamic updates understandable without relying on color, motion, or sound alone.
8. Use existing event and God View contracts wherever possible; avoid backend and database changes.

## Non-Goals

- No Figma artifact or image-generation work.
- No backend, database, SSE, WebSocket, replay payload, rule-set, or game-engine changes.
- No redesign of the lobby, history, ordinary replay, player encyclopedia, or Admin.
- No public/private spectator-mode toggle in this iteration. The current page remains an omniscient God View and continues to show roles.
- No free-form event search, filtering, annotations, or analytics dashboard.
- No always-visible full-screen vote graph or dense seat-to-seat line network.
- No new decorative raster assets. Existing backgrounds, frames, avatars, and Lucide icons are reused.
- No change to the existing voice subtitle timing contract.

## Product Decisions

### God View reveal policy

The live page already exposes every player's role. Therefore meaningful night choices and vote targets are shown as soon as the corresponding visible director event is reached.

The UI must still distinguish three states:

- `行动中`: an action was requested, but no submitted choice is visible yet.
- `已选择`: a parsed choice is visible, but the phase has not resolved.
- `已结算`: a state update confirms the outcome.

The event rail must never read future events. It is derived only from the same `stageEvents` truncated by `director.currentEventId` that currently drive the theater.

### Progressive disclosure

The center card answers “what is happening now.” The event rail answers “what just happened.” An event sheet answers “what happened in this round.”

The full event sheet is optional detail. The primary action and result must remain understandable without opening it.

### Result timing

Vote and night resolution are key director cues, not compressible technical events.

- Vote ballot update: visible for 6 seconds at 1× and 3 seconds at 2×.
- Exile result: visible for 6 seconds at 1× and 3 seconds at 2×.
- Night resolution, peaceful night, or night death: visible for 6 seconds at 1× and 3 seconds at 2×.
- Catch-up mode may compress intermediate action requests, but it must not compress these result cues below the existing director minimum.

The current `liveDirector` already applies these durations to vote, exile, peaceful-night, and death state updates. The implementation must preserve those rules and add focused tests rather than introducing a second UI timer.

## Information Architecture

The theater remains a single viewport grid:

1. Theater top bar: back, rule name, live/replay status, day selector.
2. Sky banner: current phase and round.
3. Seat stage: left seats, phase-aware center card, right seats, subtitle overlay.
4. Event rail: recent meaningful moments and one `全部战报` action.
5. Control deck: current focus strip, pause, voice, speed, latest, replay/resume.
6. Event sheet: modal bottom sheet rendered only when requested.

The event rail is outside `.mobile-live-seat-stage`, so it cannot collide with the absolute subtitle overlay.

## Phase-Aware Center Card

The existing `LiveCenterStage` becomes a phase-aware presentation surface. Speech behavior remains unchanged; action and result behavior becomes explicit.

### Shared anatomy

Every non-speech center card contains:

- Actor portrait or role mark.
- Seat and player name when an actor exists.
- Action label.
- Primary target/result text.
- Secondary progress or phase text.
- A tone class: `neutral`, `info`, `success`, `warning`, or `danger`.
- A complete accessible label that reads actor, action, target, and status in one sentence.

### Night action states

| Visible event/state | Center card example | Seat treatment | Event rail |
|---|---|---|---|
| `phase_started/night` | `第1夜 · 夜间行动开始` | No target highlight | `夜幕降临` |
| `judge_cue/*_wake` | `法官提示 · 狼人/守卫/预言家/女巫请睁眼` | Relevant role seat may receive acting emphasis | Not added to result rail |
| `action_requested/remove` | `狼人阵营 · 正在选择袭击目标` | Active wolf seat(s) use acting emphasis | `狼人开始行动` |
| `action_parsed/werewolf_kill_vote` | `1号 警徽定狼 · 选择袭击目标 · 第2轮 · 投 7号` | Acting wolf and selected target receive emphasis | `1号 刀票 → 7号` |
| `action_parsed/remove` | `狼人最终目标 · 袭击 7号` | Final target receives danger outline | `最终狼刀 → 7号` |
| `judge_cue/witch_death` | `今晚被狼人袭击的玩家是 7号玩家` | Attacked target receives danger outline | Not added to result rail |
| `action_requested/witch_save` | `3号 暗牌验心 · 正在决定是否使用解药` | Witch seat uses acting emphasis | `女巫考虑使用解药` |
| `action_parsed/witch_save` | `女巫解药 · 救 7号` or `女巫解药 · 未使用` | Saved target receives success outline | `女巫救 7号` or `女巫未使用解药` |
| `action_parsed/witch_poison` | `女巫毒药 · 毒 5号` or `未使用` | Poison target receives danger outline | `女巫毒 5号` |
| `judge_cue/*_sleep` | `法官提示 · 当前角色请闭眼` | Clear acting emphasis | Not added to result rail |
| `action_parsed/protect` | `守卫守护 · 7号` | Protected target receives success outline | `守卫守护 7号` |
| `action_parsed/investigate` | `预言家查验 · 8号 · 狼人` | Investigated target receives info outline | `预言家查验 8号` |
| night `state_updated` | `平安夜` or `昨夜死亡 · 7号` | Final affected seat marker remains | Resolution moment |

`skip` is a meaningful action and must render as `未使用`, never disappear as if the event were missing.

During werewolf consensus, each `werewolf_kill_vote` names the acting wolf so every choice and revote can be followed. The separate `remove` event uses `狼人阵营` and marks the agreed final target. These public events must contain only the actor, selected target, vote round, and safe result fields; discussion, prompts, reasoning, and raw model output stay private.

### Vote states

| Visible event/state | Center card example | Seat treatment | Event rail |
|---|---|---|---|
| `phase_started/vote` | `白天投票开始 · 0/7` | Clear old current-vote emphasis | `投票开始` |
| `action_requested/vote` | `8号 雾灯守灯 · 等待投票` | Voter uses voting emphasis | `轮到8号投票` |
| `action_parsed/vote` | `8号 → 1号 · 已投票` | Voter keeps voted marker; target shows current total | `8号 → 1号` |
| vote `state_updated` with `votes` | `1号 2票 · 8号 1票` | Every target shows final count | `完整票型已生成` |
| vote `state_updated` with `exiled` | `1号被放逐 · 2票` | Exile marker is added after reveal | `1号被放逐` |

The center card shows at most the top three tally rows. The event sheet shows every target and every voter.

Vote weights may be fractional because of sheriff rules. Display values without unnecessary trailing zeros: `2票`, `2.5票`.

Tie behavior:

- Use `平票 · 1号 2票 / 8号 2票` when the highest counts are equal.
- Do not infer an exile from a tie unless a later state update explicitly supplies `exiled`.

### Skill and terminal states

Existing `skillTriggers` become focusable result moments:

- `狼人自爆 · 6号发动自爆`
- `猎人带走 · 5号带走8号`
- `白痴翻牌 · 9号留在场上`
- `警徽移交 · 移交给4号`
- `警徽撕毁`

Terminal states keep the existing winner treatment and append a terminal event to the rail.

### Speech states

The current speaker portrait, name, speech state, public-speech label, subtitle overlay, and speaker highlighting remain unchanged.

The event rail does not append model thinking ticks, response deltas, retry details, or duplicate speech deltas. It may append one completed `X号发言` moment when the associated state update becomes visible.

## Event Rail

### Collapsed rail

The rail is a 48–52px row between the seat stage and the control deck.

- Left label: `本轮战报`.
- Middle: horizontally scrollable chips for the latest meaningful moments, newest at the end.
- Right action: `全部`, with accessible name `查看全部战报，共 N 条`.
- The latest chip uses `aria-current="true"`.
- The rail does not auto-steal focus when new events arrive.
- When the user has manually scrolled away from the end, new moments do not force-scroll the rail; an unobtrusive `有新事件` indicator appears instead.

At heights below 700px, the rail stays one line and shows no more than one full chip plus the `全部` action. It must not grow vertically.

### Meaningful-moment rules

Include:

- Round and phase starts.
- Parsed night actions, including `skip`.
- Night resolution.
- Parsed votes.
- Complete ballot updates.
- Exile, death, peaceful night, self-explosion, hunter shot, idiot reveal, badge change.
- Game completion.

Exclude:

- `model_thinking_tick`.
- `model_response_delta`.
- Generic request/response plumbing.
- `state_updated` events that only repeat already-rendered information.
- Private summaries or raw payload text.

Duplicate moments use event ID as identity. Text equality is not sufficient because two different voters can make the same choice.

## Event Sheet

`全部` opens a modal bottom sheet titled `本轮战报`.

- Maximum height: 72svh.
- Groups moments by `第 N 夜`, `第 N 天`, `投票`, and `结算`.
- Shows event time, title, detail, and tone icon/text.
- Vote result groups contain both target totals and voter lists.
- Night resolution groups show the ordered night actions followed by the resolved result.
- Clicking a row calls `director.seekToEventId(event.id)`, closes the sheet, and leaves the viewer behind live if the selected event is historical. The existing `最新` control returns to live.
- Opening the sheet does not pause the event source or director. New moments append without changing the user's current scroll position.
- Closing restores focus to the `全部` trigger.
- Escape and the close button dismiss the sheet.
- Focus remains within the sheet while open; the theater background is inert.

The implementation follows the focus, inert, Escape, and restoration behavior already established by `LobbyModal`, but does not refactor or rename lobby components in this project.

## Data and State Design

### Existing source of truth

No new API response is required. The design consumes:

- `stageEvents` from live/replay pages.
- `currentEvent` and `director.currentEventId`.
- `GodViewState.players[*].stageStatus`, `voteTarget`, and `receivedVotes`.
- `GodViewState.nightActions` and `nightActionOrder`.
- `GodViewState.nightResolution`.
- `GodViewState.vote.tallies`, `totalVotes`, and `topTarget`.
- `GodViewState.deaths`, `eventLines`, `replayMarks`, and `skillTriggers`.

### Shared event-line enrichment

`eventLineFor` in `packages/game-client/src/live/liveGodView.ts` must begin producing meaningful lines for `action_parsed` events:

- Night action label and target/skip.
- Vote actor and target.
- Badge actions and supported special actions.

Vote `state_updated` event lines must summarize the leading tally instead of only saying `投票结果更新`.

Night `state_updated` lines must prefer the resolved causal result, including witch save/poison when present.

Raw model output, private summaries, prompts, and payload dumps must never enter these lines.

### Mobile presentation model

Add a mobile-only pure model:

```ts
type MobileLiveFocusKind =
  | "waiting"
  | "speech"
  | "night-action"
  | "night-result"
  | "vote-action"
  | "vote-result"
  | "skill"
  | "terminal";

type MobileLiveFocusPresentation = {
  eventId: number | null;
  kind: MobileLiveFocusKind;
  tone: "neutral" | "info" | "success" | "warning" | "danger";
  actorName: string | null;
  actorSeat: number | null;
  actorRole: string | null;
  targetName: string | null;
  eyebrow: string;
  title: string;
  detail: string;
  progress: string | null;
  accessibleText: string;
};
```

`deriveMobileLiveFocusPresentation(currentEvent, godViewState)` is deterministic and contains no React state or timers.

`getCurrentTheaterPlayer` must resolve active action/vote/summarize actors from player `stageStatus.kind`, not only the speech flow. This fixes the current unknown portrait for non-speech actions.

### Page integration

`LivePage` and `LiveReplayPage` continue deriving `stageEvents` exactly as today. They pass `onSelectEvent={(eventId) => director.seekToEventId(eventId)}` to `MobileLiveTheater`.

The theater derives its focus presentation from `currentEvent` and `godViewState`. It renders `godViewState.eventLines` in the event rail. Future events remain unavailable until the director reaches them.

## Visual Rules

- Preserve the current black-blue arena, burgundy phase banners, gold frames, avatars, and seat medallions.
- Reuse the existing center-stage footprint; do not create a second competing hero panel.
- Keep the current speaker portrait for speech. For team or result states without a single actor, use an existing Lucide role/action icon inside the same portrait frame, not a new bitmap.
- Tone mapping:
  - `neutral`: warm gold/stone.
  - `info`: cool cyan/blue.
  - `success`: teal/green plus shield or potion label.
  - `warning`: amber plus vote/gavel label.
  - `danger`: crimson plus claw/poison/gavel label.
- Color is supplemental. Every tone also has a visible icon and text label.
- Target emphasis uses an outline and small text badge; it must not replace existing night-death or exile markers.
- Common event-sheet and rail targets are at least 44×44 CSS pixels.
- Body and event text remain at least 12px at 320px width.
- No horizontal page overflow at 320, 390, 412, or 480px.

## Motion Rules

- New action: 160–220ms opacity/translate transition.
- Submitted target: one 320ms target emphasis pulse.
- Vote count: numeric content transition without moving the seat.
- Resolution: 800–1,200ms emphasis inside the center card; director cue duration controls how long the result remains.
- Do not animate every rail item simultaneously.
- `prefers-reduced-motion: reduce` disables pulse, translate, numeric roll, glow cycling, and nonessential auto-scroll while preserving immediate state changes.
- No flashing above three times per second.

## Accessibility

- The center focus card uses `role="status"` with `aria-live="polite"` and `aria-atomic="true"` for meaningful action/result changes.
- Rapid model events are excluded from that live region.
- The rail uses `role="log"`, `aria-live="polite"`, and `aria-relevant="additions"`.
- The full event sheet uses `role="dialog"`, `aria-modal="true"`, a visible title, focus trap, Escape close, background inertness, and trigger focus restoration.
- Vote and action status must be complete as text: for example, `8号雾灯守灯投给1号暗牌验心，1号当前2票`.
- Icons have visible adjacent text; decorative icons are `aria-hidden="true"`.
- Target, saved, poisoned, voted, and exiled states do not rely on color alone.
- Existing pause, voice, speed, latest, replay, and phase controls retain their accessible names and tab order.

## Error and Recovery Behavior

### Missing actor or profile

Show the action label and target with `未知行动者`; do not fall back to a question mark without text.

### Missing or malformed choice

Show `行动结果待确认`, keep a neutral tone, and do not invent a target.

### Empty event rail

Render `等待首个关键事件` and keep `全部` disabled.

### Voice failure

Action cards and event rail remain fully usable. Voice failure continues to use the existing notice and does not suppress visual results.

### Connection backlog

The event rail follows director-visible state, not the newest SSE event. Catch-up does not leak future actions.

### Replay without saved voice

The event rail and action focus are derived from saved events and remain available even when replay audio cannot play.

## Component Architecture

### Shared package

- Modify `packages/game-client/src/live/liveGodView.ts` to enrich meaningful event lines and vote/night summaries.
- Modify `packages/game-client/src/live/liveGodView.test.ts` to protect those semantics.
- Keep existing `GodViewState` field names and API compatibility.
- Modify `packages/game-client/src/live/liveDirector.test.ts` only if new tests are needed to protect key cue durations; production duration changes are not expected.

### Mobile presentation

- Create `apps/mobile-web/src/components/mobileLiveActionModel.ts` for pure focus derivation, formatting, active actor selection, vote formatting, and fallback copy.
- Create `apps/mobile-web/src/components/mobileLiveActionModel.test.ts`.
- Create `apps/mobile-web/src/components/MobileLiveActionStage.tsx` for the phase-aware center card.
- Create `apps/mobile-web/src/components/MobileLiveActionStage.test.tsx`.
- Create `apps/mobile-web/src/components/MobileLiveEventRail.tsx` for the collapsed rail and event sheet.
- Create `apps/mobile-web/src/components/MobileLiveEventRail.test.tsx`.
- Modify `apps/mobile-web/src/components/MobileLiveTheater.tsx` to compose the action stage and event rail while preserving speech/subtitle/control behavior.
- Modify `apps/mobile-web/src/pages/LivePage.tsx` and `LiveReplayPage.tsx` to pass event-seek callbacks.
- Modify the related page tests and `apps/mobile-web/src/styles/index.css`.

## Testing Strategy

### Shared derivation tests

Cover:

- Night parsed actions, including `skip`.
- Witch save and poison.
- Guard protection and seer investigation.
- Per-voter vote lines.
- Weighted and tied tally summaries.
- Night resolution and peaceful-night causal text.
- No model delta, raw payload, prompt, or private-summary leakage.
- Event IDs remain stable and duplicate same-target votes remain distinct.

### Mobile pure-model tests

Cover every focus kind, missing fields, actor-seat resolution, team actions, fractional votes, ties, result priority, and accessible sentences.

### Component and page tests

Cover:

- Speech presentation remains unchanged.
- Night action actor and target are visible.
- `skip` is visible.
- Vote actor, target, progress, tally, tie, and exile are visible.
- Active non-speech actor portrait resolves correctly.
- Rail renders only visible meaningful events.
- Event sheet groups moments and seeks by event ID.
- Modal focus entry, trap, Escape, inert background, and restoration.
- New live-region roles are present without making model deltas chatty.
- Live pause/backlog behavior still hides future events.
- Live replay uses the same action and rail presentation.

### Browser tests

Use deterministic saved playback fixtures at 320×568, 390×844, and 412×915.

Assert:

- No horizontal overflow.
- Event rail does not overlap subtitles or controls.
- The center action/result remains readable with 8 and 12 seats.
- Common targets are at least 44×44px.
- Event sheet covers the intended viewport area, isolates the background, and restores focus.
- A night action, vote submission, vote tally, and exile result can be reached deterministically through mocked playback and director timing.
- Reduced-motion mode removes nonessential animations.

No screenshot baseline suite is added. Browser tests assert geometry, computed style, text, and semantic state.

## Acceptance Criteria

1. A visible night action identifies its actor or team, action, target/skip, and progress state.
2. A visible vote identifies the voter and selected target.
3. During voting, target seats show their current received vote count.
4. A final ballot shows all target totals and is accessible from the event sheet.
5. A night resolution clearly states death, poison, save/protect, or peaceful-night outcome.
6. Recent meaningful moments remain available in a persistent one-row rail.
7. `全部战报` opens an accessible grouped sheet and selecting an event seeks the director to that event.
8. The rail and sheet contain no model ticks, raw payloads, prompts, or private summaries.
9. Speech, subtitles, voice, pause, speed, latest, phase seek, replay/resume, and terminal behavior remain functional.
10. Future live events are not revealed before `director.currentEventId` reaches them.
11. Live and live replay use the same shared theater presentation.
12. The layout has no horizontal overflow or control/subtitle overlap at 320×568, 390×844, and 412×915.
13. Dynamic changes are announced through restrained live regions and are understandable without color or motion.
14. Unit/component tests, lint, production build, configured browser tests, and bundle budget checks pass.

## Delivery Boundaries

Deliver the implementation as independently reviewable vertical slices:

1. Enrich and test meaningful event-line derivation.
2. Add and test the mobile focus-presentation model.
3. Replace generic non-speech center content with the action focus card.
4. Add the event rail and accessible event sheet.
5. Integrate event seek into live and replay.
6. Add result emphasis, reduced motion, responsive geometry, and browser coverage.
7. Run the full verification matrix and update production documentation.

Each slice must leave live viewing and saved live replay runnable.

## Reference Principles

- The Deceivers Chronicle and live tally: <https://thedeceivrs.com/>
- PlayWerewolf real-time narrator: <https://www.playwerewolf.net/>
- Apple Live Activities guidance on glanceable updates: <https://developer.apple.com/design/human-interface-guidelines/live-activities>
- W3C status-message guidance: <https://www.w3.org/WAI/WCAG22/Understanding/status-messages>
- W3C redundant visual cues: <https://www.w3.org/WAI/WCAG22/Techniques/general/G182>
