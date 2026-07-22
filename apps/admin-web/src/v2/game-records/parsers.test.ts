import { describe, expect, it } from "vitest";

import {
  parseV2GameRecordDetail,
  parseV2GameRecordList,
} from "@/v2/game-records/parsers";

const item = {
  game_id: "v2_game_0123456789abcdef",
  title: "首句验收对局",
  status: "awaiting_observation",
  current_run_id: "v2_run_0123456789abcdef",
  record_schema_version: 1,
  last_record_seq: 2,
  last_presentation_seq: 1,
  phase_seq: 2,
  phase_id: "first_night",
  phase_state: "nightfall_announced",
  created_at: "2026-07-21T10:00:00Z",
  updated_at: "2026-07-21T10:00:00Z",
};

describe("V2 game record parsers", () => {
  it("parses the independent V2 list contract", () => {
    const result = parseV2GameRecordList({
      items: [item],
      pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
    });

    expect(result.items[0]).toMatchObject({
      game_id: item.game_id,
      current_run_id: item.current_run_id,
      last_record_seq: 2,
      last_presentation_seq: 1,
    });
  });

  it("keeps record_seq and presentation_seq as separate detail sequences", () => {
    const result = parseV2GameRecordDetail({
      ...item,
      rule_snapshot: {},
      players_snapshot: [],
      ability_snapshot: {},
      runs: [
        {
          run_id: item.current_run_id,
          attempt_no: 1,
          status: "awaiting_observation",
          started_at: item.created_at,
          completed_at: null,
        },
      ],
      events: [
        {
          event_id: 2,
          record_seq: 2,
          run_id: item.current_run_id,
          event_type: "action_succeeded",
          payload_schema_version: 1,
          payload: { presentation_seq: 1 },
          created_at: item.created_at,
        },
      ],
      presentations: [
        {
          presentation_seq: 1,
          presentation_id: "v2_pres_0123456789abcdef",
          action_id: "v2_action_0123456789abcdef",
          activation_id: null,
          phase_id: "opening",
          actor_kind: "judge",
          actor_id: "judge",
          audience: "all",
          speech_id: "v2_speech_0123456789abcdef",
          segment_index: 0,
          source_event_id: 2,
          state: "closed",
          subtitle_text: "欢迎来到这场实时狼人杀对局。",
          voice_asset_id: "v2_voice_0123456789abcdef",
          audio_duration_ms: 1800,
          created_at: item.created_at,
          closed_at: item.updated_at,
        },
      ],
      voice_assets: [
        {
          voice_asset_id: "v2_voice_0123456789abcdef",
          action_id: "v2_action_0123456789abcdef",
          activation_id: null,
          audience: "all",
          presentation_id: "v2_pres_0123456789abcdef",
          speech_id: "v2_speech_0123456789abcdef",
          segment_index: 0,
          state: "ready",
          mime_type: "audio/wav",
          sample_rate: 24000,
          channels: 1,
          sample_count: 43200,
          duration_ms: 1800,
          pcm_sha256: "a".repeat(64),
          size_bytes: 86444,
          audio_url: "/api/v1/admin/v2/games/game/voice-assets/voice/audio",
          created_at: item.created_at,
          completed_at: item.updated_at,
        },
      ],
      player_states: [],
      action_windows: [],
      ability_instances: [],
      ability_activations: [],
      effect_intents: [],
      knowledge_facts: [],
    });

    expect(result.events[0].record_seq).toBe(2);
    expect(result.presentations[0]).toMatchObject({
      presentation_seq: 1,
      source_event_id: 2,
      speech_id: "v2_speech_0123456789abcdef",
      segment_index: 0,
    });
    expect(result.voice_assets[0]).toMatchObject({
      state: "ready",
      sample_count: 43200,
      duration_ms: 1800,
    });
  });

  it("rejects a malformed sequence", () => {
    expect(() =>
      parseV2GameRecordList({
        items: [{ ...item, last_record_seq: -1 }],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toThrow("V2 对局记录数据不完整或格式错误");
  });
});
