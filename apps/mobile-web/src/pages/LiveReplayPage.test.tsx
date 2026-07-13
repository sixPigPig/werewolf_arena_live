import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveReplayPage } from "./LiveReplayPage";
import type { GamePlayback, LiveGameEvent } from "@werewolf-arena/game-client";

const gameClientMocks = vi.hoisted(() => ({
  getGamePlayback: vi.fn(),
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
  payload: { winner: "villagers" },
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

    const stage = await screen.findByRole("region", { name: "当前舞台" });
    expect(within(stage).getByText("对局开始")).toBeVisible();
    expect(within(stage).queryByText("game_started")).not.toBeInTheDocument();
    expect(
      within(stage).queryByText("model_response_delta"),
    ).not.toBeInTheDocument();
    expect(gameClientMocks.getGamePlayback).toHaveBeenCalledWith("session-1");
  });

  it("hides future speaker delta while playback is paused", async () => {
    const user = userEvent.setup();

    renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "暂停" }));
    expect(screen.getByRole("button", { name: "继续" })).toBeVisible();

    const stage = await screen.findByRole("region", { name: "当前舞台" });
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
});
