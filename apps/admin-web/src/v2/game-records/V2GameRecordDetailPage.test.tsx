import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  createMemoryRouter,
  RouterProvider,
  type RouteObject,
} from "react-router-dom";

import V2GameRecordDetailPage from "@/v2/game-records/V2GameRecordDetailPage";
import { liveRefreshInterval } from "@/v2/game-records/live-refresh";

vi.mock("@/features/auth/session-context", () => ({
  useAdminSession: () => ({ session: null }),
}));

const gameId = "v2_game_observable";
const actionId = "v2_action_opening";
const runId = "v2_run_observable";
const occurredAt = "2026-07-23T08:00:00Z";

const detail = {
  game_id: gameId,
  title: "模型可观测性验收",
  status: "awaiting_observation",
  current_run_id: runId,
  record_schema_version: 1,
  last_record_seq: 7,
  last_presentation_seq: 1,
  phase_seq: 1,
  phase_id: "opening",
  phase_state: "opening_completed",
  created_at: occurredAt,
  updated_at: "2026-07-23T08:00:03Z",
  rule_snapshot: { player_count: 9 },
  players_snapshot: [],
  judge_voice_snapshot: {
    schema_version: 1,
    voice_mode: "fixed",
    selected_tts_speaker: "judge-speaker",
    random_tts_speakers: [],
    configuration_version: 1,
  },
  ability_snapshot: { compiler_version: 1 },
  match_state: { day_number: 0, alive_player_ids: [] },
  player_identities: [
    {
      seat: 1,
      player_id: "profile-1",
      display_name: "阿青",
      avatar_url: null,
      role: "seer",
      team: "village",
      alive: true,
      death_cause: null,
    },
    {
      seat: 2,
      player_id: "profile-2",
      display_name: "白石",
      avatar_url: null,
      role: "werewolf",
      team: "werewolves",
      alive: false,
      death_cause: "exile",
    },
  ],
  runs: [
    {
      run_id: runId,
      attempt_no: 1,
      status: "awaiting_observation",
      started_at: occurredAt,
      completed_at: null,
      stop_requested_at: null,
    },
  ],
  events: [
    event(1, "game_created", {}),
    event(2, "action_opened", {
      action_id: actionId,
      context: {
        phase_id: "opening",
        action_type: "judge_opening_speech",
        objective: "欢迎玩家并宣布对局开始",
        actor: { kind: "judge", id: "judge" },
      },
    }),
    event(3, "model_request_started", {
      action_id: actionId,
      attempt_id: "v2_model_attempt_1",
    }),
    event(4, "model_first_token_received", {
      action_id: actionId,
      attempt_id: "v2_model_attempt_1",
      elapsed_ms: 18,
    }),
    event(5, "model_response_received", {
      action_id: actionId,
      attempt_id: "v2_model_attempt_1",
    }),
    event(6, "speech_segment_committed", {
      action_id: actionId,
      presentation_seq: 1,
    }),
    event(7, "action_succeeded", { action_id: actionId }),
  ],
  model_requests: [
    {
      attempt_id: "v2_model_attempt_1",
      action_id: actionId,
      run_id: runId,
      phase_id: "opening",
      action_type: "judge_opening_speech",
      actor_kind: "judge",
      actor_id: "judge",
      audience: "all",
      request_kind: "speech",
      model_id: "doubao-seed-2-0-lite-260215",
      model_provider: "agent_plan",
      judge_configuration_version: 5,
      status: "succeeded",
      request_payload: {
        model: "doubao-seed-2-0-lite-260215",
        stream: true,
        max_output_tokens: 256,
        input: [
          {
            role: "system",
            content: [
              {
                type: "input_text",
                text: "你是狼人杀法官，只输出一句开场词。",
              },
            ],
          },
          {
            role: "user",
            content: [
              {
                type: "input_text",
                text: `请执行这个实时动作：${JSON.stringify({
                  schema_version: 1,
                  action_id: actionId,
                  action_type: "judge_opening_speech",
                  game_id: gameId,
                  run_id: runId,
                  phase_id: "opening",
                  actor: { kind: "judge", id: "judge" },
                  objective: "欢迎玩家并宣布对局开始",
                  game_setup: {
                    rule_name: "九人标准局",
                    player_count: 9,
                    role_summary: "3 狼人 / 3 神职 / 3 村民",
                    max_rounds: 6,
                  },
                  output_contract: {
                    kind: "public_speech",
                    language: "zh-CN",
                    target_policy: {
                      mode: "none",
                      allowed_target_ids: [],
                    },
                  },
                })}`,
              },
            ],
          },
        ],
      },
      input_source: "persisted",
      raw_response: "夜幕将至，九位玩家请准备。",
      parsed_output: { speech: "夜幕将至，九位玩家请准备。" },
      output_source: "persisted",
      provider_request_id: "provider-request-1",
      first_token_ms: 18,
      completed_ms: 311,
      failure_kind: null,
      failure_code: null,
      started_at: "2026-07-23T08:00:01Z",
      completed_at: "2026-07-23T08:00:02Z",
    },
  ],
  presentations: [
    {
      presentation_seq: 1,
      presentation_id: "v2_presentation_1",
      action_id: actionId,
      activation_id: null,
      phase_id: "opening",
      actor_kind: "judge",
      actor_id: "judge",
      audience: "all",
      speech_id: "v2_speech_1",
      segment_index: 0,
      source_event_id: 6,
      state: "closed",
      subtitle_text:
        '```json\n{"target_player_id":null,"speech":"夜幕将至，九位玩家请准备。"}\n```',
      voice_asset_id: null,
      audio_duration_ms: null,
      created_at: "2026-07-23T08:00:02Z",
      closed_at: "2026-07-23T08:00:03Z",
    },
  ],
  voice_assets: [],
  player_states: [],
  action_windows: [
    {
      window_id: "v2_window_first_night",
      run_id: runId,
      window_seq: 1,
      window_type: "night",
      state: "closed",
      plan: [],
      result: {
        peaceful: false,
        deaths: [{ player_id: "profile-2", cause: "werewolf_attack" }],
        attack_prevented_by: null,
      },
    },
  ],
  ability_instances: [
    {
      ability_instance_id: "v2_ability_seer",
      ability_id: "seer.investigate",
    },
  ],
  ability_activations: [
    {
      activation_id: "v2_activation_seer",
      window_id: "v2_window_first_night",
      ability_instance_id: "v2_ability_seer",
      actor_player_id: "profile-1",
      status: "completed",
      skip_reason: null,
      decision: { target_player_id: "profile-2" },
      result: { alignment: "werewolves" },
    },
  ],
  effect_intents: [],
  knowledge_facts: [],
};

const templateActionId = "v2_action_dawn";
const templateDetail = {
  ...detail,
  title: "确定性模板验收",
  last_record_seq: 4,
  phase_id: "day_1",
  phase_state: "dawn_announced",
  events: [
    event(1, "game_created", {}),
    event(2, "action_opened", {
      action_id: templateActionId,
      context: {
        phase_id: "day_1",
        action_type: "judge_dawn_announcement",
        objective: "播报天亮结果",
        actor: { kind: "judge", id: "judge" },
        speech_source: "template",
      },
    }),
    event(3, "judge_speech_rendered", {
      action_id: templateActionId,
      template_id: "judge_dawn_announcement",
      template_version: 1,
      variables: { public_deaths: ["白石"] },
      text: "天亮了，昨夜出局的玩家是：白石。",
      voice_mode: "fixed",
      tts_speaker: "judge-speaker",
      judge_configuration_version: 1,
    }),
    event(4, "action_succeeded", { action_id: templateActionId }),
  ],
  model_requests: [],
  presentations: [
    {
      ...detail.presentations[0],
      action_id: templateActionId,
      phase_id: "day_1",
      subtitle_text: "天亮了，昨夜出局的玩家是：白石。",
    },
  ],
};

function event(
  recordSeq: number,
  eventType: string,
  payload: Record<string, unknown>,
) {
  return {
    event_id: recordSeq,
    record_seq: recordSeq,
    run_id: runId,
    event_type: eventType,
    payload_schema_version: 1,
    payload,
    created_at: `2026-07-23T08:00:0${Math.min(recordSeq, 9)}Z`,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const routes: RouteObject[] = [
    {
      path: "/v2/operations/games/:gameId",
      element: <V2GameRecordDetailPage />,
    },
    {
      path: "/v2/operations/games",
      element: <div>对局列表</div>,
    },
  ];
  const router = createMemoryRouter(routes, {
    initialEntries: [`/v2/operations/games/${gameId}`],
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("V2 game record detail workspace", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = String(input);
        if (url.endsWith(`/api/v1/admin/v2/games/${gameId}`)) {
          return new Response(JSON.stringify(detail), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("connects the readable flow to persisted model input, output and raw data", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "模型可观测性验收" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("doubao-seed-2-0-lite-260215")).not.toHaveLength(
      0,
    );
    expect(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const livePanel = screen.getByRole("region", { name: "实时全知态势" });
    expect(
      within(livePanel).getByRole("heading", { name: /实时全知态势/ }),
    ).toBeVisible();
    expect(within(livePanel).getByText("完整身份总览")).toBeVisible();
    expect(within(livePanel).getByText("预言家")).toBeVisible();
    expect(within(livePanel).getByText("狼人")).toBeVisible();
    expect(within(livePanel).getByText("投票放逐")).toBeVisible();
    expect(within(livePanel).getByText("预言家查验")).toBeVisible();
    expect(within(livePanel).getByText("1号 阿青 → 2号 白石")).toBeVisible();
    expect(within(livePanel).getByText("查验为狼人阵营")).toBeVisible();
    expect(
      within(livePanel).getByText("出局：2号 白石（狼人袭击）"),
    ).toBeVisible();
    expect(
      within(livePanel).getByText("夜幕将至，九位玩家请准备。"),
    ).toBeVisible();
    expect(within(livePanel).queryByText(/target_player_id/)).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    expect(await screen.findByRole("dialog")).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "模型输入" }));
    const inputPanel = screen.getByRole("tabpanel", { name: "模型输入" });
    expect(
      within(inputPanel).getByText("你是狼人杀法官，只输出一句开场词。"),
    ).toBeVisible();
    expect(
      within(inputPanel).getByText("欢迎玩家并宣布对局开始"),
    ).toBeVisible();
    expect(within(inputPanel).getByText("对局配置")).toBeVisible();
    expect(within(inputPanel).getByText("九人标准局")).toBeVisible();
    expect(within(inputPanel).getByText("公开发言")).toBeVisible();
    expect(
      within(inputPanel).queryByText(/"schema_version"/),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "模型输出" }));
    const outputPanel = screen.getByRole("tabpanel", { name: "模型输出" });
    expect(within(outputPanel).getByText("程序采用结果")).toBeVisible();
    expect(
      within(outputPanel).getByText("夜幕将至，九位玩家请准备。"),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Close|关闭/ }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByRole("switch", { name: "仅看模型请求" }));
    await waitFor(() =>
      expect(screen.queryByText("游戏创建")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /底层数据/ }));
    expect(await screen.findByText("整局状态 (1)")).toBeVisible();
  });

  it("shows deterministic template variables, final text and frozen speaker", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = String(input);
        if (url.endsWith(`/api/v1/admin/v2/games/${gameId}`)) {
          return new Response(JSON.stringify(templateDetail), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "确定性模板验收" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("judge-speaker")).not.toHaveLength(0);
    expect(screen.getByText("系统模板")).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: "查看 法官 天亮播报" }),
    );
    expect(await screen.findByText("系统确定性模板")).toBeVisible();
    expect(
      screen.queryByRole("tab", { name: "模型输入" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "模板详情" }));
    const panel = screen.getByRole("tabpanel", { name: "模板详情" });
    expect(
      within(panel).getByText("judge_dawn_announcement"),
    ).toBeVisible();
    expect(within(panel).getByText("judge-speaker")).toBeVisible();
    expect(
      within(panel).getByText("天亮了，昨夜出局的玩家是：白石。"),
    ).toBeVisible();
    expect(within(panel).getByText(/public_deaths/)).toBeVisible();
  });

  it("refreshes active games every two seconds and stops polling terminal games", () => {
    expect(liveRefreshInterval("waiting_to_start")).toBe(2_000);
    expect(liveRefreshInterval("broadcasting")).toBe(2_000);
    expect(liveRefreshInterval("awaiting_observation")).toBe(false);
    expect(liveRefreshInterval("canceled")).toBe(false);
  });
});
