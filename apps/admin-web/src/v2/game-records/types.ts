export type V2GameRecordListItem = {
  game_id: string;
  title: string;
  status: string;
  current_run_id: string;
  record_schema_version: number;
  last_record_seq: number;
  last_presentation_seq: number;
  phase_seq: number;
  phase_id: string;
  phase_state: string;
  created_at: string;
  updated_at: string;
};

export type V2GameRecordList = {
  items: V2GameRecordListItem[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    pages: number;
  };
};

export type V2GameRun = {
  run_id: string;
  attempt_no: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  stop_requested_at: string | null;
};

export type V2GameControlResult = {
  action: "stop";
  game_id: string;
  run_id: string;
  run_status: string;
  stop_requested_at: string;
  replayed: boolean;
};

export type V2GameRecordEvent = {
  event_id: number;
  record_seq: number;
  run_id: string;
  event_type: string;
  payload_schema_version: number;
  payload: Record<string, unknown>;
  created_at: string;
};

export type V2GamePresentation = {
  presentation_seq: number;
  presentation_id: string;
  action_id: string | null;
  activation_id: string | null;
  phase_id: string;
  actor_kind: string;
  actor_id: string;
  audience: string;
  speech_id: string;
  segment_index: number;
  source_event_id: number;
  state: string;
  subtitle_text: string;
  voice_asset_id: string | null;
  audio_duration_ms: number | null;
  created_at: string;
  closed_at: string | null;
};

export type V2VoiceAsset = {
  voice_asset_id: string;
  action_id: string;
  activation_id: string | null;
  audience: string;
  presentation_id: string;
  speech_id: string;
  segment_index: number;
  state: string;
  mime_type: string;
  sample_rate: number;
  channels: number;
  sample_count: number | null;
  duration_ms: number | null;
  pcm_sha256: string | null;
  size_bytes: number | null;
  audio_url: string | null;
  created_at: string;
  completed_at: string | null;
};

export type V2GameRecordDetail = V2GameRecordListItem & {
  rule_snapshot: Record<string, unknown>;
  players_snapshot: Array<Record<string, unknown>>;
  ability_snapshot: Record<string, unknown>;
  runs: V2GameRun[];
  events: V2GameRecordEvent[];
  presentations: V2GamePresentation[];
  voice_assets: V2VoiceAsset[];
  player_states: Array<Record<string, unknown>>;
  action_windows: Array<Record<string, unknown>>;
  ability_instances: Array<Record<string, unknown>>;
  ability_activations: Array<Record<string, unknown>>;
  effect_intents: Array<Record<string, unknown>>;
  knowledge_facts: Array<Record<string, unknown>>;
};
