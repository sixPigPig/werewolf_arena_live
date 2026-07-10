import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveDirector } from "./useLiveDirector";
import type { LiveGameEvent } from "../types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "round_started",
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

describe("useLiveDirector", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("plays cues in order instead of jumping to the latest event", () => {
    const initialEvents = [event({ id: 1, type: "round_started", round: 1 })];
    const { result, rerender } = renderHook(
      ({ events }: { events: LiveGameEvent[] }) => useLiveDirector(events),
      { initialProps: { events: initialEvents } },
    );

    rerender({
      events: [
        ...initialEvents,
        event({ id: 2, type: "phase_started", round: 1, phase: "day" }),
        event({
          id: 3,
          type: "game_completed",
          payload: { winner: "好人阵营" },
        }),
      ],
    });

    expect(result.current.currentEventId).toBe(1);
    expect(result.current.backlogCount).toBe(2);

    act(() => {
      vi.advanceTimersByTime(result.current.effectiveDurationMs - 1);
    });
    expect(result.current.currentEventId).toBe(1);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.currentEventId).toBe(2);
  });

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

  it("does not jump to terminal when terminal mode turns on after live playback starts", () => {
    const initialEvents = [
      event({ id: 1, type: "round_started", round: 1 }),
      event({ id: 2, type: "phase_started", round: 1, phase: "night" }),
    ];
    const { result, rerender } = renderHook(
      ({
        events,
        startAtLatestTerminal,
      }: {
        events: LiveGameEvent[];
        startAtLatestTerminal: boolean;
      }) => useLiveDirector(events, { startAtLatestTerminal }),
      {
        initialProps: {
          events: initialEvents,
          startAtLatestTerminal: false,
        },
      },
    );

    expect(result.current.currentEventId).toBe(1);

    rerender({
      events: [
        ...initialEvents,
        event({
          id: 3,
          type: "game_completed",
          payload: { winner: "好人阵营" },
        }),
      ],
      startAtLatestTerminal: true,
    });

    expect(result.current.currentEventId).toBe(1);
    expect(result.current.backlogCount).toBe(2);
  });

  it("pauses and resumes director timing without dropping later events", () => {
    const { result, rerender } = renderHook(
      ({ events }: { events: LiveGameEvent[] }) => useLiveDirector(events),
      { initialProps: { events: [event({ id: 1, type: "round_started" })] } },
    );

    act(() => {
      result.current.pause();
    });
    rerender({
      events: [
        event({ id: 1, type: "round_started" }),
        event({ id: 2, type: "phase_started", phase: "day" }),
      ],
    });

    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(result.current.currentEventId).toBe(1);
    expect(result.current.backlogCount).toBe(1);

    act(() => {
      result.current.resume();
    });
    act(() => {
      vi.advanceTimersByTime(result.current.effectiveDurationMs);
    });

    expect(result.current.currentEventId).toBe(2);
    expect(result.current.backlogCount).toBe(0);
  });

  it("holds automatic advance while external playback is blocking", () => {
    const events = [
      event({ id: 1, type: "round_started", round: 1 }),
      event({ id: 2, type: "phase_started", round: 1, phase: "day" }),
    ];
    const { result, rerender } = renderHook(
      ({ holdAdvance }: { holdAdvance: boolean }) =>
        useLiveDirector(events, { holdAdvance }),
      { initialProps: { holdAdvance: true } },
    );

    act(() => {
      vi.advanceTimersByTime(result.current.effectiveDurationMs + 1000);
    });
    expect(result.current.currentEventId).toBe(1);
    expect(result.current.backlogCount).toBe(1);

    rerender({ holdAdvance: false });
    act(() => {
      vi.advanceTimersByTime(0);
    });

    expect(result.current.currentEventId).toBe(2);
    expect(result.current.backlogCount).toBe(0);
  });

  it("catches up to the latest key event instead of the latest compressible cue", () => {
    const events = [
      event({ id: 1, type: "round_started", round: 1 }),
      event({ id: 2, type: "action_requested", actor: "张三", action: "vote" }),
      event({
        id: 3,
        type: "state_updated",
        payload: { exiled: "李四", active_players: ["张三", "王五"] },
      }),
      event({
        id: 4,
        type: "action_requested",
        actor: "王五",
        action: "debate",
      }),
    ];
    const { result } = renderHook(() => useLiveDirector(events));

    act(() => {
      result.current.catchUpToLatest();
    });

    expect(result.current.currentEventId).toBe(3);
    expect(result.current.currentCue?.compressible).toBe(false);
    expect(result.current.backlogCount).toBe(1);

    act(() => {
      result.current.catchUpToLatest();
    });
    expect(result.current.currentEventId).toBe(4);
    expect(result.current.backlogCount).toBe(0);
  });

  it("starts a caught-up cue from resume time when catch-up happens while paused", () => {
    const events = [
      event({ id: 1, type: "round_started", round: 1 }),
      event({
        id: 2,
        type: "state_updated",
        payload: { exiled: "李四", active_players: ["张三", "王五"] },
      }),
      event({
        id: 3,
        type: "action_requested",
        actor: "王五",
        action: "debate",
      }),
    ];
    const { result } = renderHook(() => useLiveDirector(events));

    act(() => {
      result.current.pause();
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
      result.current.catchUpToLatest();
    });
    expect(result.current.currentEventId).toBe(2);

    act(() => {
      vi.advanceTimersByTime(60_000);
      result.current.resume();
    });
    act(() => {
      vi.advanceTimersByTime(result.current.effectiveDurationMs);
    });

    expect(result.current.currentEventId).toBe(3);
  });

  it("compresses normal cue duration while catching up from a high backlog", () => {
    const events = Array.from({ length: 9 }, (_, index) =>
      event({ id: index + 1, type: "round_started", round: index + 1 }),
    );
    const { result } = renderHook(() => useLiveDirector(events));

    expect(result.current.currentEventId).toBe(1);
    expect(result.current.backlogCount).toBe(8);
    expect(result.current.isCatchingUp).toBe(true);
    expect(result.current.currentCue?.compressible).toBe(true);
    expect(result.current.effectiveDurationMs).toBe(500);

    act(() => {
      result.current.setSpeed(2);
    });
    expect(result.current.speed).toBe(2);
    expect(result.current.effectiveDurationMs).toBe(500);
  });

  it("halves normal cue duration at 2x speed", () => {
    const events = [
      event({ id: 1, type: "round_started", round: 1 }),
      event({ id: 2, type: "phase_started", round: 1, phase: "day" }),
    ];
    const { result } = renderHook(() => useLiveDirector(events));

    expect(result.current.effectiveDurationMs).toBe(2500);

    act(() => {
      result.current.setSpeed(2);
    });

    expect(result.current.speed).toBe(2);
    expect(result.current.effectiveDurationMs).toBe(1250);
  });

  it("resets speed to 1x when reset key changes", () => {
    const events = [
      event({ id: 1, type: "round_started", round: 1 }),
      event({ id: 2, type: "phase_started", round: 1, phase: "day" }),
    ];
    const { result, rerender } = renderHook(
      ({ resetKey }: { resetKey: string }) =>
        useLiveDirector(events, { resetKey }),
      { initialProps: { resetKey: "run_a" } },
    );

    act(() => {
      result.current.setSpeed(2);
    });
    expect(result.current.speed).toBe(2);

    rerender({ resetKey: "run_b" });

    expect(result.current.speed).toBe(1);
  });
});
