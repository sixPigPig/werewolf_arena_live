import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GodViewPage } from "./GodViewPage";

const gameId = "v2_game_0123456789abcdef";
const accessToken = "a".repeat(43);
const actionId = "v2_action_0123456789abcdef";
const presentationId = "v2_pres_0123456789abcdef";
const speechId = "v2_speech_0123456789abcdef";
const sourceStart = vi.fn();
const sourceStop = vi.fn();

class FakeAudioContext {
  currentTime = 0;
  destination = {} as AudioDestinationNode;
  resume = vi.fn(async () => undefined);
  close = vi.fn(async () => undefined);
  createBuffer = vi.fn(
    () => ({ copyToChannel: vi.fn() }) as unknown as AudioBuffer,
  );
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
  protocol = "live-v2-god-view";
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => this.onclose?.());
  readonly url: string;
  readonly protocols?: string | string[];

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
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
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GodViewPage", () => {
  it("shows every private identity without opening realtime transport", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(identitySnapshot()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const webSocketMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", webSocketMock);

    renderPage(`#access_token=${accessToken}`);

    expect(await screen.findByText("阿青")).toBeInTheDocument();
    expect(screen.getByText("狼人")).toBeInTheDocument();
    expect(screen.getByText("狼人阵营")).toBeInTheDocument();
    expect(screen.getByText("白石")).toBeInTheDocument();
    expect(screen.getByText("村民")).toBeInTheDocument();
    expect(screen.getByText("好人阵营")).toBeInTheDocument();
    expect(webSocketMock).not.toHaveBeenCalled();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe(
      `Bearer ${accessToken}`,
    );
  });

  it("shows a canceled identity snapshot as terminal without opening realtime", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ...identitySnapshot(),
            live_state: "canceled",
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
    );
    const webSocketMock = vi.fn();
    vi.stubGlobal("WebSocket", webSocketMock);

    renderPage(`#access_token=${accessToken}`);

    expect(
      await screen.findByText("本局已由管理员终止"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "进入上帝视角实时观赛" }),
    ).not.toBeInTheDocument();
    expect(webSocketMock).not.toHaveBeenCalled();
  });

  it("fails closed before any request when the credential is absent", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderPage("");

    expect(await screen.findByText(/缺少上帝视角访问凭证/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("watches opening and nightfall while every identity stays visible", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(identitySnapshot()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderPage(`#access_token=${accessToken}`);

    fireEvent.click(
      await screen.findByRole("button", { name: "进入上帝视角实时观赛" }),
    );
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    expect(socket.url).toContain(`/api/v2/god-view/games/${gameId}/ws`);
    expect(socket.url).not.toContain(accessToken);
    expect(socket.protocols).toEqual(["live-v2-god-view", accessToken]);

    act(() => {
      socket.open();
      socket.emitJson(liveSnapshot("ready", null));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));
    expect(JSON.parse(String(socket.send.mock.calls[0][0]))).toEqual({
      protocol_version: 1,
      type: "god_view.ready",
      audio: { encoding: "pcm_s16le", sample_rate: 24000, channels: 1 },
    });

    act(() => {
      socket.emitJson(liveSnapshot("ready", null));
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
      socket.emitBinary(audioFrame());
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
      socket.emitBinary(audioFrame(2));
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
    expect(screen.getByText(/当前验收切片已实时完成/)).toBeInTheDocument();
    expect(screen.queryByText("欢迎来到这场实时狼人杀对局。")).not.toBeInTheDocument();
    expect(screen.getByText("狼人")).toBeInTheDocument();
    expect(screen.getByText("村民")).toBeInTheDocument();
    expect(sourceStart).toHaveBeenCalledTimes(2);
  });

  it("does not replay the completed judge sentence after reconnect", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(identitySnapshot()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderPage(`#access_token=${accessToken}`);

    fireEvent.click(
      await screen.findByRole("button", { name: "进入上帝视角实时观赛" }),
    );
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(liveSnapshot("awaiting_observation", null));
    });

    expect(await screen.findByText(/上帝视角正在等待本步验收/)).toBeInTheDocument();
    expect(screen.queryByText("欢迎来到这场实时狼人杀对局。")).not.toBeInTheDocument();
    expect(sourceStart).not.toHaveBeenCalled();
  });

  it("stops God View audio without exposing the Admin reason", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(identitySnapshot()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderPage(`#access_token=${accessToken}`);
    fireEvent.click(
      await screen.findByRole("button", { name: "进入上帝视角实时观赛" }),
    );
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(liveSnapshot("ready", null));
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
        text: "这段全知播报会被打断。",
      });
      socket.emitBinary(audioFrame());
      socket.emitJson({
        ...state("canceled"),
        reason: "operator_interrupted",
      });
    });

    expect(
      await screen.findByText("本局已由管理员终止"),
    ).toBeInTheDocument();
    expect(screen.getByText(/不会继续播放或补播/)).toBeInTheDocument();
    expect(screen.queryByText("这段全知播报会被打断。")).toBeNull();
    expect(screen.queryByText(/人工打断异常/)).toBeNull();
    expect(socket.close).toHaveBeenCalled();
    expect(sourceStop).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /重新连接/ })).toBeNull();
  });

  it("shows private ability targets and deterministic death causes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(identitySnapshot()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("WebSocket", FakeWebSocket);
    renderPage(`#access_token=${accessToken}`);
    fireEvent.click(
      await screen.findByRole("button", { name: "进入上帝视角实时观赛" }),
    );
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.emitJson(liveSnapshot("ready", null));
    });
    await waitFor(() => expect(socket.send).toHaveBeenCalledTimes(1));
    act(() => {
      socket.emitJson({
        ...base("ability.progress_changed"),
        ability_id: "werewolf.attack",
        status: "decision_committed",
        actor_player_id: "profile-1",
        target_player_id: "profile-2",
        round_no: 1,
      });
      socket.emitJson({
        ...base("ability.progress_changed"),
        ability_id: "werewolf.attack",
        status: "completed",
        actor_player_id: "profile-1",
        target_player_id: "profile-2",
        round_no: null,
      });
      socket.emitJson({
        ...base("god_view.night_resolved"),
        deaths: [{ player_id: "profile-2", cause: "werewolf_attack" }],
        attack_prevented_by: null,
      });
      socket.emitJson({
        ...base("presentation.opened"),
        action_id: actionId,
        presentation_seq: 2,
        presentation_id: presentationId,
        phase_id: "first_night",
        actor: { kind: "player", id: "profile-1" },
        speech_id: speechId,
      });
      socket.emitJson({
        ...base("speech.segment_committed"),
        action_id: actionId,
        presentation_seq: 2,
        presentation_id: presentationId,
        speech_id: speechId,
        segment_index: 0,
        text: "我选择二号。",
      });
    });

    const progress = await screen.findByRole("region", { name: "首夜实时决策" });
    expect(within(progress).getAllByText("狼人袭击")).toHaveLength(1);
    expect(within(progress).getByText("目标：白石")).toBeInTheDocument();
    expect(screen.getByText("已死亡 · 狼人袭击")).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "阿青" })).toBeInTheDocument();
  });
});

function renderPage(hash: string) {
  const router = createMemoryRouter(
    [{ path: "/v2/games/:gameId/live/god", element: <GodViewPage /> }],
    { initialEntries: [`/v2/games/${gameId}/live/god${hash}`] },
  );
  return render(<RouterProvider router={router} />);
}

function identitySnapshot() {
  return {
    protocol_version: 1,
    type: "god_view.identity_snapshot",
    api_version: "v2",
    audience: "spectator_god_view",
    game_id: gameId,
    run_id: "v2_run_0123456789abcdef",
    live_state: "ready",
    game_phase: {
      phase_seq: 1,
      phase_id: "opening",
      phase_state: "opening_ready",
    },
    server_time: "2026-07-22T12:00:00Z",
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
      werewolf_self_explosion_enabled: false,
      exile_last_words_enabled: true,
    },
    players: [
      {
        seat: 1,
        player_id: "profile-1",
        display_name: "阿青",
        avatar_url: null,
        role: "狼人",
        team: "werewolves",
        alive: true,
        death_cause: null,
      },
      {
        seat: 2,
        player_id: "profile-2",
        display_name: "白石",
        avatar_url: null,
        role: "村民",
        team: "villagers",
        alive: true,
        death_cause: null,
      },
    ],
  };
}

function liveSnapshot(
  liveState: string,
  currentPresentation: Record<string, unknown> | null,
) {
  const identity = identitySnapshot();
  return {
    ...identity,
    type: "god_view.live_snapshot",
    live_state: liveState,
    game_phase:
      liveState === "awaiting_observation"
        ? { phase_seq: 2, phase_id: "first_night", phase_state: "nightfall_announced" }
        : identity.game_phase,
    latest_presentation_seq: currentPresentation ? 1 : 0,
    current_presentation: currentPresentation,
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
    run_id: "v2_run_0123456789abcdef",
    server_time: "2026-07-22T12:00:00Z",
  };
}

function audioFrame(presentationSeq = 1): ArrayBuffer {
  const header = new TextEncoder().encode(
    JSON.stringify({
      protocol_version: 1,
      action_id: presentationSeq === 1 ? actionId : `${actionId}2`,
      presentation_seq: presentationSeq,
      presentation_id: presentationSeq === 1 ? presentationId : `${presentationId}2`,
      speech_id: presentationSeq === 1 ? speechId : `${speechId}2`,
      segment_index: 0,
      chunk_index: 0,
      start_sample: 0,
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
