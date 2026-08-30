export type LiveState =
  | "waiting_to_start"
  | "ready"
  | "generating"
  | "broadcasting"
  | "finalizing"
  | "awaiting_observation"
  | "paused_model_error"
  | "canceled"
  | "failed";

export type ConfiguredAudioMode = "tts" | "text_only";
export type AudioMode = ConfiguredAudioMode | "legacy_unknown";
export type MatchStatus =
  | "waiting"
  | "running"
  | "completed"
  | "failed"
  | "canceled";
export type ExecutionState = "unowned" | "owned" | "stale" | "stopped";

export type RuntimeProjection = {
  audio_mode: AudioMode;
  match_status: MatchStatus;
  execution_state: ExecutionState;
  winner: "villagers" | "werewolves" | null;
  completion_reason: string | null;
  completed_at: string | null;
};

export type GamePhase = {
  phase_seq: number;
  phase_id: string;
  phase_state:
    | "legacy_frozen"
    | "opening_ready"
    | "opening_speech_closed"
    | "nightfall_ready"
    | "nightfall_announced"
    | "night_running"
    | "dawn_announcement_ready"
    | "dawn_announced"
    | "dawn_reactions_ready"
    | "public_day_ready"
    | "sheriff_election_ready"
    | "public_discussion_open"
    | "sheriff_election_open"
    | "game_completed"
    | "failed";
};

export type MatchState = {
  round_no: number;
  sheriff_player_id: string | null;
  sheriff_badge_state: "disabled" | "pending" | "held" | "destroyed";
  winner: "villagers" | "werewolves" | null;
};

export type LobbyRuleSnapshot = {
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
  first_night_last_words_enabled?: boolean;
  sheriff_badge_bomb_policy?: string;
  werewolf_attack_policy?: {
    resolution:
      | "plurality_rotating_tiebreak"
      | "plurality_seeded_random"
      | "unanimous_no_attack";
    allow_no_attack: boolean;
    allow_wolf_target: boolean;
  } | null;
  revision_id?: string;
  revision_no?: number;
  schema_version?: number;
  content_hash?: string;
  is_default?: boolean;
};

export type LobbyPlayerSnapshot = {
  seat: number;
  profile_id: string;
  name?: string | null;
  model_provider?: string;
  model?: string;
  personality_id?: string;
  personality?: string;
  appearance_id?: string;
  avatar_image_url?: string;
  avatar_asset_id?: string | null;
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

export type LobbyQualitySnapshot = {
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

export type GameCreateRequest = {
  title: string;
  audio_mode: ConfiguredAudioMode;
  lobby_snapshot: {
    schema_version: 1;
    model_binding_mode: "profile_library";
    rule_set: LobbyRuleSnapshot;
    rule_set_revision_id: string | null;
    seed: number | null;
    max_rounds: number;
    player_configs: LobbyPlayerSnapshot[];
    lineup_quality_report: LobbyQualitySnapshot;
    allow_lineup_quality_warnings: boolean;
  };
};

export type GameCreateResponse = {
  game_id: string;
  run_id: string;
  status: "waiting_to_start";
  audio_mode: ConfiguredAudioMode;
  snapshot_url: string;
  websocket_url: string;
  director_snapshot_url: string;
  director_websocket_url: string;
  god_view_snapshot_url: string;
  god_view_websocket_url: string;
  god_view_access_token: string;
};

export type Presentation = {
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

export type PublicPlayerSeat = {
  seat: number;
  player_id: string;
  display_name: string;
  avatar_url: string | null;
  alive: boolean;
};

export type PublicRuleSnapshot = {
  rule_id: string;
  name: string;
  version: string;
  player_count: number;
  roles: Array<{ role: string; count: number }>;
  max_rounds: number;
  sheriff_enabled: boolean | null;
  werewolf_self_explosion_enabled: boolean | null;
  exile_last_words_enabled: boolean | null;
  first_night_last_words_enabled: boolean | null;
};

export type PublicRoleAssignmentStatus = {
  state: "sealed" | "unavailable";
  assigned_count: number;
};

export type LiveSnapshot = RuntimeProjection & {
  protocol_version: 1;
  type: "live.snapshot";
  api_version: "v2";
  audience: "player_public";
  game_id: string;
  run_id: string;
  live_state: LiveState;
  game_phase: GamePhase;
  match_state: MatchState | null;
  latest_presentation_seq: number;
  server_time: string;
  public_rule: PublicRuleSnapshot | null;
  public_players: PublicPlayerSeat[];
  public_role_assignment: PublicRoleAssignmentStatus;
  current_presentation: Presentation | null;
};

export type GodViewPlayerIdentity = {
  seat: number;
  player_id: string;
  display_name: string;
  avatar_url: string | null;
  role: string;
  team: string | null;
  alive: boolean;
  death_cause: string | null;
};

export type DirectorSceneKind =
  | "opening"
  | "public_stage"
  | "nightfall"
  | "werewolves"
  | "guard"
  | "seer"
  | "witch"
  | "hunter"
  | "dawn"
  | "terminal";

export type DirectorScene = {
  scene_kind: DirectorSceneKind;
  action_id: string | null;
  action_type: string | null;
  ability_id: string | null;
  actor_player_id: string | null;
};

export type DirectorLiveSnapshot = RuntimeProjection & {
  protocol_version: 1;
  type: "director.live_snapshot";
  api_version: "v2";
  audience: "spectator_directed";
  game_id: string;
  run_id: string;
  live_state: LiveState;
  game_phase: GamePhase;
  match_state: MatchState | null;
  latest_presentation_seq: number;
  server_time: string;
  rule: PublicRuleSnapshot | null;
  players: GodViewPlayerIdentity[];
  current_scene: DirectorScene;
  current_presentation: Presentation | null;
};

export type GodViewIdentitySnapshot = RuntimeProjection & {
  protocol_version: 1;
  type: "god_view.identity_snapshot";
  api_version: "v2";
  audience: "spectator_god_view";
  game_id: string;
  run_id: string;
  live_state: LiveState;
  game_phase: GamePhase;
  match_state: MatchState | null;
  server_time: string;
  rule: PublicRuleSnapshot | null;
  players: GodViewPlayerIdentity[];
};

export type GodViewLiveSnapshot = RuntimeProjection & {
  protocol_version: 1;
  type: "god_view.live_snapshot";
  api_version: "v2";
  audience: "spectator_god_view";
  game_id: string;
  run_id: string;
  live_state: LiveState;
  game_phase: GamePhase;
  match_state: MatchState | null;
  latest_presentation_seq: number;
  server_time: string;
  rule: PublicRuleSnapshot | null;
  players: GodViewPlayerIdentity[];
  current_presentation: Presentation | null;
};

export type PresentationOpened = Omit<Presentation, "segment_index" | "subtitle_text" | "join_sample_cursor"> & {
  protocol_version: 1;
  type: "presentation.opened";
  game_id: string;
  run_id: string;
  server_time: string;
};

export type SegmentCommitted = {
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

export type StateChanged = {
  protocol_version: 1;
  type: "live.state_changed";
  game_id: string;
  run_id: string;
  server_time: string;
  live_state: LiveState;
  reason: string | null;
};

export type GamePhaseChanged = {
  protocol_version: 1;
  type: "game.phase_changed";
  game_id: string;
  run_id: string;
  server_time: string;
  phase_seq: number;
  previous_phase_id: GamePhase["phase_id"];
  phase_id: GamePhase["phase_id"];
  phase_state: GamePhase["phase_state"];
};

export type NightProgress = {
  protocol_version: 1;
  type: "night.progress_changed";
  game_id: string;
  run_id: string;
  server_time: string;
  stage: "night_started" | "actions_in_progress" | "night_resolved" | "dawn_announced";
  latest_presentation_seq: number;
};

export type DirectorSceneChanged = DirectorScene & {
  protocol_version: 1;
  type: "director.scene_changed";
  game_id: string;
  run_id: string;
  server_time: string;
};

export type AbilityProgress = {
  protocol_version: 1;
  type: "ability.progress_changed";
  game_id: string;
  run_id: string;
  server_time: string;
  ability_id: string;
  status: string;
  actor_player_id: string | null;
  target_player_id: string | null;
  round_no: number | null;
};

export type DawnResult = {
  protocol_version: 1;
  type: "dawn.result_announced";
  game_id: string;
  run_id: string;
  server_time: string;
  dead_player_ids: string[];
};

export type GodViewNightResolved = {
  protocol_version: 1;
  type: "god_view.night_resolved";
  game_id: string;
  run_id: string;
  server_time: string;
  deaths: Array<{ player_id: string; cause: string }>;
  attack_prevented_by: string | null;
};

export type PlayerStateChanged = {
  protocol_version: 1;
  type: "player.state_changed";
  game_id: string;
  run_id: string;
  server_time: string;
  player_id: string;
  alive: boolean;
  cause: string | null;
};

export type MatchStateChanged = MatchState & {
  protocol_version: 1;
  type: "match.state_changed";
  game_id: string;
  run_id: string;
  server_time: string;
};

export type DayProgress = {
  protocol_version: 1;
  type: "day.progress_changed";
  game_id: string;
  run_id: string;
  server_time: string;
  round_no: number;
  stage: string;
  completed_count: number | null;
  total_count: number | null;
};

export type PresentationClosed = {
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

export type PresentationFailed = {
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

export type ServerMessage =
  | LiveSnapshot
  | DirectorLiveSnapshot
  | GodViewLiveSnapshot
  | DirectorSceneChanged
  | PresentationOpened
  | SegmentCommitted
  | StateChanged
  | GamePhaseChanged
  | NightProgress
  | AbilityProgress
  | DawnResult
  | GodViewNightResolved
  | PlayerStateChanged
  | MatchStateChanged
  | DayProgress
  | PresentationClosed
  | PresentationFailed;

export type AudioFrame = {
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

export function parseGameCreateResponse(value: unknown): GameCreateResponse {
  const record = exactObject(value, [
    "game_id",
    "run_id",
    "status",
    "audio_mode",
    "snapshot_url",
    "websocket_url",
    "director_snapshot_url",
    "director_websocket_url",
    "god_view_snapshot_url",
    "god_view_websocket_url",
    "god_view_access_token",
  ]);
  return {
    game_id: id(record.game_id, "v2_game_"),
    run_id: id(record.run_id, "v2_run_"),
    status: literal(record.status, ["waiting_to_start"]),
    audio_mode: literal(record.audio_mode, ["tts", "text_only"]),
    snapshot_url: apiPath(record.snapshot_url),
    websocket_url: apiPath(record.websocket_url),
    director_snapshot_url: apiPath(record.director_snapshot_url),
    director_websocket_url: apiPath(record.director_websocket_url),
    god_view_snapshot_url: godViewApiPath(record.god_view_snapshot_url),
    god_view_websocket_url: godViewApiPath(record.god_view_websocket_url),
    god_view_access_token: godViewAccessToken(record.god_view_access_token),
  };
}

export function parseLiveSnapshotResponse(value: unknown): LiveSnapshot {
  const message = parseServerMessage(JSON.stringify(value));
  if (message.type !== "live.snapshot") throw invalid();
  return message;
}

export function parseDirectorLiveSnapshotResponse(
  value: unknown,
): DirectorLiveSnapshot {
  const message = parseServerMessage(JSON.stringify(value));
  if (message.type !== "director.live_snapshot") throw invalid();
  return message;
}

export function parseGodViewIdentitySnapshotResponse(
  value: unknown,
): GodViewIdentitySnapshot {
  const record = exactObject(value, [
    "protocol_version",
    "type",
    "api_version",
    "audience",
    "game_id",
    "run_id",
    "live_state",
    "audio_mode",
    "match_status",
    "execution_state",
    "winner",
    "completion_reason",
    "completed_at",
    "game_phase",
    "match_state",
    "server_time",
    "rule",
    "players",
  ]);
  const rule = record.rule === null ? null : publicRule(record.rule);
  const players = godViewPlayers(record.players);
  if (rule !== null && rule.player_count !== players.length) throw invalid();
  const parsedLiveState = liveState(record.live_state);
  const parsedPhase = gamePhase(record.game_phase);
  const parsedMatchState =
    record.match_state == null ? null : matchState(record.match_state);
  return {
    ...runtimeProjection(record, parsedLiveState, parsedPhase, parsedMatchState),
    protocol_version: literal(record.protocol_version, [1] as const),
    type: literal(record.type, ["god_view.identity_snapshot"]),
    api_version: literal(record.api_version, ["v2"]),
    audience: literal(record.audience, ["spectator_god_view"]),
    game_id: id(record.game_id, "v2_game_"),
    run_id: id(record.run_id, "v2_run_"),
    live_state: parsedLiveState,
    game_phase: parsedPhase,
    match_state: parsedMatchState,
    server_time: date(record.server_time),
    rule,
    players,
  };
}

export function parseServerMessage(raw: string): ServerMessage {
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
    const snapshot = exactObject(value, [
      "protocol_version",
      "type",
      "api_version",
      "audience",
      "game_id",
      "run_id",
      "live_state",
      "audio_mode",
      "match_status",
      "execution_state",
      "winner",
      "completion_reason",
      "completed_at",
      "game_phase",
      "match_state",
      "latest_presentation_seq",
      "server_time",
      "public_rule",
      "public_players",
      "public_role_assignment",
      "current_presentation",
    ]);
    const parsedLiveState = liveState(snapshot.live_state);
    const parsedPhase = gamePhase(snapshot.game_phase);
    const parsedMatchState =
      snapshot.match_state == null ? null : matchState(snapshot.match_state);
    return {
      ...base,
      ...runtimeProjection(snapshot, parsedLiveState, parsedPhase, parsedMatchState),
      type,
      api_version: literal(snapshot.api_version, ["v2"]),
      audience: literal(snapshot.audience, ["player_public"]),
      live_state: parsedLiveState,
      game_phase: parsedPhase,
      match_state: parsedMatchState,
      latest_presentation_seq: integer(snapshot.latest_presentation_seq, 0),
      public_rule:
        snapshot.public_rule === null ? null : publicRule(snapshot.public_rule),
      public_players: publicPlayerSeats(snapshot.public_players),
      public_role_assignment: publicRoleAssignmentStatus(
        snapshot.public_role_assignment,
      ),
      current_presentation:
        snapshot.current_presentation === null
          ? null
          : presentation(snapshot.current_presentation),
    };
  }
  if (type === "director.live_snapshot") {
    const snapshot = exactObject(value, [
      "protocol_version",
      "type",
      "api_version",
      "audience",
      "game_id",
      "run_id",
      "live_state",
      "audio_mode",
      "match_status",
      "execution_state",
      "winner",
      "completion_reason",
      "completed_at",
      "game_phase",
      "match_state",
      "latest_presentation_seq",
      "server_time",
      "rule",
      "players",
      "current_scene",
      "current_presentation",
    ]);
    const rule = snapshot.rule === null ? null : publicRule(snapshot.rule);
    const players = godViewPlayers(snapshot.players);
    if (rule !== null && rule.player_count !== players.length) throw invalid();
    const parsedLiveState = liveState(snapshot.live_state);
    const parsedPhase = gamePhase(snapshot.game_phase);
    const parsedMatchState =
      snapshot.match_state == null ? null : matchState(snapshot.match_state);
    return {
      ...base,
      ...runtimeProjection(snapshot, parsedLiveState, parsedPhase, parsedMatchState),
      type,
      api_version: literal(snapshot.api_version, ["v2"]),
      audience: literal(snapshot.audience, ["spectator_directed"]),
      live_state: parsedLiveState,
      game_phase: parsedPhase,
      match_state: parsedMatchState,
      latest_presentation_seq: integer(snapshot.latest_presentation_seq, 0),
      rule,
      players,
      current_scene: directorScene(snapshot.current_scene),
      current_presentation:
        snapshot.current_presentation === null
          ? null
          : presentation(snapshot.current_presentation),
    };
  }
  if (type === "god_view.live_snapshot") {
    const snapshot = exactObject(value, [
      "protocol_version",
      "type",
      "api_version",
      "audience",
      "game_id",
      "run_id",
      "live_state",
      "audio_mode",
      "match_status",
      "execution_state",
      "winner",
      "completion_reason",
      "completed_at",
      "game_phase",
      "match_state",
      "latest_presentation_seq",
      "server_time",
      "rule",
      "players",
      "current_presentation",
    ]);
    const rule = snapshot.rule === null ? null : publicRule(snapshot.rule);
    const players = godViewPlayers(snapshot.players);
    if (rule !== null && rule.player_count !== players.length) throw invalid();
    const parsedLiveState = liveState(snapshot.live_state);
    const parsedPhase = gamePhase(snapshot.game_phase);
    const parsedMatchState =
      snapshot.match_state == null ? null : matchState(snapshot.match_state);
    return {
      ...base,
      ...runtimeProjection(snapshot, parsedLiveState, parsedPhase, parsedMatchState),
      type,
      api_version: literal(snapshot.api_version, ["v2"]),
      audience: literal(snapshot.audience, ["spectator_god_view"]),
      live_state: parsedLiveState,
      game_phase: parsedPhase,
      match_state: parsedMatchState,
      latest_presentation_seq: integer(snapshot.latest_presentation_seq, 0),
      rule,
      players,
      current_presentation:
        snapshot.current_presentation === null
          ? null
          : presentation(snapshot.current_presentation),
    };
  }
  if (type === "director.scene_changed") {
    const scene = exactObject(value, [
      "protocol_version",
      "type",
      "game_id",
      "run_id",
      "server_time",
      "scene_kind",
      "action_id",
      "action_type",
      "ability_id",
      "actor_player_id",
    ]);
    return {
      ...base,
      type,
      ...directorScene({
        scene_kind: scene.scene_kind,
        action_id: scene.action_id,
        action_type: scene.action_type,
        ability_id: scene.ability_id,
        actor_player_id: scene.actor_player_id,
      }),
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
  if (type === "game.phase_changed") {
    return {
      ...base,
      type,
      phase_seq: integer(value.phase_seq, 1),
      previous_phase_id: phaseId(value.previous_phase_id),
      phase_id: phaseId(value.phase_id),
      phase_state: phaseState(value.phase_state),
    };
  }
  if (type === "night.progress_changed") {
    return {
      ...base,
      type,
      stage: literal(value.stage, [
        "night_started",
        "actions_in_progress",
        "night_resolved",
        "dawn_announced",
      ]),
      latest_presentation_seq: integer(value.latest_presentation_seq, 0),
    };
  }
  if (type === "ability.progress_changed") {
    return {
      ...base,
      type,
      ability_id: text(value.ability_id),
      status: text(value.status),
      actor_player_id:
        value.actor_player_id === null ? null : text(value.actor_player_id),
      target_player_id:
        value.target_player_id === null ? null : text(value.target_player_id),
      round_no: value.round_no === null ? null : integer(value.round_no, 1),
    };
  }
  if (type === "dawn.result_announced") {
    if (!Array.isArray(value.dead_player_ids)) throw invalid();
    return {
      ...base,
      type,
      dead_player_ids: value.dead_player_ids.map(text),
    };
  }
  if (type === "god_view.night_resolved") {
    if (!Array.isArray(value.deaths)) throw invalid();
    return {
      ...base,
      type,
      deaths: value.deaths.map((item) => {
        const death = exactObject(item, ["player_id", "cause"]);
        return { player_id: text(death.player_id), cause: text(death.cause) };
      }),
      attack_prevented_by:
        value.attack_prevented_by === null
          ? null
          : text(value.attack_prevented_by),
    };
  }
  if (type === "player.state_changed") {
    return {
      ...base,
      type,
      player_id: text(value.player_id),
      alive: boolean(value.alive),
      cause: value.cause === null ? null : text(value.cause),
    };
  }
  if (type === "match.state_changed") {
    return {
      ...base,
      type,
      ...matchState(value),
    };
  }
  if (type === "day.progress_changed") {
    const hasCompletedCount = value.completed_count !== undefined;
    const hasTotalCount = value.total_count !== undefined;
    if (hasCompletedCount !== hasTotalCount) throw invalid();
    const completedCount = hasCompletedCount
      ? integer(value.completed_count, 0)
      : null;
    const totalCount = hasTotalCount ? integer(value.total_count, 1) : null;
    if (
      completedCount !== null &&
      totalCount !== null &&
      completedCount > totalCount
    ) {
      throw invalid();
    }
    return {
      ...base,
      type,
      round_no: integer(value.round_no, 1),
      stage: text(value.stage),
      completed_count: completedCount,
      total_count: totalCount,
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
      final_chunk_index: integer(value.final_chunk_index, -1),
      final_sample_cursor: integer(value.final_sample_cursor, 0),
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

export function decodeAudioFrame(value: ArrayBuffer): AudioFrame {
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

function presentation(value: unknown): Presentation {
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

function gamePhase(value: unknown): GamePhase {
  const record = exactObject(value, ["phase_seq", "phase_id", "phase_state"]);
  return {
    phase_seq: integer(record.phase_seq, 0),
    phase_id: phaseId(record.phase_id),
    phase_state: phaseState(record.phase_state),
  };
}

function matchState(value: unknown): MatchState {
  const record = object(value);
  return {
    round_no: integer(record.round_no, 1),
    sheriff_player_id:
      record.sheriff_player_id === null ? null : text(record.sheriff_player_id),
    sheriff_badge_state: literal(record.sheriff_badge_state, [
      "disabled",
      "pending",
      "held",
      "destroyed",
    ]),
    winner:
      record.winner === null
        ? null
        : literal(record.winner, ["villagers", "werewolves"]),
  };
}

function parseActor(value: unknown): Presentation["actor"] {
  const record = object(value);
  return {
    kind: literal(record.kind, ["judge", "player"]),
    id: text(record.id),
  };
}

function publicPlayerSeats(value: unknown): PublicPlayerSeat[] {
  if (!Array.isArray(value) || value.length > 24) throw invalid();
  const players = value.map((item) => {
    const record = exactObject(item, [
      "seat",
      "player_id",
      "display_name",
      "avatar_url",
      "alive",
    ]);
    return {
      seat: integer(record.seat, 1),
      player_id: text(record.player_id),
      display_name: text(record.display_name),
      avatar_url: record.avatar_url === null ? null : text(record.avatar_url),
      alive: boolean(record.alive),
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

function publicRule(value: unknown): PublicRuleSnapshot {
  const record = exactObject(value, [
    "rule_id",
    "name",
    "version",
    "player_count",
    "roles",
    "max_rounds",
    "sheriff_enabled",
    "werewolf_self_explosion_enabled",
    "exile_last_words_enabled",
    "first_night_last_words_enabled",
  ]);
  if (!Array.isArray(record.roles) || record.roles.length === 0 || record.roles.length > 24) {
    throw invalid();
  }
  const roles = record.roles.map((value) => {
    const role = exactObject(value, ["role", "count"]);
    return { role: text(role.role), count: boundedInteger(role.count, 1, 24) };
  });
  const playerCount = boundedInteger(record.player_count, 1, 24);
  const seenRoles = new Set<string>();
  let roleCount = 0;
  for (const role of roles) {
    if (seenRoles.has(role.role)) throw invalid();
    seenRoles.add(role.role);
    roleCount += role.count;
  }
  if (roleCount !== playerCount) throw invalid();
  return {
    rule_id: text(record.rule_id),
    name: text(record.name),
    version: text(record.version),
    player_count: playerCount,
    roles,
    max_rounds: boundedInteger(record.max_rounds, 1, 20),
    sheriff_enabled: nullableBoolean(record.sheriff_enabled),
    werewolf_self_explosion_enabled: nullableBoolean(
      record.werewolf_self_explosion_enabled,
    ),
    exile_last_words_enabled: nullableBoolean(record.exile_last_words_enabled),
    first_night_last_words_enabled: nullableBoolean(
      record.first_night_last_words_enabled,
    ),
  };
}

function publicRoleAssignmentStatus(value: unknown): PublicRoleAssignmentStatus {
  const record = exactObject(value, ["state", "assigned_count"]);
  const state = literal(record.state, ["sealed", "unavailable"]);
  const assignedCount = boundedInteger(record.assigned_count, 0, 24);
  if ((state === "sealed" && assignedCount === 0) ||
      (state === "unavailable" && assignedCount !== 0)) {
    throw invalid();
  }
  return { state, assigned_count: assignedCount };
}

function directorScene(value: unknown): DirectorScene {
  const record = exactObject(value, [
    "scene_kind",
    "action_id",
    "action_type",
    "ability_id",
    "actor_player_id",
  ]);
  return {
    scene_kind: literal(record.scene_kind, [
      "opening",
      "public_stage",
      "nightfall",
      "werewolves",
      "guard",
      "seer",
      "witch",
      "hunter",
      "dawn",
      "terminal",
    ]),
    action_id: record.action_id === null ? null : text(record.action_id),
    action_type: record.action_type === null ? null : text(record.action_type),
    ability_id: record.ability_id === null ? null : text(record.ability_id),
    actor_player_id:
      record.actor_player_id === null ? null : text(record.actor_player_id),
  };
}

function godViewPlayers(value: unknown): GodViewPlayerIdentity[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 24) throw invalid();
  const players = value.map((item) => {
    const record = exactObject(item, [
      "seat",
      "player_id",
      "display_name",
      "avatar_url",
      "role",
      "team",
      "alive",
      "death_cause",
    ]);
    return {
      seat: boundedInteger(record.seat, 1, 24),
      player_id: text(record.player_id),
      display_name: text(record.display_name),
      avatar_url: record.avatar_url === null ? null : text(record.avatar_url),
      role: text(record.role),
      team: record.team === null ? null : text(record.team),
      alive: boolean(record.alive),
      death_cause: record.death_cause === null ? null : text(record.death_cause),
    };
  });
  const seats = new Set<number>();
  const playerIds = new Set<string>();
  let previousSeat = 0;
  for (const player of players) {
    if (
      player.seat <= previousSeat ||
      seats.has(player.seat) ||
      playerIds.has(player.player_id)
    ) {
      throw invalid();
    }
    previousSeat = player.seat;
    seats.add(player.seat);
    playerIds.add(player.player_id);
  }
  return players;
}

function runtimeProjection(
  record: Record<string, unknown>,
  currentLiveState: LiveState,
  phase: GamePhase,
  match: MatchState | null,
): RuntimeProjection {
  const audioMode =
    record.audio_mode === undefined
      ? "legacy_unknown"
      : literal(record.audio_mode, ["tts", "text_only", "legacy_unknown"]);
  const winner =
    record.winner === undefined
      ? (match?.winner ?? null)
      : record.winner === null
        ? null
        : literal(record.winner, ["villagers", "werewolves"]);
  if (winner !== null && match?.winner != null && match.winner !== winner) {
    throw invalid();
  }
  const derivedMatchStatus: MatchStatus =
    phase.phase_state === "game_completed" && winner !== null
      ? "completed"
      : currentLiveState === "failed" || phase.phase_state === "failed"
        ? "failed"
        : currentLiveState === "canceled"
          ? "canceled"
          : currentLiveState === "waiting_to_start"
            ? "waiting"
            : "running";
  const matchStatus =
    record.match_status === undefined
      ? derivedMatchStatus
      : literal(record.match_status, [
          "waiting",
          "running",
          "completed",
          "failed",
          "canceled",
        ]);
  const executionState =
    record.execution_state === undefined
      ? currentLiveState === "failed" ||
        currentLiveState === "canceled" ||
        phase.phase_state === "game_completed"
        ? "stopped"
        : "unowned"
      : literal(record.execution_state, ["unowned", "owned", "stale", "stopped"]);
  return {
    audio_mode: audioMode,
    match_status: matchStatus,
    execution_state: executionState,
    winner,
    completion_reason:
      record.completion_reason == null ? null : text(record.completion_reason),
    completed_at: record.completed_at == null ? null : date(record.completed_at),
  };
}

function liveState(value: unknown): LiveState {
  return literal(value, [
    "waiting_to_start",
    "ready",
    "generating",
    "broadcasting",
    "finalizing",
    "awaiting_observation",
    "paused_model_error",
    "canceled",
    "failed",
  ]);
}

function phaseId(value: unknown): GamePhase["phase_id"] {
  const result = text(value);
  if (
    result !== "legacy" &&
    result !== "opening" &&
    result !== "first_night" &&
    !/^(day_[1-9]|day_1[0-9]|day_20|night_[2-9]|night_1[0-9]|night_20)$/.test(
      result,
    )
  ) {
    throw invalid();
  }
  return result;
}

function phaseState(value: unknown): GamePhase["phase_state"] {
  return literal(value, [
    "legacy_frozen",
    "opening_ready",
    "opening_speech_closed",
    "nightfall_ready",
    "nightfall_announced",
    "night_running",
    "dawn_announcement_ready",
    "dawn_announced",
    "dawn_reactions_ready",
    "public_day_ready",
    "sheriff_election_ready",
    "public_discussion_open",
    "sheriff_election_open",
    "game_completed",
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

function boundedInteger(value: unknown, minimum: number, maximum: number): number {
  const result = integer(value, minimum);
  if (result > maximum) throw invalid();
  return result;
}

function literal<const T extends string | number>(value: unknown, values: readonly T[]): T {
  if (!values.includes(value as T)) throw invalid();
  return value as T;
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") throw invalid();
  return value;
}

function nullableBoolean(value: unknown): boolean | null {
  return value === null ? null : boolean(value);
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

function godViewApiPath(value: unknown): string {
  const result = apiPath(value);
  if (!result.startsWith("/api/v2/god-view/games/")) throw invalid();
  return result;
}

function godViewAccessToken(value: unknown): string {
  const result = text(value);
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(result)) throw invalid();
  return result;
}

function invalid(): Error {
  return new Error("V2 实时直播协议无效");
}
