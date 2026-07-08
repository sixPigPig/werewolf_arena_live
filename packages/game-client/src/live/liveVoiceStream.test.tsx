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
  createVoiceQueue,
  enqueueVoiceMessage,
  pruneStaleVoiceQueue,
  resolveVoiceStreamUrl,
  useLiveVoiceStream,
  type LiveVoiceMessage,
} from "./liveVoiceStream";

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn();
  url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  emit(message: LiveVoiceMessage) {
    this.emitRaw(JSON.stringify(message));
  }

  emitRaw(data: string) {
    this.onmessage?.({ data } as MessageEvent);
  }

  closeFromServer() {
    this.onclose?.();
  }
}

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
  resume = vi.fn().mockResolvedValue(undefined),
  state = "suspended",
}: {
  currentTime?: number;
  resume?: ReturnType<typeof vi.fn>;
  state?: AudioContextState;
} = {}) {
  const context = {
    close: vi.fn().mockResolvedValue(undefined),
    currentTime,
    resume,
    state,
  };
  const AudioContextConstructor = vi.fn(function MockAudioContext() {
    return context;
  });

  vi.stubGlobal("AudioContext", AudioContextConstructor);

  return { AudioContextConstructor, context, resume };
}

function voiceStartMessage(
  overrides: Partial<Extract<LiveVoiceMessage, { type: "voice_start" }>> = {},
): Extract<LiveVoiceMessage, { type: "voice_start" }> {
  return {
    type: "voice_start",
    utterance_id: "voice-1",
    source_event_id: 4,
    speaker_kind: "player",
    speaker_name: "阿青",
    mime_type: "audio/mpeg",
    audio_format: "mp3",
    sample_rate: 24000,
    ...overrides,
  };
}

function audioChunkMessage(
  overrides: Partial<Extract<LiveVoiceMessage, { type: "audio_chunk" }>> = {},
): Extract<LiveVoiceMessage, { type: "audio_chunk" }> {
  return {
    type: "audio_chunk",
    utterance_id: "voice-1",
    mime_type: "audio/mpeg",
    chunk_index: 0,
    audio_format: "mp3",
    sample_rate: 24000,
    data: "YWJj",
    ...overrides,
  };
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

function emitReadyUtterance(
  socket: MockWebSocket,
  utteranceId: string,
  sourceEventId: number,
  {
    audioFormat = "mp3",
    data = "YWJj",
    mimeType = "audio/mpeg",
    sampleRate = 24000,
  }: {
    audioFormat?: string;
    data?: string;
    mimeType?: string;
    sampleRate?: number;
  } = {},
) {
  socket.emit({
    type: "voice_start",
    utterance_id: utteranceId,
    source_event_id: sourceEventId,
    speaker_kind: "player",
    speaker_name: "阿青",
    mime_type: mimeType,
    audio_format: audioFormat,
    sample_rate: sampleRate,
  });
  socket.emit({
    type: "audio_chunk",
    utterance_id: utteranceId,
    mime_type: mimeType,
    chunk_index: 0,
    audio_format: audioFormat,
    sample_rate: sampleRate,
    data,
  });
  socket.emit({
    type: "voice_end",
    utterance_id: utteranceId,
    duration_ms: 1000,
  });
}

describe("live voice stream", () => {
  beforeEach(() => {
    resetPcmMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    MockWebSocket.instances = [];
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

  it("builds a websocket url from api base url", () => {
    expect(resolveVoiceStreamUrl("run-1", "http://localhost:8000")).toBe(
      "ws://localhost:8000/api/v1/games/runs/run-1/voice-stream",
    );
    expect(resolveVoiceStreamUrl("run-1", "https://example.com")).toBe(
      "wss://example.com/api/v1/games/runs/run-1/voice-stream",
    );
  });

  it("falls back to the browser origin when api base url is empty", () => {
    const expectedOrigin = window.location.origin.replace(/^http/, "ws");

    expect(resolveVoiceStreamUrl("run-1", "")).toBe(
      `${expectedOrigin}/api/v1/games/runs/run-1/voice-stream`,
    );
  });

  it("preserves relative api base prefixes without throwing", () => {
    const expectedOrigin = window.location.origin.replace(/^http/, "ws");

    expect(resolveVoiceStreamUrl("run/slash id", "/api")).toBe(
      `${expectedOrigin}/api/api/v1/games/runs/run%2Fslash%20id/voice-stream`,
    );
    expect(resolveVoiceStreamUrl("run-1", "proxy")).toBe(
      `${expectedOrigin}/proxy/api/v1/games/runs/run-1/voice-stream`,
    );
  });

  it("preserves absolute api base path prefixes", () => {
    expect(resolveVoiceStreamUrl("run-1", "https://example.com/proxy")).toBe(
      "wss://example.com/proxy/api/v1/games/runs/run-1/voice-stream",
    );
  });

  it("groups chunks by utterance and marks completed audio", () => {
    let queue = createVoiceQueue();
    queue = enqueueVoiceMessage(queue, voiceStartMessage());
    queue = enqueueVoiceMessage(queue, audioChunkMessage());
    queue = enqueueVoiceMessage(queue, {
      type: "voice_end",
      utterance_id: "voice-1",
      duration_ms: 1000,
    });

    expect(queue.items).toHaveLength(1);
    expect(queue.items[0]).toMatchObject({
      utteranceId: "voice-1",
      sourceEventId: 4,
      speakerName: "阿青",
      status: "ready",
    });
    expect(queue.items[0].chunks).toEqual(["YWJj"]);
  });

  it("de-dupes duplicate starts by utterance id", () => {
    let queue = createVoiceQueue();
    queue = enqueueVoiceMessage(queue, voiceStartMessage());
    queue = enqueueVoiceMessage(queue, audioChunkMessage());
    queue = enqueueVoiceMessage(
      queue,
      voiceStartMessage({
        source_event_id: 5,
        speaker_kind: "judge",
        speaker_name: "旁白",
        mime_type: "audio/ogg",
      }),
    );

    expect(queue.items).toHaveLength(1);
    expect(queue.items[0]).toMatchObject({
      utteranceId: "voice-1",
      sourceEventId: 5,
      speakerKind: "judge",
      speakerName: "旁白",
      mimeType: "audio/ogg",
      status: "receiving",
    });
    expect(queue.items[0].chunks).toEqual(["YWJj"]);
  });

  it("records voice errors without changing queued audio", () => {
    let queue = createVoiceQueue();
    queue = enqueueVoiceMessage(
      queue,
      voiceStartMessage({
        speaker_kind: "judge",
        speaker_name: "旁白",
      }),
    );
    queue = enqueueVoiceMessage(queue, {
      type: "voice_error",
      utterance_id: "voice-1",
      message: "TTS failed",
    });

    expect(queue.items).toHaveLength(1);
    expect(queue.items[0].status).toBe("error");
    expect(queue.errors).toEqual(["TTS failed"]);
  });

  it("ignores duplicate start messages for played utterances", () => {
    const queue: ReturnType<typeof createVoiceQueue> = {
      ...createVoiceQueue(),
      items: [
        {
          utteranceId: "voice-1",
          sourceEventId: 4,
          speakerKind: "player" as const,
          speakerName: "阿青",
          mimeType: "audio/mpeg",
          audioFormat: "mp3",
          sampleRate: 24000,
          chunks: ["YWJj"],
          chunkMetadata: [
            {
              audioFormat: "mp3",
              chunkIndex: 0,
              data: "YWJj",
              sampleRate: 24000,
            },
          ],
          isEnded: true,
          status: "played" as const,
        },
      ],
    };

    const updated = enqueueVoiceMessage(queue, {
      ...voiceStartMessage(),
      source_event_id: 8,
      speaker_kind: "judge",
      speaker_name: "旁白",
      mime_type: "audio/ogg",
    });

    expect(updated.items).toEqual(queue.items);
  });

  it("ignores late chunks and terminal messages for played utterances", () => {
    let queue: ReturnType<typeof createVoiceQueue> = {
      ...createVoiceQueue(),
      items: [
        {
          utteranceId: "voice-1",
          sourceEventId: 4,
          speakerKind: "player" as const,
          speakerName: "阿青",
          mimeType: "audio/mpeg",
          audioFormat: "mp3",
          sampleRate: 24000,
          chunks: ["YWJj"],
          chunkMetadata: [
            {
              audioFormat: "mp3",
              chunkIndex: 0,
              data: "YWJj",
              sampleRate: 24000,
            },
          ],
          isEnded: true,
          status: "played" as const,
        },
      ],
    };

    queue = enqueueVoiceMessage(queue, audioChunkMessage({ data: "ZA==" }));
    queue = enqueueVoiceMessage(queue, {
      type: "voice_end",
      utterance_id: "voice-1",
      duration_ms: 1000,
    });

    expect(queue.items[0]).toMatchObject({
      chunks: ["YWJj"],
      status: "played",
    });
  });

  it("prunes stale judge narration while retaining player speech", () => {
    let queue = createVoiceQueue();
    queue = enqueueVoiceMessage(
      queue,
      voiceStartMessage({
        utterance_id: "judge-old",
        source_event_id: 1,
        speaker_kind: "judge",
        speaker_name: "旁白",
      }),
    );
    queue = enqueueVoiceMessage(
      queue,
      voiceStartMessage({
        utterance_id: "player-old",
        source_event_id: 1,
      }),
    );

    const pruned = pruneStaleVoiceQueue(queue, 12);

    expect(pruned.items.map((item) => item.utteranceId)).toEqual([
      "player-old",
    ]);
  });

  it("does not connect until enabled", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 1,
        enabled: false,
        isPaused: false,
      }),
    );

    expect(MockWebSocket.instances).toHaveLength(0);
    expect(result.current.connectionState).toBe("idle");
  });

  it("does not connect without a run id", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream(undefined, {
        currentEventId: 1,
        enabled: true,
        isPaused: false,
      }),
    );

    expect(MockWebSocket.instances).toHaveLength(0);
    expect(result.current.connectionState).toBe("idle");
  });

  it("connects when enabled and records the current speaker after a start message", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      MockWebSocket.instances[0].emit(voiceStartMessage());
    });

    expect(result.current.connectionState).toBe("open");
    expect(result.current.currentSpeakerName).toBe("阿青");
    expect(result.current.currentItem?.utteranceId).toBe("voice-1");
  });

  it("hides the current speaker name while paused without clearing the queue", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: true,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].emit(voiceStartMessage());
    });

    expect(result.current.currentSpeakerName).toBeNull();
    expect(result.current.currentItem?.speakerName).toBe("阿青");
  });

  it("resets queued speakers and errors when switching runs", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { rerender, result } = renderHook(
      ({ runId }: { runId: string }) =>
        useLiveVoiceStream(runId, {
          currentEventId: 4,
          enabled: true,
          isPaused: false,
        }),
      { initialProps: { runId: "run-1" } },
    );

    act(() => {
      MockWebSocket.instances[0].emit(voiceStartMessage());
      MockWebSocket.instances[0].emitRaw("{not-json");
    });

    await waitFor(() => expect(result.current.errors).toHaveLength(1));
    expect(result.current.currentSpeakerName).toBe("阿青");

    rerender({ runId: "run-2" });

    await waitFor(() => expect(result.current.currentItem).toBeNull());
    expect(result.current.currentSpeakerName).toBeNull();
    expect(result.current.errors).toEqual([]);
    expect(MockWebSocket.instances[0].close).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances[1].url).toContain(
      "/api/v1/games/runs/run-2/voice-stream",
    );
  });

  it("resets queued speakers and errors when disabled", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { rerender, result } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useLiveVoiceStream("run-1", {
          currentEventId: 4,
          enabled,
          isPaused: false,
        }),
      { initialProps: { enabled: true } },
    );

    act(() => {
      MockWebSocket.instances[0].emit(voiceStartMessage());
      MockWebSocket.instances[0].emitRaw("{not-json");
    });

    await waitFor(() => expect(result.current.errors).toHaveLength(1));

    rerender({ enabled: false });

    await waitFor(() => expect(result.current.currentItem).toBeNull());
    expect(result.current.connectionState).toBe("idle");
    expect(result.current.currentSpeakerName).toBeNull();
    expect(result.current.errors).toEqual([]);
    expect(MockWebSocket.instances[0].close).toHaveBeenCalledTimes(1);
  });

  it("reports unavailable when the browser has no websocket support", async () => {
    vi.stubGlobal("WebSocket", undefined);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 1,
        enabled: true,
        isPaused: false,
      }),
    );

    await waitFor(() =>
      expect(result.current.connectionState).toBe("unavailable"),
    );
    expect(result.current.errors).toEqual([
      "Live voice streaming is unavailable in this browser.",
    ]);
  });

  it("reports malformed websocket messages without throwing", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 1,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      MockWebSocket.instances[0].emitRaw("{not-json");
    });

    await waitFor(() => expect(result.current.connectionState).toBe("error"));
    expect(result.current.errors).toEqual(["Malformed voice stream message."]);
  });

  it("rejects voice start messages missing audio metadata", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 1,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].emitRaw(
        JSON.stringify({
          type: "voice_start",
          utterance_id: "voice-1",
          source_event_id: 1,
          speaker_kind: "player",
          speaker_name: "阿青",
          mime_type: "audio/mpeg",
        }),
      );
    });

    await waitFor(() => expect(result.current.connectionState).toBe("error"));
    expect(result.current.errors).toEqual(["Malformed voice stream message."]);
  });

  it("rejects audio chunks missing chunk metadata", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 1,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].emit(voiceStartMessage({ source_event_id: 1 }));
      MockWebSocket.instances[0].emitRaw(
        JSON.stringify({
          type: "audio_chunk",
          utterance_id: "voice-1",
          mime_type: "audio/mpeg",
          data: "YWJj",
        }),
      );
    });

    await waitFor(() => expect(result.current.connectionState).toBe("error"));
    expect(result.current.errors).toEqual(["Malformed voice stream message."]);
  });

  it("unlocks audio with an AudioContext while the stream is disabled", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { AudioContextConstructor, resume } = stubAudioContext();

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 1,
        enabled: false,
        isPaused: false,
      }),
    );

    let unlocked = false;
    await act(async () => {
      unlocked = await result.current.unlockAudio();
    });

    expect(unlocked).toBe(true);
    expect(MockWebSocket.instances).toHaveLength(0);
    expect(AudioContextConstructor).toHaveBeenCalledTimes(1);
    expect(resume).toHaveBeenCalledTimes(1);
    expect(pcmMocks.createPcmAudioScheduler).toHaveBeenCalledTimes(1);
    expect(pcmMocks.resume).toHaveBeenCalledTimes(1);
  });

  it("records a Chinese playback error when audio unlock is unsupported", async () => {
    vi.stubGlobal("AudioContext", undefined);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 1,
        enabled: false,
        isPaused: false,
      }),
    );

    let unlocked = true;
    await act(async () => {
      unlocked = await result.current.unlockAudio();
    });

    expect(unlocked).toBe(false);
    expect(result.current.errors).toEqual(["当前浏览器不支持语音播放。"]);
  });

  it("closes the socket on cleanup", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { unmount } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 1,
        enabled: true,
        isPaused: false,
      }),
    );
    const socket = MockWebSocket.instances[0];

    unmount();

    expect(socket.close).toHaveBeenCalledTimes(1);
  });

  it("creates and plays an audio element for a ready utterance", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { createObjectURL, createdObjects } = stubObjectUrls(["blob:voice-1"]);
    const { audioElements, play } = stubAudioElement();

    renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4);
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
    expect(audioElements).toHaveLength(1);
    expect(audioElements[0].src).toBe("blob:voice-1");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createdObjects[0] as Blob;
    expect(blob.type).toBe("audio/mpeg");
    await expect(blob.text()).resolves.toBe("abc");
  });

  it("schedules PCM chunks as they arrive before voice end", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    stubAudioContext({ state: "running" });
    const { createObjectURL } = stubObjectUrls(["blob:voice-1"]);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      MockWebSocket.instances[0].emit(
        voiceStartMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
        }),
      );
      MockWebSocket.instances[0].emit(
        audioChunkMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
          data: "AAAAAA==",
        }),
      );
    });

    await waitFor(() =>
      expect(pcmMocks.schedule).toHaveBeenCalledWith("AAAAAA==", 24000),
    );
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(result.current.currentItem).toMatchObject({
      status: "playing",
      utteranceId: "voice-1",
    });
  });

  it("waits to schedule PCM chunks until the director reaches the source event", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    stubAudioContext({ state: "running" });

    const { rerender } = renderHook(
      ({ currentEventId }: { currentEventId: number }) =>
        useLiveVoiceStream("run-1", {
          currentEventId,
          enabled: true,
          isPaused: false,
        }),
      { initialProps: { currentEventId: 4 } },
    );

    act(() => {
      MockWebSocket.instances[0].emit(
        voiceStartMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
          source_event_id: 10,
        }),
      );
      MockWebSocket.instances[0].emit(
        audioChunkMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
          data: "AAAAAA==",
        }),
      );
    });

    expect(pcmMocks.schedule).not.toHaveBeenCalled();

    rerender({ currentEventId: 10 });

    await waitFor(() => expect(pcmMocks.schedule).toHaveBeenCalledTimes(1));
    expect(pcmMocks.schedule).toHaveBeenCalledWith("AAAAAA==", 24000);
  });

  it("suspends and resumes the PCM scheduler when playback is paused", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    stubAudioContext({ state: "running" });

    const { rerender } = renderHook(
      ({ isPaused }: { isPaused: boolean }) =>
        useLiveVoiceStream("run-1", {
          currentEventId: 4,
          enabled: true,
          isPaused,
        }),
      { initialProps: { isPaused: false } },
    );

    act(() => {
      MockWebSocket.instances[0].emit(
        voiceStartMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
        }),
      );
      MockWebSocket.instances[0].emit(
        audioChunkMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
          data: "AAAAAA==",
        }),
      );
    });

    await waitFor(() => expect(pcmMocks.schedule).toHaveBeenCalledTimes(1));
    pcmMocks.resume.mockClear();

    rerender({ isPaused: true });

    await waitFor(() => expect(pcmMocks.suspend).toHaveBeenCalledTimes(1));

    rerender({ isPaused: false });

    await waitFor(() => expect(pcmMocks.resume).toHaveBeenCalledTimes(1));
  });

  it("keeps PCM utterances active after voice end until the audio clock drains", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { context } = stubAudioContext({ currentTime: 0, state: "running" });
    pcmMocks.schedule.mockResolvedValue({
      duration: 0.05,
      endTime: 0.05,
      startTime: 0,
    });

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].emit(
        voiceStartMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
        }),
      );
      MockWebSocket.instances[0].emit(
        audioChunkMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
          data: "AAAAAA==",
        }),
      );
      MockWebSocket.instances[0].emit({
        type: "voice_end",
        utterance_id: "voice-1",
        duration_ms: 50,
      });
    });

    await vi.waitFor(() => expect(pcmMocks.schedule).toHaveBeenCalledTimes(1));
    expect(result.current.currentItem).toMatchObject({
      status: "playing",
      utteranceId: "voice-1",
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    expect(result.current.currentItem).toMatchObject({
      status: "playing",
      utteranceId: "voice-1",
    });

    context.currentTime = 0.05;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(25);
    });

    await vi.waitFor(() => expect(result.current.currentItem).toBeNull());
  });

  it("does not consume a paused PCM utterance until resume and audio clock drain", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { context } = stubAudioContext({ currentTime: 0, state: "running" });
    pcmMocks.schedule.mockResolvedValue({
      duration: 0.05,
      endTime: 0.05,
      startTime: 0,
    });

    const { rerender, result } = renderHook(
      ({ isPaused }: { isPaused: boolean }) =>
        useLiveVoiceStream("run-1", {
          currentEventId: 4,
          enabled: true,
          isPaused,
        }),
      { initialProps: { isPaused: false } },
    );

    act(() => {
      MockWebSocket.instances[0].emit(
        voiceStartMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
        }),
      );
      MockWebSocket.instances[0].emit(
        audioChunkMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
          data: "AAAAAA==",
        }),
      );
      MockWebSocket.instances[0].emit({
        type: "voice_end",
        utterance_id: "voice-1",
        duration_ms: 50,
      });
    });

    await vi.waitFor(() => expect(pcmMocks.schedule).toHaveBeenCalledTimes(1));

    rerender({ isPaused: true });
    await vi.waitFor(() => expect(pcmMocks.suspend).toHaveBeenCalledTimes(1));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(result.current.currentItem).toMatchObject({
      status: "playing",
      utteranceId: "voice-1",
    });

    context.currentTime = 0.05;
    rerender({ isPaused: false });
    await vi.waitFor(() => expect(pcmMocks.resume).toHaveBeenCalled());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(25);
    });

    await vi.waitFor(() => expect(result.current.currentItem).toBeNull());
  });

  it("re-arms PCM completion after a suspended audio context resumes", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { context } = stubAudioContext({ currentTime: 0, state: "running" });
    pcmMocks.schedule.mockResolvedValue({
      duration: 0.05,
      endTime: 0.05,
      startTime: 0,
    });

    const { rerender, result } = renderHook(
      ({ isPaused }: { isPaused: boolean }) =>
        useLiveVoiceStream("run-1", {
          currentEventId: 4,
          enabled: true,
          isPaused,
        }),
      { initialProps: { isPaused: false } },
    );

    act(() => {
      MockWebSocket.instances[0].emit(
        voiceStartMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
        }),
      );
      MockWebSocket.instances[0].emit(
        audioChunkMessage({
          audio_format: "pcm",
          mime_type: "audio/L16",
          sample_rate: 24000,
          data: "AAAAAA==",
        }),
      );
    });

    await vi.waitFor(() => expect(pcmMocks.schedule).toHaveBeenCalledTimes(1));

    context.state = "suspended";
    rerender({ isPaused: true });
    await vi.waitFor(() => expect(pcmMocks.suspend).toHaveBeenCalledTimes(1));

    act(() => {
      MockWebSocket.instances[0].emit({
        type: "voice_end",
        utterance_id: "voice-1",
        duration_ms: 50,
      });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(result.current.currentItem).toMatchObject({
      status: "playing",
      utteranceId: "voice-1",
    });

    pcmMocks.resume.mockImplementation(async () => {
      context.state = "running";
    });
    context.currentTime = 0.05;
    rerender({ isPaused: false });

    await vi.waitFor(() => expect(pcmMocks.resume).toHaveBeenCalled());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(25);
    });

    await vi.waitFor(() => expect(result.current.currentItem).toBeNull());
  });

  it("pauses audio without revoking the object URL when paused", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { revokeObjectURL } = stubObjectUrls(["blob:voice-1"]);
    const { pause, play } = stubAudioElement();

    const { rerender, unmount } = renderHook(
      ({ isPaused }: { isPaused: boolean }) =>
        useLiveVoiceStream("run-1", {
          currentEventId: 4,
          enabled: true,
          isPaused,
        }),
      { initialProps: { isPaused: false } },
    );

    act(() => {
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4);
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));

    rerender({ isPaused: true });

    await waitFor(() => expect(pause).toHaveBeenCalledTimes(1));
    expect(revokeObjectURL).not.toHaveBeenCalled();

    unmount();

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:voice-1");
  });

  it("resumes the paused utterance after unpausing", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { revokeObjectURL } = stubObjectUrls(["blob:voice-1"]);
    const { pause, play } = stubAudioElement();

    const { rerender } = renderHook(
      ({ isPaused }: { isPaused: boolean }) =>
        useLiveVoiceStream("run-1", {
          currentEventId: 4,
          enabled: true,
          isPaused,
        }),
      { initialProps: { isPaused: false } },
    );

    act(() => {
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4);
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));

    rerender({ isPaused: true });

    await waitFor(() => expect(pause).toHaveBeenCalledTimes(1));
    expect(revokeObjectURL).not.toHaveBeenCalled();

    rerender({ isPaused: false });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
  });

  it("plays the second ready utterance after the first audio ends", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { createObjectURL, revokeObjectURL } = stubObjectUrls([
      "blob:voice-1",
      "blob:voice-2",
    ]);
    const { audioElements, play } = stubAudioElement();

    renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 5,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4);
      emitReadyUtterance(MockWebSocket.instances[0], "voice-2", 5);
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));

    act(() => {
      audioElements[0].dispatchEvent(new Event("ended"));
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(audioElements).toHaveLength(2);
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(audioElements[1].src).toBe("blob:voice-2");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:voice-1");
  });

  it("does not play ready audio before the director reaches the source event", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    stubObjectUrls(["blob:voice-1"]);
    const { play } = stubAudioElement();

    const { rerender } = renderHook(
      ({ currentEventId }: { currentEventId: number }) =>
        useLiveVoiceStream("run-1", {
          currentEventId,
          enabled: true,
          isPaused: false,
        }),
      { initialProps: { currentEventId: 4 } },
    );

    act(() => {
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 10);
    });

    expect(play).not.toHaveBeenCalled();

    rerender({ currentEventId: 10 });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
  });

  it("keeps active playback when the director seeks before the source event", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { revokeObjectURL } = stubObjectUrls(["blob:voice-1"]);
    const { pause, play } = stubAudioElement();

    const { rerender, result } = renderHook(
      ({ currentEventId }: { currentEventId: number }) =>
        useLiveVoiceStream("run-1", {
          currentEventId,
          enabled: true,
          isPaused: false,
        }),
      { initialProps: { currentEventId: 10 } },
    );

    act(() => {
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 10);
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));

    rerender({ currentEventId: 4 });

    expect(result.current.currentItem).toMatchObject({
      status: "playing",
      utteranceId: "voice-1",
    });
    expect(pause).not.toHaveBeenCalled();
    expect(revokeObjectURL).not.toHaveBeenCalled();

    rerender({ currentEventId: 10 });

    expect(play).toHaveBeenCalledTimes(1);
  });

  it("pauses and resumes the current audio without consuming it", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    stubObjectUrls(["blob:voice-1"]);
    const { pause, play } = stubAudioElement();

    const { rerender, result } = renderHook(
      ({ isPaused }: { isPaused: boolean }) =>
        useLiveVoiceStream("run-1", {
          currentEventId: 4,
          enabled: true,
          isPaused,
        }),
      { initialProps: { isPaused: false } },
    );

    act(() => {
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4);
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));

    rerender({ isPaused: true });

    await waitFor(() => expect(pause).toHaveBeenCalledTimes(1));
    expect(result.current.currentItem?.status).toBe("playing");

    rerender({ isPaused: false });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(result.current.currentItem?.status).toBe("playing");
  });

  it("retries once after an unexpected websocket close", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      MockWebSocket.instances[0].closeFromServer();
    });

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(2));

    act(() => {
      MockWebSocket.instances[1].onopen?.();
    });

    expect(result.current.connectionState).toBe("open");

    act(() => {
      MockWebSocket.instances[1].closeFromServer();
    });

    await waitFor(() => expect(result.current.connectionState).toBe("closed"));
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("retries once after a websocket error followed by close", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      MockWebSocket.instances[0].onerror?.();
      MockWebSocket.instances[0].closeFromServer();
    });

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(2));
    expect(result.current.errors).toEqual([]);

    act(() => {
      MockWebSocket.instances[1].onopen?.();
    });

    expect(result.current.connectionState).toBe("open");
  });

  it("records an error and advances without changing socket state when audio playback is rejected", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    stubObjectUrls(["blob:voice-1", "blob:voice-2"]);
    const play = vi
      .fn()
      .mockRejectedValueOnce(new Error("autoplay blocked"))
      .mockResolvedValue(undefined);
    stubAudioElement({ play });

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 5,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4);
      emitReadyUtterance(MockWebSocket.instances[0], "voice-2", 5);
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
    expect(result.current.connectionState).toBe("open");
    expect(result.current.errors).toEqual(["Unable to play live voice audio."]);
  });

  it("records an error and advances when audio base64 is invalid", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    stubObjectUrls(["blob:voice-2"]);
    const { play } = stubAudioElement();

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 5,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4, {
        data: "not valid base64!",
      });
      emitReadyUtterance(MockWebSocket.instances[0], "voice-2", 5);
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
    expect(result.current.connectionState).toBe("open");
    expect(result.current.errors).toEqual(["Unable to play live voice audio."]);
  });

  it("records an error and advances when object URLs are unavailable", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: undefined,
    });
    const { play } = stubAudioElement();

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4);
    });

    await waitFor(() =>
      expect(result.current.errors).toEqual([
        "Unable to play live voice audio.",
      ]),
    );
    expect(result.current.connectionState).toBe("open");
    expect(result.current.currentItem).toBeNull();
    expect(play).not.toHaveBeenCalled();
  });

  it("revokes the object URL when audio element creation fails", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const { revokeObjectURL } = stubObjectUrls(["blob:voice-1"]);
    const createElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(
      ((tagName: string, options?: ElementCreationOptions) => {
        if (tagName.toLowerCase() === "audio") {
          throw new Error("audio unavailable");
        }
        return createElement(tagName, options);
      }) as typeof document.createElement,
    );

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4);
    });

    await waitFor(() =>
      expect(result.current.errors).toEqual([
        "Unable to play live voice audio.",
      ]),
    );
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:voice-1");
    expect(result.current.currentItem).toBeNull();
  });

  it("removes consumed audio from the active queue", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    stubObjectUrls(["blob:voice-1"]);
    const { audioElements, play } = stubAudioElement();

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      emitReadyUtterance(MockWebSocket.instances[0], "voice-1", 4);
    });

    await waitFor(() => expect(play).toHaveBeenCalledTimes(1));

    act(() => {
      audioElements[0].dispatchEvent(new Event("ended"));
    });

    await waitFor(() => expect(result.current.currentItem).toBeNull());
  });
});
