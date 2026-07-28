import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "@/routes";
import { expectAdminNotification } from "@/tests/admin-notification";

const gameId = "v2_game_0123456789abcdef";
const runId = "v2_run_0123456789abcdef";

describe("Admin V2 game control", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "false");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("requires a clear confirmation and audited reason before stopping the game", async () => {
    let stopped = false;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse({
          user: {
            id: "v2-operator",
            email: "operator@example.test",
            display_name: "值班运营",
            role: "operator",
          },
          permissions: ["v2_games.read", "runs.control"],
          csrf_token: "csrf-v2-control",
          session_expires_at: "2999-01-01T00:00:00Z",
        });
      }
      if (
        url.endsWith(`/api/v1/admin/v2/games/${gameId}/stop`) &&
        init?.method === "POST"
      ) {
        const headers = new Headers(init.headers);
        expect(headers.get("X-CSRF-Token")).toBe("csrf-v2-control");
        expect(headers.get("Idempotency-Key")).toBeTruthy();
        expect(JSON.parse(String(init.body))).toEqual({
          reason: "人工打断异常对局，避免继续消耗 API 额度",
        });
        stopped = true;
        return jsonResponse(
          {
            action: "stop",
            game_id: gameId,
            run_id: runId,
            run_status: "canceled",
            stop_requested_at: "2026-07-25T10:00:00Z",
            replayed: false,
          },
          202,
        );
      }
      if (url.endsWith(`/api/v1/admin/v2/games/${gameId}`)) {
        return jsonResponse(detail(stopped));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute();

    await user.click(
      await screen.findByRole("button", { name: "打断整局" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("确认打断整局")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/立即停止新的模型请求、关闭当前模型\/TTS 流/),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(new RegExp(gameId))).toBeInTheDocument();
    expect(within(dialog).getByText(new RegExp(runId))).toBeInTheDocument();
    expect(within(dialog).getByLabelText("操作原因")).toHaveValue(
      "人工打断异常对局，避免继续消耗 API 额度",
    );

    await user.click(
      within(dialog).getByRole("button", { name: "确认打断" }),
    );

    await expectAdminNotification("V2 对局打断请求已提交");
    expect(
      await screen.findByText("对局已由管理员打断"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "打断整局" }),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).endsWith(
              `/api/v1/admin/v2/games/${gameId}/stop`,
            ) && init?.method === "POST",
        ),
      ).toBe(true),
    );
  });
});

function renderRoute() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(routes, {
    initialEntries: [`/v2/operations/games/${gameId}`],
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function detail(stopped: boolean) {
  const now = "2026-07-25T09:00:00Z";
  return {
    game_id: gameId,
    title: "需要人工处置的 V2 对局",
    status: stopped ? "canceled" : "broadcasting",
    current_run_id: runId,
    record_schema_version: 1,
    last_record_seq: stopped ? 4 : 2,
    last_presentation_seq: 1,
    phase_seq: 1,
    phase_id: "opening",
    phase_state: "opening_ready",
    created_at: now,
    updated_at: now,
    rule_snapshot: {},
    players_snapshot: [],
    judge_voice_snapshot: {
      schema_version: 1,
      voice_mode: "fixed",
      selected_tts_speaker: "judge-speaker",
      random_tts_speakers: [],
      configuration_version: 1,
    },
    ability_snapshot: {},
    match_state: null,
    player_identities: [],
    runs: [
      {
        run_id: runId,
        attempt_no: 1,
        status: stopped ? "canceled" : "broadcasting",
        started_at: now,
        completed_at: stopped ? "2026-07-25T10:00:00Z" : null,
        stop_requested_at: stopped ? "2026-07-25T10:00:00Z" : null,
      },
    ],
    events: [],
    model_requests: [],
    presentations: [],
    voice_assets: [],
    player_states: [],
    action_windows: [],
    ability_instances: [],
    ability_activations: [],
    effect_intents: [],
    knowledge_facts: [],
  };
}

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
