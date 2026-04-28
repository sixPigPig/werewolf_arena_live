import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveDirectorControls } from "../features/games/components/LiveDirectorControls";
import { LiveEventTimeline } from "../features/games/components/LiveEventTimeline";
import { LiveStatusStrip } from "../features/games/components/LiveStatusStrip";
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

function runningRunResponse() {
  return new Response(
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
  );
}

function runResponse(
  runId: string,
  status: "running" | "completed" | "failed",
) {
  return new Response(
    JSON.stringify({
      run_id: runId,
      session_id: `session_${runId}`,
      villager_model: "deepseek-chat",
      werewolf_model: "deepseek-chat",
      seed: null,
      max_rounds: 8,
      status,
      created_at: "2026-04-24T12:00:00Z",
      started_at: "2026-04-24T12:00:01Z",
      completed_at:
        status === "completed" ? "2026-04-24T12:00:10Z" : null,
      winner: status === "completed" ? "狼人阵营" : null,
      error: status === "failed" ? "model timeout" : null,
      event_count: status === "running" ? 1 : 3,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function emitEvent(
  source: MockEventSource,
  partial: Partial<LiveGameEvent>,
) {
  source.emit(partial.type ?? "round_started", {
    id: partial.id ?? 1,
    type: partial.type ?? "round_started",
    run_id: partial.run_id ?? "run_1234abcd",
    session_id: partial.session_id ?? "session_20260424_120000_ab12cd34",
    created_at: partial.created_at ?? "2026-04-24T12:00:03Z",
    round: partial.round ?? null,
    phase: partial.phase ?? null,
    actor: partial.actor ?? null,
    action: partial.action ?? null,
    payload: partial.payload ?? {},
  });
}

function LiveGameRouteSwitcher() {
  const navigate = useNavigate();

  return (
    <>
      <button type="button" onClick={() => navigate("/games/live/run_a")}>
        run a
      </button>
      <button type="button" onClick={() => navigate("/games/live/run_b")}>
        run b
      </button>
      <Routes>
        <Route path="/games/live/:runId" element={<LiveGamePage />} />
      </Routes>
    </>
  );
}

describe("LiveGamePage", () => {
  afterEach(() => {
    vi.useRealTimers();
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
    });
    expect(screen.getByText("连接：已连接")).toBeInTheDocument();

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
    expect(await screen.findByText("已完成")).toBeInTheDocument();
  });

  it("localizes the idle live connection state", () => {
    render(
      <LiveStatusStrip
        connectionState="idle"
        run={{
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
          event_pacing: "off",
        }}
      />,
    );

    expect(screen.getByText("连接：未连接")).toBeInTheDocument();
  });

  it("allows live grid columns to shrink inside wrapped panels", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(runningRunResponse()),
    );

    const { container } = renderWithClient(
      <Routes>
        <Route path="/games/live/:runId" element={<LiveGamePage />} />
      </Routes>,
      "/games/live/run_1234abcd",
    );

    expect(await screen.findByText("实时观战")).toBeInTheDocument();
    const liveGrid = container.querySelector(".grid.gap-4");
    expect(liveGrid).not.toBeNull();
    const [playerColumn, directorColumn, eventsColumn] = Array.from(
      liveGrid!.children,
    );

    expect(playerColumn).toHaveClass("min-w-0");
    expect(directorColumn).toHaveClass("min-w-0");
    expect(eventsColumn).toHaveClass("min-w-0");
  });

  it("lets users pin a player and re-enable auto follow", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(runningRunResponse()),
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

    expect(await screen.findByRole("button", { name: /张三/ })).toHaveClass(
      "ring-2",
    );

    await userEvent.click(screen.getByRole("button", { name: /李四/ }));
    expect(screen.getByRole("button", { name: /李四/ })).toHaveClass("ring-2");

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
    expect(screen.getByRole("button", { name: /李四/ })).toHaveClass("ring-2");

    await userEvent.click(screen.getByRole("checkbox", { name: "自动跟随" }));
    expect(screen.getByRole("button", { name: /张三/ })).toHaveClass("ring-2");
  });

  it("renders failed event errors", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(runningRunResponse()),
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

    expect(await screen.findAllByText("对局失败")).toHaveLength(2);
    expect(screen.getAllByText("model timeout").length).toBeGreaterThan(0);
  });

  it("plays the director stage in order instead of jumping to the latest event", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(runningRunResponse()),
    );

    renderWithClient(
      <Routes>
        <Route path="/games/live/:runId" element={<LiveGamePage />} />
      </Routes>,
      "/games/live/run_1234abcd",
    );

    expect(await screen.findByText("实时观战")).toBeInTheDocument();
    const source = MockEventSource.instances[0];
    vi.useFakeTimers();

    act(() => {
      emitEvent(source, { id: 1, type: "round_started", round: 1 });
      emitEvent(source, {
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "day",
      });
    });

    expect(
      screen.getByRole("heading", { name: "第 1 轮开始" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "白天阶段开始" }),
    ).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2500);
    });

    expect(
      screen.getByRole("heading", { name: "白天阶段开始" }),
    ).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("opens completed runs at the terminal event instead of replaying the full backlog", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(
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
            event_pacing: "off",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
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
      emitEvent(source, { id: 1, type: "run_created" });
      emitEvent(source, { id: 2, type: "round_started", round: 1 });
      emitEvent(source, {
        id: 3,
        type: "game_completed",
        payload: { winner: "狼人阵营" },
      });
    });

    expect(
      await screen.findByRole("heading", { name: "对局完成" }),
    ).toBeInTheDocument();
    expect(screen.getByText("队列剩余：0")).toBeInTheDocument();
  });

  it("keeps ordered playback when a live-opened run later completes", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    const fetch = vi.spyOn(globalThis, "fetch");
    fetch
      .mockResolvedValueOnce(runningRunResponse())
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            run_id: "run_1234abcd",
            session_id: "session_20260424_120000_ab12cd34",
            villager_model: "deepseek-chat",
            werewolf_model: "deepseek-chat",
            seed: null,
            max_rounds: 8,
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
    const source = MockEventSource.instances[0];
    act(() => {
      emitEvent(source, { id: 1, type: "run_created" });
      emitEvent(source, { id: 2, type: "round_started", round: 1 });
      emitEvent(source, {
        id: 3,
        type: "game_completed",
        payload: { winner: "狼人阵营" },
      });
    });

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("已完成")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "运行已创建" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "对局完成" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("队列剩余：2")).toBeInTheDocument();
  });

  it("reuses each run's first terminal-start decision when switching routes", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    const fetch = vi.spyOn(globalThis, "fetch");
    const runAFetches: string[] = [];
    fetch.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/runs/run_a")) {
        runAFetches.push(url);
        return Promise.resolve(
          runResponse(
            "run_a",
            runAFetches.length === 1 ? "running" : "completed",
          ),
        );
      }
      if (url.endsWith("/api/v1/games/runs/run_b")) {
        return Promise.resolve(runResponse("run_b", "completed"));
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    renderWithClient(<LiveGameRouteSwitcher />, "/games/live/run_a");

    expect(await screen.findByText("实时观战")).toBeInTheDocument();
    const runASource = MockEventSource.instances[0];
    act(() => {
      emitEvent(runASource, { id: 1, type: "run_created", run_id: "run_a" });
      emitEvent(runASource, {
        id: 2,
        type: "round_started",
        run_id: "run_a",
        round: 1,
      });
      emitEvent(runASource, {
        id: 3,
        type: "game_completed",
        run_id: "run_a",
        payload: { winner: "狼人阵营" },
      });
    });

    await waitFor(() => expect(runAFetches).toHaveLength(2));
    expect(await screen.findByText("已完成")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "运行已创建" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "对局完成" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("队列剩余：2")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "run b" }));
    await waitFor(() =>
      expect(MockEventSource.instances.at(-1)?.url).toContain("/run_b/events"),
    );
    const runBSource = MockEventSource.instances.at(-1)!;
    act(() => {
      emitEvent(runBSource, { id: 1, type: "run_created", run_id: "run_b" });
      emitEvent(runBSource, {
        id: 2,
        type: "round_started",
        run_id: "run_b",
        round: 1,
      });
      emitEvent(runBSource, {
        id: 3,
        type: "game_completed",
        run_id: "run_b",
        payload: { winner: "狼人阵营" },
      });
    });
    expect(await screen.findByText("已完成")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "对局完成" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "run a" }));
    await waitFor(() =>
      expect(MockEventSource.instances.at(-1)?.url).toContain("/run_a/events"),
    );
    const replayedRunASource = MockEventSource.instances.at(-1)!;
    act(() => {
      emitEvent(replayedRunASource, {
        id: 1,
        type: "run_created",
        run_id: "run_a",
      });
      emitEvent(replayedRunASource, {
        id: 2,
        type: "round_started",
        run_id: "run_a",
        round: 1,
      });
      emitEvent(replayedRunASource, {
        id: 3,
        type: "game_completed",
        run_id: "run_a",
        payload: { winner: "狼人阵营" },
      });
    });

    expect(
      await screen.findByRole("heading", { name: "运行已创建" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "对局完成" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("队列剩余：2")).toBeInTheDocument();
  });

  it("keeps the director stage paused until users catch up to the latest key event", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(runningRunResponse()),
    );
    renderWithClient(
      <Routes>
        <Route path="/games/live/:runId" element={<LiveGamePage />} />
      </Routes>,
      "/games/live/run_1234abcd",
    );

    expect(await screen.findByText("实时观战")).toBeInTheDocument();
    const source = MockEventSource.instances[0];
    vi.useFakeTimers();

    act(() => {
      emitEvent(source, { id: 1, type: "round_started", round: 1 });
      emitEvent(source, {
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
      });
      emitEvent(source, {
        id: 3,
        type: "game_completed",
        payload: { winner: "好人阵营" },
      });
    });

    expect(
      screen.getByRole("heading", { name: "第 1 轮开始" }),
    ).toBeInTheDocument();
    act(() => {
      screen.getByRole("button", { name: "暂停" }).click();
    });

    act(() => {
      vi.advanceTimersByTime(20_000);
    });

    expect(
      screen.getByRole("heading", { name: "第 1 轮开始" }),
    ).toBeInTheDocument();

    act(() => {
      screen.getByRole("button", { name: "追到最新" }).click();
    });

    expect(
      screen.getByRole("heading", { name: "对局完成" }),
    ).toBeInTheDocument();
    expect(screen.getByText("胜利阵营：好人阵营")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("keeps all raw events visible and highlights the current director event", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(runningRunResponse()),
    );

    const { container } = renderWithClient(
      <Routes>
        <Route path="/games/live/:runId" element={<LiveGamePage />} />
      </Routes>,
      "/games/live/run_1234abcd",
    );

    expect(await screen.findByText("实时观战")).toBeInTheDocument();
    const source = MockEventSource.instances[0];
    vi.useFakeTimers();

    act(() => {
      emitEvent(source, { id: 1, type: "round_started", round: 1 });
      emitEvent(source, {
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "day",
      });
    });

    const timeline = container.querySelector("ol");
    expect(timeline).not.toBeNull();
    expect(within(timeline!).getByText("round_started")).toBeInTheDocument();
    expect(within(timeline!).getByText("phase_started")).toBeInTheDocument();
    expect(within(timeline!).getAllByRole("listitem")).toHaveLength(2);

    const rows = within(timeline!).getAllByRole("listitem");
    expect(rows[0]).toHaveClass("bg-slate-100", "ring-1");

    act(() => {
      vi.advanceTimersByTime(2500);
    });

    expect(rows[1]).toHaveClass("bg-slate-100", "ring-1");
    vi.useRealTimers();
  });

  it("shows the backlog count while automatically catching up", () => {
    render(
      <LiveDirectorControls
        backlogCount={8}
        isCatchingUp={true}
        isPaused={false}
        onCatchUpToLatest={() => {}}
        onSpeedChange={() => {}}
        onTogglePaused={() => {}}
        speed={1}
      />,
    );

    expect(screen.getByText("自动追进度")).toBeInTheDocument();
    expect(screen.getByText("队列 8 条")).toBeInTheDocument();
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
