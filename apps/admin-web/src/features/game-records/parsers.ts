import { AdminApiError } from "@/api/problem-details";
import { parseAdminGameP2Quality } from "@/features/p2-quality/parsers";
import type {
  AdminGameDebug,
  AdminGameDetail,
  AdminGameDiagnostics,
  AdminGameEvent,
  AdminGameList,
  AdminGameListItem,
  AdminGameModelRequestDetail,
  AdminGameModelRequestList,
  AdminGameModelRequestSummary,
  AdminGameModelRequestStatus,
  AdminGamePlayer,
  AdminGameRound,
  AdminGameRuleSet,
  AdminGameRun,
  AdminGameQualityEvaluation,
  AdminGameQualityCriticalAction,
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
  "not_scheduled", "pending", "queued", "processing", "running", "completed", "failed", "superseded",
];
const QUALITY_DATA_STATUSES: AdminQualityDataStatus[] = [
  "collecting", "available", "partial", "legacy", "unavailable",
];
const CRITICAL_ACTION_ORIGINS = [
  "canceled", "failed", "model_after_retry", "model_first_attempt", "rule_default", "state_machine", "system_fallback", "system_timeout",
] as const;
const CRITICAL_INPUT_COMPLETENESS = [
  "complete", "critical_public_fact_missing", "private_observation_missing", "rule_missing", "unknown",
] as const;
const CRITICAL_ACTION_LEGALITY = [
  "invalid_normalized", "invalid_not_executed", "invalid_system_fallback", "legal_but_canceled", "legal_executed", "legal_system_result", "not_executed", "unknown",
] as const;
const CRITICAL_REASONING_OBSERVATIONS = [
  "hard_rule_conflict", "identity_information_conflict", "internal_logic_contradiction", "not_assessed", "not_available", "used_unspecified_rule",
] as const;
const CRITICAL_DIRECT_IMPACTS = [
  "canceled_no_effect", "failed_no_effect", "game_state_effect_applied", "model_result_applied", "no_state_change", "phase_ended", "system_result_applied", "vote_recorded",
] as const;
const CRITICAL_ATTRIBUTIONS = [
  "canceled", "model_internal_logic_contradiction", "model_judgment_and_rule_input_gap", "model_reasoning_error", "not_determined", "runtime_fallback",
] as const;
const CRITICAL_COVERAGE_STATUSES = ["complete", "partial", "missing", "unknown"] as const;
const MODEL_REQUEST_STATUSES: AdminGameModelRequestStatus[] = [
  "pending",
  "completed",
  "failed",
  "response_missing",
];
const MODEL_REQUEST_SUMMARY_KEYS = [
  "request_id",
  "round_number",
  "phase",
  "actor",
  "action",
  "model",
  "status",
  "attempt_count",
  "invalid_attempt_count",
  "run_id",
  "event_id",
  "created_at",
] as const;
const MODEL_REQUEST_DETAIL_KEYS = [
  ...MODEL_REQUEST_SUMMARY_KEYS,
  "prompt",
  "raw_response",
  "parsed_output",
  "raw_choice",
  "error",
] as const;
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
    if (players.some((player) => player.role !== null)) {
      throw invalidContract("未完成或可恢复对局不得公开玩家角色");
    }
    if (recentEvents.length > 0 || diagnostics.last_event !== null) {
      throw invalidContract("未完成或可恢复对局不得公开事件元数据");
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
  const liveness = parseQualityLiveness(record.liveness);
  if (record.schema_version !== 1) {
    throw invalidContract("quality_evaluation.schema_version 不受支持");
  }
  return {
    schema_version: 1,
    evaluator_version: requiredString(record.evaluator_version, "quality_evaluation.evaluator_version"),
    evaluation_status: enumValue(record.evaluation_status, QUALITY_EVALUATION_STATUSES, "quality_evaluation.evaluation_status"),
    ...optionalQualityTaskFields(record),
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
    liveness,
    critical_actions: parseQualityCriticalActions(record.critical_actions),
    evaluated_at: nullableDateString(record.evaluated_at, "quality_evaluation.evaluated_at"),
  };
}

function parseQualityLiveness(
  value: unknown,
): AdminGameQualityEvaluation["liveness"] {
  if (value === undefined) {
    return emptyQualityLiveness();
  }
  const raw = recordValue(value);
  const featureModes = recordValue(raw.feature_modes);
  const actorMind = recordValue(raw.actor_mind);
  return {
    experience_revision: nullableString(raw.experience_revision, "quality_evaluation.liveness.experience_revision"),
    experiment_id: nullableString(raw.experiment_id, "quality_evaluation.liveness.experiment_id"),
    variant: nullableString(raw.variant, "quality_evaluation.liveness.variant"),
    feature_modes: {
      style_gate: optionalEnumValue(featureModes.style_gate, ["legacy", "async_observe"] as const, "quality_evaluation.liveness.feature_modes.style_gate"),
      actor_mind: optionalEnumValue(featureModes.actor_mind, ["off", "shadow", "read"] as const, "quality_evaluation.liveness.feature_modes.actor_mind"),
      sentence_stream: optionalEnumValue(
        featureModes.sentence_stream,
        ["off", "committed_segments", "committed_segments_v2"] as const,
        "quality_evaluation.liveness.feature_modes.sentence_stream",
      ),
      affect_delivery: optionalEnumValue(featureModes.affect_delivery, ["off", "shadow", "on"] as const, "quality_evaluation.liveness.feature_modes.affect_delivery"),
      tts_prefetch_depth: optionalEnumValue(featureModes.tts_prefetch_depth, [0, 1] as const, "quality_evaluation.liveness.feature_modes.tts_prefetch_depth"),
      voice_preempt: optionalEnumValue(featureModes.voice_preempt, ["off", "deterministic"] as const, "quality_evaluation.liveness.feature_modes.voice_preempt"),
    },
    public_speech_count: nonNegativeInteger(raw.public_speech_count, "quality_evaluation.liveness.public_speech_count"),
    timing_coverage: parseTimingCoverageRecord(raw.timing_coverage),
    stage_latency_ms: parseLatencyRecord(raw.stage_latency_ms),
    prompt_chars: parseLatencySummary(raw.prompt_chars, "quality_evaluation.liveness.prompt_chars"),
    hard_gate_duration_ms: parseLatencySummary(raw.hard_gate_duration_ms, "quality_evaluation.liveness.hard_gate_duration_ms"),
    hard_retry_count: nonNegativeInteger(raw.hard_retry_count, "quality_evaluation.liveness.hard_retry_count"),
    hard_retry_rate: nullableRate(raw.hard_retry_rate, "quality_evaluation.liveness.hard_retry_rate"),
    hard_exhausted_count: nonNegativeInteger(raw.hard_exhausted_count, "quality_evaluation.liveness.hard_exhausted_count"),
    hard_exhausted_rate: nullableRate(raw.hard_exhausted_rate, "quality_evaluation.liveness.hard_exhausted_rate"),
    partial_speech_count: nonNegativeInteger(raw.partial_speech_count, "quality_evaluation.liveness.partial_speech_count"),
    interrupted_speech_count: nonNegativeInteger(raw.interrupted_speech_count, "quality_evaluation.liveness.interrupted_speech_count"),
    voice_timing_coverage: parseCountRecord(raw.voice_timing_coverage, "quality_evaluation.liveness.voice_timing_coverage"),
    tts_to_first_audio_ms: parseLatencySummary(raw.tts_to_first_audio_ms, "quality_evaluation.liveness.tts_to_first_audio_ms"),
    turn_to_first_audio_ms: parseLatencySummary(raw.turn_to_first_audio_ms, "quality_evaluation.liveness.turn_to_first_audio_ms"),
    voice_status_counts: parseCountRecord(raw.voice_status_counts, "quality_evaluation.liveness.voice_status_counts"),
    playback_timing_coverage: parseCountRecord(raw.playback_timing_coverage, "quality_evaluation.liveness.playback_timing_coverage"),
    playback_status_counts: parseCountRecord(raw.playback_status_counts, "quality_evaluation.liveness.playback_status_counts"),
    speaker_gap_ms: parseLatencySummary(raw.speaker_gap_ms, "quality_evaluation.liveness.speaker_gap_ms"),
    actor_mind: {
      snapshot_count: nonNegativeInteger(actorMind.snapshot_count, "quality_evaluation.liveness.actor_mind.snapshot_count"),
      update_count: nonNegativeInteger(actorMind.update_count, "quality_evaluation.liveness.actor_mind.update_count"),
      source_complete_count: nonNegativeInteger(actorMind.source_complete_count, "quality_evaluation.liveness.actor_mind.source_complete_count"),
    },
  };
}

function emptyQualityLiveness(): AdminGameQualityEvaluation["liveness"] {
  const emptyLatency = { count: 0, p50: null, p95: null, max: null };
  return {
    experience_revision: null,
    experiment_id: null,
    variant: null,
    feature_modes: {},
    public_speech_count: 0,
    timing_coverage: {},
    stage_latency_ms: {},
    prompt_chars: { ...emptyLatency },
    hard_gate_duration_ms: { ...emptyLatency },
    hard_retry_count: 0,
    hard_retry_rate: null,
    hard_exhausted_count: 0,
    hard_exhausted_rate: null,
    partial_speech_count: 0,
    interrupted_speech_count: 0,
    voice_timing_coverage: {},
    tts_to_first_audio_ms: { ...emptyLatency },
    turn_to_first_audio_ms: { ...emptyLatency },
    voice_status_counts: {},
    playback_timing_coverage: {},
    playback_status_counts: {},
    speaker_gap_ms: { ...emptyLatency },
    actor_mind: { snapshot_count: 0, update_count: 0, source_complete_count: 0 },
  };
}

function parseLatencySummary(value: unknown, path: string) {
  const raw = recordValue(value);
  return {
    count: nonNegativeInteger(raw.count, `${path}.count`),
    p50: nullableNonNegativeInteger(raw.p50, `${path}.p50`),
    p95: nullableNonNegativeInteger(raw.p95, `${path}.p95`),
    max: nullableNonNegativeInteger(raw.max, `${path}.max`),
  };
}

function parseLatencyRecord(value: unknown) {
  const raw = recordValue(value);
  return Object.fromEntries(
    Object.entries(raw).map(([key, item]) => [
      key,
      parseLatencySummary(item, `quality_evaluation.liveness.stage_latency_ms.${key}`),
    ]),
  );
}

function parseTimingCoverageRecord(value: unknown) {
  const raw = recordValue(value);
  return Object.fromEntries(
    Object.entries(raw).map(([key, item]) => {
      const coverage = recordValue(item);
      const path = `quality_evaluation.liveness.timing_coverage.${key}`;
      return [key, {
        count: nonNegativeInteger(coverage.count, `${path}.count`),
        denominator: nonNegativeInteger(coverage.denominator, `${path}.denominator`),
        rate: nullableRate(coverage.rate, `${path}.rate`),
      }];
    }),
  );
}

function parseCountRecord(value: unknown, path: string): Record<string, number> {
  const raw = recordValue(value);
  return Object.fromEntries(
    Object.entries(raw).map(([key, item]) => [
      key,
      nonNegativeInteger(item, `${path}.${key}`),
    ]),
  );
}

function optionalEnumValue<T extends string | number>(
  value: unknown,
  allowed: readonly T[],
  field: string,
): T | null | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (value === null) {
    return null;
  }
  return enumValue(value, allowed, field);
}

function parseQualityCriticalActions(
  value: unknown,
): AdminGameQualityCriticalAction[] {
  const items = arrayValue(value, "quality_evaluation.critical_actions");
  if (items.length > 64) {
    throw invalidContract("quality_evaluation.critical_actions 超过 64 条");
  }
  const seenActionIds = new Set<string>();
  return items.map((value, index) => {
    const path = `quality_evaluation.critical_actions[${index}]`;
    const record = recordValue(value);
    rejectUnexpectedKeys(
      record,
      [
        "schema_version", "action_id", "round_number", "action", "action_origin",
        "input_completeness", "action_legality", "reasoning_observation",
        "direct_impact", "attribution", "clause_ids", "coverage",
      ],
      path,
    );
    if (record.schema_version !== 1) {
      throw invalidContract(`${path}.schema_version 不受支持`);
    }
    const actionId = patternString(
      record.action_id,
      /^[A-Za-z0-9_-]{1,80}$/,
      `${path}.action_id`,
    );
    if (seenActionIds.has(actionId)) {
      throw invalidContract(`${path}.action_id 重复`);
    }
    seenActionIds.add(actionId);
    const clauseIds = criticalClauseIds(record.clause_ids, `${path}.clause_ids`);
    const coverage = recordValue(record.coverage);
    rejectUnexpectedKeys(
      coverage,
      [
        "schema_version", "status", "required_count", "included_count",
        "missing_count", "missing_clause_ids",
      ],
      `${path}.coverage`,
    );
    if (coverage.schema_version !== 1) {
      throw invalidContract(`${path}.coverage.schema_version 不受支持`);
    }
    const coverageStatus = enumValue(
      coverage.status,
      CRITICAL_COVERAGE_STATUSES,
      `${path}.coverage.status`,
    );
    const requiredCount = boundedNonNegativeInteger(
      coverage.required_count,
      16,
      `${path}.coverage.required_count`,
    );
    const includedCount = boundedNonNegativeInteger(
      coverage.included_count,
      16,
      `${path}.coverage.included_count`,
    );
    const missingCount = boundedNonNegativeInteger(
      coverage.missing_count,
      16,
      `${path}.coverage.missing_count`,
    );
    const missingClauseIds = criticalClauseIds(
      coverage.missing_clause_ids,
      `${path}.coverage.missing_clause_ids`,
    );
    const coverageShapeIsValid =
      requiredCount === clauseIds.length &&
      missingCount === missingClauseIds.length &&
      missingClauseIds.every((clauseId) => clauseIds.includes(clauseId)) &&
      ({
        complete: includedCount === requiredCount && missingCount === 0,
        partial: includedCount > 0 && missingCount > 0 && includedCount + missingCount === requiredCount,
        missing: requiredCount > 0 && includedCount === 0 && missingCount === requiredCount,
        unknown: includedCount === 0 && missingCount === 0,
      })[coverageStatus];
    if (!coverageShapeIsValid) {
      throw invalidContract(`${path}.coverage 计数关系无效`);
    }
    return {
      schema_version: 1,
      action_id: actionId,
      round_number: nullableBoundedNonNegativeInteger(
        record.round_number,
        1_000_000,
        `${path}.round_number`,
      ),
      action: patternString(
        record.action,
        /^[a-z][a-z0-9_]{0,63}$/,
        `${path}.action`,
      ),
      action_origin: enumValue(record.action_origin, CRITICAL_ACTION_ORIGINS, `${path}.action_origin`),
      input_completeness: enumValue(record.input_completeness, CRITICAL_INPUT_COMPLETENESS, `${path}.input_completeness`),
      action_legality: enumValue(record.action_legality, CRITICAL_ACTION_LEGALITY, `${path}.action_legality`),
      reasoning_observation: enumValue(record.reasoning_observation, CRITICAL_REASONING_OBSERVATIONS, `${path}.reasoning_observation`),
      direct_impact: enumValue(record.direct_impact, CRITICAL_DIRECT_IMPACTS, `${path}.direct_impact`),
      attribution: enumValue(record.attribution, CRITICAL_ATTRIBUTIONS, `${path}.attribution`),
      clause_ids: clauseIds,
      coverage: {
        schema_version: 1,
        status: coverageStatus,
        required_count: requiredCount,
        included_count: includedCount,
        missing_count: missingCount,
        missing_clause_ids: missingClauseIds,
      },
    };
  });
}

function criticalClauseIds(value: unknown, field: string): string[] {
  const values = stringArray(value, field);
  if (values.length > 16) {
    throw invalidContract(`${field} 超过 16 条`);
  }
  const clauses = values.map((item, index) =>
    patternString(item, /^[a-z0-9_.-]{1,120}$/, `${field}[${index}]`),
  );
  if (new Set(clauses).size !== clauses.length) {
    throw invalidContract(`${field} 包含重复条目`);
  }
  return clauses;
}

function optionalQualityTaskFields(
  record: Record<string, unknown>,
): Partial<AdminGameQualityEvaluation> {
  const parsed: Partial<AdminGameQualityEvaluation> = {};
  if ("source_revision" in record) {
    parsed.source_revision =
      record.source_revision === null
        ? null
        : requiredString(
            record.source_revision,
            "quality_evaluation.source_revision",
          );
  }
  if ("created_at" in record) {
    parsed.created_at = nullableDateString(
      record.created_at,
      "quality_evaluation.created_at",
    );
  }
  if ("started_at" in record) {
    parsed.started_at = nullableDateString(
      record.started_at,
      "quality_evaluation.started_at",
    );
  }
  if ("completed_at" in record) {
    parsed.completed_at = nullableDateString(
      record.completed_at,
      "quality_evaluation.completed_at",
    );
  }
  if ("attempt_count" in record) {
    parsed.attempt_count = nonNegativeInteger(
      record.attempt_count,
      "quality_evaluation.attempt_count",
    );
  }
  if ("failure_reason" in record) {
    parsed.failure_reason = nullableString(
      record.failure_reason,
      "quality_evaluation.failure_reason",
    );
  }
  if ("can_retry" in record) {
    parsed.can_retry = booleanValue(
      record.can_retry,
      "quality_evaluation.can_retry",
    );
  }
  if ("latest_successful_result" in record) {
    if (record.latest_successful_result === null) {
      parsed.latest_successful_result = null;
    } else {
      const latest = recordValue(record.latest_successful_result);
      parsed.latest_successful_result = {
        evaluator_version: requiredString(
          latest.evaluator_version,
          "quality_evaluation.latest_successful_result.evaluator_version",
        ),
        source_revision: requiredString(
          latest.source_revision,
          "quality_evaluation.latest_successful_result.source_revision",
        ),
        completed_at: dateString(
          latest.completed_at,
          "quality_evaluation.latest_successful_result.completed_at",
        ),
      };
    }
  }
  return parsed;
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

export function parseAdminGameModelRequestList(
  value: unknown,
): AdminGameModelRequestList {
  const record = recordValue(value);
  rejectUnexpectedKeys(record, ["session_id", "items"], "model_requests");
  const items = arrayValue(record.items, "model_requests.items");
  if (items.length > 1000) {
    throw invalidContract("model_requests.items 超过 1000 条上限");
  }
  return {
    session_id: requiredString(record.session_id, "model_requests.session_id"),
    items: items.map((item, index) => {
      const summary = recordValue(item);
      rejectUnexpectedKeys(
        summary,
        MODEL_REQUEST_SUMMARY_KEYS,
        `model_requests.items.${index}`,
      );
      return parseModelRequestSummary(summary, `model_requests.items.${index}`);
    }),
  };
}

export function parseAdminGameModelRequestDetail(
  value: unknown,
): AdminGameModelRequestDetail {
  const record = recordValue(value);
  rejectUnexpectedKeys(record, MODEL_REQUEST_DETAIL_KEYS, "model_request");
  return {
    ...parseModelRequestSummary(record, "model_request"),
    prompt: nullableString(record.prompt, "model_request.prompt"),
    raw_response: nullableString(
      record.raw_response,
      "model_request.raw_response",
    ),
    parsed_output: nullableString(
      record.parsed_output,
      "model_request.parsed_output",
    ),
    raw_choice: nullableString(record.raw_choice, "model_request.raw_choice"),
    error: nullableString(record.error, "model_request.error"),
  };
}

function parseModelRequestSummary(
  record: Record<string, unknown>,
  path: string,
): AdminGameModelRequestSummary {
  return {
    request_id: requiredString(record.request_id, `${path}.request_id`),
    round_number: nullableNonNegativeInteger(
      record.round_number,
      `${path}.round_number`,
    ),
    phase: nullableString(record.phase, `${path}.phase`),
    actor: nullableString(record.actor, `${path}.actor`),
    action: requiredString(record.action, `${path}.action`),
    model: nullableString(record.model, `${path}.model`),
    status: enumValue(record.status, MODEL_REQUEST_STATUSES, `${path}.status`),
    attempt_count: nonNegativeInteger(
      record.attempt_count,
      `${path}.attempt_count`,
    ),
    invalid_attempt_count: nonNegativeInteger(
      record.invalid_attempt_count,
      `${path}.invalid_attempt_count`,
    ),
    run_id: nullableString(record.run_id, `${path}.run_id`),
    event_id: nullableNonNegativeInteger(record.event_id, `${path}.event_id`),
    created_at: nullableDateString(record.created_at, `${path}.created_at`),
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
    sheriff_candidates: stringArray(
      record.sheriff_candidates,
      "round.sheriff_candidates",
    ),
    sheriff_withdrawn: stringArray(
      record.sheriff_withdrawn,
      "round.sheriff_withdrawn",
    ),
    sheriff_final_candidates: stringArray(
      record.sheriff_final_candidates,
      "round.sheriff_final_candidates",
    ),
    sheriff_votes: stringRecord(record.sheriff_votes, "round.sheriff_votes"),
    sheriff_pk_candidates: stringArray(
      record.sheriff_pk_candidates,
      "round.sheriff_pk_candidates",
    ),
    sheriff_runoff_votes: stringRecord(
      record.sheriff_runoff_votes,
      "round.sheriff_runoff_votes",
    ),
    exile_pk_candidates: stringArray(
      record.exile_pk_candidates,
      "round.exile_pk_candidates",
    ),
    exile_runoff_votes: stringRecord(
      record.exile_runoff_votes,
      "round.exile_runoff_votes",
    ),
    exile_resolution_reason: nullableString(
      record.exile_resolution_reason,
      "round.exile_resolution_reason",
    ),
    sheriff_speech_order: stringArray(
      record.sheriff_speech_order,
      "round.sheriff_speech_order",
    ),
    sheriff_speech_direction: nullableString(
      record.sheriff_speech_direction,
      "round.sheriff_speech_direction",
    ),
    speech_order: stringArray(record.speech_order, "round.speech_order"),
    speech_order_choice: nullableString(
      record.speech_order_choice,
      "round.speech_order_choice",
    ),
    sheriff_speeches: speechArray(
      record.sheriff_speeches,
      "round.sheriff_speeches",
    ),
    sheriff_pk_speeches: speechArray(
      record.sheriff_pk_speeches,
      "round.sheriff_pk_speeches",
    ),
    exile_pk_speeches: speechArray(
      record.exile_pk_speeches,
      "round.exile_pk_speeches",
    ),
    exile_last_words:
      record.exile_last_words === null
        ? null
        : speechValue(record.exile_last_words, "round.exile_last_words"),
    debate: speechArray(record.debate, "round.debate"),
    sheriff_badge_target: nullableString(
      record.sheriff_badge_target,
      "round.sheriff_badge_target",
    ),
    sheriff_badge_lost: booleanValue(
      record.sheriff_badge_lost,
      "round.sheriff_badge_lost",
    ),
    sheriff_badge_lost_reason: nullableString(
      record.sheriff_badge_lost_reason,
      "round.sheriff_badge_lost_reason",
    ),
    day_ended_by_self_explosion: booleanValue(
      record.day_ended_by_self_explosion,
      "round.day_ended_by_self_explosion",
    ),
  };
}

function speechArray(value: unknown, field: string) {
  return arrayValue(value, field).map((item, index) =>
    speechValue(item, `${field}[${index}]`),
  );
}

function speechValue(value: unknown, field: string) {
  const record = recordValue(value);
  return {
    speaker: requiredString(record.speaker, `${field}.speaker`),
    message: requiredString(record.message, `${field}.message`),
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

function rejectUnexpectedKeys(
  record: Record<string, unknown>,
  allowed: readonly string[],
  path: string,
) {
  const allowedKeys = new Set(allowed);
  const unexpected = Object.keys(record).find((key) => !allowedKeys.has(key));
  if (unexpected) {
    throw invalidContract(`${path}.${unexpected} 不允许出现在响应中`);
  }
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

function patternString(value: unknown, pattern: RegExp, field: string) {
  const parsed = requiredString(value, field);
  if (!pattern.test(parsed)) {
    throw invalidContract(`${field} 格式无效`);
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

function boundedNonNegativeInteger(
  value: unknown,
  maximum: number,
  field: string,
) {
  const parsed = nonNegativeInteger(value, field);
  if (parsed > maximum) {
    throw invalidContract(`${field} 超过上限`);
  }
  return parsed;
}

function nullableBoundedNonNegativeInteger(
  value: unknown,
  maximum: number,
  field: string,
): number | null {
  return value === null
    ? null
    : boundedNonNegativeInteger(value, maximum, field);
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

function enumValue<Value extends string | number>(
  value: unknown,
  allowed: readonly Value[],
  field: string,
): Value {
  const expectsNumber = allowed.some((item) => typeof item === "number");
  const parsed = expectsNumber
    ? nonNegativeInteger(value, field)
    : stringValue(value, field);
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
