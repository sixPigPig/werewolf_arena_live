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
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";

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
  audio_mode: "tts",
  match_status: "running",
  execution_state: "owned",
  winner: null,
  completion_reason: null,
  completed_at: null,
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
  delivery_snapshot: {
    schema_version: 1,
    mode: "tts",
    source: "explicit_create_request",
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
      worker_id: "v2-worker-observable",
      worker_heartbeat_at: "2026-07-23T08:00:02Z",
      lease_expires_at: "2026-07-23T08:00:32Z",
      fence_token: 4,
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
      audience: "director",
      stored_audience: "all",
      effective_audience: "director",
      audience_source: "event_contract_narrowed",
      request_kind: "speech",
      model_id: "doubao-seed-2-0-lite-260215",
      model_provider: "agent_plan",
      judge_configuration_version: 5,
      prompt_schema_version: 6,
      prompt_projection: {
        serialized_char_count: 3210,
        ledger_schema_version: 2,
        model_view_schema_version: 1,
        ledger_statement_count: 9,
        dropped_statement_count: 0,
        current_round_statement_count: 3,
        structured_claim_count: 5,
        open_question_count: 2,
        public_timeline_schema_version: 1,
        public_timeline_event_count: 3,
        public_timeline_record_seq_min: 448,
        public_timeline_record_seq_max: 564,
        public_timeline_missing_record_seq_count: 0,
        public_timeline_kind_counts: {
          player_statement: 1,
          day_vote: 2,
        },
      },
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
                  public_timeline: {
                    schema_version: 1,
                    source_rules: {
                      record_seq_clock:
                        "所有公开事件共用同一条严格递增的时间轴。",
                    },
                    events: [
                      {
                        record_seq: 448,
                        kind: "player_statement",
                        authority: "player_claim_unverified",
                        source_event_id: "448",
                        timeline_index: 1,
                        occurred_in: { period: "day", round_no: 1 },
                        stage: "sheriff_campaign_speech",
                        speaker_ref: "seat_6",
                        statement_ref: "448",
                      },
                      {
                        record_seq: 562,
                        kind: "day_vote",
                        authority: "judge_fact",
                        source_event_id: "562",
                        timeline_index: 2,
                        occurred_in: { period: "day", round_no: 1 },
                        action_type: "sheriff_vote",
                        voter_ref: "seat_2",
                        target_ref: "seat_7",
                        weight: 1,
                      },
                      {
                        record_seq: 564,
                        kind: "day_vote",
                        authority: "judge_fact",
                        source_event_id: "564",
                        timeline_index: 3,
                        occurred_in: { period: "day", round_no: 1 },
                        action_type: "sheriff_vote",
                        voter_ref: "seat_5",
                        target_ref: "seat_7",
                        weight: 1,
                      },
                    ],
                  },
                  history: {
                    ledger_schema_version: 2,
                    model_view_schema_version: 1,
                    current_round_no: 1,
                    timeline: [
                      {
                        source_event_id: "448",
                        record_seq: 448,
                        speaker_ref: "seat_6",
                        speech: "警徽流：今晚验2号，明晚验5号。",
                        annotations: [],
                      },
                    ],
                    questions: [],
                    relations: [],
                    focus: { profile: "public_speech" },
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
      passive_observations: [
        {
          code: "wolf_cardinality_contradiction",
          severity: "warning",
          effect: "observed_only",
        },
      ],
      output_source: "persisted",
      provider_request_id: "provider-request-1",
      first_token_ms: 18,
      first_token_seen: true,
      response_headers_seen: true,
      response_headers: {
        "x-request-id": "provider-header-1",
        "x-ratelimit-remaining-requests": "9",
      },
      first_token_kind: "reasoning",
      first_visible_text_ms: 27,
      timeout_scope: "attempt_budget",
      completed_ms: 311,
      failure_kind: null,
      failure_code: null,
      model_binding_failure_streak: 0,
      model_binding_health_status: "healthy",
      model_binding_recovered_after_failures: 1,
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
  knowledge_facts: [
    {
      knowledge_fact_id: "v2_fact_seer_result",
      source_activation_id: "v2_activation_seer",
      owner_scope: "player",
      owner_id: "profile-1",
      fact_type: "investigation_alignment",
      payload: {
        night_no: 1,
        target_player_id: "profile-2",
        alignment: "werewolves",
      },
    },
  ],
};

const privateInformationDetail = {
  ...detail,
  title: "私有信息归属验收",
  player_identities: [
    ...detail.player_identities,
    {
      seat: 3,
      player_id: "profile-3",
      display_name: "未行动者",
      avatar_url: null,
      role: "villager",
      team: "village",
      alive: false,
      death_cause: "witch_poison",
    },
  ],
  ability_instances: [
    ...detail.ability_instances,
    {
      ability_instance_id: "v2_ability_werewolf",
      ability_id: "werewolf.attack",
    },
  ],
  ability_activations: [
    ...detail.ability_activations,
    {
      activation_id: "v2_activation_werewolf_discussion",
      window_id: "v2_window_first_night",
      ability_instance_id: "v2_ability_werewolf",
      actor_player_id: "profile-2",
      status: "completed",
      skip_reason: null,
      decision: {
        decision_stage: "discussion",
        target_player_id: "profile-3",
      },
      result: {
        adopted: false,
        decision_stage: "discussion",
      },
    },
  ],
  knowledge_facts: [
    ...detail.knowledge_facts,
    {
      knowledge_fact_id: "v2_fact_seer_result_second_night",
      source_activation_id: "v2_activation_seer",
      owner_scope: "player",
      owner_id: "profile-1",
      fact_type: "investigation_alignment",
      payload: {
        night_no: 2,
        target_player_id: "profile-3",
        alignment: "villagers",
      },
    },
  ],
};

const deepSeekDetail = {
  ...detail,
  title: "DeepSeek 输入兼容验收",
  model_requests: [
    {
      ...detail.model_requests[0],
      model_id: "deepseek-v4-flash",
      model_provider: "deepseek",
      request_payload: {
        model: "deepseek-v4-flash",
        stream: true,
        max_tokens: 16384,
        messages: [
          {
            role: "system",
            content: "你正在扮演一名狼人杀玩家，只能根据已提供的信息行动。",
          },
          {
            role: "user",
            content: `请完成这个实时动作：${JSON.stringify({
              schema_version: 1,
              action_id: actionId,
              action_type: "ability_werewolf_attack_decision",
              game_id: gameId,
              run_id: runId,
              phase_id: "first_night",
              actor: { kind: "player", id: "seat_3" },
              objective: "选择本轮狼人团队建议袭击的一名非狼人存活玩家",
              output_contract: {
                kind: "decision_and_speech",
                language: "zh-CN",
                target_policy: {
                  mode: "required",
                  allowed_target_ids: ["seat_1", "seat_2", "seat_4"],
                },
              },
            })}`,
          },
        ],
        response_format: { type: "json_object" },
        thinking: { type: "enabled" },
      },
    },
  ],
};

const retryDetail = {
  ...detail,
  title: "模型重试验收",
  last_record_seq: 10,
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
      attempt_no: 1,
      max_attempts: 2,
    }),
    event(4, "model_request_failed", {
      action_id: actionId,
      attempt_id: "v2_model_attempt_1",
      attempt_no: 1,
      max_attempts: 2,
      failure_kind: "model",
      failure_code: "model_transport_failed",
      retryable: true,
      terminal: false,
      failure_stage: "connect",
      exception_type: "builtins.ConnectionResetError",
      errno: 54,
      first_token_seen: false,
      elapsed_ms: 5038,
    }),
    event(5, "model_retry_scheduled", {
      action_id: actionId,
      attempt_id: "v2_model_attempt_1",
      next_attempt_id: "v2_model_attempt_2",
      failure_code: "model_transport_failed",
      delay_ms: 300,
    }),
    event(6, "model_request_started", {
      action_id: actionId,
      attempt_id: "v2_model_attempt_2",
      attempt_no: 2,
      max_attempts: 2,
      retry_of_attempt_id: "v2_model_attempt_1",
    }),
    event(7, "model_first_token_received", {
      action_id: actionId,
      attempt_id: "v2_model_attempt_2",
      first_token_ms: 925,
    }),
    event(8, "model_response_received", {
      action_id: actionId,
      attempt_id: "v2_model_attempt_2",
    }),
    event(9, "speech_segment_committed", {
      action_id: actionId,
      presentation_seq: 1,
    }),
    event(10, "action_succeeded", { action_id: actionId }),
  ],
  model_requests: [
    {
      ...detail.model_requests[0],
      attempt_id: "v2_model_attempt_1",
      attempt_no: 1,
      max_attempts: 2,
      retry_of_attempt_id: null,
      status: "failed",
      raw_response: null,
      parsed_output: null,
      output_source: "unavailable",
      provider_request_id: null,
      first_token_ms: null,
      completed_ms: null,
      failure_kind: "model",
      failure_code: "model_transport_failed",
      retryable: true,
      terminal: false,
      failure_stage: "connect",
      exception_type: "builtins.ConnectionResetError",
      errno: 54,
      http_status: null,
      first_token_seen: false,
      failure_elapsed_ms: 5038,
      completed_at: "2026-07-23T08:00:04Z",
    },
    {
      ...detail.model_requests[0],
      attempt_id: "v2_model_attempt_2",
      attempt_no: 2,
      max_attempts: 2,
      retry_of_attempt_id: "v2_model_attempt_1",
      status: "succeeded",
      first_token_ms: 925,
      completed_ms: 3342,
      started_at: "2026-07-23T08:00:06Z",
      completed_at: "2026-07-23T08:00:08Z",
    },
  ],
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

const roundSummaryDetail = {
  ...detail,
  title: "轮次摘要验收",
  status: "awaiting_observation",
  match_status: "completed",
  execution_state: "stopped",
  winner: "villagers",
  completion_reason: "deterministic_win_condition",
  completed_at: "2026-07-23T08:00:06Z",
  last_record_seq: 6,
  phase_id: "day_1",
  phase_state: "game_completed",
  runs: detail.runs.map((run) => ({
    ...run,
    status: "awaiting_observation",
    completed_at: "2026-07-23T08:00:06Z",
    worker_id: null,
    worker_heartbeat_at: null,
    lease_expires_at: null,
    fence_token: 5,
  })),
  events: [
    event(1, "game_phase_changed", {
      previous_phase_id: "opening",
      phase_id: "first_night",
      phase_state: "nightfall_ready",
    }),
    event(2, "action_window_opened", {
      window_id: "v2_window_round_1",
      window_type: "night",
      round_no: 1,
    }),
    event(3, "action_window_closed", {
      window_id: "v2_window_round_1",
      result: { peaceful: true, deaths: [] },
    }),
    event(4, "game_phase_changed", {
      previous_phase_id: "first_night",
      phase_id: "day_1",
      phase_state: "public_day_ready",
    }),
    event(5, "player_exiled", {
      round_no: 1,
      player_id: "profile-2",
    }),
    event(6, "game_completed", {
      round_no: 1,
      winner: "villagers",
      reason: "deterministic_win_condition",
    }),
  ],
  model_requests: [],
  presentations: [],
  action_windows: [
    {
      window_id: "v2_window_round_1",
      run_id: runId,
      window_seq: 1,
      window_type: "night",
      state: "closed",
      plan: [],
      result: {
        peaceful: true,
        deaths: [],
        attack_prevented_by: "guard",
      },
    },
  ],
};

const phaseIntegrityDetail = {
  ...detail,
  title: "阶段完整性验收",
  status: "awaiting_observation",
  match_status: "completed",
  execution_state: "stopped",
  winner: "villagers",
  completion_reason: "deterministic_win_condition",
  completed_at: "2026-07-23T08:00:11Z",
  last_record_seq: 11,
  phase_id: "day_2",
  phase_state: "game_completed",
  runs: detail.runs.map((run) => ({
    ...run,
    status: "awaiting_observation",
    completed_at: "2026-07-23T08:00:11Z",
    worker_id: null,
    worker_heartbeat_at: null,
    lease_expires_at: null,
    fence_token: 5,
  })),
  player_identities: detail.player_identities.map((identity) =>
    identity.player_id === "profile-2"
      ? { ...identity, death_cause: "werewolf_self_explosion" }
      : identity,
  ),
  events: [
    event(1, "game_phase_changed", {
      previous_phase_id: "opening",
      phase_id: "first_night",
      phase_state: "nightfall_ready",
    }),
    event(2, "action_window_opened", {
      window_id: "v2_window_night_1",
      window_type: "night",
      round_no: 1,
    }),
    event(3, "action_window_closed", {
      window_id: "v2_window_night_1",
      result: { peaceful: true, deaths: [] },
    }),
    event(4, "game_phase_changed", {
      previous_phase_id: "first_night",
      phase_id: "day_1",
      phase_state: "dawn_reactions_ready",
    }),
    event(5, "action_window_opened", {
      window_id: "v2_window_dawn_reaction",
      window_type: "dawn_reaction",
    }),
    event(6, "action_window_closed", {
      window_id: "v2_window_dawn_reaction",
      result: { completed: true },
    }),
    event(7, "game_phase_changed", {
      previous_phase_id: "day_1",
      phase_id: "night_2",
      phase_state: "nightfall_ready",
    }),
    event(8, "action_window_opened", {
      window_id: "v2_window_night_2",
      window_type: "night",
      round_no: 2,
    }),
    event(9, "action_window_closed", {
      window_id: "v2_window_night_2",
      result: {
        peaceful: false,
        deaths: [
          { player_id: "profile-2", cause: "werewolf_self_explosion" },
        ],
      },
    }),
    event(10, "game_phase_changed", {
      previous_phase_id: "night_2",
      phase_id: "day_2",
      phase_state: "game_completed",
    }),
    event(11, "game_completed", {
      round_no: 2,
      winner: "villagers",
      reason: "deterministic_win_condition",
    }),
  ],
  model_requests: [],
  presentations: [],
  action_windows: [
    {
      window_id: "v2_window_night_1",
      run_id: runId,
      window_seq: 1,
      window_type: "night",
      state: "closed",
      plan: [],
      result: { peaceful: true, deaths: [] },
    },
    {
      window_id: "v2_window_dawn_reaction",
      run_id: runId,
      window_seq: 2,
      window_type: "dawn_reaction",
      state: "closed",
      plan: [],
      result: { completed: true },
    },
    {
      window_id: "v2_window_night_2",
      run_id: runId,
      window_seq: 3,
      window_type: "night",
      state: "closed",
      plan: [],
      result: {
        peaceful: false,
        deaths: [
          { player_id: "profile-2", cause: "werewolf_self_explosion" },
        ],
      },
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

type DetailFixture = Record<string, unknown> & {
  events: Array<ReturnType<typeof event>>;
  game_id: string;
  last_record_seq: number;
  model_requests: Array<Record<string, unknown> & { attempt_id: string }>;
};

function stubRecordFetch(record: DetailFixture) {
  const basePath = `/api/v1/admin/v2/games/${record.game_id}`;
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const url = new URL(String(input), "http://admin.test");
    if (url.pathname === basePath) {
      const summary = Object.fromEntries(
        Object.entries(record).filter(
          ([key]) => key !== "events" && key !== "model_requests",
        ),
      );
      return jsonResponse(summary);
    }
    if (url.pathname === `${basePath}/events`) {
      const afterRecordSeq = Number(
        url.searchParams.get("after_record_seq") ?? 0,
      );
      return jsonResponse({
        after_record_seq: afterRecordSeq,
        has_more: false,
        items: record.events.filter(
          (item) => item.record_seq > afterRecordSeq,
        ),
        next_after_record_seq: record.last_record_seq,
      });
    }
    if (url.pathname.startsWith(`${basePath}/events/`)) {
      const eventId = Number(url.pathname.slice(`${basePath}/events/`.length));
      const matched = record.events.find((item) => item.event_id === eventId);
      if (matched) return jsonResponse(matched);
    }
    if (url.pathname === `${basePath}/model-requests`) {
      const afterRecordSeq = Number(
        url.searchParams.get("after_record_seq") ?? 0,
      );
      const items = record.model_requests.flatMap((request, index) => {
        const recordSeq = Number(request.record_seq ?? index + 1);
        if (recordSeq <= afterRecordSeq) return [];
        const summary = Object.fromEntries(
          Object.entries(request).filter(
            ([key]) =>
              ![
                "request_payload",
                "raw_response",
                "parsed_output",
                "passive_observations",
              ].includes(key),
          ),
        );
        return [
          {
            ...summary,
            last_record_seq: Number(
              request.last_record_seq ?? record.last_record_seq,
            ),
            passive_observation_count: Array.isArray(
              request.passive_observations,
            )
              ? request.passive_observations.length
              : 0,
            record_seq: recordSeq,
          },
        ];
      });
      return jsonResponse({
        after_record_seq: afterRecordSeq,
        has_more: false,
        items,
        next_after_record_seq: record.last_record_seq,
      });
    }
    if (url.pathname.startsWith(`${basePath}/model-requests/`)) {
      const attemptId = decodeURIComponent(
        url.pathname.slice(`${basePath}/model-requests/`.length),
      );
      const matched = record.model_requests.find(
        (item) => item.attempt_id === attemptId,
      );
      if (matched) return jsonResponse(matched);
    }
    throw new Error(`Unexpected request: ${url.toString()}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
    status: 200,
  });
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
  return { queryClient, router };
}

describe("V2 game record detail workspace", () => {
  beforeEach(() => {
    stubRecordFetch(detail);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("connects the readable flow to persisted model input, output and raw data", async () => {
    const user = userEvent.setup();
    renderPage();
    const fetchMock = vi.mocked(fetch);

    expect(
      await screen.findByRole("heading", { name: "模型可观测性验收" }),
    ).toBeInTheDocument();
    const summaryMetrics = screen.getByRole("region", { name: "对局摘要" });
    expect(within(summaryMetrics).getByText("进行中")).toBeVisible();
    expect(within(summaryMetrics).getByText("执行中")).toBeVisible();
    expect(within(summaryMetrics).getByText("语音播报")).toBeVisible();
    expect(within(summaryMetrics).queryByText(/已完成/)).not.toBeInTheDocument();
    expect(screen.getAllByText("doubao-seed-2-0-lite-260215")).not.toHaveLength(
      0,
    );
    expect(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    ).toBeInTheDocument();
    const phaseRail = screen.getByRole("navigation", { name: "对局阶段" });
    expect(phaseRail.querySelector(".ant-steps-vertical")).not.toBeNull();
    const actionRow = screen
      .getByRole("button", { name: "查看 法官 开场播报" })
      .closest("tr");
    expect(actionRow).not.toBeNull();
    await user.click(
      within(actionRow as HTMLTableRowElement).getByRole("button", {
        name: "Expand row",
      }),
    );
    expect(screen.getByLabelText("动作生命周期")).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/model-requests/v2_model_attempt_1"),
      ),
    ).toBe(true);
    const livePanel = screen.getByRole("region", { name: "全知战局态势" });
    expect(
      within(livePanel).getByRole("heading", { name: /全知战局态势/ }),
    ).toBeVisible();
    expect(within(livePanel).getByText("此刻发生了什么")).toBeVisible();
    expect(
      within(livePanel).queryByTitle(
        "展示当前历史游标对应的权威事实与动作内容",
      ),
    ).not.toBeInTheDocument();
    expect(within(livePanel).getByText("此刻全知状态")).toBeVisible();
    expect(within(livePanel).getByText("本轮已知公开信息")).toBeVisible();
    expect(within(livePanel).getByText("预言家")).toBeVisible();
    expect(within(livePanel).getByText("狼人")).toBeVisible();
    expect(within(livePanel).getByText("投票放逐")).toBeVisible();
    expect(
      within(livePanel).getByText("预言家查验 → 2号 白石"),
    ).toBeVisible();
    expect(
      within(livePanel).getByText("第1夜查验：2号 白石为狼人阵营"),
    ).toBeVisible();
    expect(
      within(livePanel).getAllByText("夜幕将至，九位玩家请准备。"),
    ).not.toHaveLength(0);
    const causalFacts = within(livePanel).getByLabelText("传给模型的全部事实");
    expect(await within(causalFacts).findByText("#448")).toBeVisible();
    expect(
      within(causalFacts).queryByText(/警徽流：今晚验2号/),
    ).not.toBeInTheDocument();
    expect(within(livePanel).getByText("3 条")).toBeVisible();
    expect(within(livePanel).getByText("#562")).toBeVisible();
    expect(within(livePanel).getByText("#564")).toBeVisible();
    expect(within(livePanel).queryByText(/target_player_id/)).not.toBeInTheDocument();
    expect(within(livePanel).queryByText("权威事实")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    const requestDialog = await screen.findByRole("dialog");
    expect(requestDialog).toBeVisible();
    expect(within(requestDialog).getByText("存储受众")).toBeVisible();
    expect(within(requestDialog).getByText("公开（all）")).toBeVisible();
    expect(within(requestDialog).getByText("生效受众")).toBeVisible();
    expect(within(requestDialog).getByText("私密（director）")).toBeVisible();
    expect(within(requestDialog).getByText("判定来源")).toBeVisible();
    expect(
      within(requestDialog).getByText("事件契约（按执行者收窄）"),
    ).toBeVisible();
    expect(within(requestDialog).getByText("首 Token 类型")).toBeVisible();
    expect(within(requestDialog).getByText("推理（reasoning）")).toBeVisible();
    expect(within(requestDialog).getByText("首可见文本")).toBeVisible();
    expect(within(requestDialog).getByText("27 ms")).toBeVisible();
    expect(within(requestDialog).getByText("超时预算范围")).toBeVisible();
    expect(
      within(requestDialog).getByText("请求尝试预算（attempt_budget）"),
    ).toBeVisible();
    expect(within(requestDialog).getByText("模型绑定健康")).toBeVisible();
    expect(within(requestDialog).getByText("健康")).toBeVisible();
    expect(within(requestDialog).getByText("连续故障次数")).toBeVisible();
    expect(within(requestDialog).getByText("本次恢复前故障")).toBeVisible();
    const responseHeaders = within(requestDialog).getByRole("region", {
      name: "模型响应头",
    });
    const responseHeadersToggle = within(responseHeaders)
      .getByText("响应头白名单（2）")
      .closest(".ant-collapse-header");
    expect(responseHeadersToggle).not.toBeNull();
    await user.click(responseHeadersToggle as HTMLElement);
    expect(responseHeaders.querySelector("pre")).toHaveTextContent(
      '"x-request-id": "provider-header-1"',
    );
    expect(responseHeaders.querySelector("pre")).toHaveTextContent(
      '"x-ratelimit-remaining-requests": "9"',
    );

    await user.click(screen.getByRole("tab", { name: "模型输入" }));
    const inputPanel = screen.getByRole("tabpanel", { name: "模型输入" });
    const inputCopyButton = within(inputPanel).getByRole("button", {
      name: "复制完整输入 JSON",
    });
    expect(inputCopyButton).toBeVisible();
    await user.click(inputCopyButton);
    expect(inputCopyButton).toHaveTextContent("已复制");
    expect(await navigator.clipboard.readText()).toBe(
      JSON.stringify(detail.model_requests[0].request_payload, null, 2),
    );
    expect(
      within(inputPanel).getByText("你是狼人杀法官，只输出一句开场词。"),
    ).toBeVisible();
    expect(
      within(inputPanel).getByText("欢迎玩家并宣布对局开始"),
    ).toBeVisible();
    expect(within(inputPanel).getByText("对局配置")).toBeVisible();
    expect(within(inputPanel).getByText("九人标准局")).toBeVisible();
    expect(within(inputPanel).getAllByText("公开发言")).not.toHaveLength(0);
    expect(within(inputPanel).getByText("V6")).toBeVisible();
    expect(within(inputPanel).getByText("3,210")).toBeVisible();
    expect(within(inputPanel).getByText("发言账本")).toBeVisible();
    expect(within(inputPanel).getByText("V2")).toBeVisible();
    expect(within(inputPanel).getByText("模型视图")).toBeVisible();
    expect(within(inputPanel).getAllByText("V1")).not.toHaveLength(0);
    expect(within(inputPanel).getByText("完整公开发言")).toBeVisible();
    expect(within(inputPanel).getByText("发言截断")).toBeVisible();
    expect(within(inputPanel).getByText("0（无截断）")).toBeVisible();
    expect(within(inputPanel).getByText("本轮完整发言")).toBeVisible();
    expect(within(inputPanel).getByText("结构化声明")).toBeVisible();
    expect(within(inputPanel).getByText("未回答提问")).toBeVisible();
    expect(
      within(inputPanel).getAllByText("统一公开时间线"),
    ).not.toHaveLength(0);
    expect(within(inputPanel).getByText("3 个事件")).toBeVisible();
    expect(within(inputPanel).getByText("#448 – #564")).toBeVisible();
    expect(within(inputPanel).getByText("玩家发言 × 1")).toBeVisible();
    expect(within(inputPanel).getByText("白天投票 × 2")).toBeVisible();
    expect(within(inputPanel).getByText("0（完整）")).toBeVisible();
    await user.click(
      within(inputPanel).getByText(
        "查看统一公开时间线详情（3 个事件）",
      ),
    );
    await waitFor(() =>
      expect(within(inputPanel).getByText("#448")).toBeVisible(),
    );
    expect(within(inputPanel).getByText("#562")).toBeVisible();
    expect(within(inputPanel).getByText("#564")).toBeVisible();
    expect(
      within(inputPanel).getByText("警徽流：今晚验2号，明晚验5号。"),
    ).toBeVisible();
    expect(within(inputPanel).getAllByText("seat_7")).toHaveLength(2);
    expect(within(inputPanel).getByText("发言账本")).toBeVisible();
    expect(
      within(inputPanel).queryByText(/"schema_version"/),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "模型输出" }));
    const outputPanel = screen.getByRole("tabpanel", { name: "模型输出" });
    const outputCopyButton = within(outputPanel).getByRole("button", {
      name: "复制完整输出 JSON",
    });
    expect(outputCopyButton).toBeVisible();
    await user.click(outputCopyButton);
    expect(outputCopyButton).toHaveTextContent("已复制");
    expect(await navigator.clipboard.readText()).toBe(
      JSON.stringify(
        {
          raw_response: detail.model_requests[0].raw_response,
          parsed_output: detail.model_requests[0].parsed_output,
        },
        null,
        2,
      ),
    );
    expect(
      within(outputPanel).getByText("旁路观察（未影响对局，1 项）"),
    ).toBeVisible();
    expect(
      within(outputPanel).getByText(/不会触发重试、改写、拦截或替换/),
    ).toBeVisible();
    expect(within(outputPanel).getByText("程序采用结果")).toBeVisible();
    expect(
      within(outputPanel).getByText("夜幕将至，九位玩家请准备。"),
    ).toBeVisible();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/model-requests/v2_model_attempt_1"),
      ),
    ).toBe(true);

    await user.click(screen.getByRole("tab", { name: "原始事件 (6)" }));
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes(`/events/2`),
      ),
    ).toBe(false);
    const rawEventLabel = screen.getByText("action_opened");
    const rawEventButton = rawEventLabel.closest(".ant-collapse-header");
    expect(rawEventButton).not.toBeNull();
    await user.click(rawEventButton as HTMLElement);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes(`/events/2`),
        ),
      ).toBe(true),
    );

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
  }, 60_000);

  it("keeps an unknown legacy request audience visibly unknown", async () => {
    const user = userEvent.setup();
    stubRecordFetch({
      ...detail,
      model_requests: [
        {
          ...detail.model_requests[0],
          audience: "legacy_unknown",
          stored_audience: null,
          effective_audience: "legacy_unknown",
          audience_source: "legacy_unknown",
        },
      ],
    });
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "模型可观测性验收" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    const requestDialog = await screen.findByRole("dialog");

    expect(within(requestDialog).getByText("未记录")).toBeVisible();
    expect(
      within(requestDialog).getByText("旧记录范围未知（legacy_unknown）"),
    ).toBeVisible();
    expect(within(requestDialog).getByText("旧记录无法判定")).toBeVisible();
    expect(
      within(requestDialog).queryByText("私密（legacy_unknown）"),
    ).not.toBeInTheDocument();
  });

  it("preloads saved voice metadata and shows the persisted duration", async () => {
    stubRecordFetch({
      ...detail,
      presentations: [
        {
          ...detail.presentations[0],
          audio_duration_ms: 1_800,
          voice_asset_id: "v2_voice_1",
        },
      ],
      voice_assets: [
        {
          voice_asset_id: "v2_voice_1",
          action_id: actionId,
          activation_id: null,
          audience: "all",
          presentation_id: "v2_presentation_1",
          speech_id: "v2_speech_1",
          segment_index: 0,
          state: "ready",
          mime_type: "audio/wav",
          sample_rate: 24_000,
          channels: 1,
          sample_count: 43_200,
          duration_ms: 1_800,
          pcm_sha256: "voice-sha",
          size_bytes: 86_444,
          audio_url:
            "/api/v1/admin/v2/games/v2_game_observable/voice-assets/v2_voice_1/audio",
          created_at: occurredAt,
          completed_at: "2026-07-23T08:00:03Z",
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "查看 法官 开场播报" }),
    );
    const audio = await screen.findByLabelText("法官保存语音");

    expect(audio).toHaveAttribute("preload", "metadata");
    expect(screen.getByText("时长 1.80 s")).toBeVisible();
  });

  it("shows only persisted owner knowledge and localizes empty/action states", async () => {
    stubRecordFetch(privateInformationDetail);
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "私有信息归属验收" }),
    ).toBeVisible();
    const panel = screen.getByRole("region", { name: "全知战局态势" });
    const inactivePlayer = within(panel).getByText("未行动者").closest("tr");
    expect(inactivePlayer).not.toBeNull();
    expect(within(inactivePlayer!).getByText("暂无私有信息")).toBeVisible();
    expect(within(inactivePlayer!).getByText("--")).toBeVisible();
    expect(within(inactivePlayer!).getByText("女巫毒杀")).toBeVisible();
    expect(within(panel).queryByText("被袭击")).not.toBeInTheDocument();
    expect(within(panel).queryByText("witch_poison")).not.toBeInTheDocument();
    expect(
      within(panel).getByText("第2夜查验：3号 未行动者为好人阵营"),
    ).toBeVisible();
    expect(
      within(panel).queryByText("第1夜查验：2号 白石为狼人阵营"),
    ).not.toBeInTheDocument();

    await user.click(
      within(panel).getByRole("button", {
        name: "查看 1号 阿青的全部私有信息（2条）",
      }),
    );

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("1号 阿青 · 全部私有信息"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("第1夜查验：2号 白石为狼人阵营"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("第2夜查验：3号 未行动者为好人阵营"),
    ).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: /Close|关闭/ }),
    );
    await waitFor(() =>
      expect(dialog).toHaveClass("ant-zoom-leave"),
    );
  });

  it("derives public timeline evidence from persisted input for older summaries", async () => {
    stubRecordFetch({
      ...detail,
      title: "统一时间线兼容验收",
      model_requests: [
        {
          ...detail.model_requests[0],
          prompt_projection: {
            serialized_char_count: 3210,
            ledger_schema_version: 2,
            ledger_statement_count: 9,
          },
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "统一时间线兼容验收" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    await user.click(screen.getByRole("tab", { name: "模型输入" }));
    const inputPanel = screen.getByRole("tabpanel", { name: "模型输入" });

    expect(within(inputPanel).getByText("3 个事件")).toBeVisible();
    expect(within(inputPanel).getByText("#448 – #564")).toBeVisible();
    expect(within(inputPanel).getByText("玩家发言 × 1")).toBeVisible();
    expect(within(inputPanel).getByText("白天投票 × 2")).toBeVisible();
  });

  it("shows V8 known-event chronology and selector audit", async () => {
    const knownEvents = {
      events: [
        {
          authority: "judge_fact",
          data: {
            decision: {
              decision_note: "在警上发言前已经决定查验6号。",
              target_player_id: "seat_6",
            },
            result: { alignment: "werewolves" },
          },
          event_ref: "knowledge-seer-night-1",
          kind: "private_ability_action_committed",
          known_at_seq: 258,
          visibility: "actor_private",
        },
        {
          authority: "player_statement",
          event_ref: "472",
          kind: "player_statement",
          known_at_seq: 472,
          speaker_ref: "seat_6",
          speech: "6号上警，我先听后置位怎么说。",
          visibility: "public",
        },
      ],
      schema_version: 1,
    };
    stubRecordFetch({
      ...detail,
      title: "V8 已知事件验收",
      model_requests: [
        {
          ...detail.model_requests[0],
          model_context_schema_version: 8,
          model_view_selector_version: 1,
          prompt_schema_version: 8,
          prompt_template_version: 1,
          prompt_projection: {
            dropped_event_count: 3,
            dropped_event_refs: ["100", "101", "102"],
            known_event_count: 2,
            known_event_record_seq_max: 472,
            known_event_record_seq_min: 258,
            known_event_total_count: 5,
            known_events_schema_version: 1,
            model_context_schema_version: 8,
            model_view_schema_version: 3,
            model_view_selector_version: 1,
            prompt_template_version: 1,
            retained_event_refs: ["knowledge-seer-night-1", "472"],
            retention_reasons: {
              "472": "current_round",
              "knowledge-seer-night-1": "actor_private",
            },
            section_char_counts: { known_events: 680, task: 90 },
            selection_budget_chars: 8000,
            selection_budget_exceeded_by_required: false,
            selection_used_chars: 680,
            serialized_char_count: 1600,
          },
          request_payload: {
            input: [
              {
                content: [
                  {
                    text: `请执行这个实时动作：${JSON.stringify({
                      known_events: knownEvents,
                      model_context_schema_version: 8,
                      prompt_template_version: 1,
                      state: { as_of_seq: 501, round_no: 1 },
                      task: {
                        at_seq: 501,
                        goal: "发表警长竞选发言。",
                        type: "sheriff_campaign_speech",
                      },
                    })}`,
                    type: "input_text",
                  },
                ],
                role: "user",
              },
            ],
            model: "doubao-seed-2-0-lite-260215",
            stream: true,
          },
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "V8 已知事件验收" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    await user.click(screen.getByRole("tab", { name: "模型输入" }));
    const inputPanel = screen.getByRole("tabpanel", { name: "模型输入" });

    expect(within(inputPanel).getByText("已选 2 / 完整 5")).toBeVisible();
    expect(within(inputPanel).getByText("未送入模型 3")).toBeVisible();
    expect(within(inputPanel).getByText("#258 – #472")).toBeVisible();
    expect(within(inputPanel).getByText("680 / 8,000 字符")).toBeVisible();
    await user.click(
      within(inputPanel).getByRole("button", {
        name: /查看动作前已知事件（2 个）/,
      }),
    );
    await waitFor(() =>
      expect(
        within(inputPanel).getByText("在警上发言前已经决定查验6号。"),
      ).toBeVisible(),
    );
    expect(within(inputPanel).getAllByText("仅当前玩家可见")).toHaveLength(2);
  });

  it("clears detail and on-demand query cache after leaving the route", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderPage();

    expect(
      await screen.findByRole("heading", { name: "模型可观测性验收" }),
    ).toBeVisible();
    expect(
      queryClient.getQueriesData({
        queryKey: v2GameRecordKeys.detail(gameId),
      }).length,
    ).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "返回列表" }));
    expect(await screen.findByText("对局列表")).toBeVisible();
    await waitFor(() =>
      expect(
        queryClient.getQueriesData({
          queryKey: v2GameRecordKeys.detail(gameId),
        }),
      ).toHaveLength(0),
    );
  });

  it("renders Chat Completions messages as readable model input", async () => {
    stubRecordFetch(deepSeekDetail);
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "DeepSeek 输入兼容验收" }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    await user.click(screen.getByRole("tab", { name: "模型输入" }));

    const inputPanel = screen.getByRole("tabpanel", { name: "模型输入" });
    expect(within(inputPanel).getByText("deepseek-v4-flash")).toBeVisible();
    expect(within(inputPanel).getByText("16384")).toBeVisible();
    expect(
      within(inputPanel).getByText(
        "你正在扮演一名狼人杀玩家，只能根据已提供的信息行动。",
      ),
    ).toBeVisible();
    expect(
      within(inputPanel).getByText(
        "选择本轮狼人团队建议袭击的一名非狼人存活玩家",
      ),
    ).toBeVisible();
    expect(within(inputPanel).getByText("可选目标")).toBeVisible();
    expect(within(inputPanel).getByText("seat_4")).toBeVisible();
    expect(within(inputPanel).queryByText("请求参数")).not.toBeInTheDocument();
    expect(
      within(inputPanel).queryByText(/"schema_version"/),
    ).not.toBeInTheDocument();
  });

  it("shows a recovered transport retry as one successful action", async () => {
    stubRecordFetch(retryDetail);
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "模型重试验收" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/重试 1 次/)).toBeVisible();
    const phaseRail = screen.getByRole("navigation", { name: "对局阶段" });
    expect(
      within(phaseRail).getByRole("button", { name: /2 次模型请求/ }),
    ).toBeVisible();

    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("2 次（重试 1 次后成功）"),
    ).toBeVisible();
    expect(within(dialog).getByText(/第 1 次 .*失败/)).toBeVisible();
    expect(within(dialog).getByText(/第 2 次 .*成功/)).toBeVisible();
    expect(
      within(dialog).getByText("model_transport_failed"),
    ).toBeVisible();
  });

  it("shows deterministic template variables, final text and frozen speaker", async () => {
    stubRecordFetch(templateDetail);
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

  it("shows a compact digest for each persisted match round", async () => {
    stubRecordFetch(roundSummaryDetail);
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "轮次摘要验收" }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "对局摘要" })).getByText(
        "已完成 · 好人阵营获胜",
      ),
    ).toBeVisible();
    const summary = screen.getByRole("region", { name: "全知战局态势" });
    expect(
      within(summary).getByRole("heading", { name: /全知战局态势/ }),
    ).toBeVisible();
    expect(within(summary).getByText("第 1 夜")).toBeVisible();
    expect(within(summary).getAllByText("第 1 天")).not.toHaveLength(0);
    expect(within(summary).getByText("平安夜")).toBeVisible();
    expect(
      within(summary).getByText("投票放逐：2号 白石（狼人）"),
    ).toBeVisible();
    expect(within(summary).getAllByText("好人阵营获胜")).not.toHaveLength(0);

    await user.click(
      within(summary).getByRole("button", {
        name: "回看第 1 夜进度",
      }),
    );
    expect(
      within(summary).getByRole("button", { name: "历史回看" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(within(summary).getByText("历史状态")).toBeVisible();
    expect(
      within(summary).getByRole("row", {
        name: /2白石profile-2 狼人 存活/,
      }),
    ).toBeVisible();
  });

  it("keeps follow-live focused on the latest repeated stage event", async () => {
    const firstSpeechActionId = "v2_action_first_day_speech";
    const latestSpeechActionId = "v2_action_latest_day_speech";
    const user = userEvent.setup();
    stubRecordFetch({
      ...detail,
      title: "实时事件跟随验收",
      phase_id: "day_2",
      phase_state: "public_discussion_open",
      last_record_seq: 6,
      events: [
        event(1, "game_phase_changed", {
          previous_phase_id: "night_2",
          phase_id: "day_2",
        }),
        event(2, "action_opened", {
          action_id: firstSpeechActionId,
          context: {
            phase_id: "day_2",
            action_type: "day_debate_speech",
            objective: "较早玩家发言",
            actor: { kind: "player", id: "profile-1" },
          },
        }),
        event(3, "action_succeeded", {
          action_id: firstSpeechActionId,
        }),
        event(4, "action_opened", {
          action_id: latestSpeechActionId,
          context: {
            phase_id: "day_2",
            action_type: "day_debate_speech",
            objective: "最新玩家发言",
            actor: { kind: "player", id: "profile-2" },
          },
        }),
        event(5, "speech_segment_committed", {
          action_id: latestSpeechActionId,
          presentation_seq: 2,
        }),
        event(6, "action_succeeded", {
          action_id: latestSpeechActionId,
        }),
      ],
      model_requests: [],
    });
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "实时事件跟随验收" }),
    ).toBeVisible();
    const panel = screen.getByRole("region", { name: "全知战局态势" });
    expect(within(panel).getAllByText("最新玩家发言")).not.toHaveLength(0);
    expect(within(panel).queryByText("较早玩家发言")).not.toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: "回看第 2 天发言" }),
    ).toHaveAttribute("aria-current", "step");
    expect(within(panel).getByText("事实 #6")).toBeVisible();
    expect(
      within(panel).queryByRole("button", { name: "回到最新" }),
    ).not.toBeInTheDocument();

    await user.click(
      within(panel).getByRole("button", { name: "查看上一事件" }),
    );
    expect(within(panel).getAllByText("较早玩家发言")).not.toHaveLength(0);
    await user.click(
      within(panel).getByRole("button", { name: "跟随实时" }),
    );
    expect(within(panel).getAllByText("最新玩家发言")).not.toHaveLength(0);
    expect(
      within(panel).getByRole("button", { name: "跟随实时" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps phase, night-window and terminal labels aligned to persisted rounds", async () => {
    stubRecordFetch(phaseIntegrityDetail);
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "阶段完整性验收" }),
    ).toBeVisible();
    expect(screen.getAllByText("第 1 夜").length).toBeGreaterThan(1);
    expect(screen.getAllByText("第 2 夜").length).toBeGreaterThan(1);
    expect(screen.queryByText("第 3 个夜间窗口")).not.toBeInTheDocument();
    expect(screen.getAllByText("狼人自爆").length).toBeGreaterThan(0);

    const currentPhase = screen.getByRole("button", {
      name: /第 2 天 2 步 · 0 次模型请求/,
    });
    expect(currentPhase).toHaveClass("ant-steps-item-finish");
    expect(currentPhase).not.toHaveClass("ant-steps-item-process");
  });

  it("renders an active phase with a loading icon instead of a numeric index", async () => {
    stubRecordFetch({
      ...detail,
      status: "broadcasting",
      runs: detail.runs.map((run) => ({
        ...run,
        status: "broadcasting",
      })),
    });
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "模型可观测性验收" }),
    ).toBeVisible();
    const phaseRail = screen.getByRole("navigation", { name: "对局阶段" });
    const currentPhase = within(phaseRail).getByRole("button", {
      name: /开场/,
    });

    expect(currentPhase).toHaveClass("ant-steps-item-process");
    expect(currentPhase.querySelector(".anticon-loading")).toBeInTheDocument();
    expect(
      currentPhase.querySelector(".ant-steps-item-icon")?.textContent,
    ).toBe("");
  });

  it("surfaces stale execution and legacy audio without inventing a result", async () => {
    stubRecordFetch({
      ...detail,
      title: "旧记录失联验收",
      audio_mode: "legacy_unknown",
      execution_state: "stale",
      delivery_snapshot: {
        schema_version: 1,
        mode: "legacy_unknown",
        source: "pre_contract_record",
      },
      runs: detail.runs.map((run) => ({
        ...run,
        worker_heartbeat_at: "2026-07-23T07:55:00Z",
        lease_expires_at: "2026-07-23T07:55:30Z",
      })),
    });
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "旧记录失联验收" }),
    ).toBeVisible();
    const summary = screen.getByRole("region", { name: "对局摘要" });
    expect(within(summary).getByText("进行中")).toBeVisible();
    expect(within(summary).getByText("执行器失联")).toBeVisible();
    expect(within(summary).getByText("旧记录模式未知")).toBeVisible();
    expect(screen.getByText("执行器失联，当前版本不可自动续局")).toBeVisible();
    expect(within(summary).queryByText(/已完成/)).not.toBeInTheDocument();
  });

  it("keeps polling through terminal delivery until the execution owner stops", () => {
    expect(liveRefreshInterval("waiting")).toBe(2_000);
    expect(liveRefreshInterval("running")).toBe(2_000);
    expect(liveRefreshInterval("completed", "owned")).toBe(2_000);
    expect(liveRefreshInterval("completed", "stale")).toBe(2_000);
    expect(liveRefreshInterval("completed", "stopped")).toBe(false);
    expect(liveRefreshInterval("failed", "stopped")).toBe(false);
    expect(liveRefreshInterval("canceled", "unowned")).toBe(false);
  });
});
