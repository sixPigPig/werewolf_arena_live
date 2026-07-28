import { AdminApiError } from "@/api/problem-details";
import type {
  AdminJob,
  AdminJobList,
  AdminJobStatus,
  AdminOverview,
  AdminOverviewAlert,
  AdminSearchResponse,
  AdminSearchResult,
  AdminSettings,
} from "@/features/dashboard/types";

const ENVIRONMENTS = ["development", "test", "staging", "production"] as const;
const JOB_STATUSES: AdminJobStatus[] = ["queued", "running", "completed", "failed"];

export function parseAdminOverview(value: unknown): AdminOverview {
  const record = objectValue(value);
  const quality = objectValue(record.quality);
  return {
    generated_at: dateValue(record.generated_at, "generated_at"),
    environment: enumValue(record.environment, ENVIRONMENTS, "environment"),
    profiles: countRecord(record.profiles, ["total", "draft", "published", "archived", "featured"]),
    games: countRecord(record.games, ["total", "complete", "incomplete", "resumable"]),
    runs: countRecord(record.runs, [
      "total", "queued", "running", "completed", "canceled", "failed", "stale", "recovery_exhausted",
    ]),
    jobs: countRecord(record.jobs, ["total", "queued", "running", "completed", "failed"]),
    quality: {
      ...countRecord(quality, [
        "cohort_days", "sample_count", "pass_count", "warn_count", "fail_count",
        "unavailable_count", "partial_count", "legacy_count", "p0_game_count",
        "pending_count", "processing_count", "worker_failed_count", "expired_lease_count",
        "critical_fact_expected", "critical_fact_recorded", "prompt_fact_expected",
        "prompt_fact_included", "voice_expected", "voice_covered", "action_sample_count",
        "speech_check_count", "repeated_speech_count", "speech_retry_exhausted_count",
        "lineup_warning_count",
      ]),
      latest_p0_at: nullableDate(quality.latest_p0_at, "quality.latest_p0_at"),
      oldest_pending_seconds: nullableNonNegativeInteger(
        quality.oldest_pending_seconds,
        "quality.oldest_pending_seconds",
      ),
      worker_up: booleanValue(quality.worker_up, "quality.worker_up"),
      action_p95_ms: nullableNonNegativeInteger(
        quality.action_p95_ms,
        "quality.action_p95_ms",
      ),
    },
    reaper_up: booleanValue(record.reaper_up, "reaper_up"),
    alerts: arrayValue(record.alerts, "alerts").map(parseAlert),
  } as AdminOverview;
}
export function parseAdminJobList(value: unknown): AdminJobList {
  const record = objectValue(value);
  const pagination = objectValue(record.pagination);
  return {
    items: arrayValue(record.items, "items").map(parseJob),
    pagination: {
      page: positiveInteger(pagination.page, "pagination.page"),
      page_size: positiveInteger(pagination.page_size, "pagination.page_size"),
      total: nonNegativeInteger(pagination.total, "pagination.total"),
      pages: nonNegativeInteger(pagination.pages, "pagination.pages"),
    },
  };
}

export function parseAdminSettings(value: unknown): AdminSettings {
  const record = objectValue(value);
  const authentication = objectValue(record.authentication);
  const compatibility = objectValue(record.compatibility);
  const workers = objectValue(record.workers);
  const liveRuns = objectValue(record.live_runs);
  return {
    environment: enumValue(record.environment, ENVIRONMENTS, "environment"),
    api_prefix: stringValue(record.api_prefix, "api_prefix"),
    tts_enabled: booleanValue(record.tts_enabled, "tts_enabled"),
    authentication: {
      oidc_enabled: booleanValue(authentication.oidc_enabled, "oidc_enabled"),
      development_login_enabled: booleanValue(authentication.development_login_enabled, "development_login_enabled"),
      secure_admin_cookie: booleanValue(authentication.secure_admin_cookie, "secure_admin_cookie"),
      secure_public_cookie: booleanValue(authentication.secure_public_cookie, "secure_public_cookie"),
      admin_session_ttl_seconds: positiveInteger(authentication.admin_session_ttl_seconds, "admin_session_ttl_seconds"),
      public_session_ttl_seconds: positiveInteger(authentication.public_session_ttl_seconds, "public_session_ttl_seconds"),
    },
    compatibility: {
      legacy_content_writes_enabled: booleanValue(compatibility.legacy_content_writes_enabled, "legacy_content_writes_enabled"),
      legacy_voice_generation_enabled: booleanValue(compatibility.legacy_voice_generation_enabled, "legacy_voice_generation_enabled"),
    },
    workers: {
      judge_voice_poll_seconds: nonNegativeNumber(workers.judge_voice_poll_seconds, "judge_voice_poll_seconds"),
      judge_voice_heartbeat_seconds: nonNegativeNumber(workers.judge_voice_heartbeat_seconds, "judge_voice_heartbeat_seconds"),
      judge_voice_probe_max_age_seconds: nonNegativeNumber(workers.judge_voice_probe_max_age_seconds, "judge_voice_probe_max_age_seconds"),
      reaper_poll_seconds: nonNegativeNumber(workers.reaper_poll_seconds, "reaper_poll_seconds"),
      reaper_stale_grace_seconds: nonNegativeNumber(workers.reaper_stale_grace_seconds, "reaper_stale_grace_seconds"),
      reaper_max_attempts: positiveInteger(workers.reaper_max_attempts, "reaper_max_attempts"),
      reaper_probe_max_age_seconds: nonNegativeNumber(workers.reaper_probe_max_age_seconds, "reaper_probe_max_age_seconds"),
    },
    live_runs: {
      lease_seconds: nonNegativeNumber(liveRuns.lease_seconds, "lease_seconds"),
      heartbeat_seconds: nonNegativeNumber(liveRuns.heartbeat_seconds, "heartbeat_seconds"),
      event_poll_seconds: nonNegativeNumber(liveRuns.event_poll_seconds, "event_poll_seconds"),
    },
  };
}

export function parseAdminSearch(value: unknown): AdminSearchResponse {
  const record = objectValue(value);
  return {
    query: stringValue(record.query, "query"),
    items: arrayValue(record.items, "items").map(parseSearchResult),
  };
}

function parseAlert(value: unknown): AdminOverviewAlert {
  const record = objectValue(value);
  return {
    code: stringValue(record.code, "alert.code"),
    severity: enumValue(record.severity, ["info", "warning", "critical"] as const, "alert.severity"),
    title: stringValue(record.title, "alert.title"),
    detail: stringValue(record.detail, "alert.detail"),
    count: nonNegativeInteger(record.count, "alert.count"),
    href: internalHref(record.href),
  };
}

function parseJob(value: unknown): AdminJob {
  const record = objectValue(value);
  const type = enumValue(record.type, ["judge_voice_generation"] as const, "job.type");
  return {
    id: stringValue(record.id, "job.id"),
    type,
    mode: enumValue(record.mode, ["missing", "all"] as const, "job.mode"),
    status: enumValue(record.status, JOB_STATUSES, "job.status"),
    total_count: nonNegativeInteger(record.total_count, "job.total_count"),
    processed_count: nonNegativeInteger(record.processed_count, "job.processed_count"),
    generated_count: nonNegativeInteger(record.generated_count, "job.generated_count"),
    failed_count: nonNegativeInteger(record.failed_count, "job.failed_count"),
    error_code: nullableString(record.error_code, "job.error_code"),
    created_at: dateValue(record.created_at, "job.created_at"),
    started_at: nullableDate(record.started_at, "job.started_at"),
    completed_at: nullableDate(record.completed_at, "job.completed_at"),
  };
}

function parseSearchResult(value: unknown): AdminSearchResult {
  const record = objectValue(value);
  return {
    type: enumValue(record.type, ["run", "game", "player", "job"] as const, "search.type"),
    id: stringValue(record.id, "search.id"),
    label: stringValue(record.label, "search.label"),
    description: stringValue(record.description, "search.description"),
    status: stringValue(record.status, "search.status"),
    href: internalHref(record.href),
  };
}

function countRecord<Key extends string>(value: unknown, keys: readonly Key[]): Record<Key, number> {
  const record = objectValue(value);
  return Object.fromEntries(keys.map((key) => [key, nonNegativeInteger(record[key], key)])) as Record<Key, number>;
}

function objectValue(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw invalidContract("响应对象无效");
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw invalidContract(`${field} 不是数组`);
  return value;
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== "string" || !value) throw invalidContract(`${field} 不是有效字符串`);
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  return value === null ? null : stringValue(value, field);
}

function booleanValue(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw invalidContract(`${field} 不是布尔值`);
  return value;
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) throw invalidContract(`${field} 不是非负整数`);
  return value;
}

function positiveInteger(value: unknown, field: string): number {
  const result = nonNegativeInteger(value, field);
  if (result < 1) throw invalidContract(`${field} 不是正整数`);
  return result;
}

function nullableNonNegativeInteger(value: unknown, field: string): number | null {
  return value === null ? null : nonNegativeInteger(value, field);
}

function nonNegativeNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw invalidContract(`${field} 不是非负数`);
  return value;
}

function dateValue(value: unknown, field: string): string {
  const result = stringValue(value, field);
  if (!Number.isFinite(Date.parse(result))) throw invalidContract(`${field} 不是有效时间`);
  return result;
}

function nullableDate(value: unknown, field: string): string | null {
  return value === null ? null : dateValue(value, field);
}

function enumValue<const Values extends readonly string[]>(value: unknown, values: Values, field: string): Values[number] {
  const parsed = stringValue(value, field);
  if (!values.includes(parsed)) throw invalidContract(`${field} 枚举值无效`);
  return parsed as Values[number];
}

function internalHref(value: unknown): string {
  const href = stringValue(value, "href");
  if (!href.startsWith("/") || href.startsWith("//")) throw invalidContract("href 不是后台内部路径");
  return href;
}

function invalidContract(detail: string) {
  return new AdminApiError({
    problem: { type: "about:blank", title: "后台总览接口响应无效", status: 502, detail, code: "admin_invalid_dashboard_response", request_id: null },
  });
}
