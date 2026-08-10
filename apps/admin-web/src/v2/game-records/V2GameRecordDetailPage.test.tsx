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
      model_generation_policy_contract_status: "supported",
      model_generation_policy_schema_version: 1,
      model_generation_policy_classification_version: 1,
      model_generation_policy_enforcement: "observe_only",
      model_generation_policy_reasoning_parameter_mode:
        "inherit_frozen_model_configuration",
      model_generation_policy_profile: "recoverable_public_speech",
      model_generation_policy_profile_source: "explicit_action_profile",
      reasoning_only_timeout_ms: 180_000,
      timeout_max_attempts: 1,
      shadow_would_timeout: false,
      finish_reason: "completed",
      provider_usage: {
        input_tokens: 120,
        output_tokens: 64,
        reasoning_tokens: 48,
        total_tokens: 184,
        cached_input_tokens: 20,
      },
      usage_update_count: 2,
      usage_conflict_observed: false,
      usage_consistency: "exact",
      queue_wait_ms: 11,
      provider_in_flight: 2,
      provider_concurrency_limit: 4,
      first_token_ms: 18,
      reasoning_only_elapsed_ms: 9,
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
      reasoning_delta_count: 7,
      text_delta_count: 2,
      max_inter_delta_ms: 17,
      last_progress_ms: 290,
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

const v11Detail = {
  ...detail,
  title: "V11 上下文审计验收",
  model_requests: [
    {
      ...detail.model_requests[0],
      prompt_schema_version: 11,
      model_context_schema_version: 11,
      prompt_template_version: 3,
      model_view_selector_version: 2,
      prompt_projection: {
        model_context_schema_version: 11,
        prompt_template_version: 3,
        known_events_schema_version: 5,
        ledger_schema_version: 5,
        model_view_schema_version: 5,
        model_view_selector_version: 2,
        serialized_char_count: 1840,
        source_event_count: 2,
        emitted_event_count: 2,
        future_filtered_event_count: 0,
        source_claim_candidate_count: 2,
        emitted_claim_count: 1,
        out_of_scope_claim_count: 0,
        rejected_claim_count: 1,
        source_question_count: 1,
        current_scope_question_count: 1,
        emitted_question_count: 1,
        out_of_scope_question_count: 0,
        invalid_question_count: 0,
        source_relation_count: 1,
        emitted_relation_count: 1,
        invalid_relation_count: 0,
        budget_dropped_event_count: 0,
        derivation_rejections: [
          {
            source_event_ref: "402",
            kind: "investigation_claim",
            reason: "missing_required_fields",
            missing_fields: ["target_ref", "claimed_result"],
          },
        ],
      },
      output_enforcement: {
        requested: "strict_json_schema",
        actual: "prompt_and_application_validation",
        schema_name: null,
        schema_version: null,
      },
      application_validation_result: "accepted",
      repair_kind: null,
      expanded_known_events: null,
      known_events_expansion_status: "not_applicable",
      request_payload: {
        model: "glm-5-2-260617",
        stream: true,
        max_output_tokens: 256,
        input: [
          {
            role: "system",
            content: [
              {
                type: "input_text",
                text: "派生项仅是启发式索引；冲突时以原始 speech 为准。",
              },
            ],
          },
          {
            role: "user",
            content: [
              {
                type: "input_text",
                text: `请执行这个实时动作：${JSON.stringify({
                  model_context_schema_version: 11,
                  prompt_template_version: 3,
                  task: {
                    type: "exile_vote",
                    goal: "选择一名合法候选人。",
                    at_seq: 1467,
                    phase_id: "day_3",
                    round_no: 3,
                  },
                  state: {
                    as_of_seq: 1467,
                    current_round_no: 3,
                    current_period: "day",
                  },
                  known_events: {
                    schema_version: 5,
                    events: [
                      {
                        event_ref: "1403",
                        record_seq: 1403,
                        known_at_seq: 1403,
                        kind: "player_statement",
                        authority: "player_claim_unverified",
                        visibility: "public",
                        speaker_ref: "seat_12",
                        speech: "12号原始发言：7号你解释一下昨天为什么投5号。",
                        annotations: [
                          {
                            claim_id: "claim_1403_1_team_claim",
                            claim_type: "team_claim",
                            authority: "player_claim_unverified",
                            sentence_index: 1,
                            claimed_team: "villagers",
                            derivation: {
                              kind: "deterministic_heuristic",
                              validator_version: 1,
                              validation_status: "complete",
                            },
                          },
                        ],
                      },
                      {
                        event_ref: "1442",
                        record_seq: 1442,
                        known_at_seq: 1442,
                        kind: "player_statement",
                        authority: "player_claim_unverified",
                        visibility: "public",
                        speaker_ref: "seat_7",
                        speech: "7号回应：我昨天认为5号的复盘更差。",
                      },
                    ],
                    questions: [
                      {
                        question_id: "question_1403_7",
                        source_event_ref: "1403",
                        source_authority: "player_claim_unverified",
                        asked_by: "seat_12",
                        addressed_to: "seat_7",
                        address_resolution: "resolved",
                        asked_at_seq: 1403,
                        topic: "vote_reason",
                        response_status: "response_detected",
                        derivation: {
                          kind: "deterministic_heuristic",
                          validator_version: 1,
                          validation_status: "complete",
                        },
                      },
                    ],
                    relations: [
                      {
                        relation_id: "relation_1442_question_1403_7",
                        type: "response_to_question",
                        from_event_ref: "1442",
                        to_question_id: "question_1403_7",
                        temporal_order_valid: true,
                        derivation: {
                          kind: "deterministic_heuristic",
                          validator_version: 1,
                          validation_status: "complete",
                        },
                      },
                    ],
                  },
                  candidates: [
                    { player_id: "seat_5", seat: 5, display_name: "5号" },
                  ],
                  response: {
                    kind: "target",
                    target_policy: { mode: "required" },
                    decision_note: { mode: "optional", max_chars: 80 },
                  },
                })}`,
              },
            ],
          },
        ],
      },
      raw_response:
        '{"target_player_id":"seat_5","decision_note":"复盘不足。"}',
      parsed_output: {
        target_player_id: "seat_5",
        decision_note: "复盘不足。",
      },
      passive_observations: [],
    },
  ],
};

const v12KnownEvents = {
  schema_version: 6,
  encoding: "lossless_refs_v1",
  defaults: {
    record_seq: "known_at_seq",
    event_ref: "record_seq_string_when_equal",
    scope_ref_by_kind: {
      player_statement: "public_player_claim_unverified",
    },
    occurred_in_ref_by_kind: {},
  },
  scope_catalog: {
    public_player_claim_unverified: {
      authority: "player_claim_unverified",
      visibility: "public",
    },
  },
  occurrence_catalog: {},
  events: [
    {
      known_at_seq: 1403,
      kind: "player_statement",
      speaker_ref: "seat_12",
      speech: "12号原始发言：7号你解释一下昨天为什么投5号。",
      annotation_count: 1,
    },
    {
      known_at_seq: 1442,
      kind: "player_statement",
      speaker_ref: "seat_7",
      speech: "7号回应：我昨天认为5号的复盘更差。",
    },
  ],
  annotations: [
    {
      source_event_ref: "1403",
      source_annotation_index: 0,
      claim_id: "claim_1403_1_team_claim",
      claim_type: "team_claim",
      authority: "player_claim_unverified",
      sentence_index: 1,
      claimed_team: "villagers",
    },
  ],
  questions: [
    {
      question_id: "question_1403_7",
      source_event_ref: "1403",
      asked_by: "seat_12",
      addressed_to: "seat_7",
      response_status: "response_detected",
    },
  ],
  relations: [
    {
      relation_id: "relation_1442_question_1403_7",
      type: "response_to_question",
      from_event_ref: "1442",
      to_question_id: "question_1403_7",
    },
  ],
};

const v12Detail = {
  ...v11Detail,
  title: "V12 无损压缩审计验收",
  model_requests: [
    {
      ...v11Detail.model_requests[0],
      prompt_schema_version: 12,
      model_context_schema_version: 12,
      prompt_template_version: 5,
      prompt_projection: {
        ...v11Detail.model_requests[0].prompt_projection,
        model_context_schema_version: 12,
        prompt_template_version: 5,
        known_events_schema_version: 6,
        serialized_char_count: 2_900,
        canonical_serialized_char_count: 2_000,
        compact_serialized_char_count: 1_200,
        compaction_saved_chars: 800,
        compaction_ratio: 0.6,
        verbatim_speech_count: 2,
        verbatim_speech_chars: 43,
        retained_event_refs: ["1403", "1442"],
        dropped_event_refs: [],
        canonical_sha256: "b".repeat(64),
        round_trip_verified: true,
      },
      expanded_known_events: {
        schema_version: 5,
        events: [
          {
            event_ref: "1403",
            record_seq: 1403,
            known_at_seq: 1403,
            kind: "player_statement",
            authority: "player_claim_unverified",
            visibility: "public",
            speaker_ref: "seat_12",
            speech: "12号原始发言：7号你解释一下昨天为什么投5号。",
            annotations: [
              {
                claim_id: "claim_1403_1_team_claim",
                claim_type: "team_claim",
                authority: "player_claim_unverified",
                sentence_index: 1,
                claimed_team: "villagers",
              },
            ],
          },
          {
            event_ref: "1442",
            record_seq: 1442,
            known_at_seq: 1442,
            kind: "player_statement",
            authority: "player_claim_unverified",
            visibility: "public",
            speaker_ref: "seat_7",
            speech: "7号回应：我昨天认为5号的复盘更差。",
          },
        ],
        questions: v12KnownEvents.questions,
        relations: v12KnownEvents.relations,
      },
      known_events_expansion_status: "verified",
      request_payload: {
        ...v11Detail.model_requests[0].request_payload,
        input: [
          {
            role: "system",
            content: [
              {
                type: "input_text",
                text: "Known Events V6 使用可读目录与确定性默认规则表达 V5 的完整语义。",
              },
            ],
          },
          {
            role: "user",
            content: [
              {
                type: "input_text",
                text: `请执行这个实时动作：${JSON.stringify({
                  model_context_schema_version: 12,
                  prompt_template_version: 5,
                  task: {
                    type: "exile_vote",
                    goal: "选择一名合法候选人。",
                    at_seq: 1467,
                    phase_id: "day_3",
                  },
                  known_events: v12KnownEvents,
                  candidates: [
                    { player_id: "seat_5", seat: 5, display_name: "5号" },
                  ],
                })}`,
              },
            ],
          },
        ],
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
      finish_reason: null,
      provider_usage: null,
      usage_update_count: null,
      usage_conflict_observed: null,
      usage_consistency: null,
      queue_wait_ms: null,
      provider_in_flight: null,
      provider_concurrency_limit: null,
      first_token_ms: null,
      reasoning_only_elapsed_ms: null,
      completed_ms: null,
      reasoning_delta_count: 0,
      text_delta_count: 0,
      max_inter_delta_ms: null,
      last_progress_ms: null,
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
      effective_attempt_limit: 2,
      retry_delay_ms: 300,
      required_retry_window_ms: 1_000,
      automatic_retry_scheduled: true,
      automatic_retry_stop_reason: null,
      failure_episode_id: "v2_mfep_0123456789abcdef01234567",
      failure_resolution: "automatic_retry_success",
      failure_episode_source_attempt_ids: ["v2_model_attempt_1"],
      resolution_event_type: "model_response_received",
      resolution_event_id: 8,
      resolution_event_record_seq: 8,
      resolution_updated_at_record_seq: 8,
      failure_episode_invariant_errors: [],
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
    expect(
      await within(causalFacts).findByText(
        /未知模型上下文合同不支持事实展开/,
      ),
    ).toBeVisible();
    expect(
      within(causalFacts).getByText(
        /Admin 不猜测压缩默认规则或旧版字段语义/,
      ),
    ).toBeVisible();
    expect(
      within(causalFacts).queryByText(/警徽流：今晚验2号/),
    ).not.toBeInTheDocument();
    expect(within(livePanel).queryByText("3 条")).not.toBeInTheDocument();
    expect(within(livePanel).queryByText("#448")).not.toBeInTheDocument();
    expect(within(livePanel).queryByText("#562")).not.toBeInTheDocument();
    expect(within(livePanel).queryByText("#564")).not.toBeInTheDocument();
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
    expect(within(requestDialog).getByText("排队等待")).toBeVisible();
    expect(within(requestDialog).getByText("11 ms")).toBeVisible();
    expect(within(requestDialog).getByText("Provider 并发")).toBeVisible();
    expect(within(requestDialog).getByText("2 / 4")).toBeVisible();
    expect(within(requestDialog).getByText("纯推理阶段")).toBeVisible();
    expect(within(requestDialog).getByText("9 ms")).toBeVisible();
    expect(within(requestDialog).getByText("首可见文本")).toBeVisible();
    expect(within(requestDialog).getByText("27 ms")).toBeVisible();
    expect(within(requestDialog).getByText("结束原因")).toBeVisible();
    expect(
      within(requestDialog).getByText("Provider 完成（completed）"),
    ).toBeVisible();
    expect(within(requestDialog).getByText("推理 / 文本增量")).toBeVisible();
    expect(within(requestDialog).getByText("7 / 2")).toBeVisible();
    expect(
      within(requestDialog).getByText("最大间隔 / 最后进度"),
    ).toBeVisible();
    expect(within(requestDialog).getByText("17 ms / 290 ms")).toBeVisible();
    expect(within(requestDialog).getByText("生成策略合同")).toBeVisible();
    expect(
      within(requestDialog).getByText("支持（supported）"),
    ).toBeVisible();
    expect(within(requestDialog).getByText("生成策略版本")).toBeVisible();
    expect(
      within(requestDialog).getByText("schema v1 / classification v1"),
    ).toBeVisible();
    expect(within(requestDialog).getByText("生成策略 Profile")).toBeVisible();
    expect(
      within(requestDialog).getByText(
        "recoverable_public_speech · 显式动作分类",
      ),
    ).toBeVisible();
    expect(within(requestDialog).getByText("Shadow 执行模式")).toBeVisible();
    expect(
      within(requestDialog).getByText(
        "仅观测（observe_only） · 继承冻结模型配置",
      ),
    ).toBeVisible();
    expect(
      within(requestDialog).getByText("Shadow 推理阈值 / 尝试上限"),
    ).toBeVisible();
    expect(within(requestDialog).getByText("180.0 s / 1")).toBeVisible();
    expect(
      within(requestDialog).getByText("Shadow 候选超时结果"),
    ).toBeVisible();
    expect(
      within(requestDialog).getByText(
        "未命中候选阈值（Shadow 仅观测，不是实际超时）",
      ),
    ).toBeVisible();
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
      within(inputPanel).getByText("历史或未知合同仅提供通用 JSON"),
    ).toBeVisible();
    const historicalInput = within(inputPanel).getByLabelText(
      "历史模型输入原始 JSON",
    );
    expect(historicalInput).toHaveTextContent("九人标准局");
    expect(historicalInput).toHaveTextContent("public_timeline");

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
          application_validation_result: null,
          finish_reason: "completed",
          output_enforcement: null,
          output_source: "persisted",
          parsed_output: detail.model_requests[0].parsed_output,
          passive_observations:
            detail.model_requests[0].passive_observations,
          provider_usage: detail.model_requests[0].provider_usage,
          raw_response: detail.model_requests[0].raw_response,
          repair_kind: null,
          usage_conflict_observed: false,
          usage_consistency: "exact",
          usage_update_count: 2,
        },
        null,
        2,
      ),
    );
    expect(
      within(outputPanel).getByText("历史或未知合同仅提供通用 JSON"),
    ).toBeVisible();
    const usageDiagnostics = within(outputPanel).getByRole("region", {
      name: "模型输出与用量诊断",
    });
    expect(within(usageDiagnostics).getByText("原始输出字符数")).toBeVisible();
    expect(within(usageDiagnostics).getByText("输入 Token")).toBeVisible();
    expect(within(usageDiagnostics).getByText("120")).toBeVisible();
    expect(within(usageDiagnostics).getByText("输出 Token")).toBeVisible();
    expect(within(usageDiagnostics).getByText("64")).toBeVisible();
    expect(within(usageDiagnostics).getByText("推理 Token（输出子集）")).toBeVisible();
    expect(within(usageDiagnostics).getByText("48")).toBeVisible();
    expect(within(usageDiagnostics).getByText("Provider 总 Token")).toBeVisible();
    expect(within(usageDiagnostics).getByText("184")).toBeVisible();
    const historicalOutput = within(outputPanel).getByLabelText(
      "历史模型输出原始 JSON",
    );
    expect(historicalOutput).toHaveTextContent("raw_response");
    expect(historicalOutput).toHaveTextContent("夜幕将至");
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

  it("separates V11 source events, derived indexes, rejections and output enforcement", async () => {
    stubRecordFetch(v11Detail);
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "V11 上下文审计验收" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    await user.click(screen.getByRole("tab", { name: "模型输入" }));
    const inputPanel = screen.getByRole("tabpanel", { name: "模型输入" });
    expect(within(inputPanel).getByText("V11 历史合同（只读）")).toBeVisible();
    const audit = within(inputPanel).getByRole("region", {
      name: "V11 上下文投影审计",
    });

    expect(within(audit).getByText("审计字段完整")).toBeVisible();
    expect(within(audit).getByText("源 2")).toBeVisible();
    expect(within(audit).getAllByText("可见 2")).not.toHaveLength(0);
    expect(within(audit).getByText("候选 2")).toBeVisible();
    expect(within(audit).getByText("拒绝 1")).toBeVisible();
    expect(within(audit).getByText("容量 0")).toBeVisible();
    await user.click(
      within(audit).getByRole("button", {
        name: /查看被拒绝的派生项（1 项）/,
      }),
    );
    await waitFor(() => expect(within(audit).getByText("402")).toBeVisible());
    expect(within(audit).getByText("验人声明")).toBeVisible();
    expect(within(audit).getByText("missing_required_fields")).toBeVisible();
    expect(within(audit).getByText("target_ref")).toBeVisible();
    expect(within(audit).getByText("claimed_result")).toBeVisible();

    await user.click(
      within(inputPanel).getByRole("button", {
        name: /查看模型实际可见的源事件（2 个）/,
      }),
    );
    await waitFor(() =>
      expect(
        within(inputPanel).getByText(
          "12号原始发言：7号你解释一下昨天为什么投5号。",
        ),
      ).toBeVisible(),
    );
    await user.click(
      within(inputPanel).getByRole("button", {
        name: /查看通过校验的派生索引（3 项）/,
      }),
    );
    await waitFor(() =>
      expect(within(inputPanel).getByText("阵营声明")).toBeVisible(),
    );
    expect(within(inputPanel).getByText("检测到回应")).toBeVisible();
    expect(within(inputPanel).getByText("对提问的回应")).toBeVisible();

    await user.click(screen.getByRole("tab", { name: "模型输出" }));
    const outputPanel = screen.getByRole("tabpanel", { name: "模型输出" });
    const enforcement = within(outputPanel).getByRole("region", {
      name: "Provider 输出约束审计",
    });
    expect(within(enforcement).getByText("严格 JSON Schema")).toBeVisible();
    expect(
      within(enforcement).getByText("提示词 + 应用层校验"),
    ).toBeVisible();
    expect(
      within(enforcement).getByText("未使用 Provider 严格 Schema"),
    ).toBeVisible();
    expect(within(enforcement).getByText("无机械修复")).toBeVisible();
    expect(within(enforcement).getByText("已接受")).toBeVisible();
    expect(within(outputPanel).getByText("程序采用结果")).toBeVisible();
    expect(within(outputPanel).getByText("seat_5")).toBeVisible();
  },
    45_000,
  );

  it("renders V12 lossless compaction separately from V11 and unknown contracts", async () => {
    stubRecordFetch(v12Detail);
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "V12 无损压缩审计验收" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    await user.click(screen.getByRole("tab", { name: "模型输入" }));
    const inputPanel = screen.getByRole("tabpanel", { name: "模型输入" });
    const audit = within(inputPanel).getByRole("region", {
      name: "V12 无损压缩审计",
    });

    expect(within(audit).getByText("审计字段完整")).toBeVisible();
    expect(within(audit).getByText("V6")).toBeVisible();
    expect(within(audit).getByText("lossless_refs_v1")).toBeVisible();
    expect(within(audit).getByText(/已验证 V5 · 2 个事件/)).toBeVisible();
    expect(within(audit).getByText("2,000 → 1,200")).toBeVisible();
    expect(within(audit).getByText("800")).toBeVisible();
    expect(within(audit).getByText("0.6000（60.00%）")).toBeVisible();
    expect(within(audit).getByText("2 条 / 43 字符")).toBeVisible();
    expect(within(audit).getByText("通过")).toBeVisible();
    expect(within(audit).getByText("2 / 0")).toBeVisible();
    expect(within(audit).getByText("b".repeat(64))).toBeVisible();
    expect(
      within(inputPanel).queryByRole("region", {
        name: "V11 上下文投影审计",
      }),
    ).not.toBeInTheDocument();

    await user.click(
      within(audit).getByRole("button", {
        name: /查看 V6 默认规则与可读目录/,
      }),
    );
    await waitFor(() =>
      expect(within(audit).getByText("V6 默认还原规则")).toBeVisible(),
    );
    expect(within(audit).getByText("作用域目录（scope_catalog）")).toBeVisible();
    expect(
      within(audit).getByText("发生阶段目录（occurrence_catalog）"),
    ).toBeVisible();

    expect(
      within(inputPanel).getByText("动作发生前已知事件（V12 无损压缩载荷）"),
    ).toBeVisible();
    expect(
      within(inputPanel).getAllByText("scope 1 / occurrence 0"),
    ).toHaveLength(2);
    expect(
      within(inputPanel).getByText("事件 2 / 注解 1 / 提问 1 / 关系 1"),
    ).toBeVisible();
    await user.click(
      within(inputPanel).getByRole("button", {
        name: /查看全局顺序的 Compact 事件（2 个）/,
      }),
    );
    await waitFor(() =>
      expect(
        within(inputPanel).getByText(
          "12号原始发言：7号你解释一下昨天为什么投5号。",
        ),
      ).toBeVisible(),
    );
    await user.click(
      within(inputPanel).getByRole("button", {
        name: /查看顶层注解及来源索引（1 项）/,
      }),
    );
    await waitFor(() =>
      expect(within(inputPanel).getByText("claim_1403_1_team_claim")).toBeVisible(),
    );

    await user.click(screen.getByRole("tab", { name: "模型输出" }));
    const outputPanel = screen.getByRole("tabpanel", { name: "模型输出" });
    expect(
      within(outputPanel).getByRole("region", {
        name: "Provider 输出约束审计",
      }),
    ).toBeVisible();
    expect(within(outputPanel).getByText("程序采用结果")).toBeVisible();
  });

  it("falls back to unsupported raw JSON for a backend-rejected V12 hybrid", async () => {
    stubRecordFetch({
      ...v12Detail,
      title: "V12 混合合同验收",
      model_requests: [
        {
          ...v12Detail.model_requests[0],
          expanded_known_events: null,
          known_events_expansion_status: "invalid",
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "V12 混合合同验收" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    await user.click(screen.getByRole("tab", { name: "模型输入" }));
    const inputPanel = screen.getByRole("tabpanel", { name: "模型输入" });
    expect(
      within(inputPanel).getByText("历史或未知合同仅提供通用 JSON"),
    ).toBeVisible();
    expect(
      within(inputPanel).getByText(/V12 模型上下文合同不受支持/),
    ).toBeVisible();
    expect(
      within(inputPanel).getByLabelText("历史模型输入原始 JSON"),
    ).toBeVisible();
    expect(
      within(inputPanel).queryByRole("region", {
        name: "V12 无损压缩审计",
      }),
    ).not.toBeInTheDocument();
  });

  it("shows missing V11 audit fields as unknown instead of guessing", async () => {
    stubRecordFetch({
      ...v11Detail,
      title: "V11 缺失审计字段验收",
      model_requests: [
        {
          ...v11Detail.model_requests[0],
          prompt_projection: {
            model_context_schema_version: 11,
            prompt_template_version: 3,
            known_events_schema_version: 5,
            ledger_schema_version: 5,
            model_view_schema_version: 5,
            model_view_selector_version: 2,
          },
          output_enforcement: undefined,
          application_validation_result: undefined,
          repair_kind: undefined,
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", {
        name: "V11 缺失审计字段验收",
      }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    await user.click(screen.getByRole("tab", { name: "模型输入" }));
    const inputPanel = screen.getByRole("tabpanel", { name: "模型输入" });
    expect(
      within(inputPanel).getByText("V11 投影审计信息缺失"),
    ).toBeVisible();
    expect(within(inputPanel).getAllByText(/未知/).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("tab", { name: "模型输出" }));
    const outputPanel = screen.getByRole("tabpanel", { name: "模型输出" });
    expect(within(outputPanel).getByText("输出审计信息不完整")).toBeVisible();
    expect(within(outputPanel).getAllByText(/未知/).length).toBeGreaterThan(0);
  });

  it("does not present a rejected V11 response as the adopted result", async () => {
    stubRecordFetch({
      ...v11Detail,
      title: "V11 输出拒绝验收",
      model_requests: [
        {
          ...v11Detail.model_requests[0],
          application_validation_result: "rejected",
          parsed_output: null,
          raw_response: '{"target_player_id":"seat_99"}',
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "V11 输出拒绝验收" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    await user.click(screen.getByRole("tab", { name: "模型输出" }));
    const outputPanel = screen.getByRole("tabpanel", { name: "模型输出" });

    expect(within(outputPanel).getByText("已拒绝")).toBeVisible();
    expect(
      within(outputPanel).getByText(
        "应用层校验已拒绝该输出，没有最终采用结果",
      ),
    ).toBeVisible();
    expect(
      within(outputPanel).queryByText("程序采用结果"),
    ).not.toBeInTheDocument();
    expect(within(outputPanel).getByText("查看模型原始返回")).toBeVisible();
  });

  it("renders historical persisted input as generic raw JSON", async () => {
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

    expect(
      within(inputPanel).getByText("历史或未知合同仅提供通用 JSON"),
    ).toBeVisible();
    const rawInput = within(inputPanel).getByLabelText("历史模型输入原始 JSON");
    expect(rawInput).toHaveTextContent("public_timeline");
    expect(rawInput).toHaveTextContent("player_statement");
    expect(within(inputPanel).queryByText("3 个事件")).not.toBeInTheDocument();
  });

  it("shows a V8 request only through generic raw JSON", async () => {
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

    expect(
      within(inputPanel).getByText("历史或未知合同仅提供通用 JSON"),
    ).toBeVisible();
    expect(
      within(inputPanel).getByText(/V8 模型上下文合同不受支持/),
    ).toBeVisible();
    const rawInput = within(inputPanel).getByLabelText("历史模型输入原始 JSON");
    expect(rawInput).toHaveTextContent("model_context_schema_version");
    expect(rawInput).toHaveTextContent("knowledge-seer-night-1");
    expect(
      within(inputPanel).queryByText("已选 2 / 完整 5"),
    ).not.toBeInTheDocument();
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

  it("renders an old Chat Completions request as generic raw JSON", async () => {
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
    expect(
      within(inputPanel).getByText("历史或未知合同仅提供通用 JSON"),
    ).toBeVisible();
    const rawInput = within(inputPanel).getByLabelText("历史模型输入原始 JSON");
    expect(rawInput).toHaveTextContent("deepseek-v4-flash");
    expect(rawInput).toHaveTextContent("16384");
    expect(rawInput).toHaveTextContent("seat_4");
    expect(
      within(inputPanel).queryByText("可选目标"),
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
    expect(within(dialog).getAllByText(/自动重试成功/)).not.toHaveLength(0);
    expect(
      within(dialog).getByText("v2_mfep_0123456789abcdef01234567"),
    ).toBeVisible();
    expect(
      within(dialog).getByText("model_response_received · event 8 · record 8"),
    ).toBeVisible();
    expect(
      within(dialog).getByText(
        "生效上限 2 / 策略 2 · 已安排 · 延迟/窗口 300 ms / 1.00 s",
      ),
    ).toBeVisible();
  });

  it("shows independent format and output-budget family retry telemetry", async () => {
    const decisionFamilyId = "v2_decision_family_vote_1";
    stubRecordFetch({
      ...retryDetail,
      title: "格式重试可观测性验收",
      model_requests: [
        {
          ...retryDetail.model_requests[0],
          decision_family_id: decisionFamilyId,
          retry_scope: "batch_initial",
          vote_batch_stage: "concurrent_initial",
          automatic_machine_format_attempt_count: 1,
          automatic_machine_format_budget: 2,
          prior_output_budget_failures: 1,
          output_budget_failure_count: 1,
          automatic_output_budget_attempt_count: 2,
          automatic_output_budget_budget: 3,
          failure_category: "output_budget",
          failure_code: "model_output_budget_exhausted",
        },
        {
          ...retryDetail.model_requests[1],
          decision_family_id: decisionFamilyId,
          retry_scope: "same_action",
          vote_batch_stage: "concurrent_initial",
          automatic_machine_format_attempt_count: null,
          automatic_machine_format_budget: 2,
          prior_output_budget_failures: 1,
          output_budget_failure_count: null,
          automatic_output_budget_attempt_count: 2,
          automatic_output_budget_budget: 3,
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "格式重试可观测性验收" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "查看 法官 开场播报" }),
    );
    const dialog = await screen.findByRole("dialog");

    expect(within(dialog).getAllByText(new RegExp(decisionFamilyId))).not.toHaveLength(0);
    expect(
      within(dialog).getAllByText("同动作自动重试（same_action）"),
    ).not.toHaveLength(0);
    expect(
      within(dialog).getByText("批次初始（batch_initial）"),
    ).toBeVisible();
    expect(
      within(dialog).getAllByText("并发初始（concurrent_initial）"),
    ).not.toHaveLength(0);
    expect(within(dialog).getByText("格式尝试 / 自动预算")).toBeVisible();
    expect(within(dialog).getByText("1 / 2")).toBeVisible();
    expect(within(dialog).getAllByText("格式 1 / 2")).toHaveLength(2);
    expect(
      within(dialog).getByText("输出预算尝试 / 自动预算"),
    ).toBeVisible();
    expect(within(dialog).getByText("输出预算既有 / 当前动作失败")).toBeVisible();
    expect(within(dialog).getByText("2 / 3")).toBeVisible();
    expect(within(dialog).getAllByText("输出预算 2 / 3")).toHaveLength(2);
    expect(
      within(dialog).getByText(
        /output_budget · model_output_budget_exhausted/,
      ),
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
