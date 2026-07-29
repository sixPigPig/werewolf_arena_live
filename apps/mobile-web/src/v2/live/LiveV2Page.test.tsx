import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routes } from "../../routes/definitions";

const gameId = "v2_game_0123456789abcdef";
const runId = "v2_run_0123456789abcdef";
const actionId = "v2_action_0123456789abcdef";
const presentationId = "v2_pres_0123456789abcdef";
const speechId = "v2_speech_0123456789abcdef";

const sourceStart = vi.fn();
const sourceStop = vi.fn();
const copyToChannel = vi.fn();

class FakeAudioContext {
  currentTime = 0;
  destination = {} as AudioDestinationNode;
  resume = vi.fn(async () => undefined);
  close = vi.fn(async () => undefined);
  createBuffer = vi.fn(() => ({ copyToChannel }) as unknown as AudioBuffer);
  createBufferSource = vi.fn(
    () =>
      ({
        buffer: null,
        connect: vi.fn(),
        start: sourceStart,
        stop: sourceStop,
        addEventListener: vi.fn(),
      }) as unknown as AudioBufferSourceNode,
  );
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  binaryType = "blob";
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => this.onclose?.());
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  open() {
    this.onopen?.();
  }

  emitJson(value: Record<string, unknown>) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(value) }));
  }

  emitBinary(value: ArrayBuffer) {
    this.onmessage?.(new MessageEvent("message", { data: value }));
  }
}

beforeEach(() => {
  window.sessionStorage.clear();
  FakeWebSocket.instances = [];
  sourceStart.mockClear();
  sourceStop.mockClear();
  copyToChannel.mockClear();
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(snapshot("waiting_to_start", null)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LiveV2Page", () => {
  it("shows the immutable public seats before starting any realtime action", async () => {
    renderPage();

    expect(await screen.findByText("阿青")).toBeInTheDocument();
    expect(screen.getByText("白石")).toBeInTheDocument();
    expect(screen.getByText("1号")).toBeInTheDocument();
    expect(screen.getByText("2号")).toBeInTheDocument();
    expect(screen.getByText("身份已私密封存 · 2 人")).toBeInTheDocument();
    expect(screen.getByText(/导演全知会在对应私密场景按需展示身份/)).toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(sourceStart).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "以导演全知入场" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /导演全知.*默认推荐/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: /推理挑战.*自己破局/ }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByRole("region", { name: "Live V2 实时演出舞台" }),
    ).toHaveAttribute("data-viewing-mode", "director");
    expect(screen.getByText(/只接收当前与未来/)).toBeInTheDocument();
  });

  it("shows a canceled REST snapshot as terminal without opening realtime", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(snapshot("canceled", null)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderPage();

    expect(await screen.findByText("本局已由管理员终止")).toBeInTheDocument();
    expect(screen.getByText(/不会追播或恢复已打断的内容/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "以导演全知入场" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "重新接入当前直播" }),
    ).not.toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(sourceStart).not.toHaveBeenCalled();
  });

  it("shows the frozen public rule before starting any realtime action", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "测试两人局" })).toBeInTheDocument();
    expect(screen.getByText("2 位玩家 · 最多 8 轮")).toBeInTheDocument();
    expect(screen.getByText("狼人")).toBeInTheDocument();
    expect(screen.getByText("村民")).toBeInTheDocument();
    expect(screen.getByText("狼人自爆").nextSibling).toHaveTextContent("开启");
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(sourceStart).not.toHaveBeenCalled();
  });

  it("does not expose the credentialed analysis console from mobile live", async () => {
    window.sessionStorage.setItem(`live-v2:god-view:${gameId}`, "a".repeat(43));
    renderPage();

    expect(await screen.findByText("演出正在此刻发生")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /进入上帝视角/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("持有全知凭证")).not.toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(sourceStart).not.toHaveBeenCalled();
  });

  it("defaults to the directed live channel and follows private scenes without exposing diagnostics", async () => {
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "以导演全知入场" }),
    );
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    expect(socket.url.endsWith(`/api/v2/director/games/${gameId}/ws`)).toBe(
      true,
    );

    act(() => {
      socket.open();
      socket.emitJson(directorSnapshot("ready"));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));
    expect(JSON.parse(String(socket.send.mock.calls[0][0]))).toEqual({
      protocol_version: 1,
      type: "director.ready",
      audio: { encoding: "pcm_s16le", sample_rate: 24000, channels: 1 },
    });

    act(() => {
      socket.emitJson({
        ...base("director.scene_changed"),
        scene_kind: "werewolves",
        action_id: actionId,
        action_type: "werewolf_kill_vote",
        ability_id: "werewolf_kill",
        actor_player_id: "profile-1",
      });
      socket.emitJson({
        ...base("ability.progress_changed"),
        ability_id: "werewolf_kill",
        status: "selected",
        actor_player_id: "profile-1",
        target_player_id: "profile-2",
        round_no: 1,
      });
      socket.emitJson({
        ...base("presentation.opened"),
        action_id: actionId,
        presentation_seq: 1,
        presentation_id: presentationId,
        phase_id: "first_night",
        actor: { kind: "player", id: "profile-1" },
        speech_id: speechId,
      });
      socket.emitJson({
        ...base("speech.segment_committed"),
        action_id: actionId,
        presentation_seq: 1,
        presentation_id: presentationId,
        speech_id: speechId,
        segment_index: 0,
        text: "```json\n{\"target_player_id\":\"profile-2\",\"speech\":\"今晚先试探白石。\"}\n```",
      });
    });

    expect(await screen.findByText("狼人房间")).toBeInTheDocument();
    expect(screen.getByText("阿青 → 白石")).toBeInTheDocument();
    expect(screen.getByText("今晚先试探白石。")).toBeInTheDocument();
    expect(screen.queryByText(/target_player_id/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Live V2 实时演出舞台" }),
    ).toHaveAttribute("data-viewing-mode", "director");
    expect(
      screen.getByText("狼人", { selector: ".mobile-v2-stage-subtitle em" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/model_request|prompt|provider/i)).not.toBeInTheDocument();
    expect(socket.close).not.toHaveBeenCalled();
  });

  it("plays the preview-only opening and nightfall in order", async () => {
    renderPage();

    expect(FakeWebSocket.instances).toHaveLength(0);
    await enterChallenge();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    expect(socket.url.endsWith(`/api/v2/live/games/${gameId}/ws`)).toBe(true);
    expect(socket.binaryType).toBe("arraybuffer");

    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));
    expect(JSON.parse(String(socket.send.mock.calls[0][0]))).toEqual({
      protocol_version: 1,
      type: "client.ready",
      audio: { encoding: "pcm_s16le", sample_rate: 24000, channels: 1 },
    });

    act(() => {
      socket.emitJson(snapshot("ready", null));
      socket.emitJson(state("generating"));
      socket.emitJson({
        ...base("presentation.opened"),
        action_id: actionId,
        presentation_seq: 1,
        presentation_id: presentationId,
        phase_id: "opening",
        actor: { kind: "judge", id: "judge" },
        speech_id: speechId,
      });
      socket.emitJson({
        ...base("speech.segment_committed"),
        action_id: actionId,
        presentation_seq: 1,
        presentation_id: presentationId,
        speech_id: speechId,
        segment_index: 0,
        text: "欢迎来到这场实时狼人杀对局。",
      });
      socket.emitJson(state("broadcasting"));
      socket.emitBinary(audioFrame(0, 0));
      socket.emitJson(state("finalizing"));
      socket.emitJson({
        ...base("presentation.closed"),
        action_id: actionId,
        presentation_seq: 1,
        presentation_id: presentationId,
        speech_id: speechId,
        final_segment_index: 0,
        final_chunk_index: 0,
        final_sample_cursor: 2,
        result: "audio_drained_and_voice_saved",
      });
      socket.emitJson({
        ...base("game.phase_changed"),
        phase_seq: 2,
        previous_phase_id: "opening",
        phase_id: "first_night",
        phase_state: "nightfall_ready",
      });
      socket.emitJson(state("generating"));
      socket.emitJson({
        ...base("presentation.opened"),
        action_id: `${actionId}2`,
        presentation_seq: 2,
        presentation_id: `${presentationId}2`,
        phase_id: "first_night",
        actor: { kind: "judge", id: "judge" },
        speech_id: `${speechId}2`,
      });
      socket.emitJson({
        ...base("speech.segment_committed"),
        action_id: `${actionId}2`,
        presentation_seq: 2,
        presentation_id: `${presentationId}2`,
        speech_id: `${speechId}2`,
        segment_index: 0,
        text: "夜幕已经降临，请所有玩家闭眼。",
      });
      socket.emitJson(state("broadcasting"));
      socket.emitBinary(audioFrame(0, 0, 2));
      socket.emitJson(state("finalizing"));
      socket.emitJson({
        ...base("presentation.closed"),
        action_id: `${actionId}2`,
        presentation_seq: 2,
        presentation_id: `${presentationId}2`,
        speech_id: `${speechId}2`,
        final_segment_index: 0,
        final_chunk_index: 0,
        final_sample_cursor: 2,
        result: "audio_drained_and_voice_saved",
      });
      socket.emitJson(state("awaiting_observation"));
    });

    expect((await screen.findAllByText("第 1 夜")).length).toBeGreaterThan(0);
    expect(screen.getByText("直播已停在当前时刻")).toBeInTheDocument();
    expect(screen.queryByText("欢迎来到这场实时狼人杀对局。")).not.toBeInTheDocument();
    expect(sourceStart).toHaveBeenCalledTimes(2);
    expect(copyToChannel).toHaveBeenCalledTimes(2);
    expect(socket.send).toHaveBeenCalledTimes(1);
  });

  it("does not replay a completed sentence after reconnect", async () => {
    renderPage();
    await enterChallenge();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.open();
      socket.emitJson(snapshot("awaiting_observation", null));
    });

    expect(
      await screen.findByText("直播已停在当前时刻"),
    ).toBeInTheDocument();
    expect(sourceStart).not.toHaveBeenCalled();
    expect(screen.queryByText("欢迎来到这场实时狼人杀对局。")).not.toBeInTheDocument();
  });

  it("labels a public player presentation with the frozen display name", async () => {
    renderPage();
    await enterChallenge();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));
    act(() => {
      socket.emitJson({
        ...base("presentation.opened"),
        action_id: actionId,
        presentation_seq: 1,
        presentation_id: presentationId,
        phase_id: "day_1",
        actor: { kind: "player", id: "profile-1" },
        speech_id: speechId,
      });
      socket.emitJson({
        ...base("speech.segment_committed"),
        action_id: actionId,
        presentation_seq: 1,
        presentation_id: presentationId,
        speech_id: speechId,
        segment_index: 0,
        text: "我选择不开枪。",
      });
      socket.emitJson(state("broadcasting"));
      socket.emitBinary(audioFrame(0, 0));
    });

    expect(await screen.findByRole("region", { name: "阿青" })).toBeInTheDocument();
    expect(screen.getByText("我选择不开枪。")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Live V2 实时演出舞台" }),
    ).toHaveAttribute("data-live-state", "broadcasting");
    expect(document.querySelector(".mobile-v2-theater.is-audio-active")).not.toBeNull();
    expect(sourceStart).toHaveBeenCalledTimes(1);
  });

  it("shows only safe night progress and public dawn deaths", async () => {
    renderPage();
    await enterChallenge();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));
    act(() => {
      socket.emitJson(snapshot("ready", null));
      socket.emitJson({
        ...base("game.phase_changed"),
        phase_seq: 2,
        previous_phase_id: "opening",
        phase_id: "first_night",
        phase_state: "night_running",
      });
      socket.emitJson({
        ...base("night.progress_changed"),
        stage: "actions_in_progress",
        latest_presentation_seq: 5,
      });
      socket.emitJson({
        ...base("dawn.result_announced"),
        dead_player_ids: ["profile-1"],
      });
      socket.emitJson({
        ...base("game.phase_changed"),
        phase_seq: 3,
        previous_phase_id: "first_night",
        phase_id: "day_1",
        phase_state: "public_day_ready",
      });
      socket.emitJson(state("awaiting_observation"));
    });

    expect(await screen.findByText("阿青 · 已死亡")).toBeInTheDocument();
    expect(screen.getAllByText("第 1 天").length).toBeGreaterThan(0);
    expect(screen.queryByText(/狼人袭击/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("listitem", { name: "1号 阿青，已公开死亡" }),
    ).toHaveClass("is-dead", "is-reacting");
    const publicStage = screen.getByRole("region", {
      name: "Live V2 实时演出舞台",
    });
    expect(within(publicStage).queryByText("狼人")).not.toBeInTheDocument();
    expect(within(publicStage).queryByText("村民")).not.toBeInTheDocument();
  });

  it("keeps later-round rhythm, public sheriff state, and the final winner on stage", async () => {
    renderPage();
    await enterChallenge();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));

    act(() => {
      socket.emitJson({
        ...base("game.phase_changed"),
        phase_seq: 6,
        previous_phase_id: "night_2",
        phase_id: "day_2",
        phase_state: "public_discussion_open",
      });
      socket.emitJson({
        ...base("match.state_changed"),
        round_no: 2,
        sheriff_player_id: "profile-1",
        sheriff_badge_state: "held",
        winner: null,
      });
      socket.emitJson({
        ...base("day.progress_changed"),
        round_no: 2,
        stage: "discussion_round_1",
      });
    });

    expect(screen.getAllByText("第 2 天").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("存活玩家正在依次公开发言").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("listitem", { name: "1号 阿青，警长" }),
    ).toHaveClass("is-sheriff");
    expect(document.querySelector(".mobile-v2-theater.is-vote")).not.toBeNull();

    act(() => {
      socket.emitJson({
        ...base("game.phase_changed"),
        phase_seq: 7,
        previous_phase_id: "day_2",
        phase_id: "day_2",
        phase_state: "game_completed",
      });
      socket.emitJson({
        ...base("match.state_changed"),
        round_no: 2,
        sheriff_player_id: "profile-1",
        sheriff_badge_state: "held",
        winner: "villagers",
      });
      socket.emitJson(state("awaiting_observation"));
    });

    expect(await screen.findByText("好人阵营获胜")).toBeInTheDocument();
    expect(screen.getByText(/正式落幕/)).toBeInTheDocument();
    expect(document.querySelector(".mobile-v2-theater.is-terminal")).not.toBeNull();
  });

  it("fails closed if a private death cause reaches the public theater", async () => {
    renderPage();
    await enterChallenge();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));

    act(() => {
      socket.emitJson({
        ...base("player.state_changed"),
        player_id: "profile-2",
        alive: false,
        cause: "werewolf_attack",
      });
    });

    expect(
      await screen.findByText("普通观众连接收到私密死亡原因，连接已关闭"),
    ).toBeInTheDocument();
    expect(socket.close).toHaveBeenCalledTimes(1);
  });

  it("presents an operator stop as an interrupted stage without enabling replay", async () => {
    renderPage();
    await enterChallenge();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));

    act(() => {
      socket.emitJson({
        ...base("live.state_changed"),
        live_state: "failed",
        reason: "operator stop",
      });
    });

    expect(await screen.findByText("运营已中断本局")).toBeInTheDocument();
    expect(screen.getByText(/只会接收当前和未来内容/)).toBeInTheDocument();
    expect(screen.queryByText("回放")).not.toBeInTheDocument();
  });

  it("stops the current presentation when the operator cancels the game", async () => {
    renderPage();
    await enterChallenge();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));

    act(() => {
      socket.emitJson({
        ...base("presentation.opened"),
        action_id: actionId,
        presentation_seq: 1,
        presentation_id: presentationId,
        phase_id: "opening",
        actor: { kind: "judge", id: "judge" },
        speech_id: speechId,
      });
      socket.emitJson({
        ...base("speech.segment_committed"),
        action_id: actionId,
        presentation_seq: 1,
        presentation_id: presentationId,
        speech_id: speechId,
        segment_index: 0,
        text: "这段话会被管理员打断。",
      });
      socket.emitBinary(audioFrame(0, 0));
      socket.emitJson({
        ...state("canceled"),
        reason: "operator_interrupted",
      });
    });

    expect(await screen.findByText("本局已由管理员终止")).toBeInTheDocument();
    expect(screen.getByText(/不会追播或恢复已打断的内容/)).toBeInTheDocument();
    expect(screen.queryByText("这段话会被管理员打断。")).not.toBeInTheDocument();
    expect(socket.close).toHaveBeenCalled();
    expect(sourceStop).toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "重新接入当前直播" }),
    ).not.toBeInTheDocument();
  });

  it("presents a failed snapshot as a terminal realtime stage without replay", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(snapshot("failed", null)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderPage();

    expect(await screen.findByText("实时演出未能继续")).toBeInTheDocument();
    expect(screen.getByText(/仍只接收当前和未来内容/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新接入当前直播" })).toBeInTheDocument();
    expect(screen.queryByText("回放")).not.toBeInTheDocument();
  });
});

async function enterChallenge() {
  fireEvent.click(
    await screen.findByRole("button", {
      name: /推理挑战.*自己破局/,
    }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "以推理挑战入场" }),
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(routes, {
    initialEntries: [`/v2/games/${gameId}/live`],
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function directorSnapshot(liveState: string) {
  return {
    ...base("director.live_snapshot"),
    api_version: "v2",
    audience: "spectator_directed",
    live_state: liveState,
    game_phase: {
      phase_seq: 2,
      phase_id: "first_night",
      phase_state: "night_running",
    },
    match_state: {
      round_no: 1,
      sheriff_player_id: null,
      sheriff_badge_state: "disabled",
      winner: null,
    },
    latest_presentation_seq: 0,
    rule: {
      rule_id: "classic_2",
      name: "测试两人局",
      version: "1",
      player_count: 2,
      roles: [
        { role: "狼人", count: 1 },
        { role: "村民", count: 1 },
      ],
      max_rounds: 8,
      sheriff_enabled: false,
      werewolf_self_explosion_enabled: true,
      exile_last_words_enabled: true,
      first_night_last_words_enabled: false,
    },
    players: [
      {
        seat: 1,
        player_id: "profile-1",
        display_name: "阿青",
        avatar_url: null,
        role: "werewolf",
        team: "werewolves",
        alive: true,
        death_cause: null,
      },
      {
        seat: 2,
        player_id: "profile-2",
        display_name: "白石",
        avatar_url: null,
        role: "villager",
        team: "villagers",
        alive: true,
        death_cause: null,
      },
    ],
    current_scene: {
      scene_kind: "nightfall",
      action_id: null,
      action_type: null,
      ability_id: null,
      actor_player_id: null,
    },
    current_presentation: null,
  };
}

function snapshot(
  liveState: string,
  presentation: Record<string, unknown> | null,
) {
  return {
    ...base("live.snapshot"),
    api_version: "v2",
    audience: "player_public",
    live_state: liveState,
    game_phase:
      liveState === "awaiting_observation"
        ? { phase_seq: 2, phase_id: "first_night", phase_state: "nightfall_announced" }
        : { phase_seq: 1, phase_id: "opening", phase_state: "opening_ready" },
    match_state: {
      round_no: 1,
      sheriff_player_id: null,
      sheriff_badge_state: "disabled",
      winner: null,
    },
    latest_presentation_seq: presentation ? 1 : 0,
    public_rule: {
      rule_id: "classic_2",
      name: "测试两人局",
      version: "1",
      player_count: 2,
      roles: [
        { role: "狼人", count: 1 },
        { role: "村民", count: 1 },
      ],
      max_rounds: 8,
      sheriff_enabled: false,
      werewolf_self_explosion_enabled: true,
      exile_last_words_enabled: true,
      first_night_last_words_enabled: false,
    },
    public_players: [
      {
        seat: 1,
        player_id: "profile-1",
        display_name: "阿青",
        avatar_url: null,
        alive: true,
      },
      {
        seat: 2,
        player_id: "profile-2",
        display_name: "白石",
        avatar_url: null,
        alive: true,
      },
    ],
    public_role_assignment: { state: "sealed", assigned_count: 2 },
    current_presentation: presentation,
  };
}

function state(liveState: string) {
  return { ...base("live.state_changed"), live_state: liveState, reason: null };
}

function base(type: string) {
  return {
    protocol_version: 1,
    type,
    game_id: gameId,
    run_id: runId,
    server_time: "2026-07-22T12:00:00Z",
  };
}

function audioFrame(
  chunkIndex: number,
  startSample: number,
  presentationSeq = 1,
): ArrayBuffer {
  const header = new TextEncoder().encode(
    JSON.stringify({
      protocol_version: 1,
      action_id: presentationSeq === 1 ? actionId : `${actionId}2`,
      presentation_seq: presentationSeq,
      presentation_id: presentationSeq === 1 ? presentationId : `${presentationId}2`,
      speech_id: presentationSeq === 1 ? speechId : `${speechId}2`,
      segment_index: 0,
      chunk_index: chunkIndex,
      start_sample: startSample,
      sample_count: 2,
      sample_rate: 24000,
      channels: 1,
      encoding: "pcm_s16le",
      is_final: true,
    }),
  );
  const value = new Uint8Array(6 + header.length + 4);
  value.set(new TextEncoder().encode("LV2A"), 0);
  new DataView(value.buffer).setUint16(4, header.length, false);
  value.set(header, 6);
  value.set(new Uint8Array([0, 0, 1, 0]), 6 + header.length);
  return value.buffer;
}
