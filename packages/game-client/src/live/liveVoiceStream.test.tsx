// @vitest-environment jsdom

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
}

describe("live voice stream", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    MockWebSocket.instances = [];
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
    queue = enqueueVoiceMessage(queue, {
      type: "voice_start",
      utterance_id: "voice-1",
      source_event_id: 4,
      speaker_kind: "player",
      speaker_name: "阿青",
      mime_type: "audio/mpeg",
    });
    queue = enqueueVoiceMessage(queue, {
      type: "audio_chunk",
      utterance_id: "voice-1",
      mime_type: "audio/mpeg",
      data: "YWJj",
    });
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
    queue = enqueueVoiceMessage(queue, {
      type: "voice_start",
      utterance_id: "voice-1",
      source_event_id: 4,
      speaker_kind: "player",
      speaker_name: "阿青",
      mime_type: "audio/mpeg",
    });
    queue = enqueueVoiceMessage(queue, {
      type: "audio_chunk",
      utterance_id: "voice-1",
      mime_type: "audio/mpeg",
      data: "YWJj",
    });
    queue = enqueueVoiceMessage(queue, {
      type: "voice_start",
      utterance_id: "voice-1",
      source_event_id: 5,
      speaker_kind: "judge",
      speaker_name: "旁白",
      mime_type: "audio/ogg",
    });

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
    queue = enqueueVoiceMessage(queue, {
      type: "voice_start",
      utterance_id: "voice-1",
      source_event_id: 4,
      speaker_kind: "judge",
      speaker_name: "旁白",
      mime_type: "audio/mpeg",
    });
    queue = enqueueVoiceMessage(queue, {
      type: "voice_error",
      utterance_id: "voice-1",
      message: "TTS failed",
    });

    expect(queue.items).toHaveLength(1);
    expect(queue.items[0].status).toBe("error");
    expect(queue.errors).toEqual(["TTS failed"]);
  });

  it("prunes stale judge narration while retaining player speech", () => {
    let queue = createVoiceQueue();
    queue = enqueueVoiceMessage(queue, {
      type: "voice_start",
      utterance_id: "judge-old",
      source_event_id: 1,
      speaker_kind: "judge",
      speaker_name: "旁白",
      mime_type: "audio/mpeg",
    });
    queue = enqueueVoiceMessage(queue, {
      type: "voice_start",
      utterance_id: "player-old",
      source_event_id: 1,
      speaker_kind: "player",
      speaker_name: "阿青",
      mime_type: "audio/mpeg",
    });

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
      MockWebSocket.instances[0].emit({
        type: "voice_start",
        utterance_id: "voice-1",
        source_event_id: 4,
        speaker_kind: "player",
        speaker_name: "阿青",
        mime_type: "audio/mpeg",
      });
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
      MockWebSocket.instances[0].emit({
        type: "voice_start",
        utterance_id: "voice-1",
        source_event_id: 4,
        speaker_kind: "player",
        speaker_name: "阿青",
        mime_type: "audio/mpeg",
      });
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
      MockWebSocket.instances[0].emit({
        type: "voice_start",
        utterance_id: "voice-1",
        source_event_id: 4,
        speaker_kind: "player",
        speaker_name: "阿青",
        mime_type: "audio/mpeg",
      });
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
      MockWebSocket.instances[0].emit({
        type: "voice_start",
        utterance_id: "voice-1",
        source_event_id: 4,
        speaker_kind: "player",
        speaker_name: "阿青",
        mime_type: "audio/mpeg",
      });
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

  it("does not create browser audio playback side effects yet", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const AudioMock = vi.fn();
    const BlobMock = vi.fn();
    vi.stubGlobal("Audio", AudioMock);
    vi.stubGlobal("Blob", BlobMock);

    renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].emit({
        type: "voice_start",
        utterance_id: "voice-1",
        source_event_id: 4,
        speaker_kind: "player",
        speaker_name: "阿青",
        mime_type: "audio/mpeg",
      });
      MockWebSocket.instances[0].emit({
        type: "audio_chunk",
        utterance_id: "voice-1",
        mime_type: "audio/mpeg",
        data: "YWJj",
      });
      MockWebSocket.instances[0].emit({
        type: "voice_end",
        utterance_id: "voice-1",
        duration_ms: 1000,
      });
    });

    expect(AudioMock).not.toHaveBeenCalled();
    expect(BlobMock).not.toHaveBeenCalled();
  });
});
