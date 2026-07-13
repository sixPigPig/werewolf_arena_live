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

import {
  currentSubtitleForPlaybackVoices,
  usePlaybackVoice,
} from "./livePlaybackVoice";
import type { PlaybackVoiceUtterance } from "../types";

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

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
    subtitle_timings: [],
    chunks: [{ chunk_index: 0, data: "YWJj" }],
    ...overrides,
  };
}

function mp3Voice(overrides: Partial<PlaybackVoiceUtterance> = {}): PlaybackVoiceUtterance {
  return voice({
    audio_format: "mp3",
    chunks: [{ chunk_index: 0, data: "YWJj" }],
    mime_type: "audio/mpeg",
    speaker_kind: "judge",
    speaker_name: "法官",
    ...overrides,
  });
}

function stubObjectUrls(objectUrls = ["blob:voice"]) {
  let nextUrlIndex = 0;
  const createdObjects: (Blob | MediaSource)[] = [];
  const createObjectURL = vi.fn((object: Blob | MediaSource) => {
    createdObjects.push(object);
    const objectUrl = objectUrls[nextUrlIndex] ?? `blob:voice-${nextUrlIndex}`;
    nextUrlIndex += 1;
    return objectUrl;
  });
  const revokeObjectURL = vi.fn();

  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: revokeObjectURL,
  });

  return { createObjectURL, createdObjects, revokeObjectURL };
}

function stubAudioElement({
  play = vi.fn().mockResolvedValue(undefined),
  pause = vi.fn(),
}: {
  play?: ReturnType<typeof vi.fn>;
  pause?: ReturnType<typeof vi.fn>;
} = {}) {
  const audioElements: HTMLAudioElement[] = [];
  const createElement = document.createElement.bind(document);

  vi.spyOn(document, "createElement").mockImplementation(
    ((tagName: string, options?: ElementCreationOptions) => {
      const element = createElement(tagName, options);

      if (tagName.toLowerCase() === "audio") {
        Object.defineProperty(element, "play", {
          configurable: true,
          value: play,
        });
        Object.defineProperty(element, "pause", {
          configurable: true,
          value: pause,
        });
        audioElements.push(element as HTMLAudioElement);
      }

      return element;
    }) as typeof document.createElement,
  );

  return { audioElements, pause, play };
}

describe("playback voice", () => {
  beforeEach(() => {
    resetPcmMocks();
    stubAudioContext();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    if (originalCreateObjectURL) {
      Object.defineProperty(URL, "createObjectURL", {
        configurable: true,
        value: originalCreateObjectURL,
      });
    } else {
      Reflect.deleteProperty(URL, "createObjectURL");
    }
    if (originalRevokeObjectURL) {
      Object.defineProperty(URL, "revokeObjectURL", {
        configurable: true,
        value: originalRevokeObjectURL,
      });
    } else {
      Reflect.deleteProperty(URL, "revokeObjectURL");
    }
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

  it("schedules saved coalesced PCM chunks after reaching the last source event", async () => {
    const coalescedVoice = voice({
      last_source_event_id: 6,
      source_event_id: 4,
    });
    const { rerender } = renderHook(
      ({ currentEventId }) =>
        usePlaybackVoice([coalescedVoice], {
          currentEventId,
          enabled: true,
          isPaused: false,
        }),
      { initialProps: { currentEventId: 4 } },
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(pcmMocks.schedule).not.toHaveBeenCalled();

    rerender({ currentEventId: 6 });

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

  it("derives the current subtitle from saved PCM timing", async () => {
    vi.useFakeTimers();
    const { context } = stubAudioContext({ currentTime: 10, state: "running" });
    pcmMocks.schedule.mockResolvedValue({
      duration: 0.82,
      endTime: 10.82,
      startTime: 10,
    });

    const { result } = renderHook(() =>
      usePlaybackVoice(
        [
          voice({
            speaker_name: "1号玩家",
            subtitle_timings: [
              { text: "我", start_ms: 18745, end_ms: 18855 },
              { text: "先发言。", start_ms: 18855, end_ms: 19565 },
            ],
          }),
        ],
        {
          currentEventId: 4,
          enabled: true,
          isPaused: false,
        },
      ),
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(pcmMocks.schedule).toHaveBeenCalledTimes(1);
    expect(result.current.currentSubtitle).toMatchObject({
      activeText: "我",
      completedText: "",
      pendingText: "先发言",
      speakerKind: "player",
      speakerName: "1号玩家",
      text: "我先发言",
    });

    context.currentTime = 10.2;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });

    expect(result.current.currentSubtitle).toMatchObject({
      activeText: "先",
      completedText: "我",
      pendingText: "发言",
      speakerKind: "player",
      speakerName: "1号玩家",
      text: "我先发言",
    });
  });

  it("plays saved non-PCM chunks with an audio element", async () => {
    vi.stubGlobal("AudioContext", undefined);
    const { createObjectURL, createdObjects, revokeObjectURL } =
      stubObjectUrls(["blob:replay-voice"]);
    const { audioElements, play } = stubAudioElement();

    const { result } = renderHook(() =>
      usePlaybackVoice([mp3Voice()], {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
    expect(result.current.connectionState).toBe("open");
    expect(result.current.currentSpeakerName).toBe("法官");
    expect(audioElements).toHaveLength(1);
    expect(audioElements[0].src).toBe("blob:replay-voice");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createdObjects[0] as Blob;
    expect(blob.type).toBe("audio/mpeg");
    await expect(blob.text()).resolves.toBe("abc");

    act(() => {
      audioElements[0].dispatchEvent(new Event("ended"));
    });

    await waitFor(() => expect(result.current.currentItem).toBeNull());
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:replay-voice");
  });

  it("derives replay subtitles from saved timings without requiring audio chunks", () => {
    const subtitle = currentSubtitleForPlaybackVoices({
      currentEventId: 41,
      elapsedMs: 220,
      isPaused: false,
      voices: [
        voice({
          chunks: [],
          last_source_event_id: 41,
          source_event_id: 32,
          speaker_name: "2号玩家",
          subtitle_timings: [
            { text: "我先", start_ms: 18745, end_ms: 18855 },
            { text: "过。", start_ms: 18855, end_ms: 19045 },
          ],
        }),
      ],
    });

    expect(subtitle).toEqual({
      activeText: "",
      completedText: "我先过",
      pageIndex: 0,
      pendingText: "",
      speakerKind: "player",
      speakerName: "2号玩家",
      text: "我先过",
      utteranceId: "voice-1",
    });
  });

  it("matches coalesced player replay subtitles by last source event id", () => {
    const replayVoice = voice({
      last_source_event_id: 41,
      source_event_id: 32,
      speaker_name: "2号玩家",
      subtitle_timings: [{ text: "我先过。", start_ms: 0, end_ms: 420 }],
    });

    expect(
      currentSubtitleForPlaybackVoices({
        currentEventId: 32,
        elapsedMs: 0,
        isPaused: false,
        voices: [replayVoice],
      }),
    ).toBeNull();
    expect(
      currentSubtitleForPlaybackVoices({
        currentEventId: 41,
        elapsedMs: 0,
        isPaused: false,
        voices: [replayVoice],
      }),
    ).toMatchObject({
      speakerKind: "player",
      speakerName: "2号玩家",
      text: "我先过",
    });
  });
});
