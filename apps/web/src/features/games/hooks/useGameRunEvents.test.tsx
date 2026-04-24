import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useGameRunEvents } from "./useGameRunEvents";

class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  listeners = new Map<string, (event: MessageEvent) => void>();
  url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(type, listener);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, payload: object) {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) });
    this.listeners.get(type)?.(event);
    this.onmessage?.(event);
  }
}

describe("useGameRunEvents", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    MockEventSource.instances = [];
  });

  it("subscribes to run events and dedupes by id", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));
    const source = MockEventSource.instances[0];
    source.onopen?.();
    source.emit("game_started", {
      id: 1,
      type: "game_started",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:00Z",
      round: null,
      phase: null,
      actor: null,
      action: null,
      payload: { players: [] },
    });
    source.emit("game_started", {
      id: 1,
      type: "game_started",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:00Z",
      round: null,
      phase: null,
      actor: null,
      action: null,
      payload: { players: [] },
    });

    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(result.current.connectionState).toBe("open");
    expect(source.url).toBe("/api/v1/games/runs/run_1234abcd/events");
  });

  it("closes the source when a terminal event arrives", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));
    const source = MockEventSource.instances[0];
    source.onopen?.();
    source.emit("game_completed", {
      id: 2,
      type: "game_completed",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:01:00Z",
      round: null,
      phase: null,
      actor: null,
      action: null,
      payload: { winner: "villagers" },
    });

    await waitFor(() => expect(result.current.connectionState).toBe("closed"));
    expect(source.closed).toBe(true);
    expect(result.current.latestEvent?.type).toBe("game_completed");
  });
});
