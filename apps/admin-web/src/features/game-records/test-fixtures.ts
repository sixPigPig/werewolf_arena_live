import type {
  AdminGameDebug,
  AdminGameDetail,
  AdminGameListItem,
} from "@/features/game-records/types";

export const contractRun = {
  run_id: "run_1234abcd",
  status: "completed",
  villager_model: "deepseek-v4-flash",
  werewolf_model: "doubao-seed-1-6-flash",
  max_rounds: 12,
  created_at: "2026-07-10T01:00:00Z",
  started_at: "2026-07-10T01:00:01Z",
  completed_at: "2026-07-10T01:03:00Z",
  event_count: 5,
  has_error: false,
} satisfies NonNullable<AdminGameListItem["latest_run"]>;

export const contractGameItem: AdminGameListItem = {
  session_id: "game_1234abcd",
  status: "complete",
  winner: "好人阵营",
  round_count: 1,
  resumable: false,
  rule_set: { id: "classic_8", name: "经典八人局", player_count: 8 },
  created_at: "2026-07-10T01:00:00Z",
  updated_at: "2026-07-10T01:03:00Z",
  latest_run: contractRun,
};

export const contractGameDetail: AdminGameDetail = {
  ...contractGameItem,
  players: [
    {
      seat: 1,
      name: "暮鸦归票",
      profile_id: "profile-1",
      model: "deepseek-v4-flash",
      role: "预言家",
      personality_id: "analytical",
      appearance_id: "default",
      avatar_image_url: "",
      tags: ["控场"],
    },
  ],
  rounds: [
    {
      number: 1,
      success: true,
      players: ["暮鸦归票"],
      public_summary: "首轮完成公开投票。",
      night_deaths: [
        { player: "雾灯听风", cause: "werewolf_attack", source: null },
      ],
      day_deaths: [],
      exiled: "灰塔",
      hunter_shot: null,
      idiot_revealed: null,
      sheriff: "暮鸦归票",
      votes: { 暮鸦归票: "灰塔" },
      sheriff_elected: "暮鸦归票",
      werewolf_self_exploded: null,
    },
  ],
  runs: [contractRun],
  recent_events: [
    {
      run_id: contractRun.run_id,
      event_id: 5,
      type: "game_completed",
      round: 1,
      phase: "summary",
      actor: null,
      action: null,
      created_at: "2026-07-10T01:03:00Z",
    },
  ],
  diagnostics: {
    run_count: 1,
    event_count: 5,
    failed_voice_count: 0,
    last_event: {
      run_id: contractRun.run_id,
      event_id: 5,
      type: "game_completed",
      round: 1,
      phase: "summary",
      actor: null,
      action: null,
      created_at: "2026-07-10T01:03:00Z",
    },
  },
};

export const contractGameDebug: AdminGameDebug = {
  session_id: contractGameItem.session_id,
  game_error: "Maximum rounds exceeded",
  run_errors: [
    { run_id: contractRun.run_id, error: "Upstream request timed out" },
  ],
};
