import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createTestQueryClient,
  renderWithClient,
} from "../tests/renderWithClient";
import { GamesPage } from "./GamesPage";

function ruleSetsResponse() {
  return {
    rule_sets: [
      {
        id: "classic_8",
        version: "2026.04",
        name: "经典 8 人局",
        description: "标准配置，适合完整推演。",
        player_count: 8,
        roles: [
          { role: "werewolf", count: 2, team: "werewolves" },
          { role: "villager", count: 4, team: "villagers" },
          { role: "seer", count: 1, team: "villagers" },
          { role: "guard", count: 1, team: "villagers" },
        ],
        role_summary: "2 狼人 / 4 村民 / 1 预言家 / 1 守卫",
        complexity: "标准",
        estimated_duration: "中",
        rule_tags: ["无警长", "顺序发言", "屠边"],
        sheriff_enabled: false,
        speech_policy: "sequential",
        speech_rounds: 1,
      },
      {
        id: "starter_6",
        version: "2026.04",
        name: "新手 6 人快局",
        description: "更短流程，适合快速验证。",
        player_count: 6,
        roles: [
          { role: "werewolf", count: 2, team: "werewolves" },
          { role: "villager", count: 3, team: "villagers" },
          { role: "seer", count: 1, team: "villagers" },
        ],
        role_summary: "2 狼人 / 3 村民 / 1 预言家",
        complexity: "入门",
        estimated_duration: "短",
        rule_tags: ["无警长", "顺序发言"],
        sheriff_enabled: false,
        speech_policy: "sequential",
        speech_rounds: 1,
      },
      {
        id: "sheriff_12",
        version: "2026.04",
        name: "标准 12 人警长局",
        description: "带警长竞选、警徽流与加权投票。",
        player_count: 12,
        roles: [
          { role: "werewolf", count: 4, team: "werewolves" },
          { role: "villager", count: 4, team: "villagers" },
          { role: "seer", count: 1, team: "villagers" },
          { role: "witch", count: 1, team: "villagers" },
          { role: "hunter", count: 1, team: "villagers" },
          { role: "idiot", count: 1, team: "villagers" },
        ],
        role_summary: "4 狼人 / 4 村民 / 1 预言家 / 1 女巫 / 1 猎人 / 1 白痴",
        complexity: "进阶",
        estimated_duration: "长",
        rule_tags: ["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
        sheriff_enabled: true,
        speech_policy: "sheriff_directed",
        speech_rounds: 2,
      },
    ],
  };
}

describe("GamesPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders available game sessions", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            sessions: [
              {
                session_id: "session_20260424_001",
                status: "complete",
                winner: "狼人阵营",
                round_count: 4,
                created_at: "2026-04-24T10:00:00Z",
              },
            ],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
    });

    renderWithClient(<GamesPage />, "/games");

    expect(
      screen.getByRole("heading", { name: "狼人杀对局复盘" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("session_20260424_001")).toBeInTheDocument();
    expect(screen.getByText("狼人阵营")).toBeInTheDocument();
    expect(screen.getByText("快速少人局")).toBeInTheDocument();
    expect(screen.getAllByText("无警长")[0]).toBeInTheDocument();
    expect(screen.getAllByText("顺序发言")[0]).toBeInTheDocument();
    expect(screen.getByText("标准警长局")).toBeInTheDocument();
    expect(screen.getByText("警徽 1.5 票")).toBeInTheDocument();
  });

  it("resumes a resumable session from the list", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/session_20260424_120000_ab12cd34/resume")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_resumed",
              session_id: "session_20260424_120000_ab12cd34",
              villager_model: "Qwen3.6-Plus",
              werewolf_model: "MiniMax-M2.7",
              seed: 21,
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
      return Promise.resolve(
        new Response(
          JSON.stringify({
            sessions: [
              {
                session_id: "session_20260424_120000_ab12cd34",
                status: "partial",
                winner: null,
                round_count: 1,
                created_at: "2026-04-24T12:00:00Z",
                resumable: true,
              },
            ],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games" element={<GamesPage />} />
        <Route
          path="/games/live/run_resumed"
          element={<p>继续后的实时观战</p>}
        />
      </Routes>,
      "/games",
    );

    expect(
      await screen.findByText("session_20260424_120000_ab12cd34"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "继续对局" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/session_20260424_120000_ab12cd34/resume",
      expect.objectContaining({ method: "POST" }),
    );
    expect(await screen.findByText("继续后的实时观战")).toBeInTheDocument();
  });

  it("renders an empty state when no sessions exist", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(<GamesPage />, "/games");

    expect(await screen.findByText("还没有可复盘的对局")).toBeInTheDocument();
  });

  it("creates a live game run and navigates to the live page", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_1234abcd",
              session_id: "session_20260424_120000_ab12cd34",
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              seed: null,
              max_rounds: 8,
              status: "queued",
              created_at: "2026-04-24T12:00:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games" element={<GamesPage />} />
        <Route
          path="/games/live/:runId"
          element={<p>实时观战 run_1234abcd</p>}
        />
      </Routes>,
      "/games",
    );

    await screen.findByLabelText("经典 8 人局");
    const launchButton = screen.getByRole("button", { name: "发起对局" });
    expect(launchButton).toBeEnabled();
    await userEvent.click(launchButton);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({
        body: JSON.stringify({
          rule_set_id: "classic_8",
          seed: null,
          max_rounds: 8,
          event_pacing: "off",
        }),
        method: "POST",
      }),
    );
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });

  it("creates a live game run with the selected official rule set", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_1234abcd",
              session_id: "session_20260424_120000_ab12cd34",
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              rule_set_id: "starter_6",
              rule_set: {
                id: "starter_6",
                version: "2026.04",
                name: "新手 6 人快局",
                player_count: 6,
                roles: [],
              },
              seed: null,
              max_rounds: 8,
              status: "queued",
              created_at: "2026-04-24T12:00:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games" element={<GamesPage />} />
        <Route
          path="/games/live/:runId"
          element={<p>实时观战 run_1234abcd</p>}
        />
      </Routes>,
      "/games",
    );

    await userEvent.click(await screen.findByLabelText("新手 6 人快局"));
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({
        body: JSON.stringify({
          rule_set_id: "starter_6",
          seed: null,
          max_rounds: 8,
          event_pacing: "off",
        }),
        method: "POST",
      }),
    );
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });

  it("creates a live game run with standard event pacing", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/v1/games/runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_id: "run_1234abcd",
              session_id: "session_20260424_120000_ab12cd34",
              villager_model: "deepseek-chat",
              werewolf_model: "deepseek-chat",
              seed: null,
              max_rounds: 8,
              event_pacing: "standard",
              status: "queued",
              created_at: "2026-04-24T12:00:00Z",
              started_at: null,
              completed_at: null,
              winner: null,
              error: null,
              event_count: 1,
            }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(
      <Routes>
        <Route path="/games" element={<GamesPage />} />
        <Route
          path="/games/live/:runId"
          element={<p>实时观战 run_1234abcd</p>}
        />
      </Routes>,
      "/games",
    );

    await userEvent.selectOptions(
      await screen.findByLabelText("演示慢速"),
      "standard",
    );
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/games/runs",
      expect.objectContaining({
        body: JSON.stringify({
          rule_set_id: "classic_8",
          seed: null,
          max_rounds: 8,
          event_pacing: "standard",
        }),
        method: "POST",
      }),
    );
    expect(await screen.findByText("实时观战 run_1234abcd")).toBeInTheDocument();
  });

  it("blocks launch when max rounds is empty", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ sessions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithClient(<GamesPage />, "/games");

    await userEvent.clear(
      await screen.findByRole("spinbutton", { name: "最大轮数" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "发起对局" }));

    expect(screen.getByText("最大轮数必须是 1 到 20 的整数")).toBeInTheDocument();
    expect(
      fetchSpy.mock.calls.some(([input]) =>
        String(input).endsWith("/api/v1/games/runs"),
      ),
    ).toBe(false);
  });

  it("renders only the error state when refreshing cached sessions fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/games/rule-sets")) {
        return Promise.resolve(
          new Response(JSON.stringify(ruleSetsResponse()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(new Response(null, { status: 500 }));
    });

    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["games"], {
      sessions: [
        {
          session_id: "session_cached",
          status: "complete",
          winner: "狼人阵营",
          round_count: 3,
          created_at: null,
        },
      ],
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/games"]}>
          <GamesPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("无法读取对局列表")).toBeInTheDocument();
    expect(screen.queryByText("session_cached")).not.toBeInTheDocument();
  });
});
