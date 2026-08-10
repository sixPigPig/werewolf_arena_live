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

  it("parses V11 projection rejections and output enforcement without inference", () => {
    const rawRequest = {
      attempt_id: "v2_model_v11",
      action_id: "v2_action_v11",
      run_id: item.current_run_id,
      phase_id: "day_3",
      action_type: "exile_vote",
      actor_kind: "player",
      actor_id: "seat_12",
      audience: "seat_12",
      request_kind: "decision",
      model_id: "glm-5-2-260617",
      model_provider: "openai_compatible",
      judge_configuration_version: null,
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
        source_event_count: 52,
        emitted_event_count: 52,
        future_filtered_event_count: 0,
        source_claim_candidate_count: 4,
        emitted_claim_count: 3,
        out_of_scope_claim_count: 0,
        rejected_claim_count: 1,
        source_question_count: 9,
        current_scope_question_count: 9,
        emitted_question_count: 9,
        out_of_scope_question_count: 0,
        invalid_question_count: 0,
        source_relation_count: 6,
        emitted_relation_count: 6,
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
        schema_name: "v2_action_decision",
        schema_version: 1,
      },
      application_validation_result: "accepted",
      repair_kind: null,
      status: "succeeded",
      input_source: "persisted",
      output_source: "persisted",
      request_payload: { model: "glm-5-2-260617" },
      raw_response: '{"target_player_id":"seat_5"}',
      parsed_output: { target_player_id: "seat_5" },
      passive_observations: [],
      provider_request_id: "provider-v11",
      first_token_ms: 123,
      completed_ms: 456,
      failure_kind: null,
      failure_code: null,
      started_at: item.created_at,
      completed_at: item.updated_at,
    };
    const request = parseV2ModelRequest(rawRequest);

    expect(request.prompt_projection).toMatchObject({
      ledger_schema_version: 5,
      emitted_event_count: 52,
      rejected_claim_count: 1,
      derivation_rejections: [
        {
          source_event_ref: "402",
          kind: "investigation_claim",
          reason: "missing_required_fields",
          missing_fields: ["target_ref", "claimed_result"],
        },
      ],
    });
    expect(request.output_enforcement).toEqual({
      requested: "strict_json_schema",
      actual: "prompt_and_application_validation",
      schema_name: "v2_action_decision",
      schema_version: 1,
    });
    expect(request.application_validation_result).toBe("accepted");
    expect(request.repair_kind).toBeNull();
    expect(request).toMatchObject({
      decision_family_id: null,
      retry_scope: "action",
      vote_batch_stage: null,
      automatic_machine_format_attempt_count: null,
      automatic_machine_format_budget: null,
      prior_output_budget_failures: null,
      output_budget_failure_count: null,
      automatic_output_budget_attempt_count: null,
      automatic_output_budget_budget: null,
      model_generation_policy_contract_status: null,
      model_generation_policy_schema_version: null,
      model_generation_policy_classification_version: null,
      model_generation_policy_enforcement: null,
      model_generation_policy_reasoning_parameter_mode: null,
      model_generation_policy_profile: null,
      model_generation_policy_profile_source: null,
      reasoning_only_timeout_ms: null,
      timeout_max_attempts: null,
      shadow_would_timeout: null,
    });

    const v12Projection = {
      ...rawRequest.prompt_projection,
      model_context_schema_version: 12,
      prompt_template_version: 5,
      known_events_schema_version: 6,
      canonical_serialized_char_count: 4_000,
      compact_serialized_char_count: 2_500,
      compaction_saved_chars: 1_500,
      compaction_ratio: 0.625,
      verbatim_speech_count: 2,
      verbatim_speech_chars: 38,
      retained_event_refs: ["1403", "1442"],
      dropped_event_refs: [],
      canonical_sha256: "a".repeat(64),
      round_trip_verified: true,
    };
    const v12Request = parseV2ModelRequest({
      ...rawRequest,
      model_context_schema_version: 12,
      prompt_template_version: 5,
      prompt_projection: v12Projection,
      expanded_known_events: {
        schema_version: 5,
        events: [],
        questions: [],
        relations: [],
      },
      known_events_expansion_status: "verified",
    });
    expect(v12Request.prompt_projection).toMatchObject({
      known_events_schema_version: 6,
      compact_serialized_char_count: 2_500,
      compaction_ratio: 0.625,
      retained_event_refs: ["1403", "1442"],
      dropped_event_refs: [],
      round_trip_verified: true,
    });
    expect(v12Request.known_events_expansion_status).toBe("verified");
    expect(v12Request.expanded_known_events).toEqual({
      schema_version: 5,
      events: [],
      questions: [],
      relations: [],
    });
    expect(() =>
      parseV2ModelRequest({
        ...rawRequest,
        model_context_schema_version: 12,
        prompt_template_version: 5,
        prompt_projection: { ...v12Projection, compaction_ratio: "0.625" },
      }),
    ).toThrow("V2 对局记录数据不完整或格式错误");
    expect(
      parseV2ModelRequest({
        ...rawRequest,
        model_context_schema_version: 12,
        prompt_template_version: 5,
        prompt_projection: {
          ...v12Projection,
          model_view_schema_version: 4,
          compaction_ratio: "hybrid-contract-raw",
        },
      }).prompt_projection,
    ).toMatchObject({
      model_context_schema_version: 12,
      model_view_schema_version: 4,
      compaction_ratio: "hybrid-contract-raw",
    });
    expect(
      parseV2ModelRequest({
        ...rawRequest,
        model_context_schema_version: 99,
        prompt_projection: { compaction_ratio: "unknown-contract-raw" },
      }).prompt_projection,
    ).toEqual({ compaction_ratio: "unknown-contract-raw" });
    expect(() =>
      parseV2ModelRequest({
        ...rawRequest,
        known_events_expansion_status: "guessed",
      }),
    ).toThrow("V2 对局记录数据不完整或格式错误");
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
          decision_family_id: "v2_decision_family_vote_1",
          retry_scope: "operator_retry",
          vote_batch_stage: "sequential_recovery",
          automatic_machine_format_attempt_count: 2,
          automatic_machine_format_budget: 2,
          prior_output_budget_failures: 2,
          output_budget_failure_count: 1,
          automatic_output_budget_attempt_count: 3,
          automatic_output_budget_budget: 3,
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
          model_binding_failure_streak: 2,
          model_binding_health_status: "degraded",
          model_binding_recovered_after_failures: null,
          started_at: item.created_at,
          completed_at: item.updated_at,
        },
      ],
      next_after_record_seq: 11,
    }).items[0];

    expect(request).toMatchObject({
      decision_family_id: "v2_decision_family_vote_1",
      retry_scope: "operator_retry",
      vote_batch_stage: "sequential_recovery",
      automatic_machine_format_attempt_count: 2,
      automatic_machine_format_budget: 2,
      prior_output_budget_failures: 2,
      output_budget_failure_count: 1,
      automatic_output_budget_attempt_count: 3,
      automatic_output_budget_budget: 3,
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
      model_binding_failure_streak: 2,
      model_binding_health_status: "degraded",
      model_binding_recovered_after_failures: null,
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

  it("parses normalized stream diagnostics and server-derived failure resolution", () => {
    const rawRequest = {
      attempt_id: "v2_model_diag_1",
      action_id: "v2_action_diag_1",
      run_id: item.current_run_id,
      phase_id: "opening",
      action_type: "judge_opening_speech",
      actor_kind: "judge",
      actor_id: "judge",
      audience: "private",
      request_kind: "speech",
      model_id: null,
      model_provider: null,
      judge_configuration_version: null,
      status: "failed",
      input_source: "unavailable",
      output_source: "unavailable",
      provider_request_id: "provider-diag-1",
      finish_reason: "max_output_tokens",
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
      first_token_ms: 19,
      reasoning_only_elapsed_ms: 31,
      completed_ms: null,
      reasoning_delta_count: 7,
      text_delta_count: 2,
      max_inter_delta_ms: 17,
      last_progress_ms: 72,
      failure_kind: "model",
      failure_code: "model_output_budget_exhausted",
      effective_attempt_limit: 2,
      retry_delay_ms: 250,
      required_retry_window_ms: 1_250,
      automatic_retry_scheduled: false,
      automatic_retry_stop_reason: "insufficient_action_budget",
      prior_output_budget_failures: 2,
      output_budget_failure_count: 1,
      automatic_output_budget_attempt_count: 3,
      automatic_output_budget_budget: 3,
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
      shadow_would_timeout: true,
      failure_episode_id: "v2_mfep_0123456789abcdef01234567",
      failure_resolution: "run_canceled",
      failure_episode_source_attempt_ids: ["v2_model_diag_1"],
      failure_episode_source_event_refs: [
        {
          event_type: "model_request_failed",
          event_id: 40,
          record_seq: 40,
        },
      ],
      failure_episode_terminal_event_refs: [
        { event_type: "game_canceled", event_id: 44, record_seq: 44 },
      ],
      resolution_event_type: "game_canceled",
      resolution_event_id: 44,
      resolution_event_record_seq: 44,
      supporting_event_type: null,
      supporting_event_id: null,
      supporting_event_record_seq: null,
      resolution_updated_at_record_seq: 44,
      failure_episode_invariant_errors: [],
      started_at: item.created_at,
      completed_at: item.updated_at,
      request_payload: null,
      raw_response: null,
      parsed_output: null,
      passive_observations: [],
    };

    const request = parseV2ModelRequest(rawRequest);

    expect(request).toMatchObject({
      finish_reason: "max_output_tokens",
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
      reasoning_only_elapsed_ms: 31,
      reasoning_delta_count: 7,
      text_delta_count: 2,
      max_inter_delta_ms: 17,
      last_progress_ms: 72,
      effective_attempt_limit: 2,
      automatic_retry_scheduled: false,
      automatic_retry_stop_reason: "insufficient_action_budget",
      prior_output_budget_failures: 2,
      output_budget_failure_count: 1,
      automatic_output_budget_attempt_count: 3,
      automatic_output_budget_budget: 3,
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
      shadow_would_timeout: true,
      failure_resolution: "run_canceled",
      failure_episode_terminal_event_refs: [
        { event_type: "game_canceled", event_id: 44, record_seq: 44 },
      ],
      resolution_updated_at_record_seq: 44,
    });
    expect(
      parseV2ModelRequest({
        ...rawRequest,
        failure_episode_id: undefined,
        failure_resolution: undefined,
      }).failure_resolution,
    ).toBe("legacy_unavailable");
    expect(() =>
      parseV2ModelRequest({
        ...rawRequest,
        provider_usage: { output_tokens: -1 },
      }),
    ).toThrow("V2 对局记录数据不完整或格式错误");
    expect(() =>
      parseV2ModelRequest({
        ...rawRequest,
        automatic_output_budget_attempt_count: -1,
      }),
    ).toThrow("V2 对局记录数据不完整或格式错误");
    expect(() =>
      parseV2ModelRequest({
        ...rawRequest,
        shadow_would_timeout: "true",
      }),
    ).toThrow("V2 对局记录数据不完整或格式错误");
    expect(() =>
      parseV2ModelRequest({
        ...rawRequest,
        model_generation_policy_schema_version: 0,
      }),
    ).toThrow("V2 对局记录数据不完整或格式错误");
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
