import { describe, expect, it } from "vitest";

import {
  deriveGodViewState,
  deriveLiveSpectatorState,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";

import {
  deriveMobileLiveFocusPresentation,
  getActiveTheaterPlayer,
} from "./mobileLiveActionModel";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "game_started",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: partial.created_at ?? "2026-04-24T12:00:00Z",
    round: partial.round ?? null,
    phase: partial.phase ?? null,
    actor: partial.actor ?? null,
    action: partial.action ?? null,
    payload: partial.payload ?? {},
  };
}

const STARTED = event({
  id: 1,
  type: "game_started",
  payload: {
    players: [
      { name: "1号 狼人A", role: "werewolf", model: "deepseek-chat" },
      { name: "2号 女巫", role: "witch", model: "deepseek-chat" },
      { name: "3号 平民A", role: "villager", model: "deepseek-chat" },
      { name: "4号 预言家", role: "seer", model: "deepseek-chat" },
      { name: "5号 守卫", role: "guard", model: "deepseek-chat" },
      { name: "6号 平民B", role: "villager", model: "deepseek-chat" },
      { name: "7号 平民C", role: "villager", model: "deepseek-chat" },
      { name: "8号 猎人", role: "hunter", model: "deepseek-chat" },
    ],
  },
});

function buildState(events: LiveGameEvent[]) {
  const spectator = deriveLiveSpectatorState(events);
  return deriveGodViewState(events, spectator, "暗夜古堡");
}

function focusFor(events: LiveGameEvent[]) {
  const state = buildState(events);
  const currentEvent = events.at(-1) ?? null;
  return { state, presentation: deriveMobileLiveFocusPresentation(currentEvent, state) };
}

describe("deriveMobileLiveFocusPresentation", () => {
  it("returns a waiting focus when there is no current event", () => {
    const state = buildState([STARTED]);
    const presentation = deriveMobileLiveFocusPresentation(null, state);

    expect(presentation.kind).toBe("waiting");
    expect(presentation.tone).toBe("neutral");
    expect(presentation.accessibleText).toBeTruthy();
  });

  it("shows the judge naming the attacked player before the witch acts", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "judge_cue",
        round: 1,
        phase: "night",
        action: "witch_death",
        payload: {
          visible_text: "今晚被狼人袭击的玩家是3号玩家。",
          target: "3号玩家",
        },
      }),
    ]);

    expect(presentation.eyebrow).toBe("法官提示");
    expect(presentation.title).toBe("今晚被狼人袭击的玩家是3号玩家。");
    expect(presentation.targetName).toBe("3号 平民A");
    expect(presentation.tone).toBe("danger");
  });

  it("shows the sheriff raise-hands cue as a daytime judge prompt", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "judge_cue",
        round: 1,
        phase: "day",
        action: "sheriff_raise_hands",
        payload: { visible_text: "想要竞选警长的玩家请举手。" },
      }),
    ]);

    expect(presentation.kind).toBe("waiting");
    expect(presentation.eyebrow).toBe("法官提示");
    expect(presentation.title).toBe("想要竞选警长的玩家请举手。");
    expect(presentation.detail).toBe("白天流程");
  });

  it("shows pending speaker count for the explicit self-explosion interruption cue", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "judge_cue",
        round: 3,
        phase: "day",
        action: "self_explosion_skip",
        payload: {
          schema_version: 1,
          cue_id: "self_explosion_skip",
          visible_text: "本轮剩余发言和放逐投票终止，直接进入夜晚。",
          static_asset_id: "self_explosion_skip",
          params: {
            stage: "debate",
            pending_actors: ["5号玩家", "7号玩家"],
          },
        },
      }),
    ]);

    expect(presentation.kind).toBe("skill");
    expect(presentation.tone).toBe("danger");
    expect(presentation.detail).toBe("剩余 2 名玩家未发言，放逐投票取消");
  });

  it("shows the elected sheriff and winning vote count", () => {
    const { state, presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "day",
        actor: "4号 预言家",
        payload: {
          sheriff: "4号 预言家",
          sheriff_elected: "4号 预言家",
          sheriff_votes: {
            "2号 女巫": "4号 预言家",
            "3号 平民A": "4号 预言家",
            "5号 守卫": "4号 预言家",
          },
          active_players: [
            "1号 狼人A",
            "2号 女巫",
            "3号 平民A",
            "4号 预言家",
            "5号 守卫",
            "6号 平民B",
            "7号 平民C",
            "8号 猎人",
          ],
        },
      }),
    ]);

    expect(presentation).toMatchObject({
      kind: "skill",
      tone: "success",
      actorName: "4号 预言家",
      actorSeat: 4,
      eyebrow: "警长竞选",
      title: "4号 当选警长",
      detail: "3票当选 · 获得警徽",
    });
    expect(state.players.find((player) => player.name === "4号 预言家")?.isSheriff).toBe(
      true,
    );
  });

  it("describes a night phase start as a night-action focus", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "night",
        payload: { active_players: ["1号 狼人A"] },
      }),
    ]);

    expect(presentation.kind).toBe("night-action");
    expect(presentation.title).toContain("夜间行动");
    expect(presentation.eyebrow).toContain("夜");
  });

  it("describes a werewolf team action without picking an arbitrary wolf portrait", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "night",
        payload: { active_players: ["1号 狼人A"] },
      }),
      event({
        id: 3,
        type: "action_requested",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
        payload: { options: ["7号 平民C"] },
      }),
    ]);

    expect(presentation.kind).toBe("night-action");
    expect(presentation.tone).toBe("danger");
    expect(presentation.actorName).toBe("狼人阵营");
    expect(presentation.actorSeat).toBeNull();
    expect(presentation.title).toContain("袭击");
    expect(presentation.accessibleText).toContain("狼人阵营");
  });

  it("describes a parsed werewolf kill with its target", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "night",
        payload: { active_players: ["1号 狼人A"] },
      }),
      event({
        id: 3,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
        payload: { choice: "7号 平民C" },
      }),
    ]);

    expect(presentation.kind).toBe("night-action");
    expect(presentation.title).toContain("狼人最终目标");
    expect(presentation.detail).toBe("袭击 7号");
    expect(presentation.targetName).toBe("7号 平民C");
    expect(presentation.accessibleText).toContain("7号");
  });

  it("describes each wolf's kill vote before the final target", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "werewolf_kill_vote",
        payload: { choice: "7号玩家", vote_round: 2 },
      }),
    ]);

    expect(presentation.kind).toBe("night-action");
    expect(presentation.actorName).toBe("1号 狼人A");
    expect(presentation.actorSeat).toBe(1);
    expect(presentation.eyebrow).toBe("狼人刀票");
    expect(presentation.title).toBe("选择袭击目标");
    expect(presentation.detail).toBe("第 2 轮 · 投 7号");
    expect(presentation.targetName).toBe("7号 平民C");
  });

  it("shows each private wolf proposal in God View", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "werewolf_discuss",
        payload: {
          choice: "4号玩家",
          message: "建议刀4号，他像预言家。",
          decision_stage: "proposal",
        },
      }),
    ]);

    expect(presentation.kind).toBe("night-action");
    expect(presentation.eyebrow).toBe("狼队密聊");
    expect(presentation.title).toBe("建议刀4号，他像预言家。");
    expect(presentation.detail).toBe("建议袭击 4号");
    expect(presentation.actorName).toBe("1号 狼人A");
  });

  it("shows the judge revealing tiebreak authority only when a tie occurs", () => {
    const visibleText =
      "狼队刀口出现平票。本夜由1号玩家行使归票权，请从4号玩家、7号玩家中确认最终刀口。";
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "judge_cue",
        round: 1,
        phase: "night",
        action: "werewolf_tiebreak_start",
        payload: { visible_text: visibleText },
      }),
    ]);

    expect(presentation.eyebrow).toBe("法官提示");
    expect(presentation.title).toBe(visibleText);
    expect(presentation.detail).toBe("夜间流程");
  });

  it("keeps a private action visible while the model is still responding", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "model_thinking_tick",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
        payload: { elapsed_ms: 1200 },
      }),
    ]);

    expect(presentation.kind).toBe("night-action");
    expect(presentation.actorName).toBe("狼人阵营");
    expect(presentation.title).toContain("袭击");
    expect(presentation.title).not.toContain("等待对局进展");
  });

  it("normalizes seat-only player aliases before rendering or highlighting", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
        payload: { choice: "7号玩家" },
      }),
    ]);

    expect(presentation.detail).toBe("袭击 7号");
    expect(presentation.detail).not.toContain("玩家号");
    expect(presentation.targetName).toBe("7号 平民C");
  });

  it("describes guard, seer, witch save, witch poison and skip actions", () => {
    const guard = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "5号 守卫",
        action: "protect",
        payload: { choice: "7号 平民C" },
      }),
    ]).presentation;
    expect(guard.title).toContain("守卫守护");
    expect(guard.targetName).toBe("7号 平民C");
    expect(guard.tone).toBe("success");

    const seer = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "4号 预言家",
        action: "investigate",
        payload: {
          choice: "1号 狼人A",
          result: { alignment: "werewolf" },
        },
      }),
    ]).presentation;
    expect(seer.title).toContain("预言家查验");
    expect(seer.targetName).toBe("1号 狼人A");
    expect(seer.detail).toContain("狼人");
    expect(seer.tone).toBe("info");

    const save = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_save",
        payload: { choice: "7号 平民C" },
      }),
    ]).presentation;
    expect(save.title).toContain("女巫解药");
    expect(save.detail).toContain("救");
    expect(save.targetName).toBe("7号 平民C");
    expect(save.tone).toBe("success");

    const saveSkip = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_save",
        payload: { choice: "skip" },
      }),
    ]).presentation;
    expect(saveSkip.detail).toContain("未使用");
    expect(saveSkip.targetName).toBeNull();
    expect(saveSkip.tone).toBe("neutral");

    const poison = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_poison",
        payload: { choice: "6号 平民B" },
      }),
    ]).presentation;
    expect(poison.title).toContain("女巫毒药");
    expect(poison.detail).toContain("毒");
    expect(poison.targetName).toBe("6号 平民B");
    expect(poison.tone).toBe("danger");

    const poisonSkip = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_poison",
        payload: { choice: "skip" },
      }),
    ]).presentation;
    expect(poisonSkip.detail).toContain("未使用");
    expect(poisonSkip.tone).toBe("neutral");
  });

  it("describes vote request, parsed vote and progress", () => {
    const request = focusFor([
      STARTED,
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "vote",
        payload: {
          active_players: ["1号 狼人A", "2号 女巫", "8号 猎人"],
        },
      }),
      event({
        id: 3,
        type: "action_requested",
        round: 1,
        phase: "vote",
        actor: "8号 猎人",
        action: "vote",
        payload: { options: ["1号 狼人A"] },
      }),
    ]).presentation;
    expect(request.kind).toBe("vote-action");
    expect(request.actorSeat).toBe(8);
    expect(request.title).toContain("投票");

    const parsed = focusFor([
      STARTED,
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "vote",
        payload: {
          active_players: ["1号 狼人A", "2号 女巫", "8号 猎人"],
        },
      }),
      event({
        id: 3,
        type: "action_parsed",
        round: 1,
        phase: "vote",
        actor: "8号 猎人",
        action: "vote",
        payload: { choice: "1号 狼人A" },
      }),
    ]).presentation;
    expect(parsed.kind).toBe("vote-action");
    expect(parsed.targetName).toBe("1号 狼人A");
    expect(parsed.accessibleText).toContain("已投票");
  });

  it("describes a weighted vote tally result without trailing zeros", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "vote",
        payload: {
          active_players: ["1号 狼人A", "2号 女巫", "3号 平民A"],
        },
      }),
      event({
        id: 3,
        type: "state_updated",
        round: 1,
        phase: "vote",
        payload: {
          votes: { "1号 狼人A": "2号 女巫", "3号 平民A": "2号 女巫" },
          vote_weights: { "1号 狼人A": 1.5 },
        },
      }),
    ]);

    expect(presentation.kind).toBe("vote-result");
    expect(presentation.detail).toContain("2.5票");
    expect(presentation.detail).not.toContain("2.50");
    expect(presentation.accessibleText).toContain("2.5票");
  });

  it("describes a tied vote tally result", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "vote",
        payload: {
          active_players: ["1号 狼人A", "2号 女巫", "3号 平民A", "6号 平民B"],
        },
      }),
      event({
        id: 3,
        type: "state_updated",
        round: 1,
        phase: "vote",
        payload: {
          votes: {
            "1号 狼人A": "3号 平民A",
            "2号 女巫": "3号 平民A",
            "3号 平民A": "6号 平民B",
            "6号 平民B": "6号 平民B",
          },
        },
      }),
    ]);

    expect(presentation.kind).toBe("vote-result");
    expect(presentation.title).toContain("平票");
    expect(presentation.detail).toContain("2票");
  });

  it("describes an exile result", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "vote",
        payload: { active_players: ["1号 狼人A", "2号 女巫"] },
      }),
      event({
        id: 3,
        type: "state_updated",
        round: 1,
        phase: "vote",
        payload: {
          active_players: ["2号 女巫"],
          exiled: "1号 狼人A",
        },
      }),
    ]);

    expect(presentation.kind).toBe("vote-result");
    expect(presentation.title).toContain("被放逐");
    expect(presentation.tone).toBe("danger");
  });

  it("describes night resolution outcomes", () => {
    const peaceful = focusFor([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          attacked: "7号 平民C",
          protected: "7号 平民C",
          eliminated: null,
          active_players: ["1号 狼人A", "7号 平民C"],
        },
      }),
    ]).presentation;
    expect(peaceful.kind).toBe("night-result");
    expect(peaceful.title).toContain("平安夜");
    expect(peaceful.tone).toBe("success");

    const death = focusFor([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          eliminated: "3号 平民A",
          active_players: ["1号 狼人A"],
        },
      }),
    ]).presentation;
    expect(death.kind).toBe("night-result");
    expect(death.title).toContain("夜晚死亡");
    expect(death.tone).toBe("danger");

    const emptyNightDeaths = focusFor([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          night_deaths: [],
          active_players: ["1号 狼人A", "7号 平民C"],
        },
      }),
    ]).presentation;
    expect(emptyNightDeaths.kind).toBe("night-result");
    expect(emptyNightDeaths.title).toBe("平安夜");

    const structuredDeaths = focusFor([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          night_deaths: [
            {
              player: "8号 猎人",
              cause: "werewolf_attack",
              source: "狼人",
            },
            {
              player: "3号 平民A",
              cause: "hunter_shot",
              source: "8号 猎人",
            },
          ],
          active_players: ["1号 狼人A", "2号 女巫"],
        },
      }),
    ]).presentation;
    expect(structuredDeaths).toMatchObject({
      kind: "night-result",
      tone: "danger",
      title: "8号 夜晚死亡",
      detail: "3号 夜晚死亡",
    });
  });

  it("describes skill triggers and terminal results", () => {
    const skill = focusFor([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 2,
        phase: "day",
        actor: "8号 猎人",
        payload: {
          hunter_shot: "1号 狼人A",
          active_players: ["8号 猎人"],
        },
      }),
    ]).presentation;
    expect(skill.kind).toBe("skill");
    expect(skill.title).toContain("猎人");
    expect(skill.accessibleText).toContain("带走");

    const terminal = focusFor([
      STARTED,
      event({
        id: 2,
        type: "game_completed",
        round: 3,
        phase: "summary",
        payload: { winner: "好人阵营" },
      }),
    ]).presentation;
    expect(terminal.kind).toBe("terminal");
    expect(terminal.accessibleText).toContain("好人阵营");
  });

  it("falls back to a readable unknown action label for missing actors or choices", () => {
    const missing = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: null,
        action: "remove",
        payload: {},
      }),
    ]).presentation;
    expect(missing.actorName).toContain("未知");
    expect(missing.accessibleText).toContain("未知");

    const malformed = focusFor([
      STARTED,
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
        payload: {},
      }),
    ]).presentation;
    expect(malformed.detail).toContain("待确认");
    expect(malformed.tone).toBe("neutral");
  });

  it("distinguishes daytime, sheriff-campaign and sheriff-PK speech", () => {
    const daytime = focusFor([
      STARTED,
      event({
        id: 2,
        type: "model_response_delta",
        round: 1,
        phase: "day",
        actor: "1号 狼人A",
        action: "debate",
        payload: { visible_text: "我是好人" },
      }),
    ]).presentation;

    const campaign = focusFor([
      STARTED,
      event({
        id: 2,
        type: "model_response_delta",
        round: 1,
        phase: "day",
        actor: "4号 预言家",
        action: "sheriff_speech",
        payload: { visible_text: "我竞选警长" },
      }),
    ]).presentation;

    const campaignPk = focusFor([
      STARTED,
      event({
        id: 2,
        type: "model_response_delta",
        round: 1,
        phase: "day",
        actor: "4号 预言家",
        action: "sheriff_pk_speech",
        payload: { visible_text: "这是我的 PK 发言" },
      }),
    ]).presentation;

    const exilePk = focusFor([
      STARTED,
      event({
        id: 2,
        type: "model_response_delta",
        round: 1,
        phase: "vote",
        actor: "4号 预言家",
        action: "exile_pk_speech",
        payload: { visible_text: "这是我的放逐 PK 发言" },
      }),
    ]).presentation;

    expect(daytime).toMatchObject({
      kind: "speech",
      actorName: "1号 狼人A",
      actorSeat: 1,
      eyebrow: "白天发言",
    });
    expect(campaign).toMatchObject({
      kind: "speech",
      eyebrow: "警长竞选发言",
      title: "4号 预言家警长竞选发言",
    });
    expect(campaignPk).toMatchObject({
      kind: "speech",
      eyebrow: "警长竞选 PK 发言",
      title: "4号 预言家警长竞选 PK 发言",
    });
    expect(exilePk).toMatchObject({
      kind: "speech",
      eyebrow: "放逐 PK 发言",
      title: "4号 预言家放逐 PK 发言",
    });
  });

  it("presents a tied runoff judge result as an explicit no-exile outcome", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "judge_cue",
        round: 1,
        phase: "vote",
        action: "exile_runoff_tied",
        payload: {
          cue_id: "exile_runoff_tied",
          visible_text: "二轮投票仍为平票，本轮无人被放逐，直接进入夜晚。",
        },
      }),
    ]);

    expect(presentation).toMatchObject({
      kind: "waiting",
      tone: "danger",
      eyebrow: "法官提示",
      title: "二轮投票仍为平票，本轮无人被放逐，直接进入夜晚。",
    });
  });

  it("always produces a complete accessible sentence", () => {
    const { presentation } = focusFor([
      STARTED,
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "vote",
        payload: { active_players: ["1号 狼人A", "2号 女巫"] },
      }),
      event({
        id: 3,
        type: "action_parsed",
        round: 1,
        phase: "vote",
        actor: "2号 女巫",
        action: "vote",
        payload: { choice: "1号 狼人A" },
      }),
    ]);

    expect(presentation.accessibleText).toContain("2号");
    expect(presentation.accessibleText).toContain("1号");
    expect(presentation.accessibleText).toContain("投票");
  });

  it("renders nested sheriff election and badge resolutions", () => {
    const elected = focusFor([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "day",
        action: "sheriff_election_resolved",
        payload: {
          sheriff_election: {
            outcome: "elected",
            sheriff: "4号 预言家",
            voters: ["2号 女巫"],
            votes: { "2号 女巫": "4号 预言家" },
          },
        },
      }),
    ]).presentation;
    expect(elected.title).toBe("4号 当选警长");

    const lost = focusFor([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "day",
        action: "sheriff_election_resolved",
        payload: {
          sheriff_election: {
            outcome: "badge_lost",
            sheriff: null,
            voters: [],
          },
        },
      }),
    ]).presentation;
    expect(lost.title).toBe("警徽流失");
    expect(lost.accessibleText).toBe("警徽流失");
  });
});

describe("getActiveTheaterPlayer", () => {
  it("resolves preparing-speech, speaking, voting, acting and summarizing players", () => {
    const speaking = buildState([
      STARTED,
      event({
        id: 2,
        type: "model_response_delta",
        round: 1,
        phase: "day",
        actor: "1号 狼人A",
        action: "debate",
        payload: { visible_text: "发言" },
      }),
    ]);
    expect(getActiveTheaterPlayer(speaking)?.name).toBe("1号 狼人A");

    const preparing = buildState([
      STARTED,
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "2号 女巫",
        action: "debate",
      }),
    ]);
    expect(getActiveTheaterPlayer(preparing)?.name).toBe("2号 女巫");

    const voting = buildState([
      STARTED,
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "vote",
        actor: "8号 猎人",
        action: "vote",
      }),
    ]);
    expect(getActiveTheaterPlayer(voting)?.name).toBe("8号 猎人");

    const acting = buildState([
      STARTED,
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "night",
        actor: "5号 守卫",
        action: "protect",
      }),
    ]);
    expect(getActiveTheaterPlayer(acting)?.name).toBe("5号 守卫");

    const summarizing = buildState([
      STARTED,
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "summary",
        actor: "4号 预言家",
        action: "summarize",
      }),
    ]);
    expect(getActiveTheaterPlayer(summarizing)?.name).toBe("4号 预言家");
  });

  it("does not promote resolved, out, affected or idle players as the active actor", () => {
    const resolved = buildState([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "day",
        payload: {
          active_players: ["1号 狼人A", "2号 女巫"],
          debate_entry: { speaker: "1号 狼人A", message: "已发言" },
        },
      }),
    ]);
    // 1号 is resolved (已发言) after the debate state update; no active actor remains.
    expect(getActiveTheaterPlayer(resolved)).toBeNull();

    const out = buildState([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "day",
        payload: {
          active_players: ["2号 女巫"],
          exiled: "1号 狼人A",
        },
      }),
    ]);
    expect(getActiveTheaterPlayer(out)).toBeNull();

    const affected = buildState([
      STARTED,
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          attacked: "7号 平民C",
          protected: "7号 平民C",
          eliminated: null,
          active_players: ["7号 平民C"],
        },
      }),
    ]);
    expect(getActiveTheaterPlayer(affected)).toBeNull();
  });
});
