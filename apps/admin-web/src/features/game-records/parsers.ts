import { AdminApiError } from "@/api/problem-details";
import { parseAdminGameP2Quality } from "@/features/p2-quality/parsers";
import type {
  AdminGameDebug,
  AdminGameDetail,
  AdminGameDiagnostics,
  AdminGameEvent,
  AdminGameList,
  AdminGameListItem,
  AdminGamePlayer,
  AdminGameRound,
  AdminGameRuleSet,
  AdminGameRun,
  GameSessionStatus,
  LiveRunStatus,
} from "@/features/game-records/types";

const SESSION_STATUSES: GameSessionStatus[] = ["complete", "partial"];
const RUN_STATUSES: LiveRunStatus[] = [
  "queued",
  "running",
  "completed",
  "failed",
  "canceled",
];
const SENSITIVE_RESPONSE_KEYS = new Set([
  "state",
  "logs",
  "checkpoint",
  "payload",
  "prompt",
  "raw_response",
  "raw_choice",
  "rejected_draft",
  "private_candidates",
  "observations",
  "known_roles",
  "gamestate",
  "private_summaries",
  "avatar_prompt",
  "key",
  "token",
  "secret",
  "api_key",
  "authorization",
  "cookie",
  "credential",
  "password",
  "session_token",
]);

export function parseAdminGameList(value: unknown): AdminGameList {
  rejectSensitiveFields(value);
  const record = recordValue(value);
  const pagination = recordValue(record.pagination);
  if (!Array.isArray(record.items)) {
    throw invalidContract("对局列表缺少 items");
  }
  return {
    items: record.items.map(parseGameListItemRecord),
    pagination: {
      page: positiveInteger(pagination.page, "pagination.page"),
      page_size: positiveInteger(pagination.page_size, "pagination.page_size"),
      total: nonNegativeInteger(pagination.total, "pagination.total"),
      pages: nonNegativeInteger(pagination.pages, "pagination.pages"),
    },
  };
}

export function parseAdminGameDetail(value: unknown): AdminGameDetail {
  rejectSensitiveFields(value);
  const record = recordValue(value);
  for (const forbidden of ["debug", "game_error", "run_errors"]) {
    if (forbidden in record) {
      throw invalidContract(
        `${forbidden} 必须通过独立的受限诊断接口读取`,
      );
    }
  }
  const base = parseGameListItemRecord(record);
  const players = arrayValue(record.players, "players").map(parsePlayer);
  const rounds = arrayValue(record.rounds, "rounds").map(parseRound);
  const recentEvents = arrayValue(record.recent_events, "recent_events").map(
    parseEvent,
  );
  const diagnostics = parseDiagnostics(record.diagnostics);
  const runs = arrayValue(record.runs, "runs").map(parseRun);
  if (
    rounds.some((round) =>
      [...round.night_deaths, ...round.day_deaths].some(
        (death) => death.cause !== null || death.source !== null,
      ),
    )
  ) {
    throw invalidContract("普通对局详情不得公开内部死亡原因或来源");
  }
  if (base.status !== "complete" || base.resumable) {
    if (base.winner !== null) {
      throw invalidContract("未完成或可恢复对局不得公开胜方");
    }
    if (players.some((player) => player.role !== null || player.model !== null)) {
      throw invalidContract("未完成或可恢复对局不得公开玩家角色或模型");
    }
    if (recentEvents.length > 0 || diagnostics.last_event !== null) {
      throw invalidContract("未完成或可恢复对局不得公开事件元数据");
    }
    if (
      [base.latest_run, ...runs].some(
        (run) =>
          run !== null &&
          (run.villager_model !== null || run.werewolf_model !== null),
      )
    ) {
      throw invalidContract("未完成或可恢复对局不得公开运行模型");
    }
    if (rounds.some((round) => !round.success)) {
      throw invalidContract("未完成或可恢复对局不得返回未完成轮次");
    }
  }
  return {
    ...base,
    players,
    rounds,
    runs,
    recent_events: recentEvents,
    diagnostics,
    p2_quality: parseAdminGameP2Quality(record.p2_quality),
  };
}

export function parseAdminGameDebug(value: unknown): AdminGameDebug {
  rejectSensitiveFields(value);
  const record = recordValue(value);
  return {
    session_id: requiredString(record.session_id, "debug.session_id"),
    game_error: nullableString(record.game_error, "debug.game_error"),
    run_errors: arrayValue(record.run_errors, "debug.run_errors").map(
      (item) => {
        const error = recordValue(item);
        return {
          run_id: requiredString(error.run_id, "debug.run_error.run_id"),
          error: requiredString(error.error, "debug.run_error.error"),
        };
      },
    ),
  };
}

function parseGameListItemRecord(value: unknown): AdminGameListItem {
  const record = recordValue(value);
  const status = enumValue(record.status, SESSION_STATUSES, "status");
  const item: AdminGameListItem = {
    session_id: requiredString(record.session_id, "session_id"),
    status,
    winner: nullableString(record.winner, "winner"),
    round_count: nonNegativeInteger(record.round_count, "round_count"),
    resumable: booleanValue(record.resumable, "resumable"),
    rule_set:
      record.rule_set === null ? null : parseRuleSet(record.rule_set),
    created_at: dateString(record.created_at, "created_at"),
    updated_at: dateString(record.updated_at, "updated_at"),
    latest_run:
      record.latest_run === null ? null : parseRun(record.latest_run),
  };
  if (
    (item.status !== "complete" || item.resumable) &&
    item.winner !== null
  ) {
    throw invalidContract("未完成或可恢复对局不得公开胜方");
  }
  if (
    (item.status !== "complete" || item.resumable) &&
    item.latest_run !== null &&
    (item.latest_run.villager_model !== null ||
      item.latest_run.werewolf_model !== null)
  ) {
    throw invalidContract("未完成或可恢复对局不得公开最新运行模型");
  }
  return item;
}

function parseRuleSet(value: unknown): AdminGameRuleSet {
  const record = recordValue(value);
  return {
    id: stringValue(record.id, "rule_set.id"),
    name: requiredString(record.name, "rule_set.name"),
    player_count: nullableNonNegativeInteger(
      record.player_count,
      "rule_set.player_count",
    ),
  };
}

function parseRun(value: unknown): AdminGameRun {
  const record = recordValue(value);
  return {
    run_id: requiredString(record.run_id, "run.run_id"),
    status: enumValue(record.status, RUN_STATUSES, "run.status"),
    villager_model: nullableString(
      record.villager_model,
      "run.villager_model",
    ),
    werewolf_model: nullableString(
      record.werewolf_model,
      "run.werewolf_model",
    ),
    max_rounds: nonNegativeInteger(record.max_rounds, "run.max_rounds"),
    created_at: dateString(record.created_at, "run.created_at"),
    started_at: nullableDateString(record.started_at, "run.started_at"),
    completed_at: nullableDateString(
      record.completed_at,
      "run.completed_at",
    ),
    event_count: nonNegativeInteger(record.event_count, "run.event_count"),
    has_error: booleanValue(record.has_error, "run.has_error"),
  };
}

function parsePlayer(value: unknown): AdminGamePlayer {
  const record = recordValue(value);
  return {
    seat: positiveInteger(record.seat, "player.seat"),
    name: requiredString(record.name, "player.name"),
    profile_id: nullableString(record.profile_id, "player.profile_id"),
    model: nullableString(record.model, "player.model"),
    role: nullableString(record.role, "player.role"),
    personality_id: stringValue(record.personality_id, "player.personality_id"),
    appearance_id: stringValue(record.appearance_id, "player.appearance_id"),
    avatar_image_url: stringValue(
      record.avatar_image_url,
      "player.avatar_image_url",
    ),
    tags: stringArray(record.tags, "player.tags"),
  };
}

function parseRound(value: unknown): AdminGameRound {
  const record = recordValue(value);
  return {
    number: nonNegativeInteger(record.number, "round.number"),
    success: booleanValue(record.success, "round.success"),
    players: stringArray(record.players, "round.players"),
    public_summary: stringValue(record.public_summary, "round.public_summary"),
    night_deaths: deathArray(record.night_deaths, "round.night_deaths"),
    day_deaths: deathArray(record.day_deaths, "round.day_deaths"),
    exiled: nullableString(record.exiled, "round.exiled"),
    hunter_shot: nullableString(record.hunter_shot, "round.hunter_shot"),
    idiot_revealed: nullableString(
      record.idiot_revealed,
      "round.idiot_revealed",
    ),
    sheriff: nullableString(record.sheriff, "round.sheriff"),
    votes: stringRecord(record.votes, "round.votes"),
    sheriff_elected: nullableString(
      record.sheriff_elected,
      "round.sheriff_elected",
    ),
    werewolf_self_exploded: nullableString(
      record.werewolf_self_exploded,
      "round.werewolf_self_exploded",
    ),
  };
}

function parseEvent(value: unknown): AdminGameEvent {
  const record = recordValue(value);
  return {
    run_id: requiredString(record.run_id, "event.run_id"),
    event_id: nonNegativeInteger(record.event_id, "event.event_id"),
    type: requiredString(record.type, "event.type"),
    round: nullableNonNegativeInteger(record.round, "event.round"),
    phase: nullableString(record.phase, "event.phase"),
    actor: nullableString(record.actor, "event.actor"),
    action: nullableString(record.action, "event.action"),
    created_at: dateString(record.created_at, "event.created_at"),
  };
}

function parseDiagnostics(value: unknown): AdminGameDiagnostics {
  const record = recordValue(value);
  return {
    run_count: nonNegativeInteger(record.run_count, "diagnostics.run_count"),
    event_count: nonNegativeInteger(
      record.event_count,
      "diagnostics.event_count",
    ),
    failed_voice_count: nonNegativeInteger(
      record.failed_voice_count,
      "diagnostics.failed_voice_count",
    ),
    last_event:
      record.last_event === null ? null : parseEvent(record.last_event),
  };
}

function deathArray(value: unknown, field: string) {
  return arrayValue(value, field).map((item) => {
    const record = recordValue(item);
    return {
      player: requiredString(record.player, `${field}.player`),
      cause: nullableString(record.cause, `${field}.cause`),
      source: nullableString(record.source, `${field}.source`),
    };
  });
}

function rejectSensitiveFields(value: unknown, path = "response") {
  if (Array.isArray(value)) {
    value.forEach((item, index) =>
      rejectSensitiveFields(item, `${path}[${index}]`),
    );
    return;
  }
  if (typeof value !== "object" || value === null) {
    return;
  }
  Object.entries(value as Record<string, unknown>).forEach(([key, child]) => {
    const normalized = key.toLowerCase();
    if (
      SENSITIVE_RESPONSE_KEYS.has(normalized) ||
      normalized.endsWith("_key") ||
      normalized.endsWith("_token") ||
      normalized.endsWith("_secret")
    ) {
      throw invalidContract(`${path}.${key} 不允许出现在后台对局响应中`);
    }
    rejectSensitiveFields(child, `${path}.${key}`);
  });
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
  if (!parsed) {
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
  if (value === null) {
    return null;
  }
  return stringValue(value, field);
}

function stringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    throw invalidContract(`${field} 不是字符串数组`);
  }
  return [...value];
}

function stringRecord(value: unknown, field: string): Record<string, string> {
  const record = recordValue(value);
  if (!Object.values(record).every((item) => typeof item === "string")) {
    throw invalidContract(`${field} 不是字符串映射`);
  }
  return { ...record } as Record<string, string>;
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

function nullableNonNegativeInteger(
  value: unknown,
  field: string,
): number | null {
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
      title: "对局接口响应无效",
      status: 502,
      detail,
      code: "admin_invalid_game_response",
      request_id: null,
    },
  });
}
