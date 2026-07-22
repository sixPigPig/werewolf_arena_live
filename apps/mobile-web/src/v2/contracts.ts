export type V2LiveState =
  | "ready"
  | "generating"
  | "broadcasting"
  | "finalizing"
  | "awaiting_observation"
  | "failed";

export type V2LobbyRuleSnapshot = {
  id: string;
  version: string;
  name: string;
  description?: string;
  player_count: number;
  roles: Array<{
    role: string;
    count: number;
    team?: string;
    model_group?: string;
    category?: string;
  }>;
  night_actions?: string[];
  day_actions?: string[];
  win_condition?: string;
  reveal_policy?: string;
  complexity?: string;
  estimated_duration?: string;
  role_summary?: string;
  sheriff_enabled?: boolean;
  sheriff_vote_weight?: number;
  speech_policy?: string;
  speech_rounds?: number;
  rule_tags?: string[];
  werewolf_self_explosion_enabled?: boolean;
  exile_last_words_enabled?: boolean;
  sheriff_badge_bomb_policy?: string;
  revision_id?: string;
  revision_no?: number;
  schema_version?: number;
  content_hash?: string;
  is_default?: boolean;
};

export type V2LobbyPlayerSnapshot = {
  seat: number;
  profile_id: string;
  name?: string | null;
  model?: string | null;
  personality_id?: string;
  personality?: string;
  appearance_id?: string;
  avatar_prompt?: string;
  avatar_image_url?: string;
  avatar_asset_id?: string | null;
  catchphrases?: string[];
  strategy_profile?: string;
  tts_speaker?: string;
  tts_dialect?: string;
  base_delivery_mood?: string;
  base_delivery_intensity?: string;
  base_delivery_pace?: string;
  base_delivery_instruction?: string;
  voice_enabled?: boolean;
  voice_config_version?: number;
  tags?: string[];
};

export type V2LobbyQualitySnapshot = {
  schema_version: 1;
  policy_mode: "observe" | "repair" | "enforce";
  player_count: number;
  configured_count: number;
  is_blocked: boolean;
  was_repaired: boolean;
  style_bucket_count: number;
  required_style_bucket_count: number;
  violations: Array<{
    code: string;
    severity: "warning" | "error";
    key: string;
    count: number;
    limit: number;
    seat_numbers: number[];
  }>;
};

export type V2GameCreateRequest = {
  title: string;
  lobby_snapshot: {
    schema_version: 1;
    rule_set: V2LobbyRuleSnapshot;
    rule_set_revision_id: string | null;
    seed: number | null;
    max_rounds: number;
    player_configs: V2LobbyPlayerSnapshot[];
    lineup_quality_report: V2LobbyQualitySnapshot;
    allow_lineup_quality_warnings: boolean;
  };
};

export type V2GameCreateResponse = {
  game_id: string;
  run_id: string;
  status: "ready";
  snapshot_url: string;
  websocket_url: string;
};

export type V2Presentation = {
  action_id: string;
  presentation_seq: number;
  presentation_id: string;
  phase_id: string;
  actor: { kind: "judge" | "player"; id: string };
  speech_id: string;
  segment_index: number;
  subtitle_text: string;
  join_sample_cursor: number;
};

export type V2PublicPlayerSeat = {
  seat: number;
  player_id: string;
  display_name: string;
  avatar_url: string | null;
};

export type V2LiveSnapshot = {
  protocol_version: 1;
  type: "live.snapshot";
  api_version: "v2";
  audience: "player_public" | "spectator_god_view";
  game_id: string;
  run_id: string;
  live_state: V2LiveState;
  latest_presentation_seq: number;
  server_time: string;
  public_players: V2PublicPlayerSeat[];
  current_presentation: V2Presentation | null;
};

export type V2PresentationOpened = Omit<V2Presentation, "segment_index" | "subtitle_text" | "join_sample_cursor"> & {
  protocol_version: 1;
  type: "presentation.opened";
  game_id: string;
  run_id: string;
  server_time: string;
};

export type V2SegmentCommitted = {
  protocol_version: 1;
  type: "speech.segment_committed";
  game_id: string;
  run_id: string;
  server_time: string;
  action_id: string;
  presentation_seq: number;
  presentation_id: string;
  speech_id: string;
  segment_index: number;
  text: string;
};

export type V2StateChanged = {
  protocol_version: 1;
  type: "live.state_changed";
  game_id: string;
  run_id: string;
  server_time: string;
  live_state: V2LiveState;
  reason: string | null;
};

export type V2PresentationClosed = {
  protocol_version: 1;
  type: "presentation.closed";
  game_id: string;
  run_id: string;
  server_time: string;
  action_id: string;
  presentation_seq: number;
  presentation_id: string;
  speech_id: string;
  final_segment_index: number;
  final_chunk_index: number;
  final_sample_cursor: number;
  result: "audio_drained_and_voice_saved";
};

export type V2PresentationFailed = {
  protocol_version: 1;
  type: "presentation.failed";
  game_id: string;
  run_id: string;
  server_time: string;
  action_id: string;
  presentation_seq: number;
  presentation_id: string;
  speech_id: string;
  failure_kind: "model" | "quality" | "tts" | "recording" | "broadcast" | "protocol";
  failure_code: string;
};

export type V2ServerMessage =
  | V2LiveSnapshot
  | V2PresentationOpened
  | V2SegmentCommitted
  | V2StateChanged
  | V2PresentationClosed
  | V2PresentationFailed;

export type V2AudioFrame = {
  header: {
    protocol_version: 1;
    action_id: string;
    presentation_seq: number;
    presentation_id: string;
    speech_id: string;
    segment_index: number;
    chunk_index: number;
    start_sample: number;
    sample_count: number;
    sample_rate: number;
    channels: 1;
    encoding: "pcm_s16le";
    is_final: boolean;
  };
  pcm: ArrayBuffer;
};

export function parseV2GameCreateResponse(value: unknown): V2GameCreateResponse {
  const record = object(value);
  return {
    game_id: id(record.game_id, "v2_game_"),
    run_id: id(record.run_id, "v2_run_"),
    status: literal(record.status, ["ready"]),
    snapshot_url: apiPath(record.snapshot_url),
    websocket_url: apiPath(record.websocket_url),
  };
}

export function parseV2LiveSnapshotResponse(value: unknown): V2LiveSnapshot {
  const message = parseV2ServerMessage(JSON.stringify(value));
  if (message.type !== "live.snapshot") throw invalid();
  return message;
}

export function parseV2ServerMessage(raw: string): V2ServerMessage {
  const value = object(JSON.parse(raw));
  if (integer(value.protocol_version, 1) !== 1) throw invalid();
  const type = text(value.type);
  const base = {
    protocol_version: 1 as const,
    game_id: text(value.game_id),
    run_id: text(value.run_id),
    server_time: date(value.server_time),
  };
  if (type === "live.snapshot") {
    return {
      ...base,
      type,
      api_version: literal(value.api_version, ["v2"]),
      audience: literal(value.audience, ["player_public", "spectator_god_view"]),
      live_state: liveState(value.live_state),
      latest_presentation_seq: integer(value.latest_presentation_seq, 0),
      public_players: publicPlayerSeats(value.public_players),
      current_presentation:
        value.current_presentation === null ? null : presentation(value.current_presentation),
    };
  }
  if (type === "live.state_changed") {
    return {
      ...base,
      type,
      live_state: liveState(value.live_state),
      reason: value.reason === null ? null : text(value.reason),
    };
  }
  if (type === "presentation.opened") {
    const actor = parseActor(value.actor);
    return {
      ...base,
      type,
      action_id: text(value.action_id),
      presentation_seq: integer(value.presentation_seq, 1),
      presentation_id: text(value.presentation_id),
      phase_id: text(value.phase_id),
      actor,
      speech_id: text(value.speech_id),
    };
  }
  if (type === "speech.segment_committed") {
    return {
      ...base,
      type,
      action_id: text(value.action_id),
      presentation_seq: integer(value.presentation_seq, 1),
      presentation_id: text(value.presentation_id),
      speech_id: text(value.speech_id),
      segment_index: integer(value.segment_index, 0),
      text: text(value.text),
    };
  }
  if (type === "presentation.closed") {
    return {
      ...base,
      type,
      action_id: text(value.action_id),
      presentation_seq: integer(value.presentation_seq, 1),
      presentation_id: text(value.presentation_id),
      speech_id: text(value.speech_id),
      final_segment_index: integer(value.final_segment_index, 0),
      final_chunk_index: integer(value.final_chunk_index, 0),
      final_sample_cursor: integer(value.final_sample_cursor, 1),
      result: literal(value.result, ["audio_drained_and_voice_saved"]),
    };
  }
  if (type === "presentation.failed") {
    return {
      ...base,
      type,
      action_id: text(value.action_id),
      presentation_seq: integer(value.presentation_seq, 1),
      presentation_id: text(value.presentation_id),
      speech_id: text(value.speech_id),
      failure_kind: literal(value.failure_kind, [
        "model",
        "quality",
        "tts",
        "recording",
        "broadcast",
        "protocol",
      ]),
      failure_code: text(value.failure_code),
    };
  }
  throw invalid();
}

export function decodeV2AudioFrame(value: ArrayBuffer): V2AudioFrame {
  const bytes = new Uint8Array(value);
  if (bytes.length < 7 || new TextDecoder().decode(bytes.slice(0, 4)) !== "LV2A") {
    throw invalid();
  }
  const headerSize = new DataView(value).getUint16(4, false);
  const payloadOffset = 6 + headerSize;
  if (payloadOffset > bytes.length) throw invalid();
  const rawHeader = object(
    JSON.parse(new TextDecoder().decode(bytes.slice(6, payloadOffset))),
  );
  const header = {
    protocol_version: literal(rawHeader.protocol_version, [1] as const),
    action_id: text(rawHeader.action_id),
    presentation_seq: integer(rawHeader.presentation_seq, 1),
    presentation_id: text(rawHeader.presentation_id),
    speech_id: text(rawHeader.speech_id),
    segment_index: integer(rawHeader.segment_index, 0),
    chunk_index: integer(rawHeader.chunk_index, 0),
    start_sample: integer(rawHeader.start_sample, 0),
    sample_count: integer(rawHeader.sample_count, 1),
    sample_rate: integer(rawHeader.sample_rate, 8000),
    channels: literal(rawHeader.channels, [1] as const),
    encoding: literal(rawHeader.encoding, ["pcm_s16le"]),
    is_final: boolean(rawHeader.is_final),
  };
  const pcm = value.slice(payloadOffset);
  if (pcm.byteLength !== header.sample_count * 2) throw invalid();
  return { header, pcm };
}

function presentation(value: unknown): V2Presentation {
  const record = object(value);
  return {
    action_id: text(record.action_id),
    presentation_seq: integer(record.presentation_seq, 1),
    presentation_id: text(record.presentation_id),
    phase_id: text(record.phase_id),
    actor: parseActor(record.actor),
    speech_id: text(record.speech_id),
    segment_index: integer(record.segment_index, 0),
    subtitle_text: text(record.subtitle_text),
    join_sample_cursor: integer(record.join_sample_cursor, 0),
  };
}

function parseActor(value: unknown): V2Presentation["actor"] {
  const record = object(value);
  return {
    kind: literal(record.kind, ["judge", "player"]),
    id: text(record.id),
  };
}

function publicPlayerSeats(value: unknown): V2PublicPlayerSeat[] {
  if (!Array.isArray(value) || value.length > 24) throw invalid();
  const players = value.map((item) => {
    const record = exactObject(item, [
      "seat",
      "player_id",
      "display_name",
      "avatar_url",
    ]);
    return {
      seat: integer(record.seat, 1),
      player_id: text(record.player_id),
      display_name: text(record.display_name),
      avatar_url: record.avatar_url === null ? null : text(record.avatar_url),
    };
  });
  let previousSeat = 0;
  const playerIds = new Set<string>();
  for (const player of players) {
    if (player.seat > 24 || player.seat <= previousSeat || playerIds.has(player.player_id)) {
      throw invalid();
    }
    previousSeat = player.seat;
    playerIds.add(player.player_id);
  }
  return players;
}

function liveState(value: unknown): V2LiveState {
  return literal(value, [
    "ready",
    "generating",
    "broadcasting",
    "finalizing",
    "awaiting_observation",
    "failed",
  ]);
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  return value as Record<string, unknown>;
}

function exactObject(value: unknown, allowedKeys: readonly string[]): Record<string, unknown> {
  const record = object(value);
  if (Object.keys(record).some((key) => !allowedKeys.includes(key))) throw invalid();
  return record;
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value) throw invalid();
  return value;
}

function integer(value: unknown, minimum: number): number {
  if (!Number.isInteger(value) || Number(value) < minimum) throw invalid();
  return Number(value);
}

function literal<const T extends string | number>(value: unknown, values: readonly T[]): T {
  if (!values.includes(value as T)) throw invalid();
  return value as T;
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

function id(value: unknown, prefix: string): string {
  const result = text(value);
  if (!result.startsWith(prefix) || result.length !== prefix.length + 16) throw invalid();
  return result;
}

function apiPath(value: unknown): string {
  const result = text(value);
  if (!result.startsWith("/api/v2/")) throw invalid();
  return result;
}

function invalid(): Error {
  return new Error("V2 实时直播协议无效");
}
