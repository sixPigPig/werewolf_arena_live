import type {
  AdminLiveRunDebug,
  AdminLiveRunDetail,
  AdminLiveRunListItem,
} from "@/features/live-runs/types";

export const contractLiveRunItem: AdminLiveRunListItem = {
  run_id: "run_1234abcd",
  session_id: "game_1234abcd",
  status: "completed",
  winner: "好人阵营",
  villager_model: "deepseek-v4-flash",
  werewolf_model: "doubao-seed-1-6-flash",
  max_rounds: 12,
  rule_set: { id: "classic_8", name: "经典八人局", player_count: 8 },
  created_at: "2026-07-10T01:00:00Z",
  started_at: "2026-07-10T01:00:01Z",
  completed_at: "2026-07-10T01:03:00Z",
  stop_requested_at: null,
  worker_heartbeat_at: "2026-07-10T01:02:58Z",
  worker_state: "released",
  recovery_attempts: 0,
  recovery_last_attempt_at: null,
  recovery_not_before: null,
  recovery_exhausted: false,
  updated_at: "2026-07-10T01:03:01Z",
  event_count: 5,
  last_activity_at: "2026-07-10T01:03:00Z",
  is_stale: false,
  voice_counts: {
    total: 4,
    pending: 0,
    synthesizing: 0,
    complete: 3,
    failed: 1,
    canceled: 0,
    other: 0,
  },
  has_error: true,
  game: { status: "complete", resumable: false, terminal: true },
};

export const contractActiveLiveRunItem: AdminLiveRunListItem = {
  ...contractLiveRunItem,
  run_id: "run_active123",
  session_id: "game_active123",
  status: "running",
  winner: null,
  villager_model: "deepseek-v4-flash",
  werewolf_model: "doubao-seed-1-6-flash",
  completed_at: null,
  worker_state: "active",
  event_count: 2,
  is_stale: true,
  voice_counts: {
    total: 2,
    pending: 1,
    synthesizing: 1,
    complete: 0,
    failed: 0,
    canceled: 0,
    other: 0,
  },
  has_error: false,
  game: { status: "partial", resumable: true, terminal: false },
};

export const contractLiveRunDetail: AdminLiveRunDetail = {
  ...contractLiveRunItem,
  recent_events: [
    {
      event_id: 5,
      type: "game_completed",
      round: 1,
      phase: "summary",
      actor: "法官",
      action: "complete",
      created_at: "2026-07-10T01:03:00Z",
    },
  ],
  p2_diagnostics: {
    schema_version: 1,
    data_status: "available",
    performance: {
      request_count: 24,
      discrete_action_sample_count: 18,
      discrete_action_p50_ms: 4200,
      discrete_action_p95_ms: null,
      discrete_action_max_ms: 13200,
      speech_first_token_sample_count: 8,
      speech_first_token_p95_ms: null,
      speech_first_token_max_ms: 7800,
      timeout_count: 1,
      fallback_count: 1,
      active_request_count: 0,
      game_duration_ms: 179000,
    },
    speech_quality: {
      checked_count: 8,
      retry_count: 2,
      exhausted_count: 0,
      low_novelty_window_count: 1,
    },
    choice_normalization: {
      exact_count: 20,
      seat_alias_count: 1,
      public_label_count: 3,
      invalid_count: 0,
      other_count: 0,
    },
  },
};

export const contractActiveLiveRunDetail: AdminLiveRunDetail = {
  ...contractActiveLiveRunItem,
  recent_events: [
    {
      event_id: 2,
      type: "activity",
      round: 1,
      phase: "day",
      actor: null,
      action: null,
      created_at: "2026-07-10T01:01:00Z",
    },
  ],
  p2_diagnostics: {
    ...contractLiveRunDetail.p2_diagnostics,
    data_status: "collecting",
    performance: {
      ...contractLiveRunDetail.p2_diagnostics.performance,
      request_count: 2,
      active_request_count: 1,
      game_duration_ms: null,
    },
  },
};

export const contractLiveRunDebug: AdminLiveRunDebug = {
  run_id: contractLiveRunItem.run_id,
  run_error: "Upstream request timed out",
  voice_error_total: 1,
  voice_errors: [
    { utterance_id: "voice_1234", error: "Synthesis request timed out" },
  ],
  truncated: false,
};
