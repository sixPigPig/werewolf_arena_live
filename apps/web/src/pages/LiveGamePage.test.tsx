import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveEventTimeline } from "../features/games/components/LiveEventTimeline";
import type { LiveGameEvent } from "../features/games/types";
import { renderWithClient } from "../tests/renderWithClient";
import { LiveGamePage } from "./LiveGamePage";

class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, (event: MessageEvent) => void>();
  url: string;

  constructor(url: string) {
    this.url = url;
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
    const fetch = vi.spyOn(globalThis, "fetch");
    fetch
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            run_id: "run_1234abcd",
            session_id: "session_20260424_120000_ab12cd34",
            villager_model: "deepseek-chat",
            werewolf_model: "deepseek-chat",
            seed: null,
            max_rounds: 8,
            rule_set_id: "starter_6",
            rule_set: {
              id: "starter_6",
              version: "2026.04",
              name: "新手 6 人快局",
              player_count: 6,
              roles: [
                { role: "狼人", count: 1 },
                { role: "预言家", count: 1 },
                { role: "医生", count: 1 },
                { role: "村民", count: 3 },
              ],
              role_summary: "1 狼人 / 1 预言家 / 1 医生 / 3 村民",
            },
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
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            run_id: "run_1234abcd",
            session_id: "session_20260424_120000_ab12cd34",
            villager_model: "deepseek-chat",
            werewolf_model: "deepseek-chat",
            seed: null,
            max_rounds: 8,
            rule_set_id: "starter_6",
            rule_set: {
              id: "starter_6",
              version: "2026.04",
              name: "新手 6 人快局",
              player_count: 6,
              roles: [
                { role: "狼人", count: 1 },
                { role: "预言家", count: 1 },
                { role: "医生", count: 1 },
                { role: "村民", count: 3 },
              ],
              role_summary: "1 狼人 / 1 预言家 / 1 医生 / 3 村民",
            },
            status: "completed",
            created_at: "2026-04-24T12:00:00Z",
            started_at: "2026-04-24T12:00:01Z",
            completed_at: "2026-04-24T12:00:10Z",
            winner: "狼人阵营",
            error: null,
            event_count: 3,
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
    expect(await screen.findByText("新手 6 人快局")).toBeInTheDocument();
    expect(
      screen.getByText("1 狼人 / 1 预言家 / 1 医生 / 3 村民"),
    ).toBeInTheDocument();
    const source = MockEventSource.instances[0];
    act(() => {
      source.onopen?.();
      source.emit("game_started", {
        id: 1,
        type: "game_started",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:01Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "村民", model: "deepseek-chat" },
          ],
        },
      });
      source.emit("action_requested", {
        id: 2,
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
        id: 3,
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
        id: 4,
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
    });

    expect(await screen.findByRole("button", { name: /张三/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /李四/ })).toBeInTheDocument();
    expect(await screen.findByText("张三 正在 debate")).toBeInTheDocument();
    expect(screen.getAllByText('{"say":"我不是狼"}').length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "查看完整复盘" })).toHaveAttribute(
      "href",
      "/games/session_20260424_120000_ab12cd34",
    );
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("completed")).toBeInTheDocument();
  });

  it("lets users pin a player and re-enable auto follow", async () => {
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
    act(() => {
      source.emit("game_started", {
        id: 1,
        type: "game_started",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:01Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "村民", model: "deepseek-chat" },
          ],
        },
      });
      source.emit("action_requested", {
        id: 2,
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
    });

    expect(await screen.findByRole("heading", { name: "张三" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /李四/ }));
    expect(screen.getByRole("heading", { name: "李四" })).toBeInTheDocument();

    act(() => {
      source.emit("action_requested", {
        id: 3,
        type: "action_requested",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:04Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "vote",
        payload: { options: ["李四"] },
      });
    });
    expect(screen.getByRole("heading", { name: "李四" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: "自动跟随" }));
    expect(screen.getByRole("heading", { name: "张三" })).toBeInTheDocument();
  });

  it("renders failed event errors", async () => {
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
    act(() => {
      source.onopen?.();
      source.emit("game_failed", {
        id: 2,
        type: "game_failed",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:10Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: { error: "model timeout" },
      });
    });

    expect(await screen.findByText("对局失败")).toBeInTheDocument();
    expect(screen.getByText("model timeout")).toBeInTheDocument();
  });

  it("renders malformed unknown timeline events as title-only rows", () => {
    const events = [
      {
        id: 1,
        type: "custom_diagnostic",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:03Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: null,
      },
    ] as unknown as LiveGameEvent[];

    const { container } = render(<LiveEventTimeline events={events} />);

    expect(screen.getAllByText("custom_diagnostic")).toHaveLength(2);
    expect(container.querySelector("pre")).not.toBeInTheDocument();
  });
});
