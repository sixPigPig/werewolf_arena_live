import { AdminApiError } from "@/api/problem-details";
import type {
  V2GameControlResult,
  V2GamePresentation,
  V2GameRecordDetail,
  V2GameRecordEvent,
  V2GameRecordList,
  V2GameRecordListItem,
  V2GameRun,
  V2ModelRequest,
  V2PlayerIdentity,
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

export function parseV2GameRecordDetail(value: unknown): V2GameRecordDetail {
  const record = object(value);
  return {
    ...parseListItem(record),
    rule_snapshot: object(record.rule_snapshot),
    players_snapshot: array(record.players_snapshot).map(object),
    judge_voice_snapshot: object(record.judge_voice_snapshot),
    ability_snapshot: object(record.ability_snapshot),
    match_state: record.match_state === null ? null : object(record.match_state),
    player_identities: array(record.player_identities).map(parsePlayerIdentity),
    runs: array(record.runs).map(parseRun),
    events: array(record.events).map(parseEvent),
    model_requests: array(record.model_requests).map(parseModelRequest),
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
  };
}

function parseEvent(value: unknown): V2GameRecordEvent {
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

function parseModelRequest(value: unknown): V2ModelRequest {
  const record = object(value);
  return {
    attempt_id: text(record.attempt_id),
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
    status: oneOf(record.status, ["running", "succeeded", "failed"] as const),
    request_payload:
      record.request_payload === null ? null : object(record.request_payload),
    input_source: oneOf(
      record.input_source,
      ["persisted", "reconstructed", "unavailable"] as const,
    ),
    raw_response: nullableText(record.raw_response),
    parsed_output:
      record.parsed_output === null ? null : object(record.parsed_output),
    output_source: oneOf(
      record.output_source,
      ["persisted", "legacy_inferred", "unavailable"] as const,
    ),
    provider_request_id: nullableText(record.provider_request_id),
    first_token_ms: nullableInteger(record.first_token_ms, 0),
    completed_ms: nullableInteger(record.completed_ms, 0),
    failure_kind: nullableText(record.failure_kind),
    failure_code: nullableText(record.failure_code),
    started_at: date(record.started_at),
    completed_at: nullableDate(record.completed_at),
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
