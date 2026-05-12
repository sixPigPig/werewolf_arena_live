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
    expect(screen.getByText("观赛舞台")).toBeInTheDocument();
    expect(screen.getByText("圆桌座位")).toBeInTheDocument();
    expect(screen.queryByText("座位盘")).not.toBeInTheDocument();
    expect(screen.getByText("剧情时间线")).toBeInTheDocument();
    expect(screen.getByText("调试事件")).toBeInTheDocument();
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
      source.emit("model_request_started", {
        id: 3,
        type: "model_request_started",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:03Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          model: "deepseek-chat",
          message: "玩家正在组织公开发言...",
          stream_field: "say",
          is_public: true,
        },
      });
      source.emit("model_response_delta", {
        id: 4,
        type: "model_response_delta",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:03Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          field: "say",
          visible_text: "我",
          is_public: true,
        },
      });
      source.emit("model_response_delta", {
        id: 5,
        type: "model_response_delta",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:03Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          field: "say",
          visible_text: "不是狼",
          is_public: true,
        },
      });
    });

    expect(
      await screen.findByRole("button", { name: /张三/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /张三/ })).toHaveAccessibleName(
      /公开发言/,
    );
    expect(screen.getByRole("button", { name: /李四/ })).toBeInTheDocument();
    expect(await screen.findByText("张三 正在公开发言")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "追到最新" }));
    expect(
      screen.getByRole("heading", { name: "张三 正在发言" }),
    ).toBeInTheDocument();
    expect(screen.getByText("张三：我不是狼")).toBeInTheDocument();
    expect(screen.queryByText("model_response_delta")).not.toBeInTheDocument();

    act(() => {
      source.emit("state_updated", {
        id: 6,
        type: "state_updated",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:04Z",
        round: 1,
        phase: "day",
        actor: null,
        action: null,
        payload: {
          active_players: ["张三"],
          exiled: "李四",
        },
      });
    });

    expect(screen.getByRole("button", { name: /张三/ })).toHaveAccessibleName(
      /发言中/,
    );
    expect(screen.getByRole("button", { name: /张三/ })).toHaveAttribute(
      "data-seat-state",
      "speaking",
    );
    const roster = screen.getByTestId("player-roster-panel");
    expect(
      within(roster).getByRole("heading", { name: "玩家列表（2人局）" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("player-roster-row-张三")).toHaveAttribute(
      "data-roster-state",
      "speaking",
    );
    expect(screen.getByTestId("player-roster-row-李四")).toHaveAttribute(
      "data-roster-state",
      "dead",
    );
    expect(
      within(screen.getByTestId("player-roster-row-张三")).getByText("发言中"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("player-roster-row-张三")).getByText("麦"),
    ).toBeInTheDocument();
    const activePlayerRoleLabel = within(
      screen.getByRole("button", { name: /张三/ }),
    ).getByText("狼人");
    expect(activePlayerRoleLabel.parentElement).toHaveClass(
      "hidden",
      "md:inline-flex",
    );
    expect(
      within(screen.getByRole("button", { name: /张三/ })).getByText("发言中"),
    ).toHaveClass("hidden", "md:block");
    expect(screen.getByRole("button", { name: /李四/ })).toHaveAccessibleName(
      /出局/,
    );

    act(() => {
      source.emit("model_response_received", {
        id: 7,
        type: "model_response_received",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:04Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          model: "deepseek-chat",
          message: "模型返回已接收，正在解析行动",
        },
      });
      source.emit("game_completed", {
        id: 8,
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

    expect(screen.queryByText('{"say":"我不是狼"}')).not.toBeInTheDocument();
    expect(screen.getByText("模型返回已接收，正在解析行动")).toBeInTheDocument();
    expect(screen.queryByText("model_response_delta")).not.toBeInTheDocument();
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

  it("uses a stage-first live layout with a separate timeline column", async () => {
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
    expect(screen.getByTestId("app-top-nav")).toHaveClass(
      "h-[56px]",
      "min-h-[56px]",
      "live-command-nav",
    );
    expect(screen.getByTestId("app-logo-placeholder")).toHaveClass(
      "h-12",
      "w-12",
    );
    expect(screen.getByTestId("app-logo-placeholder")).not.toHaveClass("border");
    expect(screen.getByRole("link", { name: "狼人杀竞技场" })).not.toHaveClass(
      "border",
    );
    expect(screen.getByTestId("app-logo-image")).toHaveClass(
      "h-full",
      "w-full",
    );
    expect(screen.getByTestId("app-logo-image").getAttribute("src")).toContain(
      "langrensha-c-logo",
    );
    expect(screen.getByRole("link", { name: "狼人杀竞技场" })).toHaveAttribute(
      "href",
      "/games",
    );
    expect(screen.getByRole("link", { name: "返回大厅" })).toHaveAttribute(
      "href",
      "/games",
    );
    const topNav = screen.getByTestId("app-top-nav");
    const liveNavContext = within(topNav).getByTestId("live-nav-context");
    expect(liveNavContext).toHaveClass("live-command-context");
    expect(
      within(liveNavContext).getByRole("heading", { name: "实时观战" }),
    ).toBeInTheDocument();
    expect(
      within(liveNavContext).getByTestId("live-status-strip"),
    ).toBeInTheDocument();
    expect(
      within(liveNavContext).getByTestId("rule-set-summary"),
    ).toBeInTheDocument();
    expect(liveNavContext).toHaveTextContent("快速执行");
    expect(
      within(topNav).getByTestId("director-controls"),
    ).toBeInTheDocument();
    expect(
      within(liveNavContext).queryByTestId("director-controls"),
    ).not.toBeInTheDocument();
    expect(within(topNav).getByLabelText("播放速度")).toBeInTheDocument();
    expect(within(topNav).getByRole("button", { name: "暂停" })).toHaveClass(
      "h-10",
      "w-10",
    );
    expect(within(topNav).getByRole("button", { name: "追到最新" })).toHaveClass(
      "h-10",
      "w-10",
    );
    expect(screen.getByTestId("live-game-page")).toHaveClass(
      "min-h-screen",
      "text-slate-100",
    );
    expect(screen.getByTestId("live-game-page").className).not.toContain("bg-");
    expect(
      container.querySelector('[data-testid="live-game-page"] > div'),
    ).toHaveClass("max-w-none", "w-full");
    expect(
      container.querySelector('[data-testid="live-game-page"] > div'),
    ).not.toHaveClass("max-w-7xl");
    expect(screen.getByTestId("live-game-page")).toHaveClass(
      "live-game-page",
    );
    expect(
      container.querySelector('[data-testid="live-game-page"] > div'),
    ).toHaveClass("live-game-content");
    expect(screen.getByTestId("live-page-shell-module")).toHaveClass(
      "live-page-shell-module",
    );
    expect(screen.queryByTestId("live-page-heading")).not.toBeInTheDocument();
    expect(screen.queryByTestId("live-status-shell")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("live-rule-summary-shell"),
    ).not.toBeInTheDocument();
    const liveGrid = container.querySelector('[data-testid="live-stage-layout"]');
    expect(liveGrid).not.toBeNull();
    expect(liveGrid).toHaveClass("live-stage-layout", "live-stage-module");
    const columns = Array.from(liveGrid!.children);
    expect(columns).toHaveLength(3);
    const [rosterColumn, stageColumn, eventsColumn] = columns;

    expect(rosterColumn).toHaveClass("live-roster-column");
    expect(stageColumn).toHaveClass("live-stage-column");
    expect(
      within(rosterColumn as HTMLElement).getByText("玩家列表（0人局）"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("player-roster-panel")).toHaveClass(
      "player-roster-panel",
    );
    expect(screen.getByTestId("player-roster-list")).toHaveClass(
      "player-roster-list",
    );
    expect(
      within(stageColumn as HTMLElement).getByText("观赛舞台"),
    ).toBeInTheDocument();
    expect(
      within(stageColumn as HTMLElement).getByText("圆桌座位"),
    ).toBeInTheDocument();
    expect(
      within(eventsColumn as HTMLElement).getByText("剧情时间线"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("live-status-strip")).toHaveClass(
      "live-command-status",
      "text-slate-300",
    );
    expect(screen.getByTestId("rule-set-summary")).toHaveClass(
      "live-command-rule-summary",
      "text-slate-100",
    );
    expect(screen.getByTestId("director-controls")).toHaveClass(
      "live-command-controls",
      "text-slate-100",
    );
    expect(screen.getByTestId("live-timeline-panel")).toHaveClass(
      "text-slate-100",
    );
    expect(screen.getByTestId("live-timeline-panel").className).not.toContain(
      "bg-",
    );
    expect(screen.getByTestId("live-director-stage-shell")).toHaveClass(
      "min-h-[36rem]",
      "lg:min-h-[40rem]",
    );
    expect(stageColumn).toHaveClass("min-w-0");
    expect(eventsColumn).toHaveClass("min-w-0");

    expect(
      within(stageColumn as HTMLElement).queryByTestId("director-controls"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("live-rule-summary-shell"),
    ).not.toBeInTheDocument();
  });

  it("keeps the first seat clear of the stage phase badge", async () => {
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
      emitEvent(source, {
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "村民", model: "deepseek-chat" },
            { name: "王五", role: "预言家", model: "deepseek-chat" },
            { name: "赵六", role: "守卫", model: "deepseek-chat" },
            { name: "孙七", role: "村民", model: "deepseek-chat" },
            { name: "周八", role: "村民", model: "deepseek-chat" },
          ],
        },
      });
    });

    expect(screen.getByRole("button", { name: /张三/ })).toHaveStyle({
      "--seat-y": "10%",
      "--seat-sm-y": "18%",
    });
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
      "is-focused",
    );

    await userEvent.click(screen.getByRole("button", { name: /李四/ }));
    expect(screen.getByRole("button", { name: /李四/ })).toHaveClass(
      "is-focused",
    );

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
    expect(screen.getByRole("button", { name: /李四/ })).toHaveClass(
      "is-focused",
    );

    await userEvent.click(screen.getByRole("switch", { name: "自动跟随" }));
    expect(screen.getByRole("button", { name: /张三/ })).toHaveClass(
      "is-focused",
    );
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

    expect((await screen.findAllByText("对局失败")).length).toBeGreaterThanOrEqual(
      2,
    );
    expect(screen.getAllByText("model timeout").length).toBeGreaterThan(0);
  });

  it("resumes a failed live run from its saved checkpoint", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/runs/run_1234abcd")) {
        return Promise.resolve(runResponse("run_1234abcd", "failed"));
      }
      if (url.endsWith("/api/v1/games/session_run_1234abcd/resume")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_resumed",
              session_id: "session_run_1234abcd",
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              seed: null,
              max_rounds: 8,
              status: "queued",
              created_at: "2026-04-24T12:05:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
              event_pacing: "off",
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    renderWithClient(
      <Routes>
        <Route
          path="/games/live/run_resumed"
          element={<p>继续后的实时观战</p>}
        />
        <Route path="/games/live/:runId" element={<LiveGamePage />} />
      </Routes>,
      "/games/live/run_1234abcd",
    );

    expect(await screen.findByText("实时观战")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "继续对局" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/session_run_1234abcd/resume",
      expect.objectContaining({ method: "POST" }),
    );
    expect(await screen.findByText("继续后的实时观战")).toBeInTheDocument();
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
      emitEvent(source, {
        id: 2,
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "村民", model: "deepseek-chat" },
          ],
        },
      });
      emitEvent(source, { id: 3, type: "round_started", round: 1 });
      emitEvent(source, {
        id: 4,
        type: "model_response_delta",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: { visible_text: "我是好人" },
      });
      emitEvent(source, {
        id: 5,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "李四",
        action: "debate",
      });
      emitEvent(source, {
        id: 6,
        type: "state_updated",
        payload: { active_players: ["张三", "李四"] },
      });
      emitEvent(source, {
        id: 7,
        type: "game_completed",
        payload: { winner: "狼人阵营" },
      });
    });

    expect(
      await screen.findByRole("heading", { name: "对局完成" }),
    ).toBeInTheDocument();
    expect(screen.getByText("队列剩余：0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /李四/ })).toHaveAccessibleName(
      /最后行动/,
    );
    expect(screen.getByRole("button", { name: /张三/ })).not.toHaveAccessibleName(
      /发言中/,
    );
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
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
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
    expect(consoleError.mock.calls.flat().join("\n")).not.toContain(
      "Cannot update a component",
    );
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

  it("shows story events by default and keeps raw events in the debug drawer", async () => {
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

    const storyHeading = screen.getByRole("heading", { name: "剧情时间线" });
    const storyPanel = storyHeading.closest("section");
    expect(storyPanel).not.toBeNull();
    const storyTimeline = storyPanel!.querySelector(
      ":scope > ol",
    ) as HTMLElement | null;
    expect(storyTimeline).not.toBeNull();
    const storyTimelineElement = storyTimeline!;
    expect(
      within(storyTimelineElement).getByText("第 1 轮开始"),
    ).toBeInTheDocument();
    expect(
      within(storyTimelineElement).getByText("白天阶段开始"),
    ).toBeInTheDocument();
    expect(
      within(storyTimelineElement).queryByText("round_started"),
    ).not.toBeInTheDocument();
    expect(within(storyTimelineElement).getAllByRole("listitem")).toHaveLength(
      2,
    );

    const rows = within(storyTimelineElement).getAllByRole("listitem");
    expect(rows[0]).toHaveClass("bg-amber-300/10", "ring-1");

    act(() => {
      vi.advanceTimersByTime(2500);
    });

    expect(rows[1]).toHaveClass("bg-amber-300/10", "ring-1");
    act(() => {
      screen.getByText("调试事件").click();
    });
    const debugPanel = screen.getByText("调试事件").closest("details");
    expect(debugPanel).not.toBeNull();
    expect(within(debugPanel!).getByText("round_started")).toBeInTheDocument();
    expect(within(debugPanel!).getByText("phase_started")).toBeInTheDocument();
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

  it("renders a localized story timeline when requested", () => {
    const events = [
      {
        id: 1,
        type: "action_requested",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:03Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: { options: ["李四"] },
      },
      {
        id: 2,
        type: "model_request_started",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:04Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: { model: "deepseek-chat" },
      },
    ] as LiveGameEvent[];

    render(<LiveEventTimeline events={events} variant="story" />);

    expect(screen.getByText("张三 正在公开发言")).toBeInTheDocument();
    expect(screen.queryByText("model_request_started")).not.toBeInTheDocument();
  });
});
