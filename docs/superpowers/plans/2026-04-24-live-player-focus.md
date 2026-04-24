# Live Player Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve `/games/live/:runId` from a raw event list into a player-focused live spectator view with a player panel, active-player stage, and raw event sidebar.

**Architecture:** Keep the backend SSE contract unchanged. Add a frontend pure state-derivation helper that turns live events into player/status/focus data, then render that state through focused live components.

**Tech Stack:** React, React Router, TanStack Query, Vitest, Testing Library, Tailwind utility classes.

---

## Files

- Create: `apps/web/src/features/games/liveSpectator.ts`
- Create: `apps/web/src/features/games/liveSpectator.test.ts`
- Create: `apps/web/src/features/games/components/LivePlayerPanel.tsx`
- Create: `apps/web/src/features/games/components/LiveFocusStage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

---

### Task 1: Live Spectator State Derivation

**Files:**
- Create: `apps/web/src/features/games/liveSpectator.ts`
- Create: `apps/web/src/features/games/liveSpectator.test.ts`

- [ ] **Step 1: Write failing tests**

Create `apps/web/src/features/games/liveSpectator.test.ts` with tests for:

```ts
import { describe, expect, it } from "vitest";

import { deriveLiveSpectatorState } from "./liveSpectator";
import type { LiveGameEvent } from "./types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "game_started",
    run_id: "run_1234abcd",
    session_id: "session_20260424_120000_ab12cd34",
    created_at: "2026-04-24T12:00:00Z",
    round: partial.round ?? null,
    phase: partial.phase ?? null,
    actor: partial.actor ?? null,
    action: partial.action ?? null,
    payload: partial.payload ?? {},
  };
}

describe("deriveLiveSpectatorState", () => {
  it("initializes players from game_started", () => {
    const state = deriveLiveSpectatorState([
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "村民", model: "deepseek-chat" },
          ],
        },
      }),
    ]);

    expect(state.players.map((player) => player.name)).toEqual(["张三", "李四"]);
    expect(state.players[0]).toMatchObject({
      role: "狼人",
      model: "deepseek-chat",
      status: "waiting",
      isAlive: true,
    });
  });

  it("focuses actor events and records latest action detail", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "狼人", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { options: [] },
      }),
      event({
        id: 3,
        type: "action_parsed",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { choice: "我不是狼" },
      }),
    ]);

    expect(state.activePlayerName).toBe("张三");
    expect(state.currentRound).toBe(1);
    expect(state.currentPhase).toBe("day");
    expect(state.players[0]).toMatchObject({
      status: "acted",
      lastAction: "debate",
      lastDetail: "我不是狼",
    });
  });

  it("marks players outside active_players as not alive", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "村民", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: { active_players: ["张三"], eliminated: "李四" },
      }),
    ]);

    expect(state.players.find((player) => player.name === "李四")?.isAlive).toBe(false);
  });
});
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/liveSpectator.test.ts
```

Expected: fail because `liveSpectator.ts` does not exist.

- [ ] **Step 3: Implement state derivation**

Create `apps/web/src/features/games/liveSpectator.ts` with:

- `LivePlayerStatus = "waiting" | "thinking" | "requesting" | "responded" | "acted" | "out"`
- `LivePlayer`
- `LiveSpectatorState`
- `deriveLiveSpectatorState(events: LiveGameEvent[]): LiveSpectatorState`

Implementation rules:

- Parse `game_started.payload.players` if it is an array of objects.
- Add fallback players when actor events mention unknown names.
- Update status from event type.
- Extract detail priority: `raw_response`, `choice`, `result.say`, `result.summary`, `error`, `winner`.
- Mark not alive from `state_updated.payload.active_players` when present.
- Track `activePlayerName`, `currentRound`, `currentPhase`, `latestActorEvent`, `latestStateEvent`.

- [ ] **Step 4: Run tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/liveSpectator.test.ts
```

Expected: pass.

---

### Task 2: Live Player Components

**Files:**
- Create: `apps/web/src/features/games/components/LivePlayerPanel.tsx`
- Create: `apps/web/src/features/games/components/LiveFocusStage.tsx`

- [ ] **Step 1: Implement `LivePlayerPanel`**

Props:

```ts
{
  players: LivePlayer[];
  activePlayerName: string | null;
  focusedPlayerName: string | null;
  autoFollow: boolean;
  onSelectPlayer: (name: string) => void;
  onAutoFollowChange: (value: boolean) => void;
}
```

Behavior:

- Show title `玩家`.
- Show checkbox `自动跟随`.
- Render one button/card per player.
- Active player gets stronger border/background.
- Focused player gets visible ring.
- Out players are muted and show `出局`.

- [ ] **Step 2: Implement `LiveFocusStage`**

Props:

```ts
{
  player: LivePlayer | null;
  currentRound: number | null;
  currentPhase: string | null;
  latestEvent: LiveGameEvent | null;
}
```

Behavior:

- Empty state: `等待玩家行动...`
- Show player name, role, status, round/phase.
- Show latest action and detail.
- Use bounded text blocks with `break-words` / `overflow-auto`.

---

### Task 3: Integrate Live Page

**Files:**
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Add page-level behavior tests**

Extend `LiveGamePage.test.tsx` to cover:

- `game_started` renders player names in the player panel.
- `action_requested` highlights/focuses actor and stage shows actor action.
- Clicking another player disables auto-follow and fixes focus.
- Re-enabling auto-follow returns focus to latest actor.

- [ ] **Step 2: Integrate state and layout**

In `LiveGamePage.tsx`:

- `const spectatorState = useMemo(() => deriveLiveSpectatorState(events), [events]);`
- `const [autoFollow, setAutoFollow] = useState(true);`
- `const [manualFocusName, setManualFocusName] = useState<string | null>(null);`
- When `autoFollow` is true and `activePlayerName` changes, clear manual focus.
- `focusedPlayerName = autoFollow ? activePlayerName : manualFocusName ?? activePlayerName`
- Render layout:

```text
grid lg:grid-cols-[18rem_minmax(0,1fr)_22rem]
left: LivePlayerPanel
middle: LiveFocusStage
right: LiveEventTimeline inside section titled 原始事件
```

Keep `LiveStatusStrip` above the grid.

- [ ] **Step 3: Run page tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/LiveGamePage.test.tsx src/features/games/liveSpectator.test.ts
```

Expected: pass.

---

### Task 4: Verification

- [ ] **Step 1: Frontend tests**

Run:

```bash
cd apps/web && pnpm test -- --run
```

Expected: pass.

- [ ] **Step 2: Frontend build**

Run:

```bash
cd apps/web && pnpm build
```

Expected: pass.

- [ ] **Step 3: Backend smoke**

No backend code should change. If any backend file changed unexpectedly, stop and review before finalizing.
