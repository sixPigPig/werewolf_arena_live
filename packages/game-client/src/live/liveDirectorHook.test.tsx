// @vitest-environment jsdom

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
});
