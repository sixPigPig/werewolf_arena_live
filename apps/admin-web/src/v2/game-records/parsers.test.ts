import { describe, expect, it } from "vitest";

import {
  parseV2GameEventPage,
  parseV2GameControlResult,
  parseV2GameRecordList,
  parseV2GameRecordSummary,
  parseV2ModelActionRetryResult,
  parseV2ModelRequest,
  parseV2ModelRequestPage,
} from "@/v2/game-records/parsers";

const item = {
  game_id: "v2_game_0123456789abcdef",
  title: "首句验收对局",
  status: "awaiting_observation",
  current_run_id: "v2_run_0123456789abcdef",
  record_schema_version: 1,
  last_record_seq: 2,
  last_presentation_seq: 1,
  phase_seq: 2,
  phase_id: "first_night",
  phase_state: "nightfall_announced",
  audio_mode: "tts",
  match_status: "running",
  execution_state: "owned",
  winner: null,
  completion_reason: null,
  completed_at: null,
  created_at: "2026-07-21T10:00:00Z",
  updated_at: "2026-07-21T10:00:00Z",
};

describe("V2 game record parsers", () => {
  it("parses the independent V2 list contract", () => {
    const result = parseV2GameRecordList({
      items: [item],
      pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
    });

    expect(result.items[0]).toMatchObject({
      game_id: item.game_id,
      current_run_id: item.current_run_id,
      last_record_seq: 2,
      last_presentation_seq: 1,
      audio_mode: "tts",
      match_status: "running",
      execution_state: "owned",
      winner: null,
    });
  });

  it("keeps terminal, stale and legacy delivery states explicit", () => {
    const result = parseV2GameRecordList({
      items: [
        {
          ...item,
          status: "awaiting_observation",
          match_status: "completed",
          execution_state: "stopped",
          winner: "villagers",
          completion_reason: "deterministic_win_condition",
          completed_at: "2026-07-21T10:05:00Z",
        },
        {
          ...item,
          audio_mode: "legacy_unknown",
          status: "awaiting_observation",
          match_status: "running",
          execution_state: "stale",
        },
      ],
      pagination: { page: 1, page_size: 20, total: 2, pages: 1 },
    });

    expect(result.items[0]).toMatchObject({
      status: "awaiting_observation",
      match_status: "completed",
      execution_state: "stopped",
      winner: "villagers",
      completion_reason: "deterministic_win_condition",
      completed_at: "2026-07-21T10:05:00Z",
    });
    expect(result.items[1]).toMatchObject({
      audio_mode: "legacy_unknown",
      status: "awaiting_observation",
      match_status: "running",
      execution_state: "stale",
      winner: null,
    });
  });

  it("keeps record_seq and presentation_seq as separate detail sequences", () => {
    const value = {
      ...item,
      rule_snapshot: {},
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
      ability_snapshot: {},
      match_state: null,
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
      ],
      runs: [
        {
          run_id: item.current_run_id,
          attempt_no: 1,
          status: "awaiting_observation",
          started_at: item.created_at,
          completed_at: null,
          stop_requested_at: null,
          worker_id: "v2-worker-a",
          worker_heartbeat_at: item.created_at,
          lease_expires_at: item.updated_at,
          fence_token: 3,
        },
      ],
      events: [
        {
          event_id: 2,
          record_seq: 2,
          run_id: item.current_run_id,
          event_type: "action_succeeded",
          payload_schema_version: 1,
          payload: { presentation_seq: 1 },
          created_at: item.created_at,
        },
      ],
      model_requests: [
        {
          attempt_id: "v2_model_0123456789abcdef",
          action_id: "v2_action_0123456789abcdef",
          run_id: item.current_run_id,
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
          judge_configuration_version: 1,
          prompt_schema_version: 2,
          model_context_schema_version: 8,
          prompt_template_version: 1,
          model_view_selector_version: 1,
          prompt_projection: {
            model_context_schema_version: 8,
            prompt_template_version: 1,
            known_events_schema_version: 1,
            known_event_count: 2,
            known_event_total_count: 5,
            dropped_event_count: 3,
            known_event_record_seq_min: 258,
            known_event_record_seq_max: 472,
            selection_budget_chars: 8000,
            selection_used_chars: 680,
            selection_budget_exceeded_by_required: false,
            retained_event_refs: ["knowledge-1", "472"],
            dropped_event_refs: ["100", "101", "102"],
            serialized_char_count: 3210,
            recent_statement_count: 3,
            older_claim_count: 2,
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
            input: [{ role: "system", content: [] }],
          },
          input_source: "persisted",
          raw_response: "欢迎来到这场实时狼人杀对局。",
          parsed_output: { speech: "欢迎来到这场实时狼人杀对局。" },
          passive_observations: [
            {
              code: "wolf_cardinality_contradiction",
              effect: "observed_only",
            },
          ],
          output_source: "persisted",
          provider_request_id: "provider-response-test",
          first_token_ms: 12,
          first_token_seen: true,
          response_headers_seen: true,
          response_headers: {
            "x-request-id": "provider-header-test",
            "x-ratelimit-remaining-requests": "9",
          },
          first_token_kind: "reasoning",
          first_visible_text_ms: 18,
          timeout_scope: "attempt_budget",
          completed_ms: 34,
          failure_kind: null,
          failure_code: null,
          started_at: item.created_at,
          completed_at: item.updated_at,
        },
      ],
      presentations: [
        {
          presentation_seq: 1,
          presentation_id: "v2_pres_0123456789abcdef",
          action_id: "v2_action_0123456789abcdef",
          activation_id: null,
          phase_id: "opening",
          actor_kind: "judge",
          actor_id: "judge",
          audience: "all",
          speech_id: "v2_speech_0123456789abcdef",
          segment_index: 0,
          source_event_id: 2,
          state: "closed",
          subtitle_text: "欢迎来到这场实时狼人杀对局。",
          voice_asset_id: "v2_voice_0123456789abcdef",
          audio_duration_ms: 1800,
          created_at: item.created_at,
          closed_at: item.updated_at,
        },
      ],
      voice_assets: [
        {
          voice_asset_id: "v2_voice_0123456789abcdef",
          action_id: "v2_action_0123456789abcdef",
          activation_id: null,
          audience: "all",
          presentation_id: "v2_pres_0123456789abcdef",
          speech_id: "v2_speech_0123456789abcdef",
          segment_index: 0,
          state: "ready",
          mime_type: "audio/wav",
          sample_rate: 24000,
          channels: 1,
          sample_count: 43200,
          duration_ms: 1800,
          pcm_sha256: "a".repeat(64),
          size_bytes: 86444,
          audio_url: "/api/v1/admin/v2/games/game/voice-assets/voice/audio",
          created_at: item.created_at,
          completed_at: item.updated_at,
        },
      ],
      player_states: [],
      action_windows: [],
      ability_instances: [],
      ability_activations: [],
      effect_intents: [],
      knowledge_facts: [],
    };
    const result = parseV2GameRecordSummary(value);
    const eventPage = parseV2GameEventPage({
      after_record_seq: 0,
      has_more: false,
      items: value.events,
      next_after_record_seq: 2,
    });
    const modelRequestPage = parseV2ModelRequestPage({
      after_record_seq: 0,
      has_more: false,
      items: value.model_requests,
      next_after_record_seq: 2,
    });
    const modelRequest = parseV2ModelRequest(value.model_requests[0]);

    expect(eventPage.items[0].record_seq).toBe(2);
    expect(result.player_identities[0]).toMatchObject({
      seat: 1,
      display_name: "阿青",
      role: "seer",
      alive: true,
    });
    expect(result.delivery_snapshot).toEqual({
      schema_version: 1,
      mode: "tts",
      source: "explicit_create_request",
    });
    expect(result.runs[0]).toMatchObject({
      worker_id: "v2-worker-a",
      worker_heartbeat_at: item.created_at,
      lease_expires_at: item.updated_at,
      fence_token: 3,
    });
    expect(modelRequestPage.items[0]).toMatchObject({
      model_id: "doubao-seed-2-0-lite-260215",
      audience: "director",
      stored_audience: "all",
      effective_audience: "director",
      audience_source: "event_contract_narrowed",
      input_source: "persisted",
      first_token_ms: 12,
      prompt_schema_version: 2,
      model_context_schema_version: 8,
      prompt_template_version: 1,
      model_view_selector_version: 1,
      prompt_projection: {
        model_context_schema_version: 8,
        prompt_template_version: 1,
        known_events_schema_version: 1,
        known_event_count: 2,
        known_event_total_count: 5,
        dropped_event_count: 3,
        known_event_record_seq_min: 258,
        known_event_record_seq_max: 472,
        selection_budget_chars: 8000,
        selection_used_chars: 680,
        selection_budget_exceeded_by_required: false,
        retained_event_refs: ["knowledge-1", "472"],
        dropped_event_refs: ["100", "101", "102"],
        serialized_char_count: 3210,
        recent_statement_count: 3,
        older_claim_count: 2,
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
      passive_observation_count: 1,
      response_headers: {
        "x-request-id": "provider-header-test",
        "x-ratelimit-remaining-requests": "9",
      },
      first_token_kind: "reasoning",
      first_visible_text_ms: 18,
      timeout_scope: "attempt_budget",
    });
    expect(modelRequest.raw_response).toBe("欢迎来到这场实时狼人杀对局。");
    expect(modelRequest.passive_observations).toEqual([
      {
        code: "wolf_cardinality_contradiction",
        effect: "observed_only",
      },
    ]);
    expect(result.presentations[0]).toMatchObject({
      presentation_seq: 1,
      source_event_id: 2,
      speech_id: "v2_speech_0123456789abcdef",
      segment_index: 0,
    });
    expect(result.voice_assets[0]).toMatchObject({
      state: "ready",
      sample_count: 43200,
      duration_ms: 1800,
    });
  });

  it("parses an idempotent V2 stop result", () => {
    expect(
      parseV2GameControlResult({
        action: "stop",
        game_id: item.game_id,
        run_id: item.current_run_id,
        run_status: "canceled",
        stop_requested_at: "2026-07-25T10:00:00Z",
        replayed: false,
      }),
    ).toEqual({
      action: "stop",
      game_id: item.game_id,
      run_id: item.current_run_id,
      run_status: "canceled",
      stop_requested_at: "2026-07-25T10:00:00Z",
      replayed: false,
    });
  });

  it("parses model retry telemetry and the operator retry result", () => {
    const request = parseV2ModelRequestPage({
      after_record_seq: 10,
      has_more: false,
      items: [
        {
          attempt_id: "v2_model_attempt_3",
          attempt_no: 3,
          cycle_attempt_no: 1,
          retry_cycle: 2,
          max_attempts: 2,
          retry_of_attempt_id: "v2_model_attempt_2",
          record_seq: 11,
          last_record_seq: 11,
          action_id: "v2_action_opening",
          run_id: item.current_run_id,
          phase_id: "opening",
          action_type: "judge_opening_speech",
          actor_kind: "judge",
          actor_id: "judge",
          audience: "all",
          request_kind: "speech",
          model_id: "doubao-seed-2-0-lite-260215",
          model_provider: "agent_plan",
          judge_configuration_version: null,
          prompt_schema_version: 5,
          prompt_projection: null,
          status: "failed",
          input_source: "persisted",
          passive_observation_count: 0,
          output_source: "unavailable",
          provider_request_id: null,
          first_token_ms: null,
          completed_ms: null,
          failure_kind: "model",
          failure_code: "model_first_token_timeout",
          retryable: true,
          terminal: true,
          failure_stage: "response_headers",
          exception_type: "TimeoutError",
          errno: null,
          http_status: null,
          first_token_seen: false,
          response_headers_seen: false,
          failure_elapsed_ms: 10_001,
          attempt_budget_ms: 30_000,
          action_budget_ms: 45_000,
          action_elapsed_ms: 10_001,
          action_remaining_ms: 34_999,
          started_at: item.created_at,
          completed_at: item.updated_at,
        },
      ],
      next_after_record_seq: 11,
    }).items[0];

    expect(request).toMatchObject({
      attempt_no: 3,
      cycle_attempt_no: 1,
      retry_cycle: 2,
      audience: "all",
      stored_audience: null,
      effective_audience: "all",
      audience_source: "legacy_unknown",
      failure_stage: "response_headers",
      response_headers_seen: false,
      response_headers: null,
      first_token_kind: null,
      first_visible_text_ms: null,
      timeout_scope: null,
      attempt_budget_ms: 30_000,
      action_budget_ms: 45_000,
      action_remaining_ms: 34_999,
    });
    expect(
      parseV2ModelActionRetryResult({
        action: "retry_model_action",
        game_id: item.game_id,
        run_id: item.current_run_id,
        run_status: "generating",
        action_id: "v2_action_opening",
        replayed: false,
      }),
    ).toEqual({
      action: "retry_model_action",
      game_id: item.game_id,
      run_id: item.current_run_id,
      run_status: "generating",
      action_id: "v2_action_opening",
      replayed: false,
    });
  });

  it("rejects a malformed sequence", () => {
    expect(() =>
      parseV2GameRecordList({
        items: [{ ...item, last_record_seq: -1 }],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toThrow("V2 对局记录数据不完整或格式错误");
  });

  it("accepts a run that has been created but not formally started", () => {
    const result = parseV2GameRecordSummary({
      ...item,
      status: "waiting_to_start",
      match_status: "waiting",
      execution_state: "unowned",
      rule_snapshot: {},
      players_snapshot: [],
      judge_voice_snapshot: {},
      delivery_snapshot: null,
      ability_snapshot: {},
      match_state: null,
      player_identities: [],
      runs: [{
        run_id: item.current_run_id,
        attempt_no: 1,
        status: "waiting_to_start",
        started_at: null,
        completed_at: null,
        stop_requested_at: null,
        worker_id: null,
        worker_heartbeat_at: null,
        lease_expires_at: null,
        fence_token: 0,
      }],
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
    });

    expect(result.runs[0].started_at).toBeNull();
    expect(result).toMatchObject({
      match_status: "waiting",
      execution_state: "unowned",
      delivery_snapshot: null,
    });
  });
});
