// @vitest-environment jsdom

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLiveDirector } from "./liveDirector";
import type { LiveGameEvent } from "../types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "game_started",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
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
