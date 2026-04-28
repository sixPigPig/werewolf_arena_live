# Classic 8 Live Observation Optimizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the misleading night-resolution semantics found while running three real classic 8-player games, then make live and replay views explain protected attacks and completed runs clearly.

**Architecture:** The backend will record a night attack separately from a confirmed elimination. The replay adapter will normalize both new logs and legacy logs where a protected target was stored as `eliminated`. Live spectator state and director playback will consume the corrected event payloads without changing the SSE contract shape beyond adding an optional `attacked` field.

**Tech Stack:** FastAPI/Python dataclasses and pytest for backend behavior; React, TypeScript, TanStack Query, React Router, Testing Library, and Vitest for frontend behavior.

---

## File Structure

- Modify `apps/api/app/werewolf/models.py`: add `RoundState.attacked` and include it in persisted game state.
- Modify `apps/api/app/werewolf/engine.py`: store the wolf kill target as `attacked`; set `eliminated` only if protection does not save the target; include `attacked` in `state_updated` events.
- Modify `apps/api/tests/test_werewolf_runner.py`: add a protected-attack regression test.
- Modify `apps/web/src/features/games/types.ts`: add optional raw `attacked` and normalized non-optional `GameRound.attacked`.
- Modify `apps/web/src/features/games/api/adapters.ts`: normalize protected attacks for new and legacy replay logs.
- Modify `apps/web/src/features/games/api/adapters.test.ts`: cover protected-attack normalization.
- Modify `apps/web/src/features/games/components/NightPhase.tsx`: show attack, protection, investigation, and actual result separately.
- Modify `apps/web/src/pages/GameDetailPage.test.tsx`: cover the replay text for a protected attack.
- Modify `apps/web/src/features/games/liveSpectator.ts`: keep protected attack targets alive, show protected-attack detail, and clear no-detail terminal/pending states.
- Modify `apps/web/src/features/games/liveSpectator.test.ts`: cover protected attacks and terminal cleanup.
- Modify `apps/web/src/features/games/liveDirector.ts`: render protected-attack cues as saved attacks instead of night deaths.
- Modify `apps/web/src/features/games/hooks/useLiveDirector.ts`: add an option for completed runs to start at the terminal cue.
- Modify `apps/web/src/features/games/hooks/useLiveDirector.test.tsx`: cover completed-run terminal start while preserving live ordered playback.
- Modify `apps/web/src/pages/LiveGamePage.tsx`: pass completed-run playback option and prepare mobile ordering wrappers.
- Modify `apps/web/src/features/games/components/LiveStatusStrip.tsx`: localize status and connection labels.
- Modify `apps/web/src/pages/LiveGamePage.test.tsx`: cover completed-run terminal playback and localized status labels.

---

### Task 1: Backend Night Attack Semantics

**Files:**
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Test: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write the failing protected-attack backend test**

Add this helper near `NoInvestigateProvider` in `apps/api/tests/test_werewolf_runner.py`:

```python
class ProtectedNightProvider:
    def __init__(self, target: str) -> None:
        self.target = target

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, temperature
        if '"remove"' in prompt:
            return json.dumps(
                {"reasoning": "测试狼人袭击被守护目标。", "remove": self.target},
                ensure_ascii=False,
            )
        if '"protect"' in prompt:
            return json.dumps(
                {"reasoning": "测试医生守护被袭击目标。", "protect": self.target},
                ensure_ascii=False,
            )
        if '"investigate"' in prompt:
            options = _extract_options(prompt)
            choice = next((option for option in options if option != self.target), options[0])
            return json.dumps(
                {"reasoning": "测试预言家正常查验。", "investigate": choice},
                ensure_ascii=False,
            )
        raise AssertionError(f"Unexpected prompt: {prompt}")
```

Add this test after `test_run_game_publishes_live_events`:

```python
def test_protected_night_attack_records_attack_without_eliminating_target() -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="session_test_protected_attack",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=202,
        rule_set=rule_set,
    )
    target = next(player.name for player in state.players if player.role == SEER)
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=ProtectedNightProvider(target),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
    )

    engine._run_night_phase(round_state, round_log, active_players)

    assert round_state.attacked == target
    assert round_state.protected == target
    assert round_state.eliminated is None
    assert target in active_players
    state_event = [event for event in sink.events if event["type"] == "state_updated"][-1]
    payload = state_event["payload"]
    assert payload["attacked"] == target
    assert payload["protected"] == target
    assert payload["eliminated"] is None
    assert target in payload["active_players"]
```

- [ ] **Step 2: Run the backend regression test and verify it fails**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_protected_night_attack_records_attack_without_eliminating_target -q
```

Expected: FAIL with `AttributeError: 'RoundState' object has no attribute 'attacked'`.

- [ ] **Step 3: Add `attacked` to persisted round state**

In `apps/api/app/werewolf/models.py`, update `RoundState`:

```python
@dataclass
class RoundState:
    number: int
    players: list[str]
    attacked: str | None = None
    eliminated: str | None = None
    protected: str | None = None
    investigated: str | None = None
    exiled: str | None = None
    debate: list[DebateEntry] = field(default_factory=list)
    bids: list[dict[str, int]] = field(default_factory=list)
    votes: list[dict[str, str]] = field(default_factory=list)
    summaries: dict[str, str] = field(default_factory=dict)
    success: bool = False
```

Update `RoundState.to_dict()` to include `attacked` before `eliminated`:

```python
return {
    "number": self.number,
    "players": self.players,
    "attacked": self.attacked,
    "eliminated": self.eliminated,
    "protected": self.protected,
    "investigated": self.investigated,
    "exiled": self.exiled,
    "debate": [entry.to_dict() for entry in self.debate],
    "bids": self.bids,
    "votes": self.votes,
    "summaries": self.summaries,
    "success": self.success,
}
```

- [ ] **Step 4: Resolve attacks separately from eliminations**

In `apps/api/app/werewolf/engine.py`, replace the night remove block with:

```python
if ACTION_REMOVE in self.rule_set.night_actions and active_wolves and non_wolves:
    wolf = players_by_name[active_wolves[0]]
    attacked, round_log.eliminate = self._player_action(
        player=wolf,
        action=ACTION_REMOVE,
        options=non_wolves,
        result_key=ACTION_REMOVE,
        round_state=round_state,
        phase="night",
    )
    round_state.attacked = attacked if isinstance(attacked, str) else None
```

Replace the night resolution block with:

```python
if round_state.attacked and round_state.attacked != round_state.protected:
    round_state.eliminated = round_state.attacked
    self._remove_player(active_players, round_state.eliminated)
    self._announce(active_players, f"第{round_state.number}轮：夜晚，{round_state.eliminated}出局。")
else:
    round_state.eliminated = None
    self._announce(active_players, f"第{round_state.number}轮：夜晚无人出局。")
```

Update the night `state_updated` payload:

```python
payload={
    "attacked": round_state.attacked,
    "eliminated": round_state.eliminated,
    "protected": round_state.protected,
    "investigated": round_state.investigated,
    "active_players": active_players.copy(),
},
```

- [ ] **Step 5: Verify backend protected-attack behavior**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py::test_protected_night_attack_records_attack_without_eliminating_target -q
```

Expected: PASS.

- [ ] **Step 6: Run backend runner tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py -q
```

Expected: PASS. If a snapshot-like assertion expected the protected target in `eliminated`, update it to assert `attacked` carries that target and `eliminated` is `None`.

- [ ] **Step 7: Commit backend semantics**

```bash
git add apps/api/app/werewolf/models.py apps/api/app/werewolf/engine.py apps/api/tests/test_werewolf_runner.py
git commit -m "fix: separate night attacks from eliminations"
```

---

### Task 2: Replay Normalization and Night Result Display

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/api/adapters.ts`
- Modify: `apps/web/src/features/games/api/adapters.test.ts`
- Modify: `apps/web/src/features/games/components/NightPhase.tsx`
- Modify: `apps/web/src/pages/GameDetailPage.test.tsx`

- [ ] **Step 1: Write replay normalization tests**

In `apps/web/src/features/games/api/adapters.test.ts`, add:

```ts
it("normalizes protected legacy attacks without marking the target eliminated", () => {
  const replay = normalizeGameReplay({
    ...rawReplay,
    state: {
      ...rawReplay.state,
      rounds: [
        {
          ...rawReplay.state.rounds[0],
          eliminated: "李四",
          protected: "李四",
        },
      ],
    },
  });

  expect(replay.rounds[0].attacked).toBe("李四");
  expect(replay.rounds[0].protected).toBe("李四");
  expect(replay.rounds[0].eliminated).toBeNull();
});

it("keeps confirmed eliminations when the attacked target is not protected", () => {
  const replay = normalizeGameReplay({
    ...rawReplay,
    state: {
      ...rawReplay.state,
      rounds: [
        {
          ...rawReplay.state.rounds[0],
          attacked: "李四",
          eliminated: "李四",
          protected: "张三",
        },
      ],
    },
  });

  expect(replay.rounds[0].attacked).toBe("李四");
  expect(replay.rounds[0].eliminated).toBe("李四");
});
```

- [ ] **Step 2: Write replay page display test**

In `apps/web/src/pages/GameDetailPage.test.tsx`, add:

```tsx
it("shows protected night attacks as saved attacks in replay", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        ...detailResponse,
        state: {
          ...detailResponse.state,
          rounds: [
            {
              ...detailResponse.state.rounds[0],
              attacked: "李四",
              eliminated: null,
              protected: "李四",
              investigated: "张三",
            },
          ],
        },
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    ),
  );

  renderWithClient(
    <Routes>
      <Route path="/games/:sessionId" element={<GameDetailPage />} />
    </Routes>,
    `/games/${sessionId}`,
  );

  expect(await screen.findByText("袭击")).toBeInTheDocument();
  expect(screen.getAllByText("李四").length).toBeGreaterThan(0);
  expect(screen.getByText("李四 被守护，平安夜")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run frontend replay tests and verify they fail**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/api/adapters.test.ts src/pages/GameDetailPage.test.tsx
```

Expected: FAIL because `attacked` is not typed/normalized and NightPhase still labels the field as `死亡`.

- [ ] **Step 4: Update round types**

In `apps/web/src/features/games/types.ts`, update `RawRoundState`:

```ts
export type RawRoundState = {
  number: number;
  players: string[];
  attacked?: string | null;
  eliminated: string | null;
  protected: string | null;
  investigated: string | null;
  exiled: string | null;
  debate: Array<{ speaker: string; message: string }>;
  bids: Array<Record<string, number>>;
  votes: Array<Record<string, string>>;
  summaries: Record<string, string>;
  success: boolean;
};
```

Update `GameRound`:

```ts
export type GameRound = Omit<
  RawRoundState,
  "attacked" | "eliminated" | "bids" | "votes"
> & {
  attacked: string | null;
  eliminated: string | null;
  bids: BidEntry[];
  bidGroups: BidGroup[];
  votes: VoteEntry[];
  voteTally: VoteTallyEntry[];
  voteCount: number;
  voteMajorityThreshold: number | null;
};
```

- [ ] **Step 5: Normalize new and legacy replay logs**

In `apps/web/src/features/games/api/adapters.ts`, at the top of `normalizeRound`, add:

```ts
const attacked = round.attacked ?? round.eliminated ?? null;
const eliminated =
  round.attacked === undefined &&
  round.eliminated !== null &&
  round.eliminated === round.protected
    ? null
    : round.eliminated;
```

Return the normalized fields after spreading `round`:

```ts
return {
  ...round,
  attacked,
  eliminated,
  bids: bidGroups.flatMap((group) => group.bids),
  bidGroups,
  votes,
  voteTally: tallyVotes(votes.map((vote) => vote.target)),
  voteCount: votes.length,
  voteMajorityThreshold:
    votes.length > 0 ? Math.floor(votes.length / 2) + 1 : null,
};
```

- [ ] **Step 6: Update NightPhase labels and result text**

In `apps/web/src/features/games/components/NightPhase.tsx`, change the summary grid to four columns:

```tsx
<dl className="grid grid-cols-2 gap-3 text-xs text-slate-600 sm:grid-cols-4">
  <div>
    <dt className="font-medium text-slate-500">袭击</dt>
    <dd className="break-words">{round.attacked ?? "无"}</dd>
  </div>
  <div>
    <dt className="font-medium text-slate-500">守护</dt>
    <dd className="break-words">{round.protected ?? "无"}</dd>
  </div>
  <div>
    <dt className="font-medium text-slate-500">查验</dt>
    <dd className="break-words">{round.investigated ?? "无"}</dd>
  </div>
  <div>
    <dt className="font-medium text-slate-500">结果</dt>
    <dd className="break-words">{nightResultText(round)}</dd>
  </div>
</dl>
```

Add below the component:

```tsx
function nightResultText(round: GameRound) {
  if (round.eliminated) {
    return `${round.eliminated} 出局`;
  }
  if (round.attacked && round.protected === round.attacked) {
    return `${round.attacked} 被守护，平安夜`;
  }
  return "平安夜";
}
```

- [ ] **Step 7: Verify replay normalization and display**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/api/adapters.test.ts src/pages/GameDetailPage.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Commit replay display changes**

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/api/adapters.ts apps/web/src/features/games/api/adapters.test.ts apps/web/src/features/games/components/NightPhase.tsx apps/web/src/pages/GameDetailPage.test.tsx
git commit -m "fix: show protected night attacks in replay"
```

---

### Task 3: Live Spectator Protected Attacks and Terminal Cleanup

**Files:**
- Modify: `apps/web/src/features/games/liveSpectator.ts`
- Modify: `apps/web/src/features/games/liveSpectator.test.ts`
- Modify: `apps/web/src/features/games/liveDirector.ts`

- [ ] **Step 1: Write live spectator protected-attack tests**

In `apps/web/src/features/games/liveSpectator.test.ts`, add:

```ts
it("keeps a protected attack target alive", () => {
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
      payload: {
        attacked: "李四",
        protected: "李四",
        eliminated: null,
        active_players: ["张三", "李四"],
      },
    }),
  ]);

  expect(state.players.find((player) => player.name === "李四")).toMatchObject({
    isAlive: true,
    lastDetail: "被守护，未出局",
  });
});

it("clears no-detail pending actions when the game reaches a terminal event", () => {
  const state = deriveLiveSpectatorState([
    event({
      id: 1,
      type: "game_started",
      payload: {
        players: [{ name: "张三", role: "村民", model: "deepseek-chat" }],
      },
    }),
    event({
      id: 2,
      type: "state_updated",
      round: 1,
      phase: "summary",
      actor: "张三",
      action: "summarize",
      payload: {},
    }),
    event({
      id: 3,
      type: "game_completed",
      payload: { winner: "好人阵营" },
    }),
  ]);

  expect(state.players[0]).toMatchObject({
    status: "waiting",
    lastAction: "",
    lastDetail: "",
  });
});
```

- [ ] **Step 2: Run live spectator tests and verify they fail**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveSpectator.test.ts
```

Expected: FAIL because protected attacks are not given live detail and terminal cleanup does not exist.

- [ ] **Step 3: Update live spectator state derivation**

In `apps/web/src/features/games/liveSpectator.ts`, call terminal cleanup inside the event loop after `state_updated` handling:

```ts
if (event.type === "game_completed" || event.type === "game_failed") {
  clearPendingPlayerStates(state);
}
```

In `applyStateUpdate`, add protected-attack handling after `active_players` handling and before eliminated handling:

```ts
const attacked = payload.attacked;
const protectedPlayer = payload.protected;
if (
  typeof attacked === "string" &&
  typeof protectedPlayer === "string" &&
  attacked === protectedPlayer
) {
  const player = ensurePlayer(state, attacked);
  player.isAlive = true;
  player.status = "waiting";
  player.lastAction = "remove";
  player.lastDetail = "被守护，未出局";
}
```

Update eliminated handling to ignore protected attacks:

```ts
const eliminated = payload.eliminated;
if (
  typeof eliminated === "string" &&
  !(typeof protectedPlayer === "string" && eliminated === protectedPlayer)
) {
  const player = ensurePlayer(state, eliminated);
  player.isAlive = false;
  player.status = "out";
  player.lastDetail = "夜晚出局";
}
```

Add this helper:

```ts
function clearPendingPlayerStates(state: MutableLiveSpectatorState) {
  for (const player of state.playersByName.values()) {
    if (player.status === "thinking" || player.status === "requesting") {
      player.status = "waiting";
    }
    if (!player.lastDetail) {
      player.lastAction = "";
    }
  }
}
```

- [ ] **Step 4: Update live director cue text for protected attacks**

In `apps/web/src/features/games/liveDirector.ts`, in `stateUpdatedCue`, read `attacked` and `protected` before the eliminated block:

```ts
const attacked = stringField(payload, "attacked");
const protectedPlayer = stringField(payload, "protected");
if (attacked && protectedPlayer === attacked) {
  return {
    ...base,
    title: "平安夜",
    body: `${attacked} 被袭击，但被医生守护。\n${activePlayersBody(payload)}`,
    importance: "key",
    durationMs: 6000,
    compressible: false,
  };
}
```

Keep the existing eliminated block after this new protected-attack block.

- [ ] **Step 5: Verify live spectator behavior**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveSpectator.test.ts src/features/games/liveDirector.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit live protected-attack handling**

```bash
git add apps/web/src/features/games/liveSpectator.ts apps/web/src/features/games/liveSpectator.test.ts apps/web/src/features/games/liveDirector.ts
git commit -m "fix: keep protected attack targets alive in live view"
```

---

### Task 4: Completed Run Director Playback

**Files:**
- Modify: `apps/web/src/features/games/hooks/useLiveDirector.ts`
- Modify: `apps/web/src/features/games/hooks/useLiveDirector.test.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Write hook test for completed-run terminal start**

In `apps/web/src/features/games/hooks/useLiveDirector.test.tsx`, add:

```ts
it("starts at the terminal cue when completed replay mode is requested", () => {
  const events = [
    event({ id: 1, type: "run_created" }),
    event({ id: 2, type: "round_started", round: 1 }),
    event({
      id: 3,
      type: "game_completed",
      payload: { winner: "狼人阵营" },
    }),
  ];

  const { result } = renderHook(() =>
    useLiveDirector(events, { startAtLatestTerminal: true }),
  );

  expect(result.current.currentEventId).toBe(3);
  expect(result.current.backlogCount).toBe(0);
  expect(result.current.currentCue?.title).toBe("对局完成");
});
```

- [ ] **Step 2: Write LiveGamePage test for completed runs**

In `apps/web/src/pages/LiveGamePage.test.tsx`, add:

```tsx
it("opens completed runs at the terminal event instead of replaying the full backlog", async () => {
  vi.stubGlobal("EventSource", MockEventSource);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        villager_model: "deepseek-chat",
        werewolf_model: "deepseek-chat",
        seed: null,
        max_rounds: 8,
        status: "completed",
        created_at: "2026-04-24T12:00:00Z",
        started_at: "2026-04-24T12:00:01Z",
        completed_at: "2026-04-24T12:00:10Z",
        winner: "狼人阵营",
        error: null,
        event_count: 3,
        event_pacing: "off",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );

  renderWithClient(
    <Routes>
      <Route path="/games/live/:runId" element={<LiveGamePage />} />
    </Routes>,
    "/games/live/run_1234abcd",
  );

  expect(await screen.findByText("实时观战")).toBeInTheDocument();
  const source = MockEventSource.instances[0];
  act(() => {
    emitEvent(source, { id: 1, type: "run_created" });
    emitEvent(source, { id: 2, type: "round_started", round: 1 });
    emitEvent(source, {
      id: 3,
      type: "game_completed",
      payload: { winner: "狼人阵营" },
    });
  });

  expect(
    await screen.findByRole("heading", { name: "对局完成" }),
  ).toBeInTheDocument();
  expect(screen.getByText("队列剩余：0")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run director tests and verify they fail**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/hooks/useLiveDirector.test.tsx src/pages/LiveGamePage.test.tsx
```

Expected: FAIL because `useLiveDirector` does not accept options and LiveGamePage always starts at the first event.

- [ ] **Step 4: Add the completed-run option to the hook**

In `apps/web/src/features/games/hooks/useLiveDirector.ts`, add:

```ts
type UseLiveDirectorOptions = {
  startAtLatestTerminal?: boolean;
};
```

Change the signature:

```ts
export function useLiveDirector(
  events: LiveGameEvent[],
  options: UseLiveDirectorOptions = {},
): UseLiveDirectorResult {
```

Add this effect after `currentCue` is computed:

```ts
useEffect(() => {
  if (!options.startAtLatestTerminal) {
    return;
  }
  const latestTerminalCue = [...cues]
    .reverse()
    .find((cue) => cue.type === "game_completed" || cue.type === "game_failed");
  if (!latestTerminalCue || currentEventId === latestTerminalCue.eventId) {
    return;
  }
  setCurrentEventId(latestTerminalCue.eventId);
  startedAtRef.current = Date.now();
  lastStartedEventIdRef.current = latestTerminalCue.eventId;
}, [cues, currentEventId, options.startAtLatestTerminal]);
```

- [ ] **Step 5: Pass completed-run mode from LiveGamePage**

In `apps/web/src/pages/LiveGamePage.tsx`, keep the hook call unconditional and compute the option from the query data before the early return branches:

```tsx
const shouldStartAtTerminal =
  run?.status === "completed" || run?.status === "failed";
const director = useLiveDirector(events, {
  startAtLatestTerminal: shouldStartAtTerminal,
});
```

Keep the existing `terminalEvent` link behavior unchanged.

- [ ] **Step 6: Verify completed-run playback**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/hooks/useLiveDirector.test.tsx src/pages/LiveGamePage.test.tsx
```

Expected: PASS, including the existing ordered-playback test that uses the default hook options.

- [ ] **Step 7: Commit director playback changes**

```bash
git add apps/web/src/features/games/hooks/useLiveDirector.ts apps/web/src/features/games/hooks/useLiveDirector.test.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "fix: open completed live runs at terminal event"
```

---

### Task 5: Live Page Copy and Mobile Ordering

**Files:**
- Modify: `apps/web/src/features/games/components/LiveStatusStrip.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Write localized status test**

In `apps/web/src/pages/LiveGamePage.test.tsx`, update the completed-link test expectation:

```tsx
expect(await screen.findByText("已完成")).toBeInTheDocument();
expect(screen.getByText("连接：已连接")).toBeInTheDocument();
```

- [ ] **Step 2: Run the LiveGamePage test and verify it fails**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: FAIL because the UI still renders `completed` and `连接：open`.

- [ ] **Step 3: Localize status and connection labels**

In `apps/web/src/features/games/components/LiveStatusStrip.tsx`, add:

```ts
const statusLabels = {
  queued: "排队中",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
} as const;

const connectionLabels: Record<string, string> = {
  connecting: "连接中",
  open: "已连接",
  closed: "已关闭",
  error: "连接异常",
};
```

Use them in the returned JSX:

```tsx
<span className="font-medium text-slate-950">
  {statusLabels[run.status] ?? run.status}
</span>
<span className="text-slate-500">
  连接：{connectionLabels[connectionState] ?? connectionState}
</span>
```

- [ ] **Step 4: Reorder live page sections on mobile without changing desktop columns**

In `apps/web/src/pages/LiveGamePage.tsx`, wrap the three grid children:

```tsx
<div className="order-2 lg:order-1">
  <LivePlayerPanel ... />
</div>
<div className="order-1 space-y-3 lg:order-2">
  <LiveDirectorStage ... />
  <LiveDirectorControls ... />
</div>
<section className="order-3 overflow-hidden rounded-md border border-slate-200 bg-white lg:order-3 lg:max-h-[calc(100vh-8rem)] lg:overflow-auto">
  ...
</section>
```

This keeps desktop as players / director / events, while mobile shows director controls before the long player list.

- [ ] **Step 5: Verify LiveGamePage copy**

Run:

```bash
pnpm --dir apps/web test -- --run src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit live page copy and layout**

```bash
git add apps/web/src/features/games/components/LiveStatusStrip.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "chore: polish live run status and mobile order"
```

---

### Task 6: Full Verification

**Files:**
- No new files. This task verifies all previous changes together.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_werewolf_runner.py tests/test_games_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run focused frontend tests**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/api/adapters.test.ts src/features/games/liveSpectator.test.ts src/features/games/hooks/useLiveDirector.test.tsx src/pages/GameDetailPage.test.tsx src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Run full automated checks**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest
```

Expected: PASS.

Run:

```bash
pnpm --dir apps/web test -- --run
```

Expected: PASS.

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS with Vite build output and no TypeScript errors.

- [ ] **Step 4: Manual verification with the observed replay**

Open:

```text
http://127.0.0.1:5173/games/session_20260428_055443_b9f97d5d
```

Expected on the replay page:
- Round 1 shows `袭击 Sam`, `守护 Sam`, and `Sam 被守护，平安夜`.
- Round 1 no longer marks Sam as the actual night death.
- Later confirmed deaths still show `<name> 出局`.

Open the completed live run:

```text
http://127.0.0.1:5173/games/live/run_8cf21152ff5a
```

Expected on the live page:
- The director stage opens on `对局完成`.
- Queue count is `0`.
- Status strip uses Chinese labels.
- On mobile width, the current director stage appears before the player list.

- [ ] **Step 5: Final commit if verification required follow-up fixes**

If verification required small follow-up fixes, commit them:

```bash
git add apps/api apps/web
git commit -m "test: verify classic live observation fixes"
```

If no follow-up fixes were required, skip this commit.

---

## Follow-up Backlog After This Plan

- Add raw-event filtering and collapsed model responses in `LiveEventTimeline`.
- Add a full-table/player-turn mode so every surviving player speaks at least once per day.
- Replace name-sorted bid tie-breaking with seat order or seed-stable random ordering.
- Add a "hidden roles / god view" toggle if live spectators should not always see identities.
- Design a true two-wolf joint night decision flow instead of using the first active werewolf as the sole killer.
