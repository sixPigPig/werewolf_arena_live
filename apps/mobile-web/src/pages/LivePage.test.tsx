import { readFileSync } from "node:fs";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LivePage } from "./LivePage";
import type { GameRun, LiveGameEvent } from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  getGameRun: vi.fn(),
  resumeGameRun: vi.fn(),
  useGameRunEvents: vi.fn(),
  useLiveVoiceStream: vi.fn(),
}));

let unlockAudio: ReturnType<typeof vi.fn>;

function readPngMetadata(path: string) {
  const image = readFileSync(path);

  return {
    colorType: image.readUInt8(25),
    height: image.readUInt32BE(20),
    width: image.readUInt32BE(16),
  };
}

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    getGameRun: gameClientMocks.getGameRun,
    resumeGameRun: gameClientMocks.resumeGameRun,
    useGameRunEvents: gameClientMocks.useGameRunEvents,
    useLiveVoiceStream: gameClientMocks.useLiveVoiceStream,
  };
});

const run: GameRun = {
  run_id: "run-1",
  session_id: "session-1",
  villager_model: "test-model",
  werewolf_model: "test-model",
  rule_set: {
    id: "classic_8",
    version: "test",
    name: "经典 8 人",
    player_count: 8,
    roles: [],
  },
  seed: null,
  max_rounds: 8,
  winner: null,
  status: "running",
  created_at: "2026-06-19T00:00:00Z",
  started_at: "2026-06-19T00:00:01Z",
  completed_at: null,
  error: null,
  event_count: 1,
};

const gameStartedEvent: LiveGameEvent = {
  id: 1,
  type: "game_started",
  run_id: "run-1",
  session_id: "session-1",
  created_at: "2026-06-19T00:00:02Z",
  round: 1,
  phase: "day",
  actor: null,
  action: null,
  payload: {
    players: [
      {
        name: "阿青",
        role: "villager",
        model: "test-model",
        avatar_image_url: "/player-avatars/gothic-female-1.png",
      },
      { name: "白石", role: "werewolf", model: "test-model" },
      { name: "南风", role: "seer", model: "test-model" },
      { name: "木子", role: "witch", model: "test-model" },
    ],
  },
};

const runCreatedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 1,
  type: "run_created",
  round: null,
  phase: null,
  payload: { session_id: "session-1" },
};

const runStartedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "run_started",
  round: null,
  phase: null,
  payload: {},
};

const startupGameStartedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 3,
};

const speakingDeltaEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "model_response_delta",
  actor: "阿青",
  action: "debate",
  payload: {
    request_id: "req-1",
    visible_text: "我先听后置位发言。",
  },
};

const backlogPhaseEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "phase_started",
  actor: null,
  action: null,
  payload: { phase: "day" },
};

const backlogRequestEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 3,
  type: "model_request_started",
  actor: "阿青",
  action: "debate",
  payload: { request_id: "req-2" },
};

const backlogSpeakingDeltaEvent: LiveGameEvent = {
  ...speakingDeltaEvent,
  id: 4,
  payload: {
    request_id: "req-2",
    visible_text: "我先听后置位发言。",
  },
};

const speechRequestEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "model_request_started",
  actor: "阿青",
  action: "debate",
  payload: { request_id: "req-judge-speech" },
};

const nightPhaseEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "phase_started",
  round: 1,
  phase: "night",
  actor: null,
  action: null,
  payload: { active_players: ["阿青", "白石", "南风", "木子"] },
};

const dayPhaseEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 3,
  type: "phase_started",
  round: 1,
  phase: "day",
  actor: null,
  action: null,
  payload: { active_players: ["阿青", "白石", "南风", "木子"] },
};

function renderLiveRoute() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [
      { path: "/games/:gameId/live", element: <LivePage /> },
      { path: "/games/:gameId/replay", element: <h1>移动复盘</h1> },
    ],
    { initialEntries: ["/games/run-1/live"] },
  );

  const renderResult = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { router, ...renderResult };
}

describe("LivePage", () => {
  beforeEach(() => {
    unlockAudio = vi.fn().mockResolvedValue(true);
    gameClientMocks.getGameRun.mockResolvedValue(run);
    gameClientMocks.resumeGameRun.mockResolvedValue(run);
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent],
      latestEvent: gameStartedEvent,
    });
    gameClientMocks.useLiveVoiceStream.mockReturnValue({
      connectionState: "idle",
      currentItem: null,
      currentSpeakerName: null,
      errors: [],
      unlockAudio,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders mobile live details for the route game id", async () => {
    renderLiveRoute();

    expect(
      await screen.findByRole("heading", { name: "实时观战" }),
    ).toHaveClass("mobile-sr-only");
    expect(
      screen.getByRole("button", { name: "返回对局大厅" }),
    ).toBeVisible();
    expect((await screen.findAllByText("经典 8 人"))[0]).toBeVisible();
    expect(screen.queryByText("连接正常")).not.toBeInTheDocument();
    expect(screen.getByText("对局开始")).toBeVisible();
    expect(screen.getByText("第 1 天")).toBeVisible();
    expect(
      screen.getByRole("region", { name: "玩家席位" }),
    ).toBeVisible();
    expect(
      screen.getByRole("article", { name: "1号 阿青 平民 存活" }),
    ).toBeVisible();
    expect(
      screen.getByRole("article", { name: "4号 木子 女巫 存活" }),
    ).toBeVisible();
    expect(gameClientMocks.getGameRun).toHaveBeenCalledWith("run-1");
    expect(gameClientMocks.useGameRunEvents).toHaveBeenCalledWith("run-1");
  });

  it("starts live theater from game_started so startup events do not delay player entry", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [runCreatedEvent, runStartedEvent, startupGameStartedEvent],
      latestEvent: startupGameStartedEvent,
    });

    renderLiveRoute();

    expect(
      await screen.findByRole("article", { name: "1号 阿青 平民 存活" }),
    ).toBeVisible();
    expect(screen.getByText("对局开始")).toBeVisible();
    expect(screen.queryByText("运行已创建")).not.toBeInTheDocument();
    expect(screen.queryByText("运行已开始")).not.toBeInTheDocument();
  });

  it("renders live seat avatars through API asset URLs", async () => {
    renderLiveRoute();

    const seat = await screen.findByRole("article", {
      name: "1号 阿青 平民 存活",
    });
    const avatar = seat.querySelector("img");

    expect(avatar).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
  });

  it("renders live seats as gothic HUD medals with separate nameplates", async () => {
    renderLiveRoute();

    const seat = await screen.findByRole("article", {
      name: "1号 阿青 平民 存活",
    });

    expect(seat.querySelector(".mobile-live-seat-medal")).not.toBeNull();
    expect(seat.querySelector(".mobile-live-seat-nameplate")).not.toBeNull();
    expect(seat.querySelector(".mobile-live-seat-status")).toHaveTextContent("存活");
  });

  it("stagger-reveals live seats from paired left and right first positions", async () => {
    renderLiveRoute();

    const leftFirstSeat = await screen.findByRole("article", {
      name: "1号 阿青 平民 存活",
    });
    const leftSecondSeat = screen.getByRole("article", {
      name: "2号 白石 狼人 存活",
    });
    const rightFirstSeat = screen.getByRole("article", {
      name: "3号 南风 预言家 存活",
    });
    const rightSecondSeat = screen.getByRole("article", {
      name: "4号 木子 女巫 存活",
    });

    expect(leftFirstSeat).toHaveClass("mobile-live-seat-reveal-left");
    expect(rightFirstSeat).toHaveClass("mobile-live-seat-reveal-right");
    expect(leftFirstSeat.getAttribute("style")).toContain(
      "--mobile-live-seat-reveal-delay: 0ms",
    );
    expect(rightFirstSeat.getAttribute("style")).toContain(
      "--mobile-live-seat-reveal-delay: 0ms",
    );
    expect(leftSecondSeat.getAttribute("style")).toContain(
      "--mobile-live-seat-reveal-delay: 90ms",
    );
    expect(rightSecondSeat.getAttribute("style")).toContain(
      "--mobile-live-seat-reveal-delay: 90ms",
    );
  });

  it("renders the current stage presenter with the speaker avatar asset", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, speakingDeltaEvent],
      latestEvent: speakingDeltaEvent,
    });

    renderLiveRoute();

    const stage = await screen.findByRole("region", { name: "当前舞台" });
    expect(within(stage).getByText("阿青")).toBeVisible();
    expect(within(stage).getByText("公开发言")).toBeVisible();
    expect(within(stage).queryByText("model_response_delta")).not.toBeInTheDocument();

    const presenterImage = stage.querySelector(".mobile-live-presenter img");
    expect(presenterImage).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
  });

  it("renders merged mobile live days and seeks by day", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, nightPhaseEvent, dayPhaseEvent],
      latestEvent: dayPhaseEvent,
    });
    const user = userEvent.setup();

    renderLiveRoute();

    expect(
      await screen.findByRole("button", { name: "选择阶段，当前第1天" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "跳转到夜一" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "选择阶段，当前第1天" }));
    expect(screen.getByRole("button", { name: "跳转到第1天" })).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "跳转到昼一" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "跳转到第1天" }));

    expect(screen.getByRole("button", { name: "选择阶段，当前第1天" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("places the mobile phase selector inside the theater top bar", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, nightPhaseEvent, dayPhaseEvent],
      latestEvent: dayPhaseEvent,
    });
    const { container } = renderLiveRoute();

    await screen.findByRole("button", { name: "选择阶段，当前第1天" });

    const topBar = container.querySelector(".mobile-live-theater-top");
    expect(topBar).not.toBeNull();
    expect(
      within(topBar as HTMLElement).getByRole("button", {
        name: "选择阶段，当前第1天",
      }),
    ).toBeVisible();
  });

  it("does not reveal a future speaker delta while playback is paused", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, speakingDeltaEvent],
      latestEvent: speakingDeltaEvent,
    });
    const user = userEvent.setup();

    renderLiveRoute();

    await user.click(await screen.findByRole("button", { name: "暂停" }));
    expect(screen.getByRole("button", { name: "继续" })).toBeVisible();

    const stage = await screen.findByRole("region", { name: "当前舞台" });
    expect(within(stage).queryByText("阿青")).not.toBeInTheDocument();
  });

  it("does not reveal a future speaker delta while catching up backlog", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [
        gameStartedEvent,
        backlogPhaseEvent,
        backlogRequestEvent,
        backlogSpeakingDeltaEvent,
      ],
      latestEvent: backlogSpeakingDeltaEvent,
    });

    renderLiveRoute();

    const stage = await screen.findByRole("region", { name: "当前舞台" });
    expect(within(stage).queryByText("阿青")).not.toBeInTheDocument();
    expect(
      within(stage).queryByText("model_response_delta"),
    ).not.toBeInTheDocument();
  });

  it("renders a lower-third subtitle for public player speech", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, backlogRequestEvent, backlogSpeakingDeltaEvent],
      latestEvent: backlogSpeakingDeltaEvent,
    });
    const user = userEvent.setup();

    renderLiveRoute();

    await user.click(await screen.findByRole("button", { name: "最新" }));

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });

    expect(subtitle).toHaveClass("mobile-live-subtitle");
    expect(subtitle).toHaveClass("mobile-live-subtitle-player-0");
    expect(within(subtitle).getByText("阿青")).toBeVisible();
    expect(within(subtitle).getByText("我先听后置位发言。")).toBeVisible();
  });

  it("renders a judge subtitle for public speech prompts", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, speechRequestEvent],
      latestEvent: speechRequestEvent,
    });
    const user = userEvent.setup();

    renderLiveRoute();

    await user.click(await screen.findByRole("button", { name: "最新" }));

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });

    expect(subtitle).toHaveClass("mobile-live-subtitle-judge");
    expect(within(subtitle).getByText("法官")).toBeVisible();
    expect(within(subtitle).getByText("请听 阿青 的发言。")).toBeVisible();
  });

  it("does not render subtitles for non-speech live events", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent],
      latestEvent: gameStartedEvent,
    });

    renderLiveRoute();

    await screen.findByRole("region", { name: "当前舞台" });

    expect(
      screen.queryByRole("status", { name: "直播字幕" }),
    ).not.toBeInTheDocument();
  });

  it("styles mobile live subtitles as a lower-third speech HUD", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const subtitleRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle\s*{[^}]+}/)?.[0] ?? "";
    const subtitleTextRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle span\s*{[^}]+}/)?.[0] ?? "";
    const judgeRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-judge\s*{[^}]+}/)?.[0] ?? "";
    const playerZeroRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-player-0\s*{[^}]+}/)?.[0] ?? "";
    const shortScreenRule =
      styles.match(
        /@media \(max-height: 860px\) {[\s\S]*?\.mobile-live-subtitle strong,\s*\n\s*\.mobile-live-subtitle span\s*{[^}]+}/,
      )?.[0] ?? "";
    const accentFromRule = (rule: string) =>
      rule.match(/--mobile-live-subtitle-accent:\s*(#[0-9a-fA-F]{6})/)?.[1] ?? "";
    const judgeAccent = accentFromRule(judgeRule);
    const playerAccents = Array.from({ length: 8 }, (_, index) => {
      const playerRule =
        styles.match(
          new RegExp(
            String.raw`(?:^|\n)\.mobile-live-subtitle-player-${index}\s*{[^}]+}`,
          ),
        )?.[0] ?? "";

      return accentFromRule(playerRule);
    });

    expect(subtitleRule).toContain("max-width: 100%");
    expect(subtitleRule).toContain("grid-template-columns: auto minmax(0, 1fr)");
    expect(subtitleTextRule).not.toContain("-webkit-line-clamp");
    expect(subtitleTextRule).not.toContain("text-overflow: ellipsis");
    expect(subtitleTextRule).not.toContain("overflow: hidden");
    expect(subtitleTextRule).toContain("word-break: break-word");
    expect(judgeRule).toContain("--mobile-live-subtitle-accent: #f4c76d");
    expect(playerZeroRule).toContain("--mobile-live-subtitle-accent: #8ddfd0");
    expect(styles).toContain(".mobile-live-subtitle-player-7");
    expect(playerAccents).not.toContain("");
    expect(playerAccents).not.toContain(judgeAccent);
    expect(shortScreenRule).toContain("font-size: 11px");
  });

  it("renders the director controls with gothic icon slots", async () => {
    renderLiveRoute();

    await screen.findByRole("button", { name: "暂停" });

    for (const name of ["暂停", "1x", "最新", "复盘"]) {
      const button = screen.getByRole("button", { name });
      expect(button.querySelector(".mobile-live-control-icon")).not.toBeNull();
      expect(button.querySelector(".mobile-live-control-label")).toHaveTextContent(name);
    }
    const voiceButton = screen.getByRole("button", { name: "开启语音" });
    expect(voiceButton.querySelector(".mobile-live-control-icon")).not.toBeNull();
    expect(voiceButton.querySelector(".mobile-live-control-label")).toHaveTextContent(
      "语音",
    );
    expect(screen.getByRole("button", { name: "复盘" })).toBeDisabled();
  });

  it("unlocks audio before enabling live voice", async () => {
    const user = userEvent.setup();
    unlockAudio.mockImplementation(async () => {
      expect(gameClientMocks.useLiveVoiceStream).toHaveBeenLastCalledWith(
        "run-1",
        expect.objectContaining({ enabled: false }),
      );
      return true;
    });

    renderLiveRoute();

    const voiceButton = await screen.findByRole("button", { name: "开启语音" });
    expect(voiceButton).toBeVisible();

    await user.click(voiceButton);

    expect(unlockAudio).toHaveBeenCalledTimes(1);
    expect(gameClientMocks.useLiveVoiceStream).toHaveBeenLastCalledWith(
      "run-1",
      expect.objectContaining({
        currentEventId: 1,
        enabled: true,
        isPaused: false,
      }),
    );
  });

  it("does not enable live voice when audio unlock fails", async () => {
    const user = userEvent.setup();
    unlockAudio.mockResolvedValue(false);

    renderLiveRoute();

    await user.click(await screen.findByRole("button", { name: "开启语音" }));

    expect(unlockAudio).toHaveBeenCalledTimes(1);
    expect(gameClientMocks.useLiveVoiceStream).toHaveBeenLastCalledWith(
      "run-1",
      expect.objectContaining({
        enabled: false,
      }),
    );
  });

  it("disables the live voice control with an unavailable accessible name", async () => {
    gameClientMocks.useLiveVoiceStream.mockReturnValue({
      connectionState: "unavailable",
      currentItem: null,
      currentSpeakerName: null,
      errors: ["语音模型配置不完整，请检查 Ark API Key、资源 ID 和音色配置。"],
      unlockAudio,
    });

    renderLiveRoute();

    const voiceButton = await screen.findByRole("button", { name: "语音不可用" });

    expect(voiceButton).toBeDisabled();
    expect(voiceButton.querySelector(".mobile-live-control-label")).toHaveTextContent(
      "不可用",
    );
    expect(
      screen.getByText("语音模型配置不完整，请检查 Ark API Key、资源 ID 和音色配置。"),
    ).toBeVisible();
  });

  it("retries live voice without leaving it disabled after an error", async () => {
    const user = userEvent.setup();
    gameClientMocks.useLiveVoiceStream.mockReturnValue({
      connectionState: "error",
      currentItem: null,
      currentSpeakerName: null,
      errors: ["Live voice stream connection failed."],
      unlockAudio,
    });

    renderLiveRoute();

    await user.click(await screen.findByRole("button", { name: "开启语音" }));

    const retryButton = await screen.findByRole("button", { name: "重试语音" });
    expect(retryButton.querySelector(".mobile-live-control-label")).toHaveTextContent(
      "重试",
    );

    await user.click(retryButton);

    await waitFor(() =>
      expect(gameClientMocks.useLiveVoiceStream).toHaveBeenCalledWith(
        "run-1",
        expect.objectContaining({ enabled: false }),
      ),
    );
    await waitFor(() =>
      expect(gameClientMocks.useLiveVoiceStream).toHaveBeenLastCalledWith(
        "run-1",
        expect.objectContaining({ enabled: true }),
      ),
    );
  });

  it("hides the bottom mobile tab bar on the immersive live page", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const tabBarRule =
      styles.match(
        /\.mobile-app-shell:has\(\.mobile-live-page\) \.mobile-tab-bar\s*{[^}]+}/,
      )?.[0] ?? "";
    const contentRegionRule =
      styles.match(
        /\.mobile-app-shell:has\(\.mobile-live-page\) \.mobile-content-region\s*{[^}]+}/,
      )?.[0] ?? "";

    expect(tabBarRule).toContain("display: none");
    expect(contentRegionRule).toContain("padding-bottom: 0");
    expect(contentRegionRule).toContain("overflow: hidden");
  });

  it("constrains the immersive live theater to one viewport", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const pageRule =
      styles.match(/(?:^|\n)\.mobile-live-page\s*{[^}]+}/)?.[0] ?? "";
    const theaterRule =
      styles.match(/(?:^|\n)\.mobile-live-theater\s*{[^}]+}/)?.[0] ?? "";
    const statusBannerRule =
      styles.match(
        /(?:^|\n)\.mobile-live-page:has\(\.mobile-live-theater\) > \.mobile-status-banner\s*{[^}]+}/,
      )?.[0] ?? "";

    expect(pageRule).toContain("height: 100svh");
    expect(pageRule).toContain("padding: 0 var(--mobile-page-padding-inline)");
    expect(theaterRule).toContain("height: 100%");
    expect(theaterRule).toContain("min-height: 0");
    expect(theaterRule).toContain(
      "padding: calc(12px + env(safe-area-inset-top)) 0 calc(10px + env(safe-area-inset-bottom))",
    );
    expect(statusBannerRule).toContain("right: var(--mobile-page-padding-inline)");
    expect(statusBannerRule).toContain("left: var(--mobile-page-padding-inline)");
  });

  it("uses gothic spectator surfaces for the mobile live theater", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const pageRule =
      styles.match(/(?:^|\n)\.mobile-live-page\s*{[^}]+}/)?.[0] ?? "";
    const topBarRule =
      styles.match(/(?:^|\n)\.mobile-live-theater-top\s*{[^}]+}/)?.[0] ?? "";
    const backButtonRule =
      styles.match(/(?:^|\n)\.mobile-live-back-button\s*{[^}]+}/)?.[0] ?? "";
    const genericTopBarDivRule =
      styles.match(/(?:^|\n)\.mobile-live-theater-top div\s*{[^}]+}/)?.[0] ?? "";
    const titleBoardRule =
      styles.match(/(?:^|\n)\.mobile-live-title-board\s*{[^}]+}/)?.[0] ?? "";
    const skyOrbRule =
      styles.match(/(?:^|\n)\.mobile-live-sky-orb\s*{[^}]+}/)?.[0] ?? "";
    const presenterRule =
      styles.match(/(?:^|\n)\.mobile-live-presenter\s*{[^}]+}/)?.[0] ?? "";
    const focusRule =
      styles.match(/(?:^|\n)\.mobile-live-focus-strip\s*{[^}]+}/)?.[0] ?? "";

    expect(pageRule).toContain("mobile-live-arena-background.png");
    expect(topBarRule).toContain("position: relative");
    expect(topBarRule).toContain("justify-content: center");
    expect(topBarRule).toContain("overflow: visible");
    expect(backButtonRule).toContain("lobby-back-button-bg.png");
    expect(backButtonRule).toContain("background: transparent");
    expect(backButtonRule).toContain("position: absolute");
    expect(backButtonRule).toContain("left: 0");
    expect(genericTopBarDivRule).toBe("");
    expect(titleBoardRule).toContain("lobby-wide-title-board.png");
    expect(titleBoardRule).toContain("background: transparent");
    expect(titleBoardRule).toContain("position: absolute");
    expect(titleBoardRule).toContain("left: 50%");
    expect(titleBoardRule).toContain("translate(-50%, -50%)");
    expect(titleBoardRule).toContain("width: min(56%, 340px)");
    expect(titleBoardRule).toContain("lobby-wide-title-board.png");
    expect(skyOrbRule).toContain("border: 3px double");
    expect(presenterRule).toContain("aspect-ratio: 0.66");
    expect(focusRule).toContain("grid-template-columns: 42px minmax(0, 1fr) auto");
  });

  it("styles the selected transparent director HUD reference", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const dayBannerRule =
      styles.match(/(?:^|\n)\.mobile-live-day-banner\s*{[^}]+}/)?.[0] ?? "";
    const seatStageAfterRule =
      [...styles.matchAll(/(?:^|\n)\.mobile-live-seat-stage::after\s*{[^}]+}/g)]
        .map((match) => match[0])
        .find((rule) => rule.includes("radial-gradient(ellipse at 50% 88%")) ?? "";
    const seatMedalRule =
      styles.match(/(?:^|\n)\.mobile-live-seat-medal\s*{[^}]+}/)?.[0] ?? "";
    const nameplateRule =
      styles.match(/(?:^|\n)\.mobile-live-seat-nameplate\s*{[^}]+}/)?.[0] ?? "";
    const actionBarRule =
      styles.match(/(?:^|\n)\.mobile-live-action-bar\s*{[^}]+}/)?.[0] ?? "";
    const actionButtonRule =
      styles.match(
        /(?:^|\n)\.mobile-live-action-bar \.mobile-button,\s*\n\.mobile-live-link\s*{[^}]+}/,
      )?.[0] ?? "";
    const liveNarrowBlockStart = styles.indexOf(
      "@media (max-width: 360px)",
      styles.indexOf(".mobile-live-action-bar"),
    );
    const liveNarrowBlockEnd = styles.indexOf(
      "@media (max-height: 860px)",
      liveNarrowBlockStart,
    );
    const liveNarrowBlock = styles.slice(liveNarrowBlockStart, liveNarrowBlockEnd);
    const narrowActionBarRule =
      liveNarrowBlock.match(
        /(?:^|\n)\s*\.mobile-live-action-bar\s*{[^}]+}/,
      )?.[0] ?? "";

    expect(dayBannerRule).toContain("lobby-action-bar-bg.png");
    expect(dayBannerRule).toContain("border-radius: 0");
    expect(dayBannerRule).toContain("right: calc(-1 * var(--mobile-page-padding-inline))");
    expect(dayBannerRule).toContain("left: calc(-1 * var(--mobile-page-padding-inline))");
    expect(dayBannerRule).toContain("min-height: 64px");
    expect(dayBannerRule).toContain("rgb(106 15 24 / 44%)");
    expect(seatStageAfterRule).toContain("radial-gradient(ellipse at 50% 88%");
    expect(seatMedalRule).toContain("lobby-profile-card-light-frame-alpha.png");
    expect(nameplateRule).toContain("lobby-settings-field-bg.png");
    expect(actionBarRule).toContain("lobby-action-bar-bg.png");
    expect(actionBarRule).toContain("grid-template-columns: repeat(5, minmax(0, 1fr))");
    expect(actionButtonRule).toContain("border-radius: 0");
    expect(narrowActionBarRule).toContain("gap: 4px");
    expect(narrowActionBarRule).toContain("padding: 11px 8px 10px");
  });

  it("defines staged reveal motion for live seats with reduced-motion fallback", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const seatRule =
      styles.match(/(?:^|\n)\.mobile-live-seat\s*{[^}]+}/)?.[0] ?? "";

    expect(seatRule).toContain("animation: mobile-live-seat-reveal");
    expect(styles).toContain("@keyframes mobile-live-seat-reveal");
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\) {[\s\S]*?\.mobile-live-seat\s*{[^}]+animation: none/,
    );
  });

  it("styles the mobile day panel below the top-right day trigger", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const phaseBarRule =
      styles.match(/(?:^|\n)\.mobile-live-phase-bar\s*{[^}]+}/)?.[0] ?? "";
    const triggerRule =
      styles.match(/(?:^|\n)\.mobile-live-phase-trigger\s*{[^}]+}/)?.[0] ?? "";
    const popoverRule =
      styles.match(/(?:^|\n)\.mobile-live-phase-popover\s*{[^}]+}/)?.[0] ?? "";
    const currentButtonRule =
      styles.match(/(?:^|\n)\.mobile-live-phase-button-current\s*{[^}]+}/)?.[0] ?? "";
    const theaterRule =
      styles.match(/(?:^|\n)\.mobile-live-theater\s*{[^}]+}/)?.[0] ?? "";

    expect(theaterRule).toContain(
      "grid-template-rows: auto minmax(128px, 20svh) minmax(0, 1fr) auto",
    );
    expect(phaseBarRule).toContain("position: absolute");
    expect(phaseBarRule).toContain("right: 0");
    expect(phaseBarRule).toContain("top: calc(50% - 17px)");
    expect(phaseBarRule).toContain("width: var(--mobile-live-phase-width)");
    expect(phaseBarRule).not.toContain("transform");
    expect(triggerRule).toContain("border-radius: 0");
    expect(triggerRule).toContain("width: 100%");
    expect(popoverRule).toContain("position: absolute");
    expect(popoverRule).toContain("top: calc(100% - 1px)");
    expect(popoverRule).toContain("right: 0");
    expect(popoverRule).toContain("left: auto");
    expect(popoverRule).toContain("transform: none");
    expect(popoverRule).toContain("width: 100%");
    expect(popoverRule).toContain(
      "max-height: min(380PX, calc(100svh - 76PX))",
    );
    expect(popoverRule).toContain("border-radius: 0");
    expect(popoverRule).toContain("backdrop-filter: blur(14px)");
    expect(popoverRule).toContain("background: rgb(6 9 14 / 62%)");
    expect(currentButtonRule).toContain("border-radius: 0");
  });

  it("uses a transparent lobby back button asset", () => {
    expect(readPngMetadata("src/assets/lobby-back-button-bg.png")).toEqual({
      colorType: 6,
      height: 216,
      width: 216,
    });
  });

  it("does not layer generated backgrounds over the full-screen live image", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const pageRule =
      styles.match(/(?:^|\n)\.mobile-live-page\s*{[^}]+}/)?.[0] ?? "";
    const pageOverlayRule =
      styles.match(/(?:^|\n)\.mobile-live-page::before\s*{[^}]+}/)?.[0] ?? "";
    const shellLiveBackgroundRule =
      styles.match(
        /(?:^|\n)\.mobile-app-shell:has\(\.mobile-live-page\)::before\s*{[^}]+}/,
      )?.[0] ?? "";
    const theaterBeforeRule =
      styles.match(/(?:^|\n)\.mobile-live-theater::before\s*{[^}]+}/)?.[0] ?? "";
    const theaterAfterRule =
      styles.match(/(?:^|\n)\.mobile-live-theater::after\s*{[^}]+}/)?.[0] ?? "";

    expect(pageRule).toContain("mobile-live-arena-background.png");
    expect(pageRule).not.toContain("mobile-gothic-castle-background.png");
    expect(pageRule).toContain("center top / cover no-repeat");
    expect(pageOverlayRule).toBe("");
    expect(shellLiveBackgroundRule).toContain("content: none");
    expect(theaterBeforeRule).toBe("");
    expect(theaterAfterRule).toBe("");
  });

  it("uses the portrait gothic arena image as the live background", () => {
    expect(
      readPngMetadata("src/assets/mobile-live-arena-background.png"),
    ).toEqual({
      colorType: 2,
      height: 1828,
      width: 860,
    });
  });

  it("keeps the lobby shell background on its original asset", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const shellBackgroundRule =
      styles.match(/(?:^|\n)\.mobile-app-shell::before\s*{[^}]+}/)?.[0] ?? "";

    expect(shellBackgroundRule).toContain("mobile-gothic-castle-background.png");
    expect(
      readPngMetadata("src/assets/mobile-gothic-castle-background.png"),
    ).toEqual({
      colorType: 2,
      height: 1870,
      width: 841,
    });
  });

  it("compresses theater seats on short phone screens", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");

    expect(styles).toMatch(
      /@media \(max-height: 860px\) {[\s\S]*?\.mobile-live-seat-medal\s*{[^}]+width: clamp\(38px, 11\.2vw, 48px\)/,
    );
    expect(styles).toMatch(
      /@media \(max-height: 700px\) {[\s\S]*?\.mobile-live-seat small\s*{[^}]+display: none/,
    );
  });
});
