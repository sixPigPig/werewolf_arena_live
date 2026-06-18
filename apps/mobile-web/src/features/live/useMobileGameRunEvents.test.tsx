import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMobileGameRunEvents } from "./useMobileGameRunEvents";

type Listener = (event: MessageEvent) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];

  listeners: Record<string, Listener[]> = {};
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners[type] = [...(this.listeners[type] ?? []), listener];
  }

  close = vi.fn();

  emit(type: string, data: unknown) {
    for (const listener of this.listeners[type] ?? []) {
      listener(new MessageEvent(type, { data: JSON.stringify(data) }));
    }
  }
}

afterEach(() => {
  MockEventSource.instances = [];
  vi.unstubAllGlobals();
});

describe("useMobileGameRunEvents", () => {
  it("collects events and closes after terminal events", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useMobileGameRunEvents("run_1"));

    MockEventSource.instances[0].onopen?.();
    MockEventSource.instances[0].emit("phase_started", {
      action: null,
      actor: null,
      created_at: "2026-06-18T00:00:00Z",
      id: 1,
      payload: { phase: "day" },
      phase: "day",
      round: 2,
      run_id: "run_1",
      session_id: "session_1",
      type: "phase_started",
    });
    MockEventSource.instances[0].emit("game_completed", {
      action: null,
      actor: null,
      created_at: "2026-06-18T00:01:00Z",
      id: 2,
      payload: { winner: "villagers" },
      phase: null,
      round: 2,
      run_id: "run_1",
      session_id: "session_1",
      type: "game_completed",
    });

    await waitFor(() => {
      expect(result.current.connectionState).toBe("closed");
      expect(result.current.events).toHaveLength(2);
    });
    expect(MockEventSource.instances[0].close).toHaveBeenCalled();
  });
});
