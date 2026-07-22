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
  FakeWebSocket.instances = [];
  sourceStart.mockClear();
  copyToChannel.mockClear();
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(snapshot("ready", null)), {
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
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(sourceStart).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "进入实时直播" })).toBeInTheDocument();
  });

  it("starts after a user gesture, plays live PCM, and stops after one sentence", async () => {
    renderPage();

    expect(FakeWebSocket.instances).toHaveLength(0);
    fireEvent.click(await screen.findByRole("button", { name: "进入实时直播" }));
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
      socket.emitJson(state("awaiting_observation"));
    });

    expect(await screen.findByText("欢迎来到这场实时狼人杀对局。")).toBeInTheDocument();
    expect(screen.getByText(/法官第一句话已直播并保存/)).toBeInTheDocument();
    expect(screen.getByText(actionId)).toBeInTheDocument();
    expect(sourceStart).toHaveBeenCalledTimes(1);
    expect(copyToChannel).toHaveBeenCalledTimes(1);
    expect(socket.send).toHaveBeenCalledTimes(1);
  });

  it("does not replay a completed sentence after reconnect", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "进入实时直播" }));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];

    act(() => {
      socket.open();
      socket.emitJson(snapshot("awaiting_observation", null));
    });

    expect(
      await screen.findByText(/法官第一句话已直播并保存/),
    ).toBeInTheDocument();
    expect(sourceStart).not.toHaveBeenCalled();
    expect(screen.queryByText("欢迎来到这场实时狼人杀对局。")).not.toBeInTheDocument();
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
    latest_presentation_seq: presentation ? 1 : 0,
    public_players: [
      {
        seat: 1,
        player_id: "profile-1",
        display_name: "阿青",
        avatar_url: null,
      },
      {
        seat: 2,
        player_id: "profile-2",
        display_name: "白石",
        avatar_url: null,
      },
    ],
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

function audioFrame(chunkIndex: number, startSample: number): ArrayBuffer {
  const header = new TextEncoder().encode(
    JSON.stringify({
      protocol_version: 1,
      action_id: actionId,
      presentation_seq: 1,
      presentation_id: presentationId,
      speech_id: speechId,
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
