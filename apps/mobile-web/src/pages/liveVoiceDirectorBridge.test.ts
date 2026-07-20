import { describe, expect, it } from "vitest";

import {
  isVoicePlaybackBlocking,
  mapVoiceCompletionToTimeline,
} from "./liveVoiceDirectorBridge";
import type { LiveGameEvent } from "@werewolf-arena/game-client";

const events: LiveGameEvent[] = [
  {
    id: 91,
    type: "model_request_started",
    run_id: "run-1",
    session_id: "game-1",
    created_at: "2026-07-20T00:00:00Z",
    round: 1,
    phase: "day",
    actor: "1号玩家",
    action: "debate",
    payload: {},
    source_run_id: "run-source",
    source_event_id: 10,
  },
  {
    id: 93,
    type: "model_response_delta",
    run_id: "run-1",
    session_id: "game-1",
    created_at: "2026-07-20T00:00:01Z",
    round: 1,
    phase: "day",
    actor: "1号玩家",
    action: "debate",
    payload: {},
    source_run_id: "run-source",
    source_event_id: 12,
  },
];

describe("live voice/director bridge", () => {
  it("holds only the logical speech matching the current cue", () => {
    const item = {
      sourceEventId: 10,
      lastSourceEventId: 12,
      speechId: "speech-1",
      status: "playing",
    };

    expect(isVoicePlaybackBlocking(item, 10, "speech-1")).toBe(true);
    expect(isVoicePlaybackBlocking(item, 10, "speech-2")).toBe(false);
    expect(isVoicePlaybackBlocking(item, 10, undefined)).toBe(false);
  });

  it("keeps the source-event fallback only for legacy voice", () => {
    expect(
      isVoicePlaybackBlocking(
        {
          sourceEventId: 10,
          lastSourceEventId: 12,
          status: "ready",
        },
        10,
        "speech-1",
      ),
    ).toBe(true);
  });

  it("preserves speechId while mapping source coordinates to timeline ids", () => {
    expect(
      mapVoiceCompletionToTimeline(
        events,
        {
          id: "speech-1:complete",
          speechId: "speech-1",
          sourceEventId: 10,
          lastSourceEventId: 12,
        },
        "run-source",
      ),
    ).toEqual({
      id: "speech-1:complete",
      speechId: "speech-1",
      sourceEventId: 91,
      lastSourceEventId: 93,
    });
  });
});
