import { readFileSync } from "node:fs";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const coalescedSpeechEvents: LiveGameEvent[] = [
  gameStartedEvent,
  {
    ...gameStartedEvent,
    id: 91,
    type: "action_requested",
    actor: "阿青",
    action: "sheriff_speech",
    payload: { options: [], result_key: "say" },
  },
  {
    ...gameStartedEvent,
    id: 92,
    type: "model_request_started",
    actor: "阿青",
    action: "sheriff_speech",
    payload: { request_id: "req-coalesced" },
  },
  {
    ...gameStartedEvent,
    id: 93,
    type: "model_response_delta",
    actor: "阿青",
    action: "sheriff_speech",
    payload: { request_id: "req-coalesced", visible_text: "我是1号玩家。" },
  },
  {
    ...gameStartedEvent,
    id: 129,
    type: "model_response_delta",
    actor: "阿青",
    action: "sheriff_speech",
    payload: {
      request_id: "req-coalesced",
      visible_text:
        "这是一段足够长的竞选发言，用来覆盖导演的最长文字展示时间，但语音应当在第一段内容到达舞台时立即开始。",
    },
  },
  {
    ...gameStartedEvent,
    id: 130,
    type: "model_response_received",
    actor: "阿青",
    action: "sheriff_speech",
    payload: { request_id: "req-coalesced", message: "模型返回已接收" },
  },
  {
    ...gameStartedEvent,
    id: 131,
    type: "action_parsed",
    actor: "阿青",
    action: "sheriff_speech",
    payload: {
      request_id: "req-coalesced",
      choice:
        "我是1号玩家。这是一段足够长的竞选发言，用来覆盖导演的最长文字展示时间，但语音应当在第一段内容到达舞台时立即开始。",
      visible_result: {
        say:
          "我是1号玩家。这是一段足够长的竞选发言，用来覆盖导演的最长文字展示时间，但语音应当在第一段内容到达舞台时立即开始。",
      },
    },
  },
];

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

const nightEliminationEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "state_updated",
  round: 1,
  phase: "night",
  actor: null,
  action: null,
  payload: {
    active_players: ["白石", "南风", "木子"],
    eliminated: "阿青",
  },
};

const dayExileEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 3,
  type: "state_updated",
  round: 1,
  phase: "day",
  actor: null,
  action: null,
  payload: {
    active_players: ["南风", "木子"],
    exiled: "白石",
  },
};

const sheriffElectedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "state_updated",
  round: 1,
  phase: "day",
  actor: "南风",
  action: null,
  payload: {
    sheriff: "南风",
    sheriff_elected: "南风",
    sheriff_candidates: ["白石", "南风"],
    sheriff_final_candidates: ["白石", "南风"],
    sheriff_voters: ["阿青", "木子"],
    sheriff_votes: { 阿青: "南风", 木子: "南风" },
    sheriff_runoff_votes: {},
    sheriff_badge_lost: false,
    active_players: ["阿青", "白石", "南风", "木子"],
  },
};

const failedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "game_failed",
  actor: null,
  action: null,
  payload: {
    error:
      'DeepSeek request failed with HTTP 402: {"error":{"message":"Insufficient Balance"}}',
  },
};

const nightPhaseStartEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "phase_started",
  round: 1,
  phase: "night",
  actor: null,
  action: null,
  payload: { active_players: ["阿青", "白石", "南风", "木子"] },
};

const werewolfKillParsedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 3,
  type: "action_parsed",
  round: 1,
  phase: "night",
  actor: "白石",
  action: "remove",
  payload: { choice: "阿青" },
};

const votePhaseStartEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "phase_started",
  round: 1,
  phase: "vote",
  actor: null,
  action: null,
  payload: { active_players: ["白石", "南风", "木子"] },
};

const firstVoteParsedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 3,
  type: "action_parsed",
  round: 1,
  phase: "vote",
  actor: "白石",
  action: "vote",
  payload: { choice: "南风" },
};

const secondVoteParsedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 4,
  type: "action_parsed",
  round: 1,
  phase: "vote",
  actor: "南风",
  action: "vote",
  payload: { choice: "白石" },
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
    vi.useRealTimers();
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
    expect(
      screen.getByRole("status", { name: "当前舞台" }).querySelector("strong"),
    ).toHaveTextContent("对局开始");
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
    expect(gameClientMocks.useGameRunEvents).toHaveBeenCalledWith(
      "run-1",
      "spectator_god_view",
    );
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
    expect(
      screen.getByRole("status", { name: "当前舞台" }).querySelector("strong"),
    ).toHaveTextContent("对局开始");
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

  it("renders live seats as compact gothic HUD medals without names or status text", async () => {
    renderLiveRoute();

    const seat = await screen.findByRole("article", {
      name: "1号 阿青 平民 存活",
    });

    expect(seat.querySelector(".mobile-live-seat-medal")).not.toBeNull();
    expect(seat.querySelector(".mobile-live-seat-nameplate")).toBeNull();
    expect(seat.querySelector(".mobile-live-seat-status")).toBeNull();
    expect(seat).not.toHaveTextContent("阿青");
    expect(seat).not.toHaveTextContent("存活");
  });

  it("shows the sheriff election result and marks the elected player's avatar", async () => {
    const user = userEvent.setup();
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, sheriffElectedEvent],
      latestEvent: sheriffElectedEvent,
    });

    renderLiveRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const stage = screen.getByRole("status", { name: "当前舞台" });
    expect(stage.querySelector("strong")).toHaveTextContent("3号 当选警长");
    expect(stage.querySelector(".mobile-live-action-detail")).toHaveTextContent(
      "2票当选 · 获得警徽",
    );
    const sheriffSeat = screen.getByRole("article", {
      name: /3号 南风 预言家 .* 警长/,
    });
    expect(sheriffSeat).toHaveClass("mobile-live-seat-sheriff");
    expect(
      within(sheriffSeat).getByRole("img", { name: "警长，持有警徽" }),
    ).toHaveClass("mobile-live-seat-sheriff-badge");
  });

  it("marks players who raised their hands during the parallel sheriff sign-up", async () => {
    const user = userEvent.setup();
    const sheriffRunEvents: LiveGameEvent[] = [
      gameStartedEvent,
      {
        ...gameStartedEvent,
        id: 2,
        type: "action_requested",
        actor: "阿青",
        action: "sheriff_run",
        payload: { options: ["上警", "不上警"] },
      },
      {
        ...gameStartedEvent,
        id: 3,
        type: "action_requested",
        actor: "白石",
        action: "sheriff_run",
        payload: { options: ["上警", "不上警"] },
      },
      {
        ...gameStartedEvent,
        id: 4,
        type: "action_parsed",
        actor: "阿青",
        action: "sheriff_run",
        payload: { choice: "上警" },
      },
      {
        ...gameStartedEvent,
        id: 5,
        type: "action_parsed",
        actor: "白石",
        action: "sheriff_run",
        payload: { choice: "不上警" },
      },
    ];
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: sheriffRunEvents,
      latestEvent: sheriffRunEvents.at(-1),
    });

    renderLiveRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const raisedSeat = screen.getByRole("article", {
      name: /1号 阿青 平民 .* 举手上警/,
    });
    expect(
      within(raisedSeat).getByRole("img", { name: "举手上警" }),
    ).toHaveClass("mobile-live-seat-raised-hand");
    expect(
      screen.getByRole("article", { name: /2号 白石 狼人/ }),
    ).not.toHaveAccessibleName(/举手上警/);
    expect(screen.getByRole("status", { name: "当前舞台" })).toHaveTextContent(
      "上警结果",
    );
  });

  it("marks night eliminations and daytime exiles over grayscale avatars", async () => {
    const user = userEvent.setup();
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, nightEliminationEvent, dayExileEvent],
      latestEvent: dayExileEvent,
    });

    renderLiveRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const nightSeat = await screen.findByRole("article", {
      name: "1号 阿青 平民 夜晚出局",
    });
    const daySeat = screen.getByRole("article", {
      name: "2号 白石 狼人 白天放逐",
    });

    expect(nightSeat).toHaveClass("mobile-live-seat-out");
    expect(daySeat).toHaveClass("mobile-live-seat-out");
    expect(within(nightSeat).getByRole("img", { name: "夜晚出局" })).toHaveClass(
      "mobile-live-seat-outcome-night",
    );
    expect(within(daySeat).getByRole("img", { name: "白天驱逐" })).toHaveClass(
      "mobile-live-seat-outcome-day-exile",
    );
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

    const stage = await screen.findByRole("status", { name: "当前舞台" });
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

    const stage = await screen.findByRole("status", { name: "当前舞台" });
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

    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).queryByText("阿青")).not.toBeInTheDocument();
    expect(
      within(stage).queryByText("model_response_delta"),
    ).not.toBeInTheDocument();
  });

  it("does not render event-derived subtitles without voice timing", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, backlogRequestEvent, backlogSpeakingDeltaEvent],
      latestEvent: backlogSpeakingDeltaEvent,
    });
    const user = userEvent.setup();

    renderLiveRoute();

    await user.click(await screen.findByRole("button", { name: "最新" }));

    await screen.findByRole("status", { name: "当前舞台" });
    expect(
      screen.queryByRole("status", {
        name: "直播字幕",
      }),
    ).not.toBeInTheDocument();
  });

  it("renders a lower-third subtitle from live voice timing", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, backlogRequestEvent, backlogSpeakingDeltaEvent],
      latestEvent: backlogSpeakingDeltaEvent,
    });
    gameClientMocks.useLiveVoiceStream.mockReturnValue({
      connectionState: "open",
      currentItem: {
        lastSourceEventId: 4,
        sourceEventId: 4,
        status: "playing",
      },
      currentSpeakerName: "1号玩家",
      currentSubtitle: {
        activeText: "听",
        completedText: "我先",
        pageIndex: 0,
        pendingText: "后置位发言。",
        speakerKind: "player",
        speakerName: "1号玩家",
        text: "我先听后置位发言。",
        utteranceId: "voice-1",
      },
      errors: [],
      unlockAudio,
    });
    const user = userEvent.setup();

    renderLiveRoute();

    await user.click(await screen.findByRole("button", { name: "最新" }));

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });

    expect(subtitle).toHaveClass("mobile-live-subtitle");
    expect(subtitle).toHaveClass("mobile-live-subtitle-player-0");
    expect(within(subtitle).getByText("1号玩家")).toBeVisible();
    expect(within(subtitle).getByLabelText("我先听后置位发言")).toBeVisible();
    expect(
      subtitle.querySelector(".mobile-live-subtitle-completed"),
    ).toHaveTextContent("我先");
    expect(
      subtitle.querySelector(".mobile-live-subtitle-active"),
    ).toHaveTextContent("听");
    expect(
      subtitle.querySelector(".mobile-live-subtitle-pending"),
    ).toHaveTextContent("后置位发言");
    expect(
      within(await screen.findByRole("status", { name: "当前舞台" })).queryByRole(
        "status",
        { name: "直播字幕" },
      ),
    ).not.toBeInTheDocument();
  });

  it("renders judge subtitles from live voice timing", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent],
      latestEvent: gameStartedEvent,
    });
    gameClientMocks.useLiveVoiceStream.mockReturnValue({
      connectionState: "open",
      currentItem: {
        lastSourceEventId: 1,
        sourceEventId: 1,
        status: "playing",
      },
      currentSpeakerName: "法官",
      currentSubtitle: {
        speakerKind: "judge",
        speakerName: "法官",
        text: "本局游戏开始，请所有玩家确认自己的身份牌。",
        utteranceId: "voice-judge",
      },
      errors: [],
      unlockAudio,
    });

    renderLiveRoute();

    await screen.findByRole("status", { name: "当前舞台" });

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });

    expect(subtitle).toHaveClass("mobile-live-subtitle-judge");
    expect(within(subtitle).getByText("法官")).toBeVisible();
    expect(
      within(subtitle).getByLabelText("本局游戏开始请所有玩家确认自己的身份牌"),
    ).toBeVisible();
  });

  it("styles mobile live subtitles as a full-width single-line KTV HUD", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const seatStageRule =
      styles.match(/(?:^|\n)\.mobile-live-seat-stage\s*{[^}]+}/)?.[0] ?? "";
    const subtitleRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle\s*{[^}]+}/)?.[0] ?? "";
    const speakerRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle\s*>\s*strong\s*{[^}]+}/)?.[0] ?? "";
    const subtitleTextRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-text\s*{[^}]+}/)?.[0] ?? "";
    const activeTextRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-active\s*{[^}]+}/)?.[0] ?? "";
    const completedTextRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-completed\s*{[^}]+}/)?.[0] ?? "";
    const pendingTextRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-pending\s*{[^}]+}/)?.[0] ?? "";
    const judgeRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-judge\s*{[^}]+}/)?.[0] ?? "";
    const playerZeroRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-player-0\s*{[^}]+}/)?.[0] ?? "";
    const shortScreenRule =
      styles.match(
        /@media \(max-height: 860px\) {[\s\S]*?\.mobile-live-subtitle-text\s*{[^}]+}/,
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

    expect(subtitleRule).toContain("position: absolute");
    expect(subtitleRule).toContain("right: 10px");
    expect(subtitleRule).toContain("left: 10px");
    expect(subtitleRule).toContain("display: flex");
    expect(subtitleRule).toContain("justify-content: center");
    expect(subtitleRule).toContain("min-height: 44px");
    expect(seatStageRule).toContain("padding-bottom: 48px");
    expect(speakerRule).toContain("font-size: 13px");
    expect(subtitleTextRule).not.toContain("-webkit-line-clamp");
    expect(subtitleTextRule).toContain("font-size: 16px");
    expect(subtitleTextRule).toContain("text-overflow: clip");
    expect(subtitleTextRule).toContain("overflow: hidden");
    expect(subtitleTextRule).toContain("white-space: nowrap");
    expect(subtitleTextRule).toContain("word-break: normal");
    expect(activeTextRule).toContain("var(--mobile-live-subtitle-accent)");
    expect(completedTextRule).toContain("var(--mobile-live-subtitle-accent)");
    expect(pendingTextRule).toContain("62%");
    expect(judgeRule).toContain("--mobile-live-subtitle-accent: #f4c76d");
    expect(playerZeroRule).toContain("--mobile-live-subtitle-accent: #8ddfd0");
    expect(styles).toContain(".mobile-live-subtitle-player-7");
    expect(playerAccents).not.toContain("");
    expect(playerAccents).not.toContain(judgeAccent);
    expect(shortScreenRule).toContain("font-size: 15px");
  });

  it("renders the director controls with gothic icon slots", async () => {
    renderLiveRoute();

    await screen.findByRole("button", { name: "暂停" });

    for (const name of ["暂停", "1x", "最新", "复盘"]) {
      const button = screen.getByRole("button", { name });
      expect(button.querySelector(".mobile-live-control-icon")).not.toBeNull();
      expect(button.querySelector(".mobile-live-control-label")).toHaveTextContent(name);
    }
    const voiceButton = screen.getByRole("button", { name: "关闭语音" });
    expect(voiceButton.querySelector(".mobile-live-control-icon")).not.toBeNull();
    expect(voiceButton.querySelector(".mobile-live-control-label")).toHaveTextContent(
      "语音",
    );
    expect(screen.getByRole("button", { name: "复盘" })).toBeDisabled();
  });

  it("enables and unlocks live voice automatically on entry", async () => {
    renderLiveRoute();

    const voiceButton = await screen.findByRole("button", { name: "关闭语音" });
    expect(voiceButton).toBeVisible();

    await waitFor(() => expect(unlockAudio).toHaveBeenCalledTimes(1));
    expect(gameClientMocks.useLiveVoiceStream).toHaveBeenLastCalledWith(
      "run-1",
      expect.objectContaining({
        currentEventId: 1,
        enabled: true,
        isPaused: false,
      }),
    );
  });

  it("holds the speech cue when coalesced voice reaches its first source event", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: coalescedSpeechEvents,
      latestEvent: coalescedSpeechEvents.at(-1) ?? null,
    });
    gameClientMocks.useLiveVoiceStream.mockReturnValue({
      connectionState: "open",
      currentItem: {
        lastSourceEventId: 131,
        sourceEventId: 93,
        status: "playing",
      },
      currentSpeakerName: "1号玩家",
      currentSubtitle: null,
      errors: [],
      unlockAudio,
    });
    const user = userEvent.setup();

    renderLiveRoute();

    await user.click(await screen.findByRole("button", { name: "暂停" }));
    await user.click(screen.getByRole("button", { name: "最新" }));
    await waitFor(() =>
      expect(gameClientMocks.useLiveVoiceStream).toHaveBeenLastCalledWith(
        "run-1",
        expect.objectContaining({ currentEventId: 129 }),
      ),
    );

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    act(() => {
      vi.advanceTimersByTime(30000);
    });

    expect(gameClientMocks.useLiveVoiceStream).toHaveBeenLastCalledWith(
      "run-1",
      expect.objectContaining({ currentEventId: 129 }),
    );
  });

  it("allows manually disabling live voice after automatic startup", async () => {
    const user = userEvent.setup();

    renderLiveRoute();

    await user.click(await screen.findByRole("button", { name: "关闭语音" }));

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

  it("shows the recorded failure reason when a live run fails", async () => {
    gameClientMocks.getGameRun.mockResolvedValue({
      ...run,
      status: "failed",
      error:
        'DeepSeek request failed with HTTP 402: {"error":{"message":"Insufficient Balance"}}',
    });
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "closed",
      events: [gameStartedEvent, failedEvent],
      latestEvent: failedEvent,
    });

    renderLiveRoute();

    expect(
      await screen.findByText(
        'DeepSeek request failed with HTTP 402: {"error":{"message":"Insufficient Balance"}}',
      ),
    ).toBeVisible();
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
    const nightOutcomeRule =
      styles.match(/(?:^|\n)\.mobile-live-seat-outcome-night\s*{[^}]+}/)?.[0] ?? "";
    const outAvatarRule =
      styles.match(/(?:^|\n)\.mobile-live-seat-out \.mobile-live-seat-avatar\s*{[^}]+}/)?.[0] ?? "";
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
    expect(nightOutcomeRule).toContain("color: #f23d47");
    expect(outAvatarRule).toContain("filter: grayscale(1)");
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
      "grid-template-rows: auto minmax(108px, 18svh) minmax(0, 1fr) auto auto",
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

  it("shows the night action actor and target in the action focus card", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, nightPhaseStartEvent, werewolfKillParsedEvent],
      latestEvent: werewolfKillParsedEvent,
    });
    const user = userEvent.setup();

    renderLiveRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).getByText("狼人最终目标")).toBeVisible();
    expect(within(stage).getByText("袭击 1号")).toBeVisible();
  });

  it("emphasizes every living wolf while the werewolf team is choosing", async () => {
    const teamStartedEvent: LiveGameEvent = {
      ...gameStartedEvent,
      payload: {
        players: [
          { name: "阿青", role: "villager", model: "test-model" },
          { name: "白石", role: "werewolf", model: "test-model" },
          { name: "南风", role: "werewolf", model: "test-model" },
          { name: "木子", role: "witch", model: "test-model" },
        ],
      },
    };
    const teamRequestEvent: LiveGameEvent = {
      ...gameStartedEvent,
      id: 2,
      type: "action_requested",
      phase: "night",
      actor: "白石",
      action: "remove",
      payload: { options: ["阿青", "木子"] },
    };
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [teamStartedEvent, teamRequestEvent],
      latestEvent: teamRequestEvent,
    });
    const user = userEvent.setup();

    renderLiveRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    expect(
      screen.getByRole("article", { name: "2号 白石 狼人 夜间行动中" }),
    ).toHaveClass("mobile-live-seat-acting");
    expect(
      screen.getByRole("article", { name: "3号 南风 狼人 存活" }),
    ).toHaveClass("mobile-live-seat-acting");
    expect(
      screen.getByRole("article", { name: "1号 阿青 平民 存活" }),
    ).not.toHaveClass("mobile-live-seat-acting");
  });

  it("shows each wolf's target and the final wolf kill in the report", async () => {
    const teamStartedEvent: LiveGameEvent = {
      ...gameStartedEvent,
      payload: {
        players: [
          { name: "阿青", role: "villager", model: "test-model" },
          { name: "白石", role: "werewolf", model: "test-model" },
          { name: "南风", role: "werewolf", model: "test-model" },
          { name: "木子", role: "witch", model: "test-model" },
        ],
      },
    };
    const wolfVote = (
      id: number,
      actor: string,
      choice: string,
      voteRound: number,
    ): LiveGameEvent => ({
      ...gameStartedEvent,
      id,
      type: "action_parsed",
      phase: "night",
      actor,
      action: "werewolf_kill_vote",
      payload: { choice, vote_round: voteRound },
    });
    const finalTarget: LiveGameEvent = {
      ...gameStartedEvent,
      id: 6,
      type: "action_parsed",
      phase: "night",
      actor: null,
      action: "remove",
      payload: { choice: "阿青", vote_round: 2, final_target: true },
    };
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [
        teamStartedEvent,
        wolfVote(2, "白石", "阿青", 1),
        wolfVote(3, "南风", "木子", 1),
        wolfVote(4, "白石", "阿青", 2),
        wolfVote(5, "南风", "阿青", 2),
        finalTarget,
      ],
      latestEvent: finalTarget,
    });
    const user = userEvent.setup();

    renderLiveRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const rail = screen.getByRole("log");
    expect(within(rail).getAllByText("2号 刀票 -> 1号")).toHaveLength(2);
    expect(within(rail).getByText("3号 刀票 -> 4号")).toBeVisible();
    expect(within(rail).getByText("3号 刀票 -> 1号")).toBeVisible();
    expect(within(rail).getByText("最终狼刀 -> 1号")).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: /查看全部战报，共 \d+ 条/ }),
    );
    const dialog = await screen.findByRole("dialog", { name: "本轮战报" });
    await user.click(
      within(dialog).getByRole("button", {
        name: /跳转到战报：3号 刀票 -> 4号/,
      }),
    );

    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).getByText("3号 南风")).toBeVisible();
    expect(within(stage).getByText("选择袭击目标")).toBeVisible();
    expect(within(stage).getByText("投 4号")).toBeVisible();
  });

  it("renders the vote focus and a persisted event rail behind the director", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [
        gameStartedEvent,
        votePhaseStartEvent,
        firstVoteParsedEvent,
        secondVoteParsedEvent,
      ],
      latestEvent: secondVoteParsedEvent,
    });
    const user = userEvent.setup();

    renderLiveRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).getByText("3号 -> 2号")).toBeVisible();

    const rail = screen.getByRole("log");
    // Only director-visible moments appear; no future second-vote before catch-up.
    expect(within(rail).getByText("投票阶段开始")).toBeVisible();
    expect(within(rail).getByText("2号 -> 3号")).toBeVisible();
    expect(within(rail).getByText("3号 -> 2号")).toBeVisible();
    expect(within(rail).queryByText("model_response_delta")).not.toBeInTheDocument();
  });

  it("seeks the director when selecting an older event from the event sheet", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [
        gameStartedEvent,
        votePhaseStartEvent,
        firstVoteParsedEvent,
        secondVoteParsedEvent,
      ],
      latestEvent: secondVoteParsedEvent,
    });
    gameClientMocks.useLiveVoiceStream.mockReturnValue({
      connectionState: "idle",
      currentItem: null,
      currentSpeakerName: null,
      errors: [],
      unlockAudio,
    });
    const user = userEvent.setup();

    renderLiveRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    // Catch up to latest so all moments are visible, then open the sheet.
    const railAll = screen.getByRole("button", {
      name: /查看全部战报，共 \d+ 条/,
    });
    await user.click(railAll);

    const dialog = await screen.findByRole("dialog", { name: "本轮战报" });
    const olderRow = within(dialog).getByRole("button", {
      name: /跳转到战报：投票阶段开始/,
    });
    await user.click(olderRow);

    expect(dialog).not.toBeInTheDocument();
    // After seeking to the phase-start event, the focus card shows the vote phase start.
    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).getByText("白天投票开始")).toBeVisible();
  });

  it("does not reveal a future vote event while the director is behind backlog", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [
        gameStartedEvent,
        votePhaseStartEvent,
        firstVoteParsedEvent,
        secondVoteParsedEvent,
      ],
      latestEvent: secondVoteParsedEvent,
    });

    renderLiveRoute();

    const rail = await screen.findByRole("log");
    // Director starts at game_started; the parsed vote must not be visible yet.
    expect(within(rail).queryByText("2号 -> 3号")).not.toBeInTheDocument();

    await userEvent.click(await screen.findByRole("button", { name: "最新" }));
    expect(within(rail).getByText("2号 -> 3号")).toBeInTheDocument();
  });
});
