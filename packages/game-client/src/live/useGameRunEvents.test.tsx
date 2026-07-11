// @vitest-environment jsdom

import { act, renderHook, waitFor } from "@testing-library/react";
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

  emitRaw(type: string, data: string) {
    const event = new MessageEvent(type, { data });
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
    act(() => {
      source.onopen?.();
      source.emit("game_started", {
        id: 1,
        type: "game_started",
        run_id: "run_1234abcd",
        session_id: "game_1200abcd",
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
        session_id: "game_1200abcd",
        created_at: "2026-04-24T12:00:00Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: { players: [] },
      });
    });

    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(result.current.connectionState).toBe("open");
    expect(source.url).toBe("/api/v1/games/runs/run_1234abcd/events");
  });

  it("reports an error when EventSource is unavailable", async () => {
    vi.stubGlobal("EventSource", undefined);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));

    await waitFor(() => expect(result.current.connectionState).toBe("error"));
    expect(result.current.events).toHaveLength(0);
    expect(result.current.latestEvent).toBeNull();
  });

  it("closes the source when a terminal event arrives", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));
    const source = MockEventSource.instances[0];
    act(() => {
      source.onopen?.();
      source.emit("game_completed", {
        id: 2,
        type: "game_completed",
        run_id: "run_1234abcd",
        session_id: "game_1200abcd",
        created_at: "2026-04-24T12:01:00Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: { winner: "villagers" },
      });
    });

    await waitFor(() => expect(result.current.connectionState).toBe("closed"));
    expect(source.closed).toBe(true);
    expect(result.current.latestEvent?.type).toBe("game_completed");
  });

  it("closes the source when an administrator cancels the run", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));
    const source = MockEventSource.instances[0];
    act(() => {
      source.onopen?.();
      source.emit("game_canceled", {
        id: 2,
        type: "game_canceled",
        run_id: "run_1234abcd",
        session_id: "game_1200abcd",
        created_at: "2026-04-24T12:01:00Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: {},
      });
    });

    await waitFor(() => expect(result.current.connectionState).toBe("closed"));
    expect(source.closed).toBe(true);
    expect(result.current.latestEvent?.type).toBe("game_canceled");
  });

  it("ignores late callbacks after a terminal event closes the source", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));
    const source = MockEventSource.instances[0];
    act(() => {
      source.onopen?.();
      source.emit("game_completed", {
        id: 2,
        type: "game_completed",
        run_id: "run_1234abcd",
        session_id: "game_1200abcd",
        created_at: "2026-04-24T12:01:00Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: { winner: "villagers" },
      });
    });

    await waitFor(() => expect(result.current.connectionState).toBe("closed"));

    act(() => {
      source.onerror?.();
      source.emit("state_updated", {
        id: 3,
        type: "state_updated",
        run_id: "run_1234abcd",
        session_id: "game_1200abcd",
        created_at: "2026-04-24T12:02:00Z",
        round: 1,
        phase: "day",
        actor: null,
        action: null,
        payload: { status: "late" },
      });
    });

    expect(result.current.connectionState).toBe("closed");
    expect(result.current.events).toHaveLength(1);
    expect(result.current.latestEvent?.type).toBe("game_completed");
  });

  it("resets events when subscribing to another run", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { rerender, result } = renderHook(
      ({ runId }: { runId: string }) => useGameRunEvents(runId),
      { initialProps: { runId: "run_first" } },
    );
    const firstSource = MockEventSource.instances[0];
    act(() => {
      firstSource.emit("game_completed", {
        id: 1,
        type: "game_completed",
        run_id: "run_first",
        session_id: "game_1200abcd",
        created_at: "2026-04-24T12:01:00Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: { winner: "villagers" },
      });
    });

    await waitFor(() => expect(result.current.events).toHaveLength(1));

    rerender({ runId: "run_second" });

    await waitFor(() => expect(result.current.events).toHaveLength(0));
    expect(result.current.latestEvent).toBeNull();
    expect(result.current.connectionState).toBe("connecting");
    expect(MockEventSource.instances[1].url).toBe(
      "/api/v1/games/runs/run_second/events",
    );
  });

  it("subscribes to model streaming progress events", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));
    const source = MockEventSource.instances[0];
    act(() => {
      source.emit("model_response_delta", {
        id: 3,
        type: "model_response_delta",
        run_id: "run_1234abcd",
        session_id: "game_1200abcd",
        created_at: "2026-04-24T12:00:04Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          visible_text: "我不是狼",
          field: "say",
          is_public: true,
        },
      });
      source.emit("model_thinking_tick", {
        id: 4,
        type: "model_thinking_tick",
        run_id: "run_1234abcd",
        session_id: "game_1200abcd",
        created_at: "2026-04-24T12:00:05Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          elapsed_ms: 3000,
          message: "正在组织发言...",
        },
      });
    });

    await waitFor(() => expect(result.current.events).toHaveLength(2));
    expect(result.current.events.map((event) => event.type)).toEqual([
      "model_response_delta",
      "model_thinking_tick",
    ]);
  });

  it("keeps prior events and reports an error when a stream event is malformed", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));
    const source = MockEventSource.instances[0];
    act(() => {
      source.onopen?.();
      source.emit("game_started", {
        id: 1,
        type: "game_started",
        run_id: "run_1234abcd",
        session_id: "game_1200abcd",
        created_at: "2026-04-24T12:00:00Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: { players: [] },
      });
    });

    await waitFor(() => expect(result.current.events).toHaveLength(1));

    act(() => {
      source.emitRaw("round_started", "{not-json");
    });

    await waitFor(() => expect(result.current.connectionState).toBe("error"));
    expect(result.current.events).toHaveLength(1);
    expect(result.current.latestEvent?.type).toBe("game_started");
  });
});
