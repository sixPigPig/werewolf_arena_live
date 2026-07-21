import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveReplayPage } from "./LiveReplayPage";
import type { GamePlayback, LiveGameEvent } from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  getGamePlayback: vi.fn(),
  getGamePlaybackVoice: vi.fn(),
  resumeGameRun: vi.fn(),
  useLiveDirector: vi.fn(),
  usePlaybackVoice: vi.fn(),
}));

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );

  return {
    ...actual,
    getGamePlayback: gameClientMocks.getGamePlayback,
    getGamePlaybackVoice: gameClientMocks.getGamePlaybackVoice,
    resumeGameRun: gameClientMocks.resumeGameRun,
    useLiveDirector: (...args: Parameters<typeof actual.useLiveDirector>) => {
      gameClientMocks.useLiveDirector(...args);
      return actual.useLiveDirector(...args);
    },
    usePlaybackVoice: gameClientMocks.usePlaybackVoice,
  };
});

const gameStartedEvent: LiveGameEvent = {
  id: 1,
  type: "game_started",
  run_id: "playback_session-1",
  session_id: "session-1",
  created_at: "2026-06-19T00:00:00Z",
  round: null,
  phase: null,
  actor: null,
  action: null,
  payload: {
    players: [
      { name: "阿青", role: "villager", model: "test-model" },
      { name: "白石", role: "werewolf", model: "test-model" },
      { name: "南风", role: "seer", model: "test-model" },
      { name: "木子", role: "witch", model: "test-model" },
    ],
  },
};

const phaseStartedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "phase_started",
  round: 1,
  phase: "day",
  payload: {
    active_players: ["阿青", "白石", "南风", "木子"],
    phase: "day",
  },
};

const requestStartedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 3,
  type: "model_request_started",
  round: 1,
  phase: "day",
  actor: "阿青",
  action: "debate",
  payload: { request_id: "req-1" },
};

const responseDeltaEvent: LiveGameEvent = {
  ...requestStartedEvent,
  id: 4,
  type: "model_response_delta",
  payload: {
    request_id: "req-1",
    visible_text: "我先听后置位发言。",
  },
};

const completedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 5,
  type: "game_completed",
  round: 1,
  phase: "day",
  payload: {
    winner: "villagers",
    terminal_keep_from_event_id: 4,
  },
};

const failedEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 5,
  type: "game_failed",
  round: 1,
  phase: "day",
  payload: { error: "模型中断" },
};

function buildPlayback(overrides: Partial<GamePlayback> = {}): GamePlayback {
  return {
    session_id: "session-1",
    status: "complete",
    rule_set: {
      id: "classic_8",
      version: "test",
      name: "经典 8 人",
      player_count: 8,
      roles: [],
    },
    resumable: false,
    voices: [],
    events: [
      gameStartedEvent,
      phaseStartedEvent,
      requestStartedEvent,
      responseDeltaEvent,
      completedEvent,
    ],
    ...overrides,
  };
}

function renderLiveReplayRoute() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter(
    [
      { path: "/games/:gameId/live-replay", element: <LiveReplayPage /> },
      { path: "/games/:gameId/live", element: <h1>实时观战</h1> },
      { path: "/games/:gameId/replay", element: <h1>移动复盘</h1> },
      { path: "/history", element: <h1>对局历史</h1> },
    ],
    { initialEntries: ["/games/session-1/live-replay"] },
  );

  const renderResult = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  return { router, ...renderResult };
}

describe("LiveReplayPage", () => {
  beforeEach(() => {
    gameClientMocks.getGamePlayback.mockResolvedValue(buildPlayback());
    gameClientMocks.resumeGameRun.mockResolvedValue({
      run_id: "run-resumed",
      session_id: "session-1",
    });
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "idle",
      currentSpeakerName: null,
      errors: [],
      unlockAudio: vi.fn(async () => true),
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads saved playback events and starts from the first event", async () => {
    renderLiveReplayRoute();

    expect(
      await screen.findByRole("heading", { name: "历史直播回放" }),
    ).toHaveClass("mobile-sr-only");
    expect((await screen.findAllByText("经典 8 人"))[0]).toBeVisible();
    expect(screen.getByRole("region", { name: "实时观战剧场" })).toHaveClass(
      "mobile-live-theater",
    );
    expect(screen.getByText("历史回放")).toBeVisible();

    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(stage.querySelector("strong")).toHaveTextContent("对局开始");
    expect(within(stage).queryByText("game_started")).not.toBeInTheDocument();
    expect(
      within(stage).queryByText("model_response_delta"),
    ).not.toBeInTheDocument();
    expect(gameClientMocks.getGamePlayback).toHaveBeenCalledWith(
      "session-1",
      "spectator_god_view",
    );
  });

  it("shows a recovered hunter no-shot presentation only once in replay", async () => {
    const user = userEvent.setup();
    const presentationId =
      "settlement:session-1:2:day:阿青:hunter:阿青:presentation";
    const payload = {
      presentation_id: presentationId,
      hunter_shot_status: "skipped",
      hunter_shot: null,
      day_deaths: [
        { player: "阿青", cause: "vote_exile", source: null },
      ],
      active_players: ["白石", "南风", "木子"],
    };
    const parentResult: LiveGameEvent = {
      ...gameStartedEvent,
      id: 10,
      run_id: "run-parent",
      round: 2,
      phase: "day",
      actor: "阿青",
      action: "hunter_shot_resolved",
      type: "state_updated",
      payload,
    };
    const childResult: LiveGameEvent = {
      ...parentResult,
      id: 12,
      run_id: "run-child",
    };
    const resumedEvent: LiveGameEvent = {
      ...gameStartedEvent,
      id: 11,
      run_id: "run-child",
      round: 2,
      phase: "day",
      type: "game_resumed",
      payload: {},
    };
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        events: [gameStartedEvent, parentResult, resumedEvent, childResult],
      }),
    );

    renderLiveReplayRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const eventRail = screen.getByRole("log");
    expect(
      within(eventRail).getAllByText("猎人选择不发动技能"),
    ).toHaveLength(1);
    expect(eventRail.querySelectorAll('[data-event-id="12"]')).toHaveLength(1);
    expect(eventRail.querySelector('[data-event-id="10"]')).toBeNull();
  });

  it("hides future speaker delta while playback is paused", async () => {
    const user = userEvent.setup();

    renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "暂停" }));
    expect(screen.getByRole("button", { name: "继续" })).toBeVisible();

    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).queryByText("阿青")).not.toBeInTheDocument();
    expect(
      within(stage).queryByText("model_response_delta"),
    ).not.toBeInTheDocument();
  });

  it("renders timed replay subtitles from saved voice metadata without audio playback", async () => {
    const user = userEvent.setup();

    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        voices: [
          {
            utterance_id: "voice-1",
            source_event_id: 4,
            last_source_event_id: 4,
            speaker_kind: "player",
            speaker_name: "1号玩家",
            mime_type: "audio/L16",
            audio_format: "pcm",
            sample_rate: 24000,
            duration_ms: 100,
            subtitle_timings: [
              { text: "语音时间轴字幕", start_ms: 18745, end_ms: 18845 },
            ],
            chunks: [],
          },
        ],
        events: [
          gameStartedEvent,
          phaseStartedEvent,
          requestStartedEvent,
          responseDeltaEvent,
        ],
      }),
    );

    renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "最新" }));

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });
    expect(subtitle).toHaveClass("mobile-live-subtitle-player-0");
    expect(within(subtitle).getByText("1号玩家")).toBeVisible();
    expect(within(subtitle).getByLabelText("语音时间轴字幕")).toBeVisible();
  });

  it("renders saved private replay subtitles in the red private style", async () => {
    const user = userEvent.setup();

    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        voices: [
          {
            utterance_id: "voice-private",
            audience: "spectator_god_view",
            source_event_id: 4,
            last_source_event_id: 4,
            speaker_kind: "player",
            speaker_name: "1号玩家",
            mime_type: "audio/L16",
            audio_format: "pcm",
            sample_rate: 24000,
            duration_ms: 100,
            subtitle_timings: [
              { text: "今晚建议刀3号", start_ms: 0, end_ms: 100 },
            ],
            chunks: [],
          },
        ],
        events: [
          gameStartedEvent,
          phaseStartedEvent,
          requestStartedEvent,
          responseDeltaEvent,
        ],
      }),
    );

    renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "最新" }));
    const subtitle = await screen.findByRole("status", { name: "直播字幕" });
    expect(subtitle).toHaveClass("mobile-live-subtitle-private");
    expect(subtitle).not.toHaveClass("mobile-live-subtitle-player-0");
  });

  it("prefers timed replay voice subtitles over event-derived subtitles", async () => {
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "open",
      currentSpeakerName: "1号玩家",
      currentSubtitle: {
        speakerKind: "player",
        speakerName: "1号玩家",
        text: "语音时间轴字幕",
        utteranceId: "voice-1",
      },
      errors: [],
      unlockAudio: vi.fn(async () => true),
    });
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        events: [
          gameStartedEvent,
          phaseStartedEvent,
          requestStartedEvent,
          responseDeltaEvent,
        ],
      }),
    );
    const user = userEvent.setup();

    renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "最新" }));

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });
    expect(within(subtitle).getByText("语音时间轴字幕")).toBeVisible();
    expect(within(subtitle).queryByText("我先听后置位发言。")).not.toBeInTheDocument();
  });

  it("prefers the active playback voice subtitle over replay clock fallback", async () => {
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "open",
      currentSpeakerName: "1号玩家",
      currentSubtitle: {
        speakerKind: "player",
        speakerName: "1号玩家",
        text: "真实语音正在说的字幕",
        utteranceId: "voice-1",
      },
      errors: [],
      unlockAudio: vi.fn(async () => true),
    });
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        voices: [
          {
            utterance_id: "voice-1",
            source_event_id: 4,
            last_source_event_id: 4,
            speaker_kind: "player",
            speaker_name: "1号玩家",
            mime_type: "audio/L16",
            audio_format: "pcm",
            sample_rate: 24000,
            duration_ms: 100,
            subtitle_timings: [
              { text: "回放时钟兜底字幕", start_ms: 0, end_ms: 200 },
            ],
            chunks: [],
          },
        ],
        events: [
          gameStartedEvent,
          phaseStartedEvent,
          requestStartedEvent,
          responseDeltaEvent,
        ],
      }),
    );
    const user = userEvent.setup();

    renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "最新" }));

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });
    expect(within(subtitle).getByText("真实语音正在说的字幕")).toBeVisible();
    expect(within(subtitle).queryByText("回放时钟兜底字幕")).not.toBeInTheDocument();
  });

  it("does not show the replay-clock subtitle while audio is still loading", async () => {
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "open",
      currentItem: {
        lastSourceEventId: 4,
        sourceEventId: 4,
        status: "receiving",
      },
      currentSpeakerName: "1号玩家",
      currentSubtitle: null,
      errors: [],
      unlockAudio: vi.fn(async () => true),
    });
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        voices: [
          {
            utterance_id: "voice-1",
            source_event_id: 4,
            last_source_event_id: 4,
            speaker_kind: "player",
            speaker_name: "1号玩家",
            mime_type: "audio/L16",
            audio_format: "pcm",
            sample_rate: 24000,
            duration_ms: 100,
            subtitle_timings: [
              { text: "不应提前显示的字幕", start_ms: 0, end_ms: 200 },
            ],
            chunks: [],
          },
        ],
        events: [
          gameStartedEvent,
          phaseStartedEvent,
          requestStartedEvent,
          responseDeltaEvent,
        ],
      }),
    );
    const user = userEvent.setup();

    renderLiveReplayRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    await waitFor(() => {
      expect(gameClientMocks.useLiveDirector).toHaveBeenLastCalledWith(
        expect.any(Array),
        expect.objectContaining({ holdAdvance: true }),
      );
    });
    expect(
      screen.queryByRole("status", { name: "直播字幕" }),
    ).not.toBeInTheDocument();
  });

  it("holds replay director advancement while saved voice is playing", async () => {
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "open",
      currentItem: {
        lastSourceEventId: 4,
        sourceEventId: 4,
        status: "playing",
      },
      currentSpeakerName: "1号玩家",
      currentSubtitle: {
        speakerKind: "player",
        speakerName: "1号玩家",
        text: "语音时间轴字幕",
        utteranceId: "voice-1",
      },
      errors: [],
      unlockAudio: vi.fn(async () => true),
    });
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        events: [
          gameStartedEvent,
          phaseStartedEvent,
          requestStartedEvent,
          responseDeltaEvent,
        ],
      }),
    );
    const user = userEvent.setup();

    renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "最新" }));

    await waitFor(() => {
      expect(gameClientMocks.useLiveDirector).toHaveBeenLastCalledWith(
        expect.any(Array),
        expect.objectContaining({
          holdAdvance: true,
          resetKey: "session-1",
          startAtLatestTerminal: false,
        }),
      );
    });
  });

  it("holds replay at the first event of a coalesced saved voice", async () => {
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "open",
      currentItem: {
        lastSourceEventId: 4,
        sourceEventId: 1,
        status: "playing",
      },
      currentSpeakerName: "1号玩家",
      errors: [],
      unlockAudio: vi.fn(async () => true),
    });

    renderLiveReplayRoute();

    await waitFor(() => {
      expect(gameClientMocks.useLiveDirector).toHaveBeenLastCalledWith(
        expect.any(Array),
        expect.objectContaining({ holdAdvance: true }),
      );
    });
  });

  it("retries saved replay audio through the playback hook", async () => {
    const retryAudio = vi.fn(async () => true);
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "error",
      currentSpeakerName: null,
      errors: ["Unable to play saved replay voice audio."],
      retryAudio,
      unlockAudio: vi.fn(async () => false),
    });
    const user = userEvent.setup();

    renderLiveReplayRoute();
    await user.click(await screen.findByRole("button", { name: "重试语音" }));

    expect(retryAudio).toHaveBeenCalledTimes(1);
  });

  it("renders the phase selector", async () => {
    const user = userEvent.setup();

    renderLiveReplayRoute();

    await user.click(
      await screen.findByRole("button", { name: "选择阶段，当前第1天" }),
    );

    expect(screen.getByRole("button", { name: "跳转到第1天" })).toBeVisible();
  });

  it("does not show resume for completed records", async () => {
    renderLiveReplayRoute();

    await screen.findByRole("heading", { name: "历史直播回放" });

    expect(
      screen.queryByRole("button", { name: "继续对局" }),
    ).not.toBeInTheDocument();
  });

  it("resumes failed resumable records and navigates to live", async () => {
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        status: "partial",
        resumable: true,
        events: [gameStartedEvent, failedEvent],
      }),
    );
    const user = userEvent.setup();
    const { router } = renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "继续对局" }));

    expect(gameClientMocks.resumeGameRun).toHaveBeenCalledWith("session-1");
    await screen.findByRole("heading", { name: "实时观战" });
    expect(router.state.location.pathname).toBe("/games/run-resumed/live");
  });

  it("enables saved replay voice when opening the page", async () => {
    const unlockAudio = vi.fn(async () => true);
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "idle",
      currentSpeakerName: null,
      errors: [],
      unlockAudio,
    });
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        voices: [
          {
            utterance_id: "voice-1",
            source_event_id: 4,
            last_source_event_id: 4,
            speaker_kind: "player",
            speaker_name: "阿青",
            mime_type: "audio/L16",
            audio_format: "pcm",
            sample_rate: 24000,
            duration_ms: 100,
            subtitle_timings: [],
            chunks: [{ chunk_index: 0, data: "YWJj" }],
          },
        ],
      }),
    );
    renderLiveReplayRoute();

    expect(await screen.findByRole("button", { name: "关闭语音" })).toBeVisible();
    await waitFor(() => expect(unlockAudio).toHaveBeenCalled());
    await waitFor(() => {
      expect(gameClientMocks.usePlaybackVoice).toHaveBeenLastCalledWith(
        expect.arrayContaining([
          expect.objectContaining({ utterance_id: "voice-1" }),
        ]),
        expect.objectContaining({ enabled: true, isPaused: false }),
      );
    });
  });

  it("shows unavailable replay voice when the playback has no saved voice", async () => {
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "unavailable",
      currentSpeakerName: null,
      errors: ["这局回放没有保存的语音。"],
      unlockAudio: vi.fn(async () => false),
    });

    renderLiveReplayRoute();

    expect(await screen.findByRole("button", { name: "语音不可用" })).toBeDisabled();
    expect(screen.getByText("这局回放没有保存的语音。")).toBeVisible();
  });

  it("renders the same action focus and event rail from saved playback", async () => {
    const user = userEvent.setup();
    const nightPhase: LiveGameEvent = {
      ...gameStartedEvent,
      id: 6,
      type: "phase_started",
      round: 1,
      phase: "night",
      payload: {
        active_players: ["阿青", "白石", "南风", "木子"],
        phase: "night",
      },
    };
    const werewolfKill: LiveGameEvent = {
      ...gameStartedEvent,
      id: 7,
      type: "action_parsed",
      round: 1,
      phase: "night",
      actor: "白石",
      action: "remove",
      payload: { choice: "阿青" },
    };
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        events: [gameStartedEvent, nightPhase, werewolfKill],
      }),
    );

    renderLiveReplayRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).getByText("狼人最终目标")).toBeVisible();
    expect(within(stage).getByText("袭击 1号")).toBeVisible();
    expect(within(stage).getByText("来源未知 · 旧数据")).toBeVisible();

    const rail = screen.getByRole("log");
    expect(within(rail).getByText("最终狼刀 -> 1号")).toBeVisible();
  });

  it("replays a persisted system vote with its provenance intact", async () => {
    const user = userEvent.setup();
    const systemVote: LiveGameEvent = {
      ...gameStartedEvent,
      id: 7,
      type: "action_parsed",
      round: 1,
      phase: "vote",
      actor: "白石",
      action: "vote",
      payload: {
        choice: "南风",
        action_origin: "system_fallback",
        public_reason_code: "system_vote_timeout",
      },
    };
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({ events: [gameStartedEvent, systemVote] }),
    );

    renderLiveReplayRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).getByText("系统代投")).toBeVisible();
    expect(screen.getByRole("log")).toHaveTextContent(
      "系统代投：2号 -> 3号",
    );
  });

  it("seeks the replay director when selecting an event from the sheet", async () => {
    const user = userEvent.setup();
    const votePhase: LiveGameEvent = {
      ...gameStartedEvent,
      id: 6,
      type: "phase_started",
      round: 1,
      phase: "vote",
      payload: {
        active_players: ["阿青", "白石", "南风", "木子"],
        phase: "vote",
      },
    };
    const firstVote: LiveGameEvent = {
      ...gameStartedEvent,
      id: 7,
      type: "action_parsed",
      round: 1,
      phase: "vote",
      actor: "白石",
      action: "vote",
      payload: { choice: "南风" },
    };
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        events: [gameStartedEvent, votePhase, firstVote],
      }),
    );

    renderLiveReplayRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const railAll = screen.getByRole("button", {
      name: /查看全部战报，共 \d+ 条/,
    });
    await user.click(railAll);

    const dialog = await screen.findByRole("dialog", { name: "本轮战报" });
    await user.click(
      within(dialog).getByRole("button", { name: /跳转到战报：投票阶段开始/ }),
    );

    expect(dialog).not.toBeInTheDocument();
    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).getByText("白天投票开始")).toBeVisible();
  });

  it("renders action and result moments without saved voice", async () => {
    const user = userEvent.setup();
    const nightResolution: LiveGameEvent = {
      ...gameStartedEvent,
      id: 6,
      type: "state_updated",
      round: 1,
      phase: "night",
      payload: {
        active_players: ["白石", "南风", "木子"],
        attacked: "阿青",
        eliminated: "阿青",
      },
    };
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
        voices: [],
        events: [gameStartedEvent, nightResolution],
      }),
    );
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "unavailable",
      currentSpeakerName: null,
      errors: ["这局回放没有保存的语音。"],
      unlockAudio: vi.fn(async () => false),
    });

    renderLiveReplayRoute();
    await user.click(await screen.findByRole("button", { name: "最新" }));

    const stage = await screen.findByRole("status", { name: "当前舞台" });
    expect(within(stage).getByText("1号 夜晚死亡")).toBeVisible();

    const rail = screen.getByRole("log");
    expect(within(rail).getByText("1号 夜晚死亡")).toBeVisible();
  });
});
