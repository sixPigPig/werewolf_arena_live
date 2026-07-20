import { describe, expect, it } from "vitest";

import {
  createSpeechPlaybackShadowState,
  nextSchedulableSpeechSegment,
  speechPlaybackSessionReducer,
  type SpeechPlaybackShadowAction,
  type SpeechPlaybackShadowState,
} from "./speechPlaybackSession";

function reduce(
  actions: SpeechPlaybackShadowAction[],
  initial = createSpeechPlaybackShadowState(),
) {
  return actions.reduce<SpeechPlaybackShadowState>(
    speechPlaybackSessionReducer,
    initial,
  );
}

function opened(): SpeechPlaybackShadowAction {
  return {
    type: "speech_opened",
    speechId: "speech-1",
    sourceEventId: 10,
    speaker: "1号玩家",
    audience: "player_public",
  };
}

function segment(
  index: number,
): Extract<SpeechPlaybackShadowAction, { type: "segment_received" }> {
  return {
    type: "segment_received",
    speechId: "speech-1",
    utteranceId: `voice-${index}`,
    segmentId: `segment-${index}`,
    segmentIndex: index,
    sourceEventId: 10 + index,
    lastSourceEventId: 10 + index,
    speaker: "1号玩家",
    audience: "player_public",
  };
}

function ready(index: number): SpeechPlaybackShadowAction {
  return {
    type: "segment_ready",
    utteranceId: `voice-${index}`,
    durationMs: 1000 + index * 100,
  };
}

function started(index: number): SpeechPlaybackShadowAction {
  return { type: "segment_started", utteranceId: `voice-${index}` };
}

function finished(index: number): SpeechPlaybackShadowAction {
  return {
    type: "segment_finished",
    utteranceId: `voice-${index}`,
    status: "completed",
    playedMs: 1000 + index * 100,
  };
}

function sealed(
  finalSegmentIndex: number,
): Extract<SpeechPlaybackShadowAction, { type: "speech_sealed" }> {
  return {
    type: "speech_sealed",
    speechId: "speech-1",
    finalSegmentIndex,
    segmentCount: finalSegmentIndex + 1,
    speechStatus: "spoken",
    lastSourceEventId: 20,
  };
}

describe("speechPlaybackSessionReducer", () => {
  it("collects out-of-order segments but schedules only the contiguous prefix", () => {
    let state = reduce([opened(), segment(2)]);
    expect(state.sessions["speech-1"].highestContiguousIndex).toBe(-1);

    state = reduce([segment(0)], state);
    expect(state.sessions["speech-1"].highestContiguousIndex).toBe(0);

    state = reduce([segment(1), ready(0), ready(1), ready(2)], state);
    const session = state.sessions["speech-1"];
    expect(session.highestContiguousIndex).toBe(2);
    expect(nextSchedulableSpeechSegment(session)?.segmentIndex).toBe(0);

    state = reduce([started(0), finished(0)], state);
    expect(
      nextSchedulableSpeechSegment(state.sessions["speech-1"])?.segmentIndex,
    ).toBe(1);
  });

  it("does not complete on an intermediate segment and completes exactly once", () => {
    let state = reduce([
      opened(),
      segment(0),
      segment(1),
      ready(0),
      ready(1),
      sealed(1),
      started(0),
      finished(0),
    ]);
    expect(state.sessions["speech-1"]).toMatchObject({
      state: "sealed",
      completionEmitted: false,
    });

    state = reduce([started(1), finished(1)], state);
    const completed = state;
    expect(completed.sessions["speech-1"]).toMatchObject({
      state: "completed",
      completionEmitted: true,
      playedMs: 2100,
    });

    expect(reduce([finished(1)], completed)).toBe(completed);
  });

  it("completes when a late seal arrives after the final audio", () => {
    const state = reduce([
      opened(),
      segment(0),
      ready(0),
      started(0),
      finished(0),
      sealed(0),
    ]);

    expect(state.sessions["speech-1"]).toMatchObject({
      state: "completed",
      finalSegmentIndex: 0,
      completionEmitted: true,
    });
  });

  it("waits for a missing segment even when the seal and later segment exist", () => {
    let state = reduce([
      opened(),
      segment(0),
      segment(2),
      ready(0),
      ready(2),
      sealed(2),
      started(0),
      finished(0),
    ]);

    expect(state.sessions["speech-1"]).toMatchObject({
      state: "sealed",
      highestContiguousIndex: 0,
      completionEmitted: false,
    });
    expect(nextSchedulableSpeechSegment(state.sessions["speech-1"])).toBeNull();

    state = reduce([segment(1), ready(1)], state);
    expect(
      nextSchedulableSpeechSegment(state.sessions["speech-1"])?.segmentIndex,
    ).toBe(1);
  });

  it("de-duplicates identical segments and fails closed on conflicting ones", () => {
    const original = reduce([opened(), segment(0)]);
    expect(reduce([segment(0)], original)).toBe(original);

    const conflicting = reduce(
      [
        {
          ...segment(0),
          utteranceId: "voice-conflict",
          segmentId: "segment-conflict",
        },
      ],
      original,
    );
    expect(conflicting.sessions["speech-1"]).toMatchObject({
      state: "failed",
      completionEmitted: true,
    });
    expect(conflicting.sessions["speech-1"].contractViolations).toContain(
      "segment_identity_conflict",
    );
  });

  it("accepts an idempotent seal and rejects a conflicting second seal", () => {
    const original = reduce([opened(), segment(0), sealed(0)]);
    expect(reduce([sealed(0)], original)).toBe(original);

    const conflicting = reduce(
      [
        {
          ...sealed(1),
          segmentCount: 2,
        },
      ],
      original,
    );
    expect(conflicting.sessions["speech-1"].state).toBe("failed");
    expect(conflicting.sessions["speech-1"].contractViolations).toContain(
      "speech_seal_conflict",
    );
  });

  it("moves any non-terminal session to one interrupted terminal state", () => {
    const interrupted = reduce([
      opened(),
      segment(0),
      {
        type: "speech_preempted",
        speechId: "speech-1",
        cutAfterSegmentIndex: 0,
        reason: "self_explosion",
      },
    ]);
    expect(interrupted.sessions["speech-1"]).toMatchObject({
      state: "interrupted",
      completionEmitted: true,
      preemptReason: "self_explosion",
    });

    expect(
      reduce(
        [
          {
            type: "speech_preempted",
            speechId: "speech-1",
            reason: "duplicate",
          },
        ],
        interrupted,
      ),
    ).toBe(interrupted);
  });
});
