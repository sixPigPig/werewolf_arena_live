import { AdminApiError } from "@/api/problem-details";
import type {
  V2GameControlResult,
  V2GameEventPage,
  V2GamePresentation,
  V2GameRecordEvent,
  V2GameRecordList,
  V2GameRecordListItem,
  V2GameRecordSummary,
  V2GameRun,
  V2ModelRequest,
  V2ModelActionRetryResult,
  V2ModelRequestPage,
  V2ModelRequestSummary,
  V2PlayerIdentity,
  V2PromptProjection,
  V2VoiceAsset,
} from "@/v2/game-records/types";

export function parseV2GameControlResult(
  value: unknown,
): V2GameControlResult {
  const record = object(value);
  return {
    action: oneOf(record.action, ["stop"] as const),
    game_id: text(record.game_id),
    run_id: text(record.run_id),
    run_status: text(record.run_status),
    stop_requested_at: date(record.stop_requested_at),
    replayed: boolean(record.replayed),
  };
}

export function parseV2ModelActionRetryResult(
  value: unknown,
): V2ModelActionRetryResult {
  const record = object(value);
  return {
    action: oneOf(record.action, ["retry_model_action"] as const),
    game_id: text(record.game_id),
    run_id: text(record.run_id),
    run_status: text(record.run_status),
    action_id: text(record.action_id),
    replayed: boolean(record.replayed),
  };
}

export function parseV2GameRecordList(value: unknown): V2GameRecordList {
  const record = object(value);
  const pagination = object(record.pagination);
  return {
    items: array(record.items).map(parseListItem),
    pagination: {
      page: integer(pagination.page, 1),
      page_size: integer(pagination.page_size, 1),
      total: integer(pagination.total, 0),
      pages: integer(pagination.pages, 0),
    },
  };
}

export function parseV2GameRecordSummary(value: unknown): V2GameRecordSummary {
  const record = object(value);
  return {
    ...parseListItem(record),
    rule_snapshot: object(record.rule_snapshot),
    players_snapshot: array(record.players_snapshot).map(object),
    judge_voice_snapshot: object(record.judge_voice_snapshot),
    delivery_snapshot:
      record.delivery_snapshot === null ? null : object(record.delivery_snapshot),
    ability_snapshot: object(record.ability_snapshot),
    match_state: record.match_state === null ? null : object(record.match_state),
    player_identities: array(record.player_identities).map(parsePlayerIdentity),
    runs: array(record.runs).map(parseRun),
    presentations: array(record.presentations).map(parsePresentation),
    voice_assets: array(record.voice_assets).map(parseVoiceAsset),
    player_states: array(record.player_states).map(object),
    action_windows: array(record.action_windows).map(object),
    ability_instances: array(record.ability_instances).map(object),
    ability_activations: array(record.ability_activations).map(object),
    effect_intents: array(record.effect_intents).map(object),
    knowledge_facts: array(record.knowledge_facts).map(object),
  };
}

export function parseV2GameEventPage(value: unknown): V2GameEventPage {
  const record = object(value);
  return {
    items: array(record.items).map(parseV2GameRecordEvent),
    after_record_seq: integer(record.after_record_seq, 0),
    next_after_record_seq: integer(record.next_after_record_seq, 0),
    has_more: boolean(record.has_more),
  };
}

export function parseV2ModelRequestPage(
  value: unknown,
): V2ModelRequestPage {
  const record = object(value);
  return {
    items: array(record.items).map(parseV2ModelRequestSummary),
    after_record_seq: integer(record.after_record_seq, 0),
    next_after_record_seq: integer(record.next_after_record_seq, 0),
    has_more: boolean(record.has_more),
  };
}

function parsePlayerIdentity(value: unknown): V2PlayerIdentity {
  const record = object(value);
  return {
    seat: integer(record.seat, 1),
    player_id: text(record.player_id),
    display_name: text(record.display_name),
    avatar_url: nullableText(record.avatar_url),
    role: text(record.role),
    team: nullableText(record.team),
    alive: boolean(record.alive),
    death_cause: nullableText(record.death_cause),
  };
}

function parseListItem(value: unknown): V2GameRecordListItem {
  const record = object(value);
  return {
    game_id: text(record.game_id),
    title: text(record.title),
    status: text(record.status),
    current_run_id: text(record.current_run_id),
    record_schema_version: integer(record.record_schema_version, 1),
    last_record_seq: integer(record.last_record_seq, 0),
    last_presentation_seq: integer(record.last_presentation_seq, 0),
    phase_seq: integer(record.phase_seq, 0),
    phase_id: text(record.phase_id),
    phase_state: text(record.phase_state),
    audio_mode: oneOf(record.audio_mode, ["tts", "text_only", "legacy_unknown"] as const),
    match_status: oneOf(
      record.match_status,
      ["waiting", "running", "completed", "failed", "canceled"] as const,
    ),
    execution_state: oneOf(
      record.execution_state,
      ["unowned", "owned", "stale", "stopped"] as const,
    ),
    winner:
      record.winner === null
        ? null
        : oneOf(record.winner, ["villagers", "werewolves"] as const),
    completion_reason: nullableText(record.completion_reason),
    completed_at: nullableDate(record.completed_at),
    created_at: date(record.created_at),
    updated_at: date(record.updated_at),
  };
}

function parseRun(value: unknown): V2GameRun {
  const record = object(value);
  return {
    run_id: text(record.run_id),
    attempt_no: integer(record.attempt_no, 1),
    status: text(record.status),
    started_at: nullableDate(record.started_at),
    completed_at: record.completed_at === null ? null : date(record.completed_at),
    stop_requested_at: nullableDate(record.stop_requested_at),
    worker_id: nullableText(record.worker_id),
    worker_heartbeat_at: nullableDate(record.worker_heartbeat_at),
    lease_expires_at: nullableDate(record.lease_expires_at),
    fence_token: integer(record.fence_token, 0),
  };
}

export function parseV2GameRecordEvent(
  value: unknown,
): V2GameRecordEvent {
  const record = object(value);
  return {
    event_id: integer(record.event_id, 1),
    record_seq: integer(record.record_seq, 1),
    run_id: text(record.run_id),
    event_type: text(record.event_type),
    payload_schema_version: integer(record.payload_schema_version, 1),
    payload: object(record.payload),
    created_at: date(record.created_at),
  };
}

function parsePresentation(value: unknown): V2GamePresentation {
  const record = object(value);
  return {
    presentation_seq: integer(record.presentation_seq, 1),
    presentation_id: text(record.presentation_id),
    action_id: nullableText(record.action_id),
    activation_id: nullableText(record.activation_id),
    phase_id: text(record.phase_id),
    actor_kind: text(record.actor_kind),
    actor_id: text(record.actor_id),
    audience: text(record.audience),
    speech_id: text(record.speech_id),
    segment_index: integer(record.segment_index, 0),
    source_event_id: integer(record.source_event_id, 1),
    state: text(record.state),
    subtitle_text: text(record.subtitle_text),
    voice_asset_id: nullableText(record.voice_asset_id),
    audio_duration_ms: nullableInteger(record.audio_duration_ms, 0),
    created_at: date(record.created_at),
    closed_at: nullableDate(record.closed_at),
  };
}

function parseVoiceAsset(value: unknown): V2VoiceAsset {
  const record = object(value);
  return {
    voice_asset_id: text(record.voice_asset_id),
    action_id: text(record.action_id),
    activation_id: nullableText(record.activation_id),
    audience: text(record.audience),
    presentation_id: text(record.presentation_id),
    speech_id: text(record.speech_id),
    segment_index: integer(record.segment_index, 0),
    state: text(record.state),
    mime_type: text(record.mime_type),
    sample_rate: integer(record.sample_rate, 1),
    channels: integer(record.channels, 1),
    sample_count: nullableInteger(record.sample_count, 0),
    duration_ms: nullableInteger(record.duration_ms, 0),
    pcm_sha256: nullableText(record.pcm_sha256),
    size_bytes: nullableInteger(record.size_bytes, 0),
    audio_url: nullableText(record.audio_url),
    created_at: date(record.created_at),
    completed_at: nullableDate(record.completed_at),
  };
}

export function parseV2ModelRequestSummary(
  value: unknown,
): V2ModelRequestSummary {
  const record = object(value);
  return {
    attempt_id: text(record.attempt_id),
    attempt_no:
      record.attempt_no === undefined ? 1 : integer(record.attempt_no, 1),
    cycle_attempt_no:
      record.cycle_attempt_no === undefined
        ? integer(record.attempt_no ?? 1, 1)
        : integer(record.cycle_attempt_no, 1),
    retry_cycle:
      record.retry_cycle === undefined
        ? 1
        : integer(record.retry_cycle, 1),
    max_attempts:
      record.max_attempts === undefined ? 1 : integer(record.max_attempts, 1),
    retry_of_attempt_id:
      record.retry_of_attempt_id === undefined
        ? null
        : nullableText(record.retry_of_attempt_id),
    record_seq:
      record.record_seq === undefined ? 1 : integer(record.record_seq, 1),
    last_record_seq:
      record.last_record_seq === undefined
        ? integer(record.record_seq ?? 1, 1)
        : integer(record.last_record_seq, 1),
    action_id: text(record.action_id),
    run_id: text(record.run_id),
    phase_id: text(record.phase_id),
    action_type: text(record.action_type),
    actor_kind: text(record.actor_kind),
    actor_id: text(record.actor_id),
    audience: text(record.audience),
    request_kind: text(record.request_kind),
    model_id: nullableText(record.model_id),
    model_provider: nullableText(record.model_provider),
    judge_configuration_version: nullableInteger(
      record.judge_configuration_version,
      0,
    ),
    prompt_schema_version:
      record.prompt_schema_version === undefined
        ? null
        : nullableInteger(record.prompt_schema_version, 0),
    model_context_schema_version:
      record.model_context_schema_version === undefined
        ? null
        : nullableInteger(record.model_context_schema_version, 0),
    prompt_template_version:
      record.prompt_template_version === undefined
        ? null
        : nullableInteger(record.prompt_template_version, 0),
    model_view_selector_version:
      record.model_view_selector_version === undefined
        ? null
        : nullableInteger(record.model_view_selector_version, 0),
    prompt_projection:
      record.prompt_projection === undefined ||
      record.prompt_projection === null
        ? null
        : parsePromptProjection(record.prompt_projection),
    status: oneOf(record.status, ["running", "succeeded", "failed"] as const),
    input_source: oneOf(
      record.input_source,
      ["persisted", "reconstructed", "unavailable"] as const,
    ),
    passive_observation_count:
      record.passive_observation_count === undefined
        ? Array.isArray(record.passive_observations)
          ? record.passive_observations.length
          : 0
        : integer(record.passive_observation_count, 0),
    output_source: oneOf(
      record.output_source,
      ["persisted", "legacy_inferred", "unavailable"] as const,
    ),
    provider_request_id: nullableText(record.provider_request_id),
    first_token_ms: nullableInteger(record.first_token_ms, 0),
    completed_ms: nullableInteger(record.completed_ms, 0),
    failure_kind: nullableText(record.failure_kind),
    failure_code: nullableText(record.failure_code),
    ...(record.failure_category === undefined
      ? {}
      : { failure_category: nullableText(record.failure_category) }),
    ...(record.repair_kind === undefined
      ? {}
      : { repair_kind: nullableText(record.repair_kind) }),
    retryable:
      record.retryable === undefined ? null : nullableBoolean(record.retryable),
    terminal:
      record.terminal === undefined ? null : nullableBoolean(record.terminal),
    failure_stage:
      record.failure_stage === undefined
        ? null
        : nullableText(record.failure_stage),
    exception_type:
      record.exception_type === undefined
        ? null
        : nullableText(record.exception_type),
    errno:
      record.errno === undefined ? null : nullableInteger(record.errno, 0),
    http_status:
      record.http_status === undefined
        ? null
        : nullableInteger(record.http_status, 100),
    first_token_seen:
      record.first_token_seen === undefined
        ? null
        : nullableBoolean(record.first_token_seen),
    response_headers_seen:
      record.response_headers_seen === undefined
        ? null
        : nullableBoolean(record.response_headers_seen),
    failure_elapsed_ms:
      record.failure_elapsed_ms === undefined
        ? null
        : nullableInteger(record.failure_elapsed_ms, 0),
    attempt_budget_ms:
      record.attempt_budget_ms === undefined
        ? null
        : nullableInteger(record.attempt_budget_ms, 0),
    action_budget_ms:
      record.action_budget_ms === undefined
        ? null
        : nullableInteger(record.action_budget_ms, 0),
    action_elapsed_ms:
      record.action_elapsed_ms === undefined
        ? null
        : nullableInteger(record.action_elapsed_ms, 0),
    action_remaining_ms:
      record.action_remaining_ms === undefined
        ? null
        : nullableInteger(record.action_remaining_ms, 0),
    started_at: date(record.started_at),
    completed_at: nullableDate(record.completed_at),
  };
}

function parsePromptProjection(value: unknown): V2PromptProjection {
  const projection = object(value);
  for (const key of [
    "model_context_schema_version",
    "prompt_template_version",
    "known_events_schema_version",
    "model_view_schema_version",
    "model_view_selector_version",
  ]) {
    validateOptionalInteger(projection, key, 0, true);
  }
  for (const key of [
    "known_event_count",
    "known_event_total_count",
    "dropped_event_count",
    "selection_budget_chars",
    "selection_used_chars",
  ]) {
    validateOptionalInteger(projection, key, 0);
  }
  for (const key of [
    "known_event_record_seq_min",
    "known_event_record_seq_max",
  ]) {
    validateOptionalInteger(projection, key, 1, true);
  }
  if (projection.selection_budget_exceeded_by_required !== undefined) {
    boolean(projection.selection_budget_exceeded_by_required);
  }
  for (const key of ["retained_event_refs", "dropped_event_refs"]) {
    if (projection[key] !== undefined) {
      array(projection[key]).forEach(text);
    }
  }
  for (const key of ["retention_reasons", "section_char_counts"]) {
    if (projection[key] !== undefined) object(projection[key]);
  }
  validateOptionalInteger(
    projection,
    "public_timeline_schema_version",
    1,
    true,
  );
  validateOptionalInteger(
    projection,
    "public_timeline_event_count",
    0,
  );
  validateOptionalInteger(
    projection,
    "public_timeline_record_seq_min",
    1,
    true,
  );
  validateOptionalInteger(
    projection,
    "public_timeline_record_seq_max",
    1,
    true,
  );
  validateOptionalInteger(
    projection,
    "public_timeline_missing_record_seq_count",
    0,
  );
  if (projection.public_timeline_kind_counts !== undefined) {
    const counts = object(projection.public_timeline_kind_counts);
    for (const count of Object.values(counts)) integer(count, 0);
  }
  return projection;
}

function validateOptionalInteger(
  record: Record<string, unknown>,
  key: string,
  minimum: number,
  nullable = false,
) {
  const value = record[key];
  if (value === undefined || (nullable && value === null)) return;
  integer(value, minimum);
}

export function parseV2ModelRequest(value: unknown): V2ModelRequest {
  const record = object(value);
  return {
    ...parseV2ModelRequestSummary(record),
    request_payload:
      record.request_payload === null ? null : object(record.request_payload),
    raw_response: nullableText(record.raw_response),
    parsed_output:
      record.parsed_output === null ? null : object(record.parsed_output),
    passive_observations:
      record.passive_observations === undefined
        ? []
        : array(record.passive_observations).map(object),
  };
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  return value as Record<string, unknown>;
}

function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw invalid();
  return value;
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value) throw invalid();
  return value;
}

function integer(value: unknown, minimum: number): number {
  if (!Number.isInteger(value) || Number(value) < minimum) throw invalid();
  return Number(value);
}

function nullableInteger(value: unknown, minimum: number): number | null {
  return value === null ? null : integer(value, minimum);
}

function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}

function nullableBoolean(value: unknown): boolean | null {
  return value === null ? null : boolean(value);
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") throw invalid();
  return value;
}

function date(value: unknown): string {
  const result = text(value);
  if (!Number.isFinite(Date.parse(result))) throw invalid();
  return result;
}

function nullableDate(value: unknown): string | null {
  return value === null ? null : date(value);
}

function oneOf<const T extends readonly string[]>(
  value: unknown,
  options: T,
): T[number] {
  if (
    typeof value !== "string" ||
    !(options as readonly string[]).includes(value)
  ) {
    throw invalid();
  }
  return value as T[number];
}

function invalid() {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "V2 对局记录响应无效",
      status: 502,
      detail: "V2 对局记录数据不完整或格式错误。",
      code: "admin_invalid_v2_game_record_response",
      request_id: null,
    },
  });
}
