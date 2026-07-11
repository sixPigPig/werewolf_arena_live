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
  reaper_up: true,
  alerts: [],
};

const PREVIEW_SETTINGS: AdminSettings = {
  environment: "development",
  api_prefix: "/api/v1",
  tts_enabled: false,
  authentication: { oidc_enabled: false, development_login_enabled: false, secure_admin_cookie: false, secure_public_cookie: false, admin_session_ttl_seconds: 28800, public_session_ttl_seconds: 2592000 },
  compatibility: { legacy_content_writes_enabled: false, legacy_favorite_writes_enabled: false, legacy_voice_generation_enabled: false },
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
