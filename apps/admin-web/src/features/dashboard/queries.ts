import { useQuery } from "@tanstack/react-query";

import { getAdminOverview, getAdminSettings, getAdminV2Metrics } from "@/features/dashboard/api";
import type { AdminRuntimeMode } from "@/features/auth/types";
import type { AdminOverview, AdminSettings, AdminV2Metrics } from "@/features/dashboard/types";

const PREVIEW_OVERVIEW: AdminOverview = {
  generated_at: "2026-07-12T00:00:00Z",
  environment: "development",
  profiles: { total: 12, draft: 2, published: 9, archived: 1, featured: 3 },
  jobs: { total: 8, queued: 1, running: 0, completed: 7, failed: 0 },
  alerts: [],
};

const PREVIEW_SETTINGS: AdminSettings = {
  environment: "development",
  api_prefix: "/api/v1",
  tts_enabled: false,
  authentication: { oidc_enabled: false, development_login_enabled: false, secure_admin_cookie: false, secure_public_cookie: false, admin_session_ttl_seconds: 28800, public_session_ttl_seconds: 2592000 },
  compatibility: { legacy_content_writes_enabled: false, legacy_voice_generation_enabled: false },
  workers: { judge_voice_poll_seconds: 2, judge_voice_heartbeat_seconds: 10, judge_voice_probe_max_age_seconds: 45 },
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

const PREVIEW_V2_METRICS: AdminV2Metrics = {
  generated_at: "2026-07-12T00:00:00Z",
  window_days: 7,
  runs: {
    by_status: { completed: 6, failed: 2, generating: 1 },
    finished: 8,
    completed: 6,
    failed: 2,
    success_rate: 0.75,
  },
  model_failures: {
    total: 14,
    by_category: { transport: 9, timeout: 4, admission_capacity: 1 },
    top_failure_codes: { model_transport_failed: 9, model_total_timeout: 4 },
  },
  signals: {
    death_reasons: { worker_lease_expired: 2 },
    degraded_vote_abstains: 3,
    auto_resumed_model_actions: 5,
    reaped_runs: 2,
  },
};

export function useV2MetricsQuery(runtimeMode: AdminRuntimeMode, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["admin", "dashboard", "v2-metrics"],
    queryFn: ({ signal }) => (runtimeMode === "preview" ? PREVIEW_V2_METRICS : getAdminV2Metrics(signal)),
    refetchInterval: runtimeMode === "authenticated" ? 30_000 : false,
    staleTime: 15_000,
  });
}
