import { AdminApiError } from "@/api/problem-details";
import type {
  AdminLiveRunDebug,
  AdminLiveRunControlResult,
  AdminLiveRunDetail,
  AdminLiveRunEvent,
  AdminLiveRunGame,
  AdminLiveRunList,
  AdminLiveRunListItem,
  AdminLiveRunRuleSet,
  AdminLiveRunStatus,
  AdminLiveRunVoiceCounts,
  AdminLiveRunWorkerState,
} from "@/features/live-runs/types";

const RUN_STATUSES: AdminLiveRunStatus[] = [
  "queued",
  "running",
  "completed",
  "failed",
  "canceled",
];
const GAME_STATUSES = ["complete", "partial"] as const;
const WORKER_STATES: AdminLiveRunWorkerState[] = [
  "active",
  "stale",
  "unassigned",
  "released",
];
const SENSITIVE_KEYS = new Set([
  "payload",
  "player_configs",
  "lineup_quality_warnings",
  "lineup_warnings",
  "warnings",
  "raw_error",
  "error_message",
  "traceback",
  "stack",
  "prompt",
  "raw_response",
  "token",
  "secret",
  "seed",
  "state",
  "logs",
  "checkpoint",
  "audio",
  "api_key",
  "authorization",
  "cookie",
  "credential",
  "credentials",
  "password",
  "session_token",
  "request_id",
  "speaker",
  "speaker_name",
  "text",
  "text_hash",
  "subtitle_timings",
  "utterances",
  "chunks",
  "audio_chunks",
]);
const INLINE_DEBUG_KEYS = new Set([
  "debug",
  "error",
  "errors",
  "run_error",
  "voice_errors",
  "voice_error_total",
  "truncated",
]);

export function parseAdminLiveRunList(value: unknown): AdminLiveRunList {
  rejectSensitiveFields(value, false);
  const record = recordValue(value);
  const pagination = recordValue(record.pagination);
  return {
    items: arrayValue(record.items, "items").map(parseListItem),
    pagination: {
      page: positiveInteger(pagination.page, "pagination.page"),
      page_size: positiveInteger(pagination.page_size, "pagination.page_size"),
      total: nonNegativeInteger(pagination.total, "pagination.total"),
      pages: nonNegativeInteger(pagination.pages, "pagination.pages"),
    },
  };
}

export function parseAdminLiveRunDetail(value: unknown): AdminLiveRunDetail {
  rejectSensitiveFields(value, false);
  const record = recordValue(value);
  const item = parseListItem(record);
  const recentEvents = arrayValue(record.recent_events, "recent_events").map(
    parseEvent,
  );
  if (recentEvents.length > 50) {
    throw invalidContract("recent_events 超过最多 50 条的安全上限");
  }
  const canRevealEventIdentity =
    item.status === "completed" && item.game?.terminal === true;
  if (
    !canRevealEventIdentity &&
    recentEvents.some((event) => event.actor !== null || event.action !== null)
  ) {
    throw invalidContract("活跃或未终局运行不得公开事件 actor/action");
  }
  if (!canRevealEventIdentity) {
    const safeTypes = new Set([
      "run_created",
      "run_started",
      "game_started",
      "round_started",
      "phase_started",
      "game_completed",
      "game_failed",
      "activity",
      "runtime_warning",
    ]);
    const safePhases = new Set(["night", "day", "vote", "summary", null]);
    if (
      recentEvents.some(
        (event) =>
          !safeTypes.has(event.type) || !safePhases.has(event.phase),
      )
    ) {
      throw invalidContract("活跃或未终局运行包含未归类的事件元数据");
    }
  }
  return { ...item, recent_events: recentEvents };
}

export function parseAdminLiveRunDebug(value: unknown): AdminLiveRunDebug {
  rejectSensitiveFields(value, true);
  const record = recordValue(value);
  const voiceErrors = arrayValue(record.voice_errors, "debug.voice_errors").map(
    (value) => {
      const error = recordValue(value);
      return {
        utterance_id: requiredString(
          error.utterance_id,
          "debug.voice_error.utterance_id",
        ),
        error: requiredString(error.error, "debug.voice_error.error"),
      };
    },
  );
  if (voiceErrors.length > 20) {
    throw invalidContract("debug.voice_errors 超过最多 20 条的安全上限");
  }
  const parsed = {
    run_id: requiredString(record.run_id, "debug.run_id"),
    run_error: nullableString(record.run_error, "debug.run_error"),
    voice_error_total: nonNegativeInteger(
      record.voice_error_total,
      "debug.voice_error_total",
    ),
    voice_errors: voiceErrors,
    truncated: booleanValue(record.truncated, "debug.truncated"),
  };
  if (parsed.voice_error_total < parsed.voice_errors.length) {
    throw invalidContract("debug.voice_error_total 小于返回的错误数量");
  }
  if (
    parsed.truncated !==
    (parsed.voice_error_total > parsed.voice_errors.length)
  ) {
    throw invalidContract("debug.truncated 与错误总数不一致");
  }
  return parsed;
}

function parseListItem(value: unknown): AdminLiveRunListItem {
  const record = recordValue(value);
  const item: AdminLiveRunListItem = {
    run_id: requiredString(record.run_id, "run_id"),
    session_id: requiredString(record.session_id, "session_id"),
    status: enumValue(record.status, RUN_STATUSES, "status"),
    winner: nullableString(record.winner, "winner"),
    villager_model: nullableString(record.villager_model, "villager_model"),
    werewolf_model: nullableString(record.werewolf_model, "werewolf_model"),
    max_rounds: nonNegativeInteger(record.max_rounds, "max_rounds"),
    rule_set: record.rule_set === null ? null : parseRuleSet(record.rule_set),
    created_at: dateString(record.created_at, "created_at"),
    started_at: nullableDateString(record.started_at, "started_at"),
    completed_at: nullableDateString(record.completed_at, "completed_at"),
    stop_requested_at: nullableDateString(
      record.stop_requested_at,
      "stop_requested_at",
    ),
    worker_heartbeat_at: nullableDateString(
      record.worker_heartbeat_at,
      "worker_heartbeat_at",
    ),
    worker_state: enumValue(record.worker_state, WORKER_STATES, "worker_state"),
    recovery_attempts: nonNegativeInteger(
      record.recovery_attempts,
      "recovery_attempts",
    ),
    recovery_last_attempt_at: nullableDateString(
      record.recovery_last_attempt_at,
      "recovery_last_attempt_at",
    ),
    recovery_not_before: nullableDateString(
      record.recovery_not_before,
      "recovery_not_before",
    ),
    recovery_exhausted: booleanValue(
      record.recovery_exhausted,
      "recovery_exhausted",
    ),
    updated_at: dateString(record.updated_at, "updated_at"),
    event_count: nonNegativeInteger(record.event_count, "event_count"),
    last_activity_at: dateString(
      record.last_activity_at,
      "last_activity_at",
    ),
    is_stale: booleanValue(record.is_stale, "is_stale"),
    voice_counts: parseVoiceCounts(record.voice_counts),
    has_error: booleanValue(record.has_error, "has_error"),
    game: record.game === null ? null : parseGame(record.game),
  };
  const canRevealResult =
    item.status === "completed" && item.game?.terminal === true;
  const canRevealModels =
    item.status === "completed" && item.game?.terminal === true;
  if (!canRevealResult && item.winner !== null) {
    throw invalidContract("未安全终局的运行不得公开胜方");
  }
  if (
    !canRevealModels &&
    (item.villager_model !== null || item.werewolf_model !== null)
  ) {
    throw invalidContract("未成功终局的运行不得公开模型配置");
  }
  if (!isActiveStatus(item.status) && item.is_stale) {
    throw invalidContract("已终止运行不得标记为可能失联");
  }
  if (isActiveStatus(item.status) && item.worker_state === "released") {
    throw invalidContract("活跃运行不得标记为 Worker 已释放");
  }
  if (!isActiveStatus(item.status) && item.worker_state !== "released") {
    throw invalidContract("已终止运行必须标记为 Worker 已释放");
  }
  if (item.recovery_exhausted && item.worker_state !== "stale") {
    throw invalidContract("只有失联运行可以标记为自动恢复已耗尽");
  }
  return item;
}

export function parseAdminLiveRunControl(
  value: unknown,
): AdminLiveRunControlResult {
  rejectSensitiveFields(value, false);
  const record = recordValue(value);
  return {
    action: enumValue(record.action, ["stop", "resume"] as const, "action"),
    target_run_id: requiredString(record.target_run_id, "target_run_id"),
    run_id: requiredString(record.run_id, "run_id"),
    session_id: requiredString(record.session_id, "session_id"),
    run_status: enumValue(record.run_status, RUN_STATUSES, "run_status"),
    stop_requested_at: nullableDateString(
      record.stop_requested_at,
      "stop_requested_at",
    ),
    replayed: booleanValue(record.replayed, "replayed"),
  };
}

function parseRuleSet(value: unknown): AdminLiveRunRuleSet {
  const record = recordValue(value);
  return {
    id: requiredString(record.id, "rule_set.id"),
    name: requiredString(record.name, "rule_set.name"),
    player_count: nullableNonNegativeInteger(
      record.player_count,
      "rule_set.player_count",
    ),
  };
}

function parseVoiceCounts(value: unknown): AdminLiveRunVoiceCounts {
  const record = recordValue(value);
  const counts = {
    total: nonNegativeInteger(record.total, "voice_counts.total"),
    pending: nonNegativeInteger(record.pending, "voice_counts.pending"),
    synthesizing: nonNegativeInteger(
      record.synthesizing,
      "voice_counts.synthesizing",
    ),
    complete: nonNegativeInteger(record.complete, "voice_counts.complete"),
    failed: nonNegativeInteger(record.failed, "voice_counts.failed"),
    canceled: nonNegativeInteger(record.canceled, "voice_counts.canceled"),
    other: nonNegativeInteger(record.other, "voice_counts.other"),
  };
  const bucketTotal =
    counts.pending +
    counts.synthesizing +
    counts.complete +
    counts.failed +
    counts.canceled +
    counts.other;
  if (bucketTotal !== counts.total) {
    throw invalidContract("voice_counts 分类之和与 total 不一致");
  }
  return counts;
}

function parseGame(value: unknown): AdminLiveRunGame {
  const record = recordValue(value);
  const game = {
    status: enumValue(record.status, GAME_STATUSES, "game.status"),
    resumable: booleanValue(record.resumable, "game.resumable"),
    terminal: booleanValue(record.terminal, "game.terminal"),
  };
  if (game.terminal !== (game.status === "complete" && !game.resumable)) {
    throw invalidContract("game.terminal 与对局状态不一致");
  }
  return game;
}

function parseEvent(value: unknown): AdminLiveRunEvent {
  const record = recordValue(value);
  return {
    event_id: nonNegativeInteger(record.event_id, "event.event_id"),
    type: requiredString(record.type, "event.type"),
    round: nullableNonNegativeInteger(record.round, "event.round"),
    phase: nullableString(record.phase, "event.phase"),
    actor: nullableString(record.actor, "event.actor"),
    action: nullableString(record.action, "event.action"),
    created_at: dateString(record.created_at, "event.created_at"),
  };
}

function rejectSensitiveFields(
  value: unknown,
  allowDebugFields: boolean,
  path = "response",
) {
  if (Array.isArray(value)) {
    value.forEach((item, index) =>
      rejectSensitiveFields(item, allowDebugFields, `${path}[${index}]`),
    );
    return;
  }
  if (typeof value !== "object" || value === null) {
    return;
  }
  Object.entries(value as Record<string, unknown>).forEach(([key, child]) => {
    const normalized = key.toLowerCase();
    if (
      SENSITIVE_KEYS.has(normalized) ||
      (normalized.includes("player") && normalized.includes("config")) ||
      (normalized.includes("lineup") && normalized.includes("warning")) ||
      (normalized.includes("raw") && normalized.includes("error")) ||
      normalized.endsWith("_key") ||
      normalized.endsWith("_token") ||
      normalized.endsWith("_secret") ||
      (!allowDebugFields && INLINE_DEBUG_KEYS.has(normalized))
    ) {
      throw invalidContract(`${path}.${key} 不允许出现在后台运行响应中`);
    }
    rejectSensitiveFields(child, allowDebugFields, `${path}.${key}`);
  });
}

function isActiveStatus(status: AdminLiveRunStatus) {
  return status === "queued" || status === "running";
}

function recordValue(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw invalidContract("响应不是对象");
  }
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) {
    throw invalidContract(`${field} 不是数组`);
  }
  return value;
}

function requiredString(value: unknown, field: string) {
  const parsed = stringValue(value, field);
  if (!parsed.trim()) {
    throw invalidContract(`${field} 不能为空`);
  }
  return parsed;
}

function stringValue(value: unknown, field: string) {
  if (typeof value !== "string") {
    throw invalidContract(`${field} 不是字符串`);
  }
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  return value === null ? null : stringValue(value, field);
}

function positiveInteger(value: unknown, field: string) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw invalidContract(`${field} 不是正整数`);
  }
  return value;
}

function nonNegativeInteger(value: unknown, field: string) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw invalidContract(`${field} 不是非负整数`);
  }
  return value;
}

function nullableNonNegativeInteger(value: unknown, field: string) {
  return value === null ? null : nonNegativeInteger(value, field);
}

function booleanValue(value: unknown, field: string) {
  if (typeof value !== "boolean") {
    throw invalidContract(`${field} 不是布尔值`);
  }
  return value;
}

function enumValue<Value extends string>(
  value: unknown,
  allowed: readonly Value[],
  field: string,
): Value {
  const parsed = stringValue(value, field);
  if (!allowed.includes(parsed as Value)) {
    throw invalidContract(`${field} 状态无效`);
  }
  return parsed as Value;
}

function dateString(value: unknown, field: string) {
  const parsed = requiredString(value, field);
  if (!Number.isFinite(Date.parse(parsed))) {
    throw invalidContract(`${field} 不是有效时间`);
  }
  return parsed;
}

function nullableDateString(value: unknown, field: string): string | null {
  return value === null ? null : dateString(value, field);
}

function invalidContract(detail: string) {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "运行接口响应无效",
      status: 502,
      detail,
      code: "admin_invalid_live_run_response",
      request_id: null,
    },
  });
}
