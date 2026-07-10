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

    act(() => {
      result.current.seekToEventId(5);
    });
    expect(result.current.currentEventId).toBe(5);
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
});
