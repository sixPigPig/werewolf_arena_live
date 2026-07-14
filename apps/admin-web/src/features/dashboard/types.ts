export type AdminOverview = {
  generated_at: string;
  environment: "development" | "test" | "staging" | "production";
  profiles: {
    total: number;
    draft: number;
    published: number;
    archived: number;
    featured: number;
  };
  games: {
    total: number;
    complete: number;
    incomplete: number;
    resumable: number;
  };
  runs: {
    total: number;
    queued: number;
    running: number;
    completed: number;
    canceled: number;
    failed: number;
    stale: number;
    recovery_exhausted: number;
  };
  jobs: {
    total: number;
    queued: number;
    running: number;
    completed: number;
    failed: number;
  };
  quality: {
    cohort_days: number;
    sample_count: number;
    pass_count: number;
    warn_count: number;
    fail_count: number;
    unavailable_count: number;
    partial_count: number;
    legacy_count: number;
    p0_game_count: number;
    latest_p0_at: string | null;
    pending_count: number;
    processing_count: number;
    worker_failed_count: number;
    expired_lease_count: number;
    oldest_pending_seconds: number | null;
    worker_up: boolean;
    critical_fact_expected: number;
    critical_fact_recorded: number;
    prompt_fact_expected: number;
    prompt_fact_included: number;
    voice_expected: number;
    voice_covered: number;
    action_sample_count: number;
    action_p95_ms: number | null;
    speech_check_count: number;
    repeated_speech_count: number;
    speech_retry_exhausted_count: number;
    lineup_warning_count: number;
  };
  reaper_up: boolean;
  alerts: AdminOverviewAlert[];
};
export type AdminOverviewAlert = {
  code: string;
  severity: "info" | "warning" | "critical";
  title: string;
  detail: string;
  count: number;
  href: string;
};

export type AdminJobStatus = "queued" | "running" | "completed" | "failed";

export type AdminJob = {
  id: string;
  type: "judge_voice_generation";
  mode: "missing" | "all";
  status: AdminJobStatus;
  total_count: number;
  processed_count: number;
  generated_count: number;
  failed_count: number;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type AdminJobList = {
  items: AdminJob[];
  pagination: { page: number; page_size: number; total: number; pages: number };
};

export type AdminSettings = {
  environment: AdminOverview["environment"];
  api_prefix: string;
  tts_enabled: boolean;
  authentication: {
    oidc_enabled: boolean;
    development_login_enabled: boolean;
    secure_admin_cookie: boolean;
    secure_public_cookie: boolean;
    admin_session_ttl_seconds: number;
    public_session_ttl_seconds: number;
  };
  compatibility: {
    legacy_content_writes_enabled: boolean;
    legacy_favorite_writes_enabled: boolean;
    legacy_voice_generation_enabled: boolean;
  };
  workers: {
    judge_voice_poll_seconds: number;
    judge_voice_heartbeat_seconds: number;
    judge_voice_probe_max_age_seconds: number;
    reaper_poll_seconds: number;
    reaper_stale_grace_seconds: number;
    reaper_max_attempts: number;
    reaper_probe_max_age_seconds: number;
  };
  live_runs: {
    lease_seconds: number;
    heartbeat_seconds: number;
    event_poll_seconds: number;
  };
};

export type AdminSearchResult = {
  type: "run" | "game" | "player" | "job";
  id: string;
  label: string;
  description: string;
  status: string;
  href: string;
};

export type AdminSearchResponse = {
  query: string;
  items: AdminSearchResult[];
};
