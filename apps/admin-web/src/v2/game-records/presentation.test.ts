import { describe, expect, it } from "vitest";

import {
  actionLabel,
  buildV2HistoricalIdentities,
  buildV2RoundSummaries,
  phaseLabel,
} from "@/v2/game-records/presentation";
import type {
  V2GameRecordEvent,
  V2PlayerIdentity,
} from "@/v2/game-records/types";

const identities: V2PlayerIdentity[] = [
  {
    seat: 1,
    player_id: "player-1",
    display_name: "阿青",
    avatar_url: null,
    role: "villager",
    team: "villagers",
    alive: false,
    death_cause: "werewolf_attack",
  },
  {
    seat: 2,
    player_id: "player-2",
    display_name: "白石",
    avatar_url: null,
    role: "werewolf",
    team: "werewolves",
    alive: false,
    death_cause: "exile",
  },
  {
    seat: 3,
    player_id: "player-3",
    display_name: "林晚",
    avatar_url: null,
    role: "hunter",
    team: "villagers",
    alive: true,
    death_cause: null,
  },
];

describe("V2 game record presentation", () => {
  it("localizes every action emitted by the V2 engines", () => {
    const labels = {
      judge_opening_speech: "开场播报",
      judge_nightfall_announcement: "夜幕播报",
      judge_hunter_shot_announcement: "猎人开枪播报",
      judge_werewolf_self_explosion: "狼人自爆播报",
      werewolf_attack_wake: "狼人睁眼",
      werewolf_attack_sleep: "狼人闭眼",
      judge_dawn_announcement: "天亮播报",
      judge_public_discussion_opening: "白天讨论开场",
      judge_sheriff_election_opening: "警长竞选开场",
      judge_sheriff_elected: "警长产生播报",
      judge_sheriff_badge_result: "警徽去向播报",
      judge_sheriff_badge_destroyed: "警徽流失播报",
      judge_exile_result: "放逐结果播报",
      judge_no_exile: "无人放逐播报",
      judge_day_summary: "日间总结",
      judge_game_completed: "对局结束播报",
      guard_protect_wake: "守卫睁眼",
      guard_protect_sleep: "守卫闭眼",
      seer_investigate_wake: "预言家睁眼",
      seer_investigate_result: "预言家查验结果",
      seer_investigate_sleep: "预言家闭眼",
      witch_wake: "女巫睁眼",
      witch_attack_observation: "女巫查看袭击目标",
      witch_sleep: "女巫闭眼",
      first_night_last_words: "首夜遗言",
      sheriff_run: "上警决定",
      sheriff_campaign_speech: "竞选发言",
      sheriff_withdraw: "退水决定",
      sheriff_vote: "警长投票",
      sheriff_pk_speech: "警长平票发言",
      sheriff_runoff_vote: "警长加赛投票",
      sheriff_speech_order: "警长选择发言顺序",
      day_speech: "白天发言",
      day_debate_speech: "白天发言",
      exile_vote: "放逐投票",
      exile_pk_speech: "放逐平票发言",
      exile_runoff_vote: "放逐加赛投票",
      exile_last_words: "遗言",
      hunter_death_shot: "猎人开枪决定",
      sheriff_badge_resolution: "警徽去向决定",
      werewolf_self_explosion: "狼人自爆决定",
      "ability_werewolf.attack_decision": "狼人袭击决策",
      "ability_guard.protect_decision": "守卫守护决策",
      "ability_seer.investigate_decision": "预言家查验决策",
      "ability_witch.heal_decision": "女巫使用解药决策",
      "ability_witch.poison_decision": "女巫使用毒药决策",
      "ability_hunter.death_shot_decision": "猎人开枪决策",
    };

    for (const [actionType, expected] of Object.entries(labels)) {
      expect(actionLabel(actionType)).toBe(expected);
    }
  });

  it("uses the persisted round number for numbered night labels", () => {
    expect(phaseLabel("first_night")).toBe("第 1 夜");
    expect(phaseLabel("day_1")).toBe("第 1 天");
    expect(phaseLabel("night_2")).toBe("第 2 夜");
    expect(phaseLabel("day_2")).toBe("第 2 天");
    expect(phaseLabel("night_3")).toBe("第 3 夜");
  });

  it("builds deterministic round digests from persisted settlement events", () => {
    const summaries = buildV2RoundSummaries(
      [
        event(1, "game_phase_changed", {
          phase_id: "first_night",
          phase_state: "nightfall_ready",
        }),
        event(2, "action_window_opened", {
          window_id: "window-1",
          window_type: "night",
          round_no: 1,
        }),
        event(3, "action_window_closed", {
          window_id: "window-1",
          result: {
            peaceful: false,
            deaths: [
              { player_id: "player-1", cause: "werewolf_attack" },
            ],
          },
        }),
        event(4, "sheriff_elected", {
          round_no: 1,
          player_id: "player-3",
        }),
        event(5, "player_exiled", {
          round_no: 1,
          player_id: "player-2",
        }),
        event(6, "game_phase_changed", {
          previous_phase_id: "day_1",
          phase_id: "night_2",
          phase_state: "nightfall_ready",
        }),
        event(7, "action_window_opened", {
          window_id: "window-2",
          window_type: "night",
          round_no: 2,
        }),
        event(8, "action_window_closed", {
          window_id: "window-2",
          result: { peaceful: true, deaths: [] },
        }),
        event(9, "hunter_response_resolved", {
          round_no: 2,
          hunter_player_id: "player-3",
          target_player_id: null,
        }),
        event(10, "game_completed", {
          round_no: 2,
          winner: "villagers",
        }),
      ],
      identities,
      "awaiting_observation",
    );

    expect(summaries).toHaveLength(2);
    expect(summaries[0]).toMatchObject({
      roundNo: 1,
      reachedDay: true,
      status: "succeeded",
      firstRecordSeq: 1,
      lastRecordSeq: 5,
      endedAt: "2026-07-29T08:00:06Z",
    });
    expect(summaries[0].highlights.map((item) => item.label)).toEqual([
      "夜间出局：1号 阿青（村民）（狼人袭击）",
      "警长产生：3号 林晚（猎人）",
      "投票放逐：2号 白石（狼人）",
    ]);
    expect(summaries[1]).toMatchObject({
      roundNo: 2,
      reachedDay: false,
      status: "succeeded",
      firstRecordSeq: 6,
      lastRecordSeq: 10,
      endedAt: "2026-07-29T08:00:10Z",
    });
    expect(summaries[1].highlights.map((item) => item.label)).toEqual([
      "平安夜",
      "猎人未开枪：3号 林晚（猎人）",
      "对局结束：好人阵营获胜",
    ]);
  });

  it("marks the last digest as canceled when the durable game is canceled", () => {
    const summaries = buildV2RoundSummaries(
      [
        event(1, "game_phase_changed", {
          phase_id: "first_night",
          phase_state: "nightfall_ready",
        }),
        event(2, "game_canceled", {
          reason_code: "operator_interrupted",
        }),
      ],
      identities,
      "canceled",
    );

    expect(summaries[0]).toMatchObject({
      roundNo: 1,
      status: "canceled",
      endedAt: "2026-07-29T08:00:02Z",
    });
    expect(summaries[0].highlights[0].label).toBe("管理员已中止本局");
  });

  it("reconstructs player life state at a historical fact sequence", () => {
    const events = [
      event(1, "game_phase_changed", {
        phase_id: "first_night",
      }),
      event(2, "action_window_closed", {
        result: {
          deaths: [
            { player_id: "player-1", cause: "werewolf_attack" },
          ],
        },
      }),
      event(3, "player_exiled", {
        player_id: "player-2",
      }),
    ];

    expect(
      buildV2HistoricalIdentities(events, identities, 1).map((item) => ({
        alive: item.alive,
        cause: item.death_cause,
        playerId: item.player_id,
      })),
    ).toEqual([
      { alive: true, cause: null, playerId: "player-1" },
      { alive: true, cause: null, playerId: "player-2" },
      { alive: true, cause: null, playerId: "player-3" },
    ]);

    expect(
      buildV2HistoricalIdentities(events, identities, 2).map((item) => ({
        alive: item.alive,
        cause: item.death_cause,
        playerId: item.player_id,
      })),
    ).toEqual([
      { alive: false, cause: "werewolf_attack", playerId: "player-1" },
      { alive: true, cause: null, playerId: "player-2" },
      { alive: true, cause: null, playerId: "player-3" },
    ]);

    expect(buildV2HistoricalIdentities(events, identities, 3)).toEqual(
      identities,
    );
  });
});

function event(
  recordSeq: number,
  eventType: string,
  payload: Record<string, unknown>,
): V2GameRecordEvent {
  return {
    event_id: recordSeq,
    record_seq: recordSeq,
    run_id: "v2_run_summary",
    event_type: eventType,
    payload_schema_version: 1,
    payload,
    created_at: `2026-07-29T08:00:${String(recordSeq).padStart(2, "0")}Z`,
  };
}
