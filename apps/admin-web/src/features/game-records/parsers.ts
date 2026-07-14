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
  AdminGameQualityEvaluation,
  AdminGameQualityIssues,
  AdminGameQualityRetry,
  AdminQualityDataStatus,
  AdminQualityEvaluationStatus,
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
const QUALITY_EVALUATION_STATUSES: AdminQualityEvaluationStatus[] = [
  "not_scheduled", "pending", "processing", "completed", "failed", "superseded",
];
const QUALITY_DATA_STATUSES: AdminQualityDataStatus[] = [
  "collecting", "available", "partial", "legacy", "unavailable",
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
    quality_evaluation: parseAdminGameQualityEvaluation(
      record.quality_evaluation,
    ),
  };
}

export function parseAdminGameQualityEvaluation(
  value: unknown,
): AdminGameQualityEvaluation {
  rejectSensitiveFields(value, "quality_evaluation");
  const record = recordValue(value);
  const coverage = recordValue(record.source_coverage);
  const issueCounts = recordValue(record.issue_counts);
  const facts = recordValue(record.facts);
  const structure = recordValue(record.structure);
  const voice = recordValue(record.voice);
  const performance = recordValue(record.performance);
  const content = recordValue(record.content);
  if (record.schema_version !== 1) {
    throw invalidContract("quality_evaluation.schema_version 不受支持");
  }
  return {
    schema_version: 1,
    evaluator_version: requiredString(record.evaluator_version, "quality_evaluation.evaluator_version"),
    evaluation_status: enumValue(record.evaluation_status, QUALITY_EVALUATION_STATUSES, "quality_evaluation.evaluation_status"),
    data_status: enumValue(record.data_status, QUALITY_DATA_STATUSES, "quality_evaluation.data_status"),
    verdict: enumValue(record.verdict, ["pass", "warn", "fail", "unavailable"] as const, "quality_evaluation.verdict"),
    source_coverage: {
      state: requiredString(coverage.state, "quality_evaluation.source_coverage.state"),
      logs: requiredString(coverage.logs, "quality_evaluation.source_coverage.logs"),
      events: requiredString(coverage.events, "quality_evaluation.source_coverage.events"),
      voice: requiredString(coverage.voice, "quality_evaluation.source_coverage.voice"),
      subtitles: requiredString(coverage.subtitles, "quality_evaluation.source_coverage.subtitles"),
      pending_voice_count: nonNegativeInteger(coverage.pending_voice_count, "quality_evaluation.source_coverage.pending_voice_count"),
      failed_voice_count: nonNegativeInteger(coverage.failed_voice_count, "quality_evaluation.source_coverage.failed_voice_count"),
    },
    issue_counts: {
      P0: nonNegativeInteger(issueCounts.P0, "quality_evaluation.issue_counts.P0"),
      P1: nonNegativeInteger(issueCounts.P1, "quality_evaluation.issue_counts.P1"),
      P2: nonNegativeInteger(issueCounts.P2, "quality_evaluation.issue_counts.P2"),
    },
    facts: {
      critical_opportunity_count: nonNegativeInteger(facts.critical_opportunity_count, "quality_evaluation.facts.critical_opportunity_count"),
      critical_recorded_count: nonNegativeInteger(facts.critical_recorded_count, "quality_evaluation.facts.critical_recorded_count"),
      critical_fact_write_rate: nullableRate(facts.critical_fact_write_rate, "quality_evaluation.facts.critical_fact_write_rate"),
      prompt_expected_critical_count: nonNegativeInteger(facts.prompt_expected_critical_count, "quality_evaluation.facts.prompt_expected_critical_count"),
      prompt_included_critical_count: nonNegativeInteger(facts.prompt_included_critical_count, "quality_evaluation.facts.prompt_included_critical_count"),
      prompt_missing_critical_count: nonNegativeInteger(facts.prompt_missing_critical_count, "quality_evaluation.facts.prompt_missing_critical_count"),
      critical_fact_prompt_coverage_rate: nullableRate(facts.critical_fact_prompt_coverage_rate, "quality_evaluation.facts.critical_fact_prompt_coverage_rate"),
      deterministic_contradiction_count: nonNegativeInteger(facts.deterministic_contradiction_count, "quality_evaluation.facts.deterministic_contradiction_count"),
    },
    structure: {
      max_consecutive_self_explosions: nonNegativeInteger(structure.max_consecutive_self_explosions, "quality_evaluation.structure.max_consecutive_self_explosions"),
      chain_three_count: nonNegativeInteger(structure.chain_three_count, "quality_evaluation.structure.chain_three_count"),
      normal_day_debate_round_count: nonNegativeInteger(structure.normal_day_debate_round_count, "quality_evaluation.structure.normal_day_debate_round_count"),
      sheriff_model_request_count: nonNegativeInteger(structure.sheriff_model_request_count, "quality_evaluation.structure.sheriff_model_request_count"),
      public_model_request_count: nonNegativeInteger(structure.public_model_request_count, "quality_evaluation.structure.public_model_request_count"),
      sheriff_model_request_rate: nullableRate(structure.sheriff_model_request_rate, "quality_evaluation.structure.sheriff_model_request_rate"),
    },
    voice: {
      narratable_event_count: nonNegativeInteger(voice.narratable_event_count, "quality_evaluation.voice.narratable_event_count"),
      effective_voice_event_count: nonNegativeInteger(voice.effective_voice_event_count, "quality_evaluation.voice.effective_voice_event_count"),
      missing_narratable_event_count: nonNegativeInteger(voice.missing_narratable_event_count, "quality_evaluation.voice.missing_narratable_event_count"),
      voice_coverage_rate: nullableRate(voice.voice_coverage_rate, "quality_evaluation.voice.voice_coverage_rate"),
      voice_source_event_lag: nullableNonNegativeInteger(voice.voice_source_event_lag, "quality_evaluation.voice.voice_source_event_lag"),
      terminal_judge_voice_coverage: nullableBoolean(voice.terminal_judge_voice_coverage, "quality_evaluation.voice.terminal_judge_voice_coverage"),
      pending_voice_count: nonNegativeInteger(voice.pending_voice_count, "quality_evaluation.voice.pending_voice_count"),
      failed_voice_count: nonNegativeInteger(voice.failed_voice_count, "quality_evaluation.voice.failed_voice_count"),
      interruption_count: nonNegativeInteger(voice.interruption_count, "quality_evaluation.voice.interruption_count"),
      replay_count: nonNegativeInteger(voice.replay_count, "quality_evaluation.voice.replay_count"),
    },
    performance: {
      action_count: nonNegativeInteger(performance.action_count, "quality_evaluation.performance.action_count"),
      action_duration_ms_max: nullableNonNegativeInteger(performance.action_duration_ms_max, "quality_evaluation.performance.action_duration_ms_max"),
      action_duration_p95_ms: nullableNonNegativeInteger(performance.action_duration_p95_ms, "quality_evaluation.performance.action_duration_p95_ms"),
      first_token_count: nonNegativeInteger(performance.first_token_count, "quality_evaluation.performance.first_token_count"),
      first_token_ms_max: nullableNonNegativeInteger(performance.first_token_ms_max, "quality_evaluation.performance.first_token_ms_max"),
      first_token_p95_ms: nullableNonNegativeInteger(performance.first_token_p95_ms, "quality_evaluation.performance.first_token_p95_ms"),
      game_duration_ms: nullableNonNegativeInteger(performance.game_duration_ms, "quality_evaluation.performance.game_duration_ms"),
      timeout_count: nonNegativeInteger(performance.timeout_count, "quality_evaluation.performance.timeout_count"),
      retry_count: nonNegativeInteger(performance.retry_count, "quality_evaluation.performance.retry_count"),
      fallback_count: nonNegativeInteger(performance.fallback_count, "quality_evaluation.performance.fallback_count"),
    },
    content: {
      speech_check_count: nonNegativeInteger(content.speech_check_count, "quality_evaluation.content.speech_check_count"),
      repeated_speech_count: nonNegativeInteger(content.repeated_speech_count, "quality_evaluation.content.repeated_speech_count"),
      repeated_speech_rate: nullableRate(content.repeated_speech_rate, "quality_evaluation.content.repeated_speech_rate"),
      speech_rewrite_count: nonNegativeInteger(content.speech_rewrite_count, "quality_evaluation.content.speech_rewrite_count"),
      speech_rewrite_recovered_count: nonNegativeInteger(content.speech_rewrite_recovered_count, "quality_evaluation.content.speech_rewrite_recovered_count"),
      speech_retry_exhausted_count: nonNegativeInteger(content.speech_retry_exhausted_count, "quality_evaluation.content.speech_retry_exhausted_count"),
      privacy_p0_issue_count: nonNegativeInteger(content.privacy_p0_issue_count, "quality_evaluation.content.privacy_p0_issue_count"),
      lineup_warning_count: nonNegativeInteger(content.lineup_warning_count, "quality_evaluation.content.lineup_warning_count"),
    },
    evaluated_at: nullableDateString(record.evaluated_at, "quality_evaluation.evaluated_at"),
  };
}

export function parseAdminGameQualityIssues(value: unknown): AdminGameQualityIssues {
  rejectSensitiveFields(value, "quality_issues");
  const record = recordValue(value);
  return {
    session_id: requiredString(record.session_id, "quality_issues.session_id"),
    evaluation_id: nullableString(record.evaluation_id, "quality_issues.evaluation_id"),
    items: arrayValue(record.items, "quality_issues.items").map((value) => {
      const issue = recordValue(value);
      return {
        issue_id: requiredString(issue.issue_id, "quality_issue.issue_id"),
        code: requiredString(issue.code, "quality_issue.code"),
        severity: enumValue(issue.severity, ["P0", "P1", "P2"] as const, "quality_issue.severity"),
        channel: requiredString(issue.channel, "quality_issue.channel"),
        round_number: nullableNonNegativeInteger(issue.round_number, "quality_issue.round_number"),
        event_id: nullableNonNegativeInteger(issue.event_id, "quality_issue.event_id"),
        utterance_id: nullableString(issue.utterance_id, "quality_issue.utterance_id"),
        first_detected_at: dateString(issue.first_detected_at, "quality_issue.first_detected_at"),
      };
    }),
  };
}

export function parseAdminGameQualityRetry(value: unknown): AdminGameQualityRetry {
  rejectSensitiveFields(value, "quality_retry");
  const record = recordValue(value);
  return {
    session_id: requiredString(record.session_id, "quality_retry.session_id"),
    evaluation_id: requiredString(record.evaluation_id, "quality_retry.evaluation_id"),
    status: enumValue(record.status, ["pending"] as const, "quality_retry.status"),
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
    const isQualityCoverageStatus =
      path.endsWith("quality_evaluation.source_coverage") &&
      (normalized === "state" || normalized === "logs");
    if (
      (SENSITIVE_RESPONSE_KEYS.has(normalized) && !isQualityCoverageStatus) ||
      normalized === "text" ||
      normalized.endsWith("_text") ||
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

function nullableBoolean(value: unknown, field: string): boolean | null {
  return value === null ? null : booleanValue(value, field);
}

function nullableRate(value: unknown, field: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw invalidContract(`${field} 不是 0 到 1 的比率`);
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
