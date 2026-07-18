import { describe, expect, it } from "vitest";

import { buildLivePhaseSegments } from "./livePhaseBar";
import type { LiveGameEvent } from "../types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "phase_started",
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

describe("buildLivePhaseSegments", () => {
  it("builds ordered night and day phase segments from phase start events", () => {
    const segments = buildLivePhaseSegments(
      [
        event({ id: 1, type: "game_started" }),
        event({ id: 2, type: "round_started", round: 1 }),
        event({ id: 3, round: 1, phase: "night" }),
        event({ id: 4, round: 1, phase: "day" }),
        event({ id: 5, round: 2, phase: "night" }),
        event({ id: 6, round: 2, phase: "day" }),
      ],
      5,
    );

    expect(segments.map((segment) => segment.label)).toEqual([
      "夜一",
      "昼一",
      "夜二",
      "昼二",
    ]);
    expect(segments.map((segment) => segment.startEventId)).toEqual([
      3, 4, 5, 6,
    ]);
    expect(segments[2]).toMatchObject({
      id: "round-2-night",
      round: 2,
      phase: "night",
      isCurrent: true,
      isVisited: true,
    });
    expect(segments[3]).toMatchObject({
      isCurrent: false,
      isVisited: false,
    });
  });

  it("ignores non-main phases and duplicate phase starts", () => {
    const segments = buildLivePhaseSegments(
      [
        event({ id: 7, round: 1, phase: "night" }),
        event({ id: 8, round: 1, phase: "night" }),
        event({ id: 9, round: 1, phase: "vote" }),
        event({ id: 10, round: 1, phase: "summary" }),
        event({ id: 11, round: null, phase: "day" }),
        event({ id: 12, round: 1, phase: "day" }),
      ],
      10,
    );

    expect(segments).toHaveLength(2);
    expect(segments.map((segment) => segment.startEventId)).toEqual([7, 12]);
    expect(segments.map((segment) => segment.label)).toEqual(["夜一", "昼一"]);
    expect(segments[0]).toMatchObject({
      isCurrent: true,
      isVisited: true,
    });
    expect(segments[1]).toMatchObject({
      isCurrent: false,
      isVisited: false,
    });
  });

  it("keeps the current day active through vote, summary and terminal events", () => {
    const events = [
      event({ id: 3, round: 1, phase: "night" }),
      event({ id: 6, round: 1, phase: "day" }),
      event({ id: 8, round: 1, phase: "vote" }),
      event({ id: 10, round: 1, phase: "summary" }),
      event({ id: 12, type: "game_completed", round: null, phase: null }),
    ];

    expect(
      buildLivePhaseSegments(events, 8).find((segment) => segment.isCurrent),
    ).toMatchObject({ label: "昼一" });
    expect(
      buildLivePhaseSegments(events, 12).find((segment) => segment.isCurrent),
    ).toMatchObject({ label: "昼一" });
  });

  it("does not mark a phase current before the first phase start", () => {
    const segments = buildLivePhaseSegments(
      [
        event({ id: 3, round: 1, phase: "night" }),
        event({ id: 6, round: 1, phase: "day" }),
      ],
      2,
    );

    expect(segments.some((segment) => segment.isCurrent)).toBe(false);
    expect(segments.some((segment) => segment.isVisited)).toBe(false);
  });

  it("uses phase instance identity and closes the segment on phase_completed", () => {
    const events = [
      event({
        id: 3,
        round: 1,
        phase: "day",
        payload: { phase_instance_id: "day-1" },
      }),
      event({
        id: 8,
        type: "phase_completed",
        round: 1,
        phase: "day",
        payload: {
          phase_instance_id: "day-1",
          completion_status: "completed",
          completion_reason: "self_explosion",
        },
      }),
    ];

    expect(buildLivePhaseSegments(events, 7)[0]).toMatchObject({
      id: "phase-day-1",
      phaseInstanceId: "day-1",
      isCurrent: true,
    });
    expect(buildLivePhaseSegments(events, 8)[0]).toMatchObject({
      completionEventId: 8,
      completionStatus: "completed",
      completionReason: "self_explosion",
      isCurrent: false,
      isVisited: true,
    });
  });
});
