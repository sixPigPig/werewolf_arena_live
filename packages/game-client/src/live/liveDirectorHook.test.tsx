// @vitest-environment jsdom

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLiveDirector } from "./liveDirector";
import type { LiveGameEvent } from "../types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "game_started",
    run_id: partial.run_id ?? "run_1234abcd",
    session_id: partial.session_id ?? "game_1200abcd",
    created_at: "2026-04-24T12:00:00Z",
    round: partial.round ?? null,
    phase: partial.phase ?? null,
    actor: partial.actor ?? null,
    action: partial.action ?? null,
    payload: partial.payload ?? {},
  };
}

const events = [
  event({ id: 1, type: "game_started" }),
  event({ id: 3, type: "phase_started", round: 1, phase: "night" }),
  event({ id: 5, type: "phase_started", round: 1, phase: "day" }),
  event({ id: 9, type: "game_completed", payload: { winner: "好人阵营" } }),
];

describe("useLiveDirector seekToEventId", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("jumps to the requested cue or the nearest available cue", () => {
    const { result } = renderHook(() => useLiveDirector(events));
    expect(result.current.cursorVersion).toBe(0);

    act(() => {
      result.current.seekToEventId(5);
    });
    expect(result.current.currentEventId).toBe(5);
    expect(result.current.cursorVersion).toBe(1);
    expect(result.current.currentCue?.phase).toBe("day");

    act(() => {
      result.current.seekToEventId(4);
    });
    expect(result.current.currentEventId).toBe(5);

    act(() => {
      result.current.seekToEventId(99);
    });
    expect(result.current.currentEventId).toBe(9);

    act(() => {
      result.current.seekToEventId(0);
    });
    expect(result.current.currentEventId).toBe(1);
  });

  it("changes cursor version only for explicit navigation", () => {
    const { result } = renderHook(() => useLiveDirector(events));

    act(() => {
      result.current.advance();
    });
    expect(result.current.currentEventId).toBe(3);
    expect(result.current.cursorVersion).toBe(0);

    act(() => {
      result.current.catchUpToLatest();
    });
    expect(result.current.cursorVersion).toBe(1);
  });

  it("preserves the paused state when seeking", () => {
    const { result } = renderHook(() => useLiveDirector(events));

    act(() => {
      result.current.pause();
    });
    act(() => {
      result.current.seekToEventId(5);
    });

    expect(result.current.isPaused).toBe(true);
    expect(result.current.currentEventId).toBe(5);
  });

  it("allows seeking away after a completed run starts at the terminal cue", () => {
    const { result } = renderHook(() =>
      useLiveDirector(events, { startAtLatestTerminal: true }),
    );

    expect(result.current.currentEventId).toBe(9);

    act(() => {
      result.current.seekToEventId(3);
    });

    expect(result.current.currentEventId).toBe(3);
    expect(result.current.currentCue?.phase).toBe("night");
  });

  it("does not jump to terminal when terminal mode turns on after live playback starts", () => {
    const initialEvents = [
      event({ id: 1, type: "game_started" }),
      event({ id: 3, type: "phase_started", round: 1, phase: "night" }),
    ];
    const { rerender, result } = renderHook(
      ({
        liveEvents,
        startAtLatestTerminal,
      }: {
        liveEvents: LiveGameEvent[];
        startAtLatestTerminal: boolean;
      }) => useLiveDirector(liveEvents, { startAtLatestTerminal }),
      {
        initialProps: {
          liveEvents: initialEvents,
          startAtLatestTerminal: false,
        },
      },
    );

    expect(result.current.currentEventId).toBe(1);

    rerender({
      liveEvents: [
        ...initialEvents,
        event({ id: 9, type: "game_completed", payload: { winner: "好人阵营" } }),
      ],
      startAtLatestTerminal: true,
    });

    expect(result.current.currentEventId).toBe(1);
    expect(result.current.backlogCount).toBe(2);
  });

  it("preserves unplayed backlog when a completion event arrives", () => {
    const initialEvents = [
      event({ id: 1, type: "game_started" }),
      event({ id: 3, type: "phase_started", round: 1, phase: "day" }),
      event({
        id: 5,
        type: "model_request_started",
        actor: "1号玩家",
        action: "debate",
        payload: { request_id: "req-backlog" },
      }),
      event({
        id: 6,
        type: "model_response_delta",
        actor: "1号玩家",
        action: "debate",
        payload: { request_id: "req-backlog", visible_text: "这段已经失去意义。" },
      }),
      event({
        id: 7,
        type: "state_updated",
        round: 1,
        phase: "vote",
        action: "exile_resolved",
        payload: { eliminated: "1号玩家" },
      }),
    ];
    const { rerender, result } = renderHook(
      ({ liveEvents }: { liveEvents: LiveGameEvent[] }) =>
        useLiveDirector(liveEvents),
      { initialProps: { liveEvents: initialEvents } },
    );

    expect(result.current.currentEventId).toBe(1);

    rerender({
      liveEvents: [
        ...initialEvents,
        event({
          id: 9,
          type: "game_completed",
          payload: {
            winner: "狼人阵营",
            terminal_keep_from_event_id: 7,
          },
        }),
      ],
    });

    expect(result.current.currentCue).toMatchObject({ eventId: 1 });
    expect(result.current.currentEventId).toBe(1);
    expect(result.current.cues.some((cue) => cue.eventId === 7)).toBe(true);
    expect(result.current.cues.some((cue) => cue.eventId === 9)).toBe(true);
  });

  it("keeps completed replay playback at the first event", () => {
    const completedReplayEvents = [
      event({ id: 3, type: "game_started" }),
      event({
        id: 955,
        type: "state_updated",
        round: 3,
        phase: "vote",
        action: "exile_resolved",
        payload: { exiled: "1号玩家" },
      }),
      event({
        id: 957,
        type: "game_completed",
        payload: {
          winner: "狼人阵营",
          terminal_keep_from_event_id: 955,
        },
      }),
    ];
    const { result } = renderHook(() => useLiveDirector(completedReplayEvents));

    expect(result.current.currentEventId).toBe(3);
    expect(result.current.currentCue).toMatchObject({
      eventId: 3,
      type: "game_started",
    });
    expect(result.current.cues.map((cue) => cue.eventId)).toEqual([
      3, 955, 957,
    ]);
  });

  it("does not skip run_2d12b755578b backlog at completion", () => {
    // Client layer for apps/api/tests/fixtures/run_2d12b755578b_terminal_regression.json.
    const scenarioEvent = (partial: Partial<LiveGameEvent>) =>
      event({
        ...partial,
        run_id: "run_2d12b755578b",
        session_id: "game_d8a3c680",
      });
    const initialEvents = [
      scenarioEvent({ id: 1, type: "game_started" }),
      scenarioEvent({ id: 1200, type: "phase_started", round: 4, phase: "day" }),
      scenarioEvent({ id: 1304, type: "phase_started", round: 4, phase: "vote" }),
      scenarioEvent({
        id: 1305,
        type: "state_updated",
        round: 4,
        phase: "vote",
        action: "exile_resolved",
        payload: { exiled: "2号玩家", active_players: ["1号玩家", "3号玩家"] },
      }),
      scenarioEvent({
        id: 1306,
        type: "judge_cue",
        round: 4,
        phase: "vote",
        action: "exile_result",
        payload: {
          visible_text: "2号玩家得票最高，被放逐出局。",
          static_asset_id: "exile_result_2",
        },
      }),
    ];
    const { rerender, result } = renderHook(
      ({ liveEvents }: { liveEvents: LiveGameEvent[] }) =>
        useLiveDirector(liveEvents),
      { initialProps: { liveEvents: initialEvents } },
    );

    expect(result.current.currentEventId).toBe(1);

    rerender({
      liveEvents: [
        ...initialEvents,
        scenarioEvent({
          id: 1307,
          type: "game_completed",
          payload: {
            winner: "狼人阵营",
            terminal_keep_from_event_id: 1305,
          },
        }),
      ],
    });

    expect(result.current.currentCue).toMatchObject({ eventId: 1 });
    expect(result.current.currentEventId).toBe(1);
    expect(result.current.cues.some((cue) => cue.eventId === 1305)).toBe(true);
    expect(result.current.cues.some((cue) => cue.eventId === 1307)).toBe(true);
  });

  it("keeps a coalesced cue when completion arrives", () => {
    const initialEvents = [
      event({ id: 1, type: "game_started" }),
      event({
        id: 4,
        type: "model_request_started",
        actor: "1号玩家",
        action: "debate",
        payload: { request_id: "req-overlap" },
      }),
      event({
        id: 5,
        type: "phase_started",
        round: 1,
        phase: "vote",
      }),
      event({
        id: 6,
        type: "model_response_delta",
        actor: "1号玩家",
        action: "debate",
        payload: { request_id: "req-overlap", visible_text: "合并发言跨过边界。" },
      }),
    ];
    const { rerender, result } = renderHook(
      ({ liveEvents }: { liveEvents: LiveGameEvent[] }) =>
        useLiveDirector(liveEvents),
      { initialProps: { liveEvents: initialEvents } },
    );

    act(() => result.current.seekToEventId(4));
    expect(result.current.currentCue).toMatchObject({ eventId: 4, latestEventId: 6 });

    rerender({
      liveEvents: [
        ...initialEvents,
        event({
          id: 9,
          type: "game_completed",
          payload: {
            winner: "好人阵营",
            terminal_keep_from_event_id: 6,
          },
        }),
      ],
    });

    expect(result.current.currentCue).toMatchObject({ eventId: 4, latestEventId: 6 });
    expect(result.current.currentEventId).toBe(6);
    expect(result.current.cues.some((cue) => cue.eventId === 9)).toBe(true);
  });

  it("preserves a resumed run folded timeline from its first cue", () => {
    const decisiveEvent: LiveGameEvent = {
      ...event({
        id: 12,
        type: "state_updated",
        action: "exile_resolved",
        payload: { eliminated: "1号玩家" },
      }),
      source_run_id: "run-resumed",
      source_event_id: 45,
    };
    const completedEvent: LiveGameEvent = {
      ...event({
        id: 14,
        type: "game_completed",
        payload: {
          winner: "狼人阵营",
          terminal_keep_from_event_id: 45,
        },
      }),
      source_run_id: "run-resumed",
      source_event_id: 47,
    };
    const { result } = renderHook(() =>
      useLiveDirector([
        event({ id: 1, type: "game_started" }),
        decisiveEvent,
        completedEvent,
      ]),
    );

    expect(result.current.currentEventId).toBe(1);
    expect(result.current.cues.map((cue) => cue.eventId)).toEqual([1, 12, 14]);
  });

  it("does not replay a child-run presentation that was already current in the parent run", () => {
    const presentationId = "game_same:hunter:settlement-1";
    const parentPresentation = event({
      id: 10,
      run_id: "run-parent",
      session_id: "game_same",
      type: "state_updated",
      action: "hunter_shot_resolved",
      payload: {
        presentation_id: presentationId,
        hunter_shot_status: "shot",
        hunter_shot: "4号玩家",
      },
    });
    const childPresentation = event({
      id: 20,
      run_id: "run-child",
      session_id: "game_same",
      type: "state_updated",
      action: "hunter_shot_resolved",
      payload: {
        presentation_id: presentationId,
        hunter_shot_status: "shot",
        hunter_shot: "4号玩家",
      },
    });
    const childCompletion = event({
      id: 21,
      run_id: "run-child",
      session_id: "game_same",
      type: "game_completed",
      payload: { winner: "好人阵营" },
    });
    const { rerender, result } = renderHook(
      ({ liveEvents, resetKey, sessionKey }) =>
        useLiveDirector(liveEvents, { resetKey, sessionKey }),
      {
        initialProps: {
          liveEvents: [parentPresentation],
          resetKey: "run-parent",
          sessionKey: "game_same",
        },
      },
    );

    expect(result.current.currentCue).toMatchObject({
      eventId: 10,
      presentationId,
    });

    rerender({
      liveEvents: [childPresentation, childCompletion],
      resetKey: "run-child",
      sessionKey: "game_same",
    });

    expect(result.current.cues.map((cue) => cue.eventId)).toEqual([21]);
    expect(result.current.currentCue).toMatchObject({
      eventId: 21,
      type: "game_completed",
    });
  });

  it("applies semantic presentation dedupe to recovered primary results", () => {
    const presentationId =
      "settlement:game_same:3:vote:2号玩家:primary:presentation";
    const primaryResult = (id: number, runId: string) =>
      event({
        id,
        run_id: runId,
        session_id: "game_same",
        type: "state_updated",
        action: "exile_resolved",
        payload: {
          presentation_id: presentationId,
          exiled: "2号玩家",
          active_players: ["1号玩家", "3号玩家"],
        },
      });
    const { rerender, result } = renderHook(
      ({ liveEvents, resetKey }) =>
        useLiveDirector(liveEvents, {
          resetKey,
          sessionKey: "game_same",
        }),
      {
        initialProps: {
          liveEvents: [primaryResult(30, "run-parent")],
          resetKey: "run-parent",
        },
      },
    );
    expect(result.current.currentCue).toMatchObject({
      eventId: 30,
      presentationId,
      action: "exile_resolved",
    });

    rerender({
      liveEvents: [
        primaryResult(40, "run-child"),
        event({
          id: 41,
          run_id: "run-child",
          session_id: "game_same",
          type: "game_completed",
          payload: { winner: "狼人阵营" },
        }),
      ],
      resetKey: "run-child",
    });

    expect(result.current.cues.map((cue) => cue.eventId)).toEqual([41]);
    expect(result.current.currentCue?.type).toBe("game_completed");
  });

  it("removes a queued child occurrence after the parent presentation becomes current", () => {
    const presentationId = "game_same:hunter:shot:initial-backlog";
    const hunterResult = (id: number, runId: string) =>
      event({
        id,
        run_id: runId,
        session_id: "game_same",
        type: "state_updated",
        action: "hunter_shot_resolved",
        payload: {
          presentation_id: presentationId,
          hunter_shot_status: "shot",
          hunter_shot: "4号玩家",
        },
      });
    const { result } = renderHook(() =>
      useLiveDirector(
        [
          hunterResult(50, "run-parent"),
          hunterResult(60, "run-child"),
          event({
            id: 61,
            run_id: "run-child",
            session_id: "game_same",
            type: "game_completed",
            payload: { winner: "好人阵营" },
          }),
        ],
        { resetKey: "run-child", sessionKey: "game_same" },
      ),
    );

    expect(result.current.currentCue).toMatchObject({
      eventId: 50,
      presentationId,
    });
    expect(result.current.cues.map((cue) => cue.eventId)).toEqual([50, 61]);

    act(() => result.current.advance());
    expect(result.current.currentCue).toMatchObject({
      eventId: 61,
      type: "game_completed",
    });
  });

  it("can jump to the child occurrence when the queued parent was never presented", () => {
    const presentationId = "game_same:hunter:skipped:initial-backlog";
    const hunterResult = (id: number, runId: string) =>
      event({
        id,
        run_id: runId,
        session_id: "game_same",
        type: "state_updated",
        action: "hunter_shot_resolved",
        payload: {
          presentation_id: presentationId,
          hunter_shot_status: "skipped",
          hunter_shot: null,
        },
      });
    const { result } = renderHook(() =>
      useLiveDirector(
        [
          event({
            id: 1,
            run_id: "run-parent",
            session_id: "game_same",
            type: "game_started",
          }),
          hunterResult(70, "run-parent"),
          hunterResult(80, "run-child"),
        ],
        { resetKey: "run-child", sessionKey: "game_same" },
      ),
    );
    expect(result.current.currentEventId).toBe(1);

    act(() => result.current.catchUpToLatest());

    expect(result.current.currentCue).toMatchObject({
      eventId: 80,
      presentationId,
      body: "猎人选择不发动技能。",
    });
    expect(result.current.cues.map((cue) => cue.eventId)).toEqual([1, 80]);
  });

  it("shows a child-run presentation when the parent occurrence never became current", () => {
    const presentationId = "game_same:hunter:settlement-2";
    const parentStart = event({
      id: 1,
      run_id: "run-parent",
      session_id: "game_same",
      type: "game_started",
    });
    const parentPresentation = event({
      id: 10,
      run_id: "run-parent",
      session_id: "game_same",
      type: "state_updated",
      action: "hunter_shot_resolved",
      payload: {
        presentation_id: presentationId,
        hunter_shot_status: "skipped",
        hunter_shot: null,
      },
    });
    const childStart = event({
      id: 11,
      run_id: "run-child",
      session_id: "game_same",
      type: "game_resumed",
    });
    const childPresentation = event({
      id: 20,
      run_id: "run-child",
      session_id: "game_same",
      type: "state_updated",
      action: "hunter_shot_resolved",
      payload: {
        presentation_id: presentationId,
        hunter_shot_status: "skipped",
        hunter_shot: null,
      },
    });
    const { rerender, result } = renderHook(
      ({ liveEvents, resetKey, sessionKey }) =>
        useLiveDirector(liveEvents, { resetKey, sessionKey }),
      {
        initialProps: {
          liveEvents: [parentStart, parentPresentation],
          resetKey: "run-parent",
          sessionKey: "game_same",
        },
      },
    );

    expect(result.current.currentEventId).toBe(1);

    rerender({
      liveEvents: [childStart, childPresentation],
      resetKey: "run-child",
      sessionKey: "game_same",
    });
    expect(result.current.cues.map((cue) => cue.eventId)).toEqual([11, 20]);

    act(() => result.current.advance());
    expect(result.current.currentCue).toMatchObject({
      eventId: 20,
      presentationId,
      body: "猎人选择不发动技能。",
    });
  });

  it("clears presentation history when the session continuity key changes", () => {
    const presentationId = "opaque-hunter-presentation";
    const { rerender, result } = renderHook(
      ({ liveEvents, resetKey, sessionKey }) =>
        useLiveDirector(liveEvents, { resetKey, sessionKey }),
      {
        initialProps: {
          liveEvents: [
            event({
              id: 10,
              run_id: "run-one",
              session_id: "game-one",
              type: "state_updated",
              action: "hunter_shot_resolved",
              payload: {
                presentation_id: presentationId,
                hunter_shot_status: "skipped",
              },
            }),
          ],
          resetKey: "run-one",
          sessionKey: "game-one",
        },
      },
    );
    expect(result.current.currentCue?.presentationId).toBe(presentationId);

    rerender({
      liveEvents: [
        event({
          id: 20,
          run_id: "run-two",
          session_id: "game-two",
          type: "state_updated",
          action: "hunter_shot_resolved",
          payload: {
            presentation_id: presentationId,
            hunter_shot_status: "skipped",
          },
        }),
      ],
      resetKey: "run-two",
      sessionKey: "game-two",
    });

    expect(result.current.currentCue).toMatchObject({
      eventId: 20,
      presentationId,
    });
  });

  it("can start live playback at the first requested event type", () => {
    const startupEvents = [
      event({ id: 1, type: "run_created" }),
      event({ id: 2, type: "run_started" }),
      event({ id: 3, type: "game_started" }),
      event({ id: 4, type: "phase_started", round: 1, phase: "night" }),
    ];

    const { result } = renderHook(() =>
      useLiveDirector(startupEvents, { startAtEventType: "game_started" }),
    );

    expect(result.current.currentEventId).toBe(3);
    expect(result.current.currentCue?.type).toBe("game_started");
    expect(result.current.backlogCount).toBe(1);
  });

  it("keeps the current cue when streaming deltas extend its event range", () => {
    const initialEvents = [
      event({ id: 1, type: "game_started" }),
      event({
        id: 2,
        type: "model_request_started",
        actor: "张三",
        action: "debate",
        payload: { request_id: "req_123", model: "deepseek-chat" },
      }),
    ];
    const { rerender, result } = renderHook(
      ({ liveEvents }: { liveEvents: LiveGameEvent[] }) =>
        useLiveDirector(liveEvents),
      { initialProps: { liveEvents: initialEvents } },
    );

    act(() => {
      result.current.seekToEventId(2);
    });
    expect(result.current.currentCue).toMatchObject({
      eventId: 2,
      latestEventId: 2,
      type: "model_request_started",
    });

    rerender({
      liveEvents: [
        ...initialEvents,
        event({
          id: 3,
          type: "model_response_delta",
          actor: "张三",
          action: "debate",
          payload: {
            request_id: "req_123",
            visible_text: "我不是狼",
            is_public: true,
          },
        }),
      ],
    });

    expect(result.current.currentCue).toMatchObject({
      eventId: 2,
      latestEventId: 3,
      type: "model_request_started",
      body: "张三：我不是狼",
    });
    expect(result.current.currentEventId).toBe(3);
    expect(result.current.backlogCount).toBe(0);
  });

  it("recovers a missing cue by moving forward instead of restarting", () => {
    const initialEvents = [
      event({ id: 1, type: "game_started" }),
      event({ id: 3, type: "phase_started", round: 1, phase: "night" }),
      event({ id: 5, type: "phase_started", round: 1, phase: "day" }),
    ];
    const { rerender, result } = renderHook(
      ({ liveEvents }: { liveEvents: LiveGameEvent[] }) =>
        useLiveDirector(liveEvents),
      { initialProps: { liveEvents: initialEvents } },
    );

    act(() => {
      result.current.seekToEventId(3);
    });
    expect(result.current.currentEventId).toBe(3);

    rerender({ liveEvents: [initialEvents[0], initialEvents[2]] });

    expect(result.current.currentEventId).toBe(5);
    expect(result.current.currentCue?.phase).toBe("day");
  });

  it("does not auto-advance while external playback is holding the current cue", () => {
    vi.useFakeTimers();

    const { rerender, result } = renderHook(
      ({ holdAdvance }: { holdAdvance: boolean }) =>
        useLiveDirector(events, { holdAdvance }),
      { initialProps: { holdAdvance: true } },
    );

    expect(result.current.currentEventId).toBe(1);

    act(() => {
      vi.advanceTimersByTime(30000);
    });

    expect(result.current.currentEventId).toBe(1);

    rerender({ holdAdvance: false });

    act(() => {
      vi.advanceTimersByTime(0);
    });

    expect(result.current.currentEventId).toBe(3);
  });

  it("clears only the matching cue fallback time after voice completes", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useLiveDirector(events));

    act(() => {
      result.current.completeVoicePlayback({
        id: "voice-1:1",
        sourceEventId: 1,
        lastSourceEventId: 1,
      });
    });
    expect(result.current.effectiveDurationMs).toBe(0);

    act(() => {
      vi.advanceTimersByTime(0);
    });
    expect(result.current.currentEventId).toBe(3);
    expect(result.current.effectiveDurationMs).toBeGreaterThan(0);

    act(() => {
      result.current.completeVoicePlayback({
        id: "stale-voice:1",
        sourceEventId: 1,
        lastSourceEventId: 1,
      });
    });
    expect(result.current.effectiveDurationMs).toBeGreaterThan(0);
  });
});
