import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../tests/renderWithClient";
import { LiveGamePage } from "./LiveGamePage";

class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, (event: MessageEvent) => void>();

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(type, listener);
  }

  close() {}

  emit(type: string, payload: object) {
    this.listeners.get(type)?.(
      new MessageEvent(type, { data: JSON.stringify(payload) }),
    );
  }
}

describe("LiveGamePage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    MockEventSource.instances = [];
  });

  it("renders live events and completed replay link", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run_1234abcd",
          session_id: "session_20260424_120000_ab12cd34",
          villager_model: "deepseek-chat",
          werewolf_model: "deepseek-chat",
          seed: null,
          max_rounds: 8,
          status: "running",
          created_at: "2026-04-24T12:00:00Z",
          started_at: "2026-04-24T12:00:01Z",
          completed_at: null,
          winner: null,
          error: null,
          event_count: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderWithClient(
      <Routes>
        <Route path="/games/live/:runId" element={<LiveGamePage />} />
      </Routes>,
      "/games/live/run_1234abcd",
    );

    expect(await screen.findByText("实时观战")).toBeInTheDocument();
    const source = MockEventSource.instances[0];
    source.onopen?.();
    source.emit("action_requested", {
      id: 1,
      type: "action_requested",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:03Z",
      round: 1,
      phase: "day",
      actor: "张三",
      action: "debate",
      payload: { options: [] },
    });
    source.emit("model_response_received", {
      id: 2,
      type: "model_response_received",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:04Z",
      round: 1,
      phase: "day",
      actor: "张三",
      action: "debate",
      payload: { raw_response: "{\"say\":\"我不是狼\"}" },
    });
    source.emit("game_completed", {
      id: 3,
      type: "game_completed",
      run_id: "run_1234abcd",
      session_id: "session_20260424_120000_ab12cd34",
      created_at: "2026-04-24T12:00:10Z",
      round: null,
      phase: null,
      actor: null,
      action: null,
      payload: { winner: "狼人阵营" },
    });

    expect(await screen.findByText("张三 正在 debate")).toBeInTheDocument();
    expect(screen.getByText('{"say":"我不是狼"}')).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看完整复盘" })).toHaveAttribute(
      "href",
      "/games/session_20260424_120000_ab12cd34",
    );
  });
});
