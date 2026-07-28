import { useQuery } from "@tanstack/react-query";

import { getAdminOverview, getAdminSettings } from "@/features/dashboard/api";
import type { AdminRuntimeMode } from "@/features/auth/types";
import type { AdminOverview, AdminSettings } from "@/features/dashboard/types";

const PREVIEW_OVERVIEW: AdminOverview = {
  generated_at: "2026-07-12T00:00:00Z",
  environment: "development",
  profiles: { total: 12, draft: 2, published: 9, archived: 1, featured: 3 },
  games: { total: 48, complete: 45, incomplete: 3, resumable: 1 },
  runs: { total: 50, queued: 1, running: 1, completed: 45, canceled: 1, failed: 2, stale: 0, recovery_exhausted: 0 },
  jobs: { total: 8, queued: 1, running: 0, completed: 7, failed: 0 },
  quality: {
    cohort_days: 7,
    sample_count: 24,
    pass_count: 20,
    warn_count: 3,
    fail_count: 1,
    unavailable_count: 0,
    partial_count: 2,
    legacy_count: 4,
    p0_game_count: 0,
    latest_p0_at: null,
    pending_count: 1,
    processing_count: 0,
    worker_failed_count: 0,
    expired_lease_count: 0,
    oldest_pending_seconds: 12,
    worker_up: true,
    critical_fact_expected: 80,
    critical_fact_recorded: 77,
    prompt_fact_expected: 160,
    prompt_fact_included: 154,
    voice_expected: 120,
    voice_covered: 116,
    action_sample_count: 240,
    action_p95_ms: 8000,
    speech_check_count: 140,
    repeated_speech_count: 4,
    speech_retry_exhausted_count: 1,
    lineup_warning_count: 3,
  },
  reaper_up: true,
  alerts: [],
};

const PREVIEW_SETTINGS: AdminSettings = {
  environment: "development",
  api_prefix: "/api/v1",
  tts_enabled: false,
  authentication: { oidc_enabled: false, development_login_enabled: false, secure_admin_cookie: false, secure_public_cookie: false, admin_session_ttl_seconds: 28800, public_session_ttl_seconds: 2592000 },
  compatibility: { legacy_content_writes_enabled: false, legacy_voice_generation_enabled: false },
  workers: { judge_voice_poll_seconds: 2, judge_voice_heartbeat_seconds: 10, judge_voice_probe_max_age_seconds: 45, reaper_poll_seconds: 5, reaper_stale_grace_seconds: 30, reaper_max_attempts: 3, reaper_probe_max_age_seconds: 45 },
  live_runs: { lease_seconds: 15, heartbeat_seconds: 3, event_poll_seconds: 0.25 },
};

export function useOverviewQuery(runtimeMode: AdminRuntimeMode, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["admin", "dashboard", "overview"],
    queryFn: ({ signal }) => runtimeMode === "preview" ? PREVIEW_OVERVIEW : getAdminOverview(signal),
    refetchInterval: runtimeMode === "authenticated" ? 30_000 : false,
    staleTime: 15_000,
  });
}

export function useSettingsQuery(runtimeMode: AdminRuntimeMode, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["admin", "dashboard", "settings"],
    queryFn: ({ signal }) => runtimeMode === "preview" ? PREVIEW_SETTINGS : getAdminSettings(signal),
    staleTime: 5 * 60_000,
  });
}
