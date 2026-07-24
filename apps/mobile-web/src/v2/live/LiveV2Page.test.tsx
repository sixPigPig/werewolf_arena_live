import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routes } from "../../routes/definitions";

const gameId = "v2_game_0123456789abcdef";
const runId = "v2_run_0123456789abcdef";
const actionId = "v2_action_0123456789abcdef";
const presentationId = "v2_pres_0123456789abcdef";
const speechId = "v2_speech_0123456789abcdef";

const sourceStart = vi.fn();
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
        stop: vi.fn(),
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
    expect(screen.getByText(/普通直播不会展示任何座位对应的角色或阵营/)).toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(sourceStart).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "进入实时观赛" })).toBeInTheDocument();
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

  it("offers the separately credentialed God View without starting realtime", async () => {
    window.sessionStorage.setItem(`live-v2:god-view:${gameId}`, "a".repeat(43));
    renderPage();

    const link = await screen.findByRole("link", { name: /进入上帝视角/ });
    expect(link).toHaveAttribute(
      "href",
      `/v2/games/${gameId}/live/god#access_token=${"a".repeat(43)}`,
    );
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(sourceStart).not.toHaveBeenCalled();
  });

  it("plays the preview-only opening and nightfall in order", async () => {
    renderPage();

    expect(FakeWebSocket.instances).toHaveLength(0);
    fireEvent.click(await screen.findByRole("button", { name: "进入实时观赛" }));
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

    expect(await screen.findByText("天黑，请闭眼")).toBeInTheDocument();
    expect(screen.getByText(/当前对局已停止/)).toBeInTheDocument();
    expect(screen.queryByText("欢迎来到这场实时狼人杀对局。")).not.toBeInTheDocument();
    expect(sourceStart).toHaveBeenCalledTimes(2);
    expect(copyToChannel).toHaveBeenCalledTimes(2);
    expect(socket.send).toHaveBeenCalledTimes(1);
  });

  it("does not replay a completed sentence after reconnect", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "进入实时观赛" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.open();
      socket.emitJson(snapshot("awaiting_observation", null));
    });

    expect(
      await screen.findByText(/当前对局已停止/),
    ).toBeInTheDocument();
    expect(sourceStart).not.toHaveBeenCalled();
    expect(screen.queryByText("欢迎来到这场实时狼人杀对局。")).not.toBeInTheDocument();
  });

  it("labels a public player presentation with the frozen display name", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "进入实时观赛" }));
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
    });

    expect(await screen.findByRole("region", { name: "阿青" })).toBeInTheDocument();
  });

  it("shows only safe night progress and public dawn deaths", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "进入实时观赛" }));
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
    expect(screen.getByText("黎明结算完成")).toBeInTheDocument();
    expect(screen.queryByText(/狼人袭击/)).not.toBeInTheDocument();
  });

  it("shows the dynamically selected public discussion window", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "进入实时观赛" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
      socket.emitJson({
        ...base("game.phase_changed"),
        phase_seq: 3,
        previous_phase_id: "day_1",
        phase_id: "day_1",
        phase_state: "public_discussion_open",
      });
      socket.emitJson(state("awaiting_observation"));
    });

    expect(await screen.findByText("白天发言已开始")).toBeInTheDocument();
    expect(screen.getByText(/存活玩家正在依次实时发言和投票/)).toBeInTheDocument();
  });

  it("tracks later rounds, sheriff state, public deaths, and the final winner", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "进入实时观赛" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
      socket.emitJson({
        ...base("game.phase_changed"),
        phase_seq: 5,
        previous_phase_id: "day_1",
        phase_id: "night_2",
        phase_state: "night_running",
      });
      socket.emitJson({
        ...base("match.state_changed"),
        round_no: 2,
        sheriff_player_id: "profile-1",
        sheriff_badge_state: "held",
        winner: null,
      });
      socket.emitJson({
        ...base("player.state_changed"),
        player_id: "profile-2",
        alive: false,
        cause: null,
      });
    });

    expect(await screen.findByText("第 2 夜")).toBeInTheDocument();
    expect(screen.getByText(/第 2 轮 · 警长：阿青/)).toBeInTheDocument();
    expect(screen.getByText("白石 · 已死亡")).toBeInTheDocument();

    act(() => {
      socket.emitJson({
        ...base("game.phase_changed"),
        phase_seq: 6,
        previous_phase_id: "night_2",
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
    expect(await screen.findByText(/对局已结束：好人阵营获胜/)).toBeInTheDocument();
    expect(screen.getByText("胜负条件已经由确定性规则结算。")).toBeInTheDocument();
    expect(screen.queryByText(/实时阶段：/)).not.toBeInTheDocument();
  });

  it("fails closed if the public stream receives a private death cause", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "进入实时观赛" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(snapshot("ready", null));
      socket.emitJson({
        ...base("player.state_changed"),
        player_id: "profile-2",
        alive: false,
        cause: "werewolf_attack",
      });
    });

    expect(await screen.findByText(/普通观众连接收到私密死亡原因/)).toBeInTheDocument();
    expect(socket.close).toHaveBeenCalled();
  });
});

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
