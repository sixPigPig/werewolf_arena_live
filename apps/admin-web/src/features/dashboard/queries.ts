import { useQuery } from "@tanstack/react-query";

import { getAdminOverview, getAdminSettings } from "@/features/dashboard/api";
import type { AdminRuntimeMode } from "@/features/auth/types";
import type { AdminOverview, AdminSettings } from "@/features/dashboard/types";

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
