import { describe, expect, it } from "vitest";

import { projectLivePresentationEvents } from "./livePresentation";
import type { LiveGameEvent } from "../types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "state_updated",
    run_id: partial.run_id ?? "run-parent",
    session_id: partial.session_id ?? "game-one",
    created_at: "2026-07-17T00:00:00Z",
    round: partial.round ?? 2,
    phase: partial.phase ?? "day",
    actor: partial.actor ?? null,
    action: partial.action ?? "exile_resolved",
    payload: partial.payload ?? {},
  };
}

describe("projectLivePresentationEvents", () => {
  it("keeps only the latest occurrence of a stable presentation across unrelated events", () => {
    const parent = event({
      id: 10,
      payload: {
        presentation_id: "settlement:game-one:2:day:primary:presentation",
        exiled: "2号玩家",
      },
    });
    const unrelated = event({
      id: 11,
      type: "game_resumed",
      run_id: "run-child",
      action: null,
      payload: {},
    });
    const child = event({
      id: 12,
      run_id: "run-child",
      payload: {
        presentation_id: "settlement:game-one:2:day:primary:presentation",
        exiled: "2号玩家",
      },
    });

    expect(projectLivePresentationEvents([parent, unrelated, child])).toEqual([
      unrelated,
      child,
    ]);
  });

  it("does not content-dedupe legacy events or distinct presentation IDs", () => {
    const legacyOne = event({ id: 1, payload: { exiled: "2号玩家" } });
    const legacyTwo = event({ id: 2, payload: { exiled: "2号玩家" } });
    const firstPresentation = event({
      id: 3,
      payload: { presentation_id: "presentation-one", exiled: "2号玩家" },
    });
    const secondPresentation = event({
      id: 4,
      payload: { presentation_id: "presentation-two", exiled: "2号玩家" },
    });
    const events = [
      legacyOne,
      legacyTwo,
      firstPresentation,
      secondPresentation,
    ];

    expect(projectLivePresentationEvents(events)).toBe(events);
    expect(projectLivePresentationEvents(events)).toHaveLength(4);
  });
});
