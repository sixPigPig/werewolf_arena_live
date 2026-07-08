// @vitest-environment jsdom

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pcmMocks = vi.hoisted(() => ({
  close: vi.fn().mockResolvedValue(undefined),
  createPcmAudioScheduler: vi.fn(),
  resume: vi.fn().mockResolvedValue(undefined),
  schedule: vi.fn().mockResolvedValue({
    duration: 0.01,
    endTime: 0.01,
    startTime: 0,
  }),
  suspend: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("./livePcmPlayer", () => ({
  createPcmAudioScheduler: pcmMocks.createPcmAudioScheduler,
}));

import { usePlaybackVoice } from "./livePlaybackVoice";
import type { PlaybackVoiceUtterance } from "../types";

function resetPcmMocks() {
  pcmMocks.close.mockReset();
  pcmMocks.resume.mockReset();
  pcmMocks.schedule.mockReset();
  pcmMocks.suspend.mockReset();
  pcmMocks.createPcmAudioScheduler.mockReset();
  pcmMocks.close.mockResolvedValue(undefined);
  pcmMocks.resume.mockResolvedValue(undefined);
  pcmMocks.schedule.mockResolvedValue({
    duration: 0.01,
    endTime: 0.01,
    startTime: 0,
  });
  pcmMocks.suspend.mockResolvedValue(undefined);
  pcmMocks.createPcmAudioScheduler.mockReturnValue({
    close: pcmMocks.close,
    resume: pcmMocks.resume,
    schedule: pcmMocks.schedule,
    suspend: pcmMocks.suspend,
  });
}

function stubAudioContext({
  currentTime = 0,
  state = "running",
}: {
  currentTime?: number;
  state?: AudioContextState;
} = {}) {
  const context = {
    close: vi.fn().mockResolvedValue(undefined),
    currentTime,
    resume: vi.fn().mockResolvedValue(undefined),
    state,
  };
  const AudioContextConstructor = vi.fn(function MockAudioContext() {
    return context;
  });

  vi.stubGlobal("AudioContext", AudioContextConstructor);

  return { AudioContextConstructor, context };
}

function voice(overrides: Partial<PlaybackVoiceUtterance> = {}): PlaybackVoiceUtterance {
  return {
    utterance_id: "voice-1",
    source_event_id: 4,
    last_source_event_id: 4,
    speaker_kind: "player",
    speaker_name: "阿青",
    mime_type: "audio/L16",
    audio_format: "pcm",
    sample_rate: 24000,
    duration_ms: 100,
    chunks: [{ chunk_index: 0, data: "YWJj" }],
    ...overrides,
  };
}

describe("playback voice", () => {
  beforeEach(() => {
    resetPcmMocks();
    stubAudioContext();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reports unavailable when enabled with no saved voices", async () => {
    const { result } = renderHook(() =>
      usePlaybackVoice([], { currentEventId: 1, enabled: true, isPaused: false }),
    );

    expect(result.current.connectionState).toBe("unavailable");
    await waitFor(() => {
      expect(result.current.errors.at(-1)).toBe("这局回放没有保存的语音。");
    });
  });

  it("unlocks audio before scheduling saved PCM", async () => {
    const { result } = renderHook(() =>
      usePlaybackVoice([voice()], { currentEventId: 4, enabled: false, isPaused: false }),
    );

    await act(async () => {
      await expect(result.current.unlockAudio()).resolves.toBe(true);
    });

    expect(pcmMocks.resume).toHaveBeenCalled();
  });

  it("schedules saved PCM chunks after reaching the source event", async () => {
    const { rerender } = renderHook(
      ({ currentEventId }) =>
        usePlaybackVoice([voice()], {
          currentEventId,
          enabled: true,
          isPaused: false,
        }),
      { initialProps: { currentEventId: 3 } },
    );

    expect(pcmMocks.schedule).not.toHaveBeenCalled();

    rerender({ currentEventId: 4 });

    await waitFor(() => {
      expect(pcmMocks.schedule).toHaveBeenCalledWith("YWJj", 24000);
    });
  });

  it("suspends and resumes with replay pause state", async () => {
    const { rerender } = renderHook(
      ({ isPaused }) =>
        usePlaybackVoice([voice()], {
          currentEventId: 4,
          enabled: true,
          isPaused,
        }),
      { initialProps: { isPaused: false } },
    );

    await waitFor(() => {
      expect(pcmMocks.schedule).toHaveBeenCalled();
    });

    rerender({ isPaused: true });
    await waitFor(() => {
      expect(pcmMocks.suspend).toHaveBeenCalled();
    });

    rerender({ isPaused: false });
    await waitFor(() => {
      expect(pcmMocks.resume).toHaveBeenCalled();
    });
  });
});
