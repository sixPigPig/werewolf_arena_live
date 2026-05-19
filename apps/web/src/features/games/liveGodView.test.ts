import { describe, expect, it } from "vitest";

import { deriveGodViewState } from "./liveGodView";
import { deriveLiveSpectatorState } from "./liveSpectator";
import type { LiveGameEvent } from "./types";

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

describe("deriveGodViewState", () => {
  it("derives player identities, camps, alive counts and current seat", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "7号 暗夜领主", role: "狼人", model: "deepseek-chat" },
            { name: "2号 银月诗人", role: "女巫", model: "deepseek-chat" },
            { name: "4号 暗鸦学者", role: "平民", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 3,
        phase: "day",
        actor: "7号 暗夜领主",
        action: "debate",
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "暗夜古堡");

    expect(state.boardName).toBe("暗夜古堡");
    expect(state.dayNightLabel).toBe("第 3 天");
    expect(state.phaseLabel).toBe("白天发言");
    expect(state.currentSeatLabel).toBe("发言席：1 号");
    expect(state.countdownLabel).toBe("00:45");
    expect(state.aliveLabel).toBe("存活 3/3");
    expect(state.progress).toMatchObject({
      wolvesAlive: 1,
      godsAlive: 1,
      villagersAlive: 1,
      totalAlive: 3,
      totalPlayers: 3,
    });
    expect(state.players[0]).toMatchObject({
      seatNumber: 1,
      camp: "狼人阵营",
      identityGroup: "狼人",
      isSpeaking: true,
      statusLabel: "发言中",
    });
    expect(state.players[1]).toMatchObject({
      camp: "好人阵营",
      identityGroup: "神职",
    });
  });

  it("summarizes night actions, deaths, votes, sheriff state and replay marks", () => {
    const events = [
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "1号 狼人", role: "werewolf", model: "deepseek-chat" },
            { name: "2号 女巫", role: "witch", model: "deepseek-chat" },
            { name: "3号 预言家", role: "seer", model: "deepseek-chat" },
            { name: "4号 平民", role: "villager", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "phase_started",
        round: 2,
        phase: "night",
        payload: { active_players: ["1号 狼人", "2号 女巫", "3号 预言家", "4号 平民"] },
      }),
      event({
        id: 3,
        type: "action_parsed",
        round: 2,
        phase: "night",
        actor: "1号 狼人",
        action: "eliminate",
        payload: { choice: "4号 平民" },
      }),
      event({
        id: 4,
        type: "state_updated",
        round: 2,
        phase: "night",
        payload: {
          active_players: ["1号 狼人", "2号 女巫", "3号 预言家"],
          attacked: "4号 平民",
          protected: "2号 女巫",
          investigated: "1号 狼人",
          eliminated: "4号 平民",
          night_deaths: [
            { player: "4号 平民", cause: "werewolf_attack", source: "狼人" },
          ],
          sheriff: "2号 女巫",
          sheriff_candidates: ["2号 女巫", "3号 预言家"],
          sheriff_voters: ["1号 狼人", "4号 平民"],
          votes: {
            "1号 狼人": "3号 预言家",
            "2号 女巫": "3号 预言家",
            "3号 预言家": "1号 狼人",
          },
          vote_weights: { "2号 女巫": 1.5 },
        },
      }),
      event({
        id: 5,
        type: "game_completed",
        created_at: "2026-04-24T12:00:10Z",
        payload: { winner: "狼人阵营" },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "暗夜古堡");

    expect(state.dayNightLabel).toBe("第 2 夜");
    expect(state.winnerLabel).toBe("狼人阵营");
    expect(state.players.find((player) => player.name === "4号 平民")).toMatchObject({
      isAlive: false,
      statusLabel: "夜晚出局",
      receivedVotes: 0,
    });
    expect(state.nightActions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: "狼人目标", value: "击杀 4号 平民" }),
        expect.objectContaining({ label: "守卫守护", value: "守护 2号 女巫" }),
        expect.objectContaining({ label: "预言家查验", value: "查验 1号 狼人" }),
      ]),
    );
    expect(state.deaths[0]).toMatchObject({
      player: "4号 平民",
      cause: "狼人击杀",
      publicText: "天亮公布",
    });
    expect(state.vote.tallies[0]).toMatchObject({
      target: "3号 预言家",
      count: 2.5,
      voters: ["1号 狼人", "2号 女巫"],
    });
    expect(state.sheriff).toMatchObject({
      current: "2号 女巫",
      candidates: ["2号 女巫", "3号 预言家"],
      voters: ["1号 狼人", "4号 平民"],
    });
    expect(state.publicFacts).toContain("4号 平民 夜晚死亡");
    expect(state.replayMarks.map((mark) => mark.text)).toContain("结算：狼人阵营");
  });

  it("derives previous current and next speakers from speech order", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "Harold", role: "seer", model: "deepseek-chat" },
            { name: "Jackson", role: "villager", model: "deepseek-chat" },
            { name: "Bert", role: "werewolf", model: "deepseek-chat" },
            { name: "Isaac", role: "guard", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "day",
        payload: {
          active_players: ["Harold", "Jackson", "Bert", "Isaac"],
          speech_order: ["Harold", "Jackson", "Bert", "Isaac"],
        },
      }),
      event({
        id: 3,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "Isaac",
        action: "debate",
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "经典 8 人局");

    expect(state.speakerFlow.previous?.name).toBe("Bert");
    expect(state.speakerFlow.current?.name).toBe("Isaac");
    expect(state.speakerFlow.next?.name).toBe("Harold");
    expect(state.speakerFlow.modeLabel).toBe("顺序发言");
  });

  it("derives peaceful night resolution and visible night action order", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "Harold", role: "seer", model: "deepseek-chat" },
            { name: "Jackson", role: "villager", model: "deepseek-chat" },
            { name: "Bert", role: "werewolf", model: "deepseek-chat" },
            { name: "Isaac", role: "guard", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          active_players: ["Harold", "Jackson", "Bert", "Isaac"],
          attacked: "Isaac",
          protected: "Isaac",
          investigated: "Jackson",
          eliminated: null,
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "经典 8 人局");

    expect(state.nightResolution).toMatchObject({
      label: "平安夜",
      detail: "Isaac 被狼人袭击，但被守卫守护。",
      tone: "safe",
    });
    expect(state.nightActionOrder.map((item) => item.label)).toEqual([
      "狼人目标",
      "守卫守护",
      "预言家查验",
    ]);
    expect(state.replayMarks.map((mark) => mark.text)).not.toContain(
      "state_updated",
    );
    expect(state.replayMarks.map((mark) => mark.text)).toContain("平安夜");
  });

  it("derives sheriff rule state and neutral win pressure", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "Harold", role: "seer", model: "deepseek-chat" },
            { name: "Jackson", role: "villager", model: "deepseek-chat" },
            { name: "Bert", role: "werewolf", model: "deepseek-chat" },
            { name: "Isaac", role: "guard", model: "deepseek-chat" },
          ],
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "经典 8 人局", {
      sheriffEnabled: false,
    });

    expect(state.sheriffRuleState).toEqual({
      enabled: false,
      label: "本局无警长规则",
    });
    expect(state.winPressure.label).toBe("局势未到临界");
  });

  it("marks win pressure when wolves are near parity", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "Wolf A", role: "werewolf", model: "deepseek-chat" },
            { name: "Wolf B", role: "werewolf", model: "deepseek-chat" },
            { name: "Seer", role: "seer", model: "deepseek-chat" },
            { name: "Villager", role: "villager", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "state_updated",
        payload: {
          active_players: ["Wolf A", "Wolf B", "Seer", "Villager"],
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "压力测试");

    expect(state.winPressure.label).toBe("狼人压制");
    expect(state.winPressure.tone).toBe("danger");
  });

  it("derives skill trigger lines from state updates", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "Wolf", role: "werewolf", model: "deepseek-chat" },
            { name: "Hunter", role: "hunter", model: "deepseek-chat" },
            { name: "Villager", role: "villager", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "state_updated",
        round: 2,
        phase: "day",
        actor: "Hunter",
        payload: {
          werewolf_self_exploded: "Wolf",
          hunter_shot: "Villager",
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "技能测试");

    expect(state.skillTriggers).toEqual([
      expect.objectContaining({
        label: "狼人自爆",
        detail: "Wolf 发动自爆。",
        tone: "danger",
      }),
      expect.objectContaining({
        label: "猎人带走",
        detail: "Hunter 带走 Villager。",
        tone: "warning",
      }),
    ]);
  });

  it("does not expose secret wolf consensus actions from public live events", () => {
    const events = [
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "1号 狼人", role: "werewolf", model: "deepseek-chat" },
            { name: "2号 狼人", role: "werewolf", model: "deepseek-chat" },
            { name: "3号 平民", role: "villager", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: null,
        action: "werewolf_discuss",
        payload: { message: "狼人正在秘密协商狼刀" },
      }),
      event({
        id: 3,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: null,
        action: "werewolf_kill_vote",
        payload: { message: "狼人正在秘密协商狼刀" },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "暗夜古堡");

    expect(state.nightActions).toEqual([]);
  });

  it("uses honest fallback states when no live facts are available", () => {
    const spectator = deriveLiveSpectatorState([]);

    const state = deriveGodViewState([], spectator, "实时对局");

    expect(state.boardName).toBe("实时对局");
    expect(state.dayNightLabel).toBe("等待开局");
    expect(state.phaseLabel).toBe("阶段未开始");
    expect(state.currentSeatLabel).toBe("发言席：等待");
    expect(state.countdownLabel).toBe("待命");
    expect(state.aliveLabel).toBe("存活 0/0");
    expect(state.winMode).toBe("屠边");
    expect(state.nightActions).toEqual([
      { label: "狼人目标", value: "等待夜间行动", tone: "muted" },
      { label: "预言家查验", value: "暂无记录", tone: "muted" },
      { label: "女巫药剂", value: "暂无记录", tone: "muted" },
      { label: "守卫守护", value: "暂无记录", tone: "muted" },
    ]);
    expect(state.deaths).toEqual([]);
    expect(state.vote.tallies).toEqual([]);
  });
});
