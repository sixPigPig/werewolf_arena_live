import { describe, expect, it } from "vitest";

import {
  actionLabel,
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
  it("distinguishes the sheriff signup decision from the campaign speech", () => {
    expect(actionLabel("sheriff_run")).toBe("上警决定");
    expect(actionLabel("sheriff_campaign_speech")).toBe("竞选发言");
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
