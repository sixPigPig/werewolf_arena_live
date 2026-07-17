import { describe, expect, it } from "vitest";

import { deriveGodViewState } from "./liveGodView";
import { deriveLiveSpectatorState } from "./liveSpectator";
import type { LiveGameEvent } from "../types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "game_started",
    run_id: partial.run_id ?? "run_1234abcd",
    session_id: partial.session_id ?? "game_1200abcd",
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
    expect(state.countdownLabel).toBe("准备中");
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
      isSpeaking: false,
      statusLabel: "准备发言",
      stageStatus: { kind: "preparing-speech", label: "准备发言" },
    });
    expect(state.players[1]).toMatchObject({
      camp: "好人阵营",
      identityGroup: "神职",
    });
  });

  it("shows vote actors as voting instead of speaking", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "villager", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "李四",
        action: "vote",
        payload: { options: ["张三"] },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "投票测试");
    const voter = state.players.find((player) => player.name === "李四");
    const other = state.players.find((player) => player.name === "张三");

    expect(state.currentSeatLabel).toBe("投票席：2 号");
    expect(state.countdownLabel).toBe("投票中");
    expect(state.speakerFlow.current).toBeNull();
    expect(voter).toMatchObject({
      isSpeaking: false,
      statusLabel: "投票中",
      stageStatus: { kind: "voting", label: "投票中" },
    });
    expect(other).toMatchObject({
      isSpeaking: false,
      statusLabel: "存活",
      stageStatus: { kind: "idle", label: "存活" },
    });
  });

  it("keeps visible public speech in the speaking state", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "villager", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "model_response_delta",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: { visible_text: "我是一张好人牌" },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "发言测试");
    const speaker = state.players.find((player) => player.name === "张三");

    expect(state.currentSeatLabel).toBe("发言席：1 号");
    expect(state.countdownLabel).toBe("00:45");
    expect(speaker).toMatchObject({
      isSpeaking: true,
      statusLabel: "发言中",
      stageStatus: { kind: "speaking", label: "发言中" },
    });
  });

  it("clears stale speaker state when a public exile is resolved", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "villager", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
      }),
      event({
        id: 3,
        type: "state_updated",
        round: 1,
        phase: "day",
        payload: {
          active_players: ["张三"],
          exiled: "李四",
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "结算测试");
    const speaker = state.players.find((player) => player.name === "张三");
    const exiled = state.players.find((player) => player.name === "李四");

    expect(state.currentSeatLabel).toBe("结算：李四");
    expect(state.countdownLabel).toBe("结算中");
    expect(state.speakerFlow.current).toBeNull();
    expect(speaker).toMatchObject({
      isSpeaking: false,
      statusLabel: "存活",
      stageStatus: { kind: "idle", label: "存活" },
    });
    expect(exiled).toMatchObject({
      isSpeaking: false,
      isAlive: false,
      exitKind: "day-exile",
      statusLabel: "白天放逐",
      stageStatus: { kind: "out", label: "白天放逐" },
    });
  });

  it("shows summary actors as summarizing instead of speaking", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "villager", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "summary",
        actor: "张三",
        action: "summarize",
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "总结测试");
    const summarizer = state.players.find((player) => player.name === "张三");

    expect(state.currentSeatLabel).toBe("总结席：1 号");
    expect(state.countdownLabel).toBe("总结中");
    expect(summarizer).toMatchObject({
      isSpeaking: false,
      statusLabel: "总结中",
      stageStatus: { kind: "summarizing", label: "总结中" },
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
      exitKind: "night",
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

  it("marks the elected sheriff and exposes the election result in the event rail", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "阿青", role: "villager", model: "deepseek-chat" },
            { name: "白石", role: "seer", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "day",
        actor: "白石",
        payload: {
          sheriff: "白石",
          sheriff_elected: "白石",
          sheriff_votes: { 阿青: "白石" },
          active_players: ["阿青", "白石"],
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "警长竞选测试");

    expect(state.sheriff.current).toBe("白石");
    expect(state.players.find((player) => player.name === "白石")?.isSheriff).toBe(
      true,
    );
    expect(state.eventLines[0]).toMatchObject({
      text: "2号 当选警长",
      detail: "2号 当选警长并获得警徽",
      tone: "success",
    });
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

  it("reads structured night death events instead of marking them peaceful", () => {
    const events = [
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "阿烈", role: "seer", model: "test-model" },
            { name: "纪衡", role: "hunter", model: "test-model" },
          ],
        },
      }),
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "night",
        action: "hunter_shot_resolved",
        payload: {
          night_deaths: [
            { player: "纪衡", cause: "werewolf_attack", source: "狼人" },
            { player: "阿烈", cause: "hunter_shot", source: "纪衡" },
          ],
          active_players: [],
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "结构化死亡测试");

    expect(state.nightResolution).toMatchObject({
      label: "昨夜死亡",
      detail: "纪衡、阿烈 夜晚出局。",
      tone: "danger",
    });
    expect(state.eventLines[0]?.text).toBe("2号 夜晚死亡，1号 夜晚死亡");
    expect(state.eventLines[0]?.text).not.toBe("平安夜");
  });

  it("folds parent and child hunter-shot presentations into one display result", () => {
    const presentationId =
      "settlement:game_hunter:2:day:1号猎人:hunter:1号猎人:presentation";
    const shotPayload = {
      presentation_id: presentationId,
      hunter_shot_status: "shot",
      hunter_shot: "2号平民A",
      day_deaths: [
        { player: "1号猎人", cause: "vote_exile", source: null },
        { player: "2号平民A", cause: "hunter_shot", source: "1号猎人" },
      ],
      active_players: ["3号平民B", "4号狼人"],
    };
    const events = [
      event({
        id: 1,
        run_id: "run-parent",
        session_id: "game_hunter",
        type: "game_started",
        payload: {
          players: [
            { name: "1号猎人", role: "hunter", model: "test-model" },
            { name: "2号平民A", role: "villager", model: "test-model" },
            { name: "3号平民B", role: "villager", model: "test-model" },
            { name: "4号狼人", role: "werewolf", model: "test-model" },
          ],
        },
      }),
      event({
        id: 10,
        run_id: "run-parent",
        session_id: "game_hunter",
        type: "state_updated",
        round: 2,
        phase: "day",
        actor: "1号猎人",
        action: "hunter_shot_resolved",
        payload: shotPayload,
      }),
      event({
        id: 11,
        run_id: "run-child",
        session_id: "game_hunter",
        type: "game_resumed",
        round: 2,
        phase: "day",
      }),
      event({
        id: 12,
        run_id: "run-child",
        session_id: "game_hunter",
        type: "state_updated",
        round: 2,
        phase: "day",
        actor: "1号猎人",
        action: "hunter_shot_resolved",
        payload: shotPayload,
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "猎人恢复测试");
    const shotLines = state.eventLines.filter(
      (line) => line.text === "猎人带走 2号",
    );
    const shotMarks = state.replayMarks.filter(
      (line) => line.text === "猎人带走 2号",
    );

    expect(shotLines).toEqual([expect.objectContaining({ id: 12 })]);
    expect(shotMarks).toEqual([expect.objectContaining({ id: 12 })]);
    expect(
      state.skillTriggers.filter((trigger) => trigger.label === "猎人带走"),
    ).toEqual([expect.objectContaining({ id: 12 })]);
    expect(
      state.deaths.filter((death) => death.player === "2号平民A"),
    ).toHaveLength(1);
    expect(state.players.find((player) => player.name === "2号平民A")).toMatchObject({
      isAlive: false,
    });
    expect(state.players.find((player) => player.name === "3号平民B")).toMatchObject({
      isAlive: true,
    });
    expect(state.progress.totalAlive).toBe(2);
  });

  it("folds parent and child hunter no-shot presentations into one explicit result", () => {
    const presentationId =
      "settlement:game_hunter_skip:2:day:1号猎人:hunter:1号猎人:presentation";
    const skippedPayload = {
      presentation_id: presentationId,
      hunter_shot_status: "skipped",
      hunter_shot: null,
      day_deaths: [
        { player: "1号猎人", cause: "vote_exile", source: null },
      ],
      active_players: ["2号平民", "3号狼人"],
    };
    const events = [
      event({
        id: 1,
        run_id: "run-parent",
        session_id: "game_hunter_skip",
        type: "game_started",
        payload: {
          players: [
            { name: "1号猎人", role: "hunter", model: "test-model" },
            { name: "2号平民", role: "villager", model: "test-model" },
            { name: "3号狼人", role: "werewolf", model: "test-model" },
          ],
        },
      }),
      event({
        id: 20,
        run_id: "run-parent",
        session_id: "game_hunter_skip",
        type: "state_updated",
        round: 2,
        phase: "day",
        actor: "1号猎人",
        action: "hunter_shot_resolved",
        payload: skippedPayload,
      }),
      event({
        id: 21,
        run_id: "run-child",
        session_id: "game_hunter_skip",
        type: "game_resumed",
        round: 2,
        phase: "day",
      }),
      event({
        id: 22,
        run_id: "run-child",
        session_id: "game_hunter_skip",
        type: "state_updated",
        round: 2,
        phase: "day",
        actor: "1号猎人",
        action: "hunter_shot_resolved",
        payload: skippedPayload,
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "猎人不发动恢复测试");
    const skippedLines = state.eventLines.filter(
      (line) => line.text === "猎人选择不发动技能",
    );
    const skippedMarks = state.replayMarks.filter(
      (line) => line.text === "猎人选择不发动技能",
    );

    expect(skippedLines).toEqual([expect.objectContaining({ id: 22 })]);
    expect(skippedMarks).toEqual([expect.objectContaining({ id: 22 })]);
    expect(
      state.skillTriggers.filter((trigger) => trigger.label === "猎人带走"),
    ).toHaveLength(0);
    expect(state.players.find((player) => player.name === "1号猎人")).toMatchObject({
      isAlive: false,
    });
    expect(state.players.find((player) => player.name === "2号平民")).toMatchObject({
      isAlive: true,
    });
    expect(state.progress.totalAlive).toBe(2);
  });

  it("folds a recovered primary exile presentation without dropping its final state", () => {
    const presentationId =
      "settlement:game_exile:3:vote:2号平民:primary:presentation";
    const exilePayload = {
      presentation_id: presentationId,
      exiled: "2号平民",
      day_deaths: [
        { player: "2号平民", cause: "vote_exile", source: null },
      ],
      active_players: ["1号狼人", "3号预言家"],
    };
    const events = [
      event({
        id: 1,
        run_id: "run-parent",
        session_id: "game_exile",
        type: "game_started",
        payload: {
          players: [
            { name: "1号狼人", role: "werewolf", model: "test-model" },
            { name: "2号平民", role: "villager", model: "test-model" },
            { name: "3号预言家", role: "seer", model: "test-model" },
          ],
        },
      }),
      event({
        id: 30,
        run_id: "run-parent",
        session_id: "game_exile",
        type: "state_updated",
        round: 3,
        phase: "vote",
        action: "exile_resolved",
        payload: exilePayload,
      }),
      event({
        id: 31,
        run_id: "run-child",
        session_id: "game_exile",
        type: "game_resumed",
        round: 3,
        phase: "vote",
      }),
      event({
        id: 32,
        run_id: "run-child",
        session_id: "game_exile",
        type: "state_updated",
        round: 3,
        phase: "vote",
        action: "exile_resolved",
        payload: exilePayload,
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "放逐恢复测试");
    const exileLines = state.eventLines.filter(
      (line) => line.text === "2号 被放逐",
    );
    const exileMarks = state.replayMarks.filter(
      (line) => line.text === "2号 被放逐",
    );

    expect(exileLines).toEqual([expect.objectContaining({ id: 32 })]);
    expect(exileMarks).toEqual([expect.objectContaining({ id: 32 })]);
    expect(state.players.find((player) => player.name === "2号平民")).toMatchObject({
      isAlive: false,
      exitKind: "day-exile",
    });
    expect(state.progress.totalAlive).toBe(2);
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

  it("does not let historical secret wolf events suppress later night fallback", () => {
    const events = [
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "1号 狼人", role: "werewolf", model: "deepseek-chat" },
            { name: "2号 女巫", role: "witch", model: "deepseek-chat" },
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
        action: "werewolf_kill_vote",
        payload: { message: "狼人正在秘密协商狼刀" },
      }),
      event({
        id: 3,
        type: "phase_started",
        round: 2,
        phase: "night",
        payload: {
          active_players: ["1号 狼人", "2号 女巫", "3号 平民"],
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);

    const state = deriveGodViewState(events, spectator, "暗夜古堡");

    expect(state.nightActions).toEqual([
      { label: "狼人目标", value: "等待夜间行动", tone: "muted" },
      { label: "预言家查验", value: "暂无记录", tone: "muted" },
      { label: "女巫药剂", value: "暂无记录", tone: "muted" },
      { label: "守卫守护", value: "暂无记录", tone: "muted" },
    ]);
  });

  it("uses honest fallback states when no live facts are available", () => {
    const spectator = deriveLiveSpectatorState([]);

    const state = deriveGodViewState([], spectator, "实时对局");

    expect(state.boardName).toBe("实时对局");
    expect(state.dayNightLabel).toBe("等待开局");
    expect(state.phaseLabel).toBe("阶段未开始");
    expect(state.currentSeatLabel).toBe("等待");
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

  it("keeps raised hands and withdrawal marks until the sheriff election resolves", () => {
    const started = event({
      id: 1,
      type: "game_started",
      payload: {
        players: [
          { name: "阿青", role: "villager", model: "test-model" },
          { name: "白石", role: "werewolf", model: "test-model" },
        ],
      },
    });
    const requests = [
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "阿青",
        action: "sheriff_run",
      }),
      event({
        id: 3,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "白石",
        action: "sheriff_run",
      }),
    ];
    const firstResult = event({
      id: 4,
      type: "action_parsed",
      round: 1,
      phase: "day",
      actor: "阿青",
      action: "sheriff_run",
      payload: { choice: "上警" },
    });
    const finalResult = event({
      id: 5,
      type: "action_parsed",
      round: 1,
      phase: "day",
      actor: "白石",
      action: "sheriff_run",
      payload: { choice: "不上警" },
    });
    const nextStage = event({
      id: 6,
      type: "action_requested",
      round: 1,
      phase: "day",
      actor: "阿青",
      action: "sheriff_speech",
    });
    const withdrawal = event({
      id: 7,
      type: "action_parsed",
      round: 1,
      phase: "day",
      actor: "阿青",
      action: "sheriff_withdraw",
      payload: { result: { withdraw: "退水" } },
    });
    const interruptedResolution = event({
      id: 8,
      type: "state_updated",
      round: 1,
      phase: "day",
      action: "sheriff_election_resolved",
      payload: {
        sheriff_election: {
          outcome: "postponed",
          reason_code: "first_pre_election_self_explosion",
        },
        sheriff_election_pending: true,
      },
    });

    const partialEvents = [started, ...requests, firstResult];
    const partialState = deriveGodViewState(
      partialEvents,
      deriveLiveSpectatorState(partialEvents),
      "上警测试",
    );
    expect(partialState.players.find((player) => player.name === "阿青")).toMatchObject({
      hasRaisedHand: true,
    });
    expect(partialState.players.find((player) => player.name === "白石")).toMatchObject({
      hasRaisedHand: false,
    });

    const resultEvents = [...partialEvents, finalResult];
    const resultState = deriveGodViewState(
      resultEvents,
      deriveLiveSpectatorState(resultEvents),
      "上警测试",
    );
    expect(resultState.players.find((player) => player.name === "阿青")).toMatchObject({
      hasRaisedHand: true,
    });

    const speechEvents = [...resultEvents, nextStage];
    const speechState = deriveGodViewState(
      speechEvents,
      deriveLiveSpectatorState(speechEvents),
      "上警测试",
    );
    expect(speechState.phaseLabel).toBe("警长竞选");
    expect(speechState.players.find((player) => player.name === "阿青")).toMatchObject({
      hasRaisedHand: true,
      hasWithdrawn: false,
    });

    const withdrawnEvents = [...speechEvents, withdrawal];
    const withdrawnState = deriveGodViewState(
      withdrawnEvents,
      deriveLiveSpectatorState(withdrawnEvents),
      "上警测试",
    );
    expect(withdrawnState.players.find((player) => player.name === "阿青")).toMatchObject({
      hasRaisedHand: true,
      hasWithdrawn: true,
    });

    const resolvedEvents = [...withdrawnEvents, interruptedResolution];
    const resolvedState = deriveGodViewState(
      resolvedEvents,
      deriveLiveSpectatorState(resolvedEvents),
      "上警测试",
    );
    expect(resolvedState.phaseLabel).toBe("白天发言");
    expect(
      resolvedState.players.every(
        (player) => !player.hasRaisedHand && !player.hasWithdrawn,
      ),
    ).toBe(true);
  });
});

function eightPlayerEvents(): LiveGameEvent[] {
  return [
    event({
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
    }),
  ];
}

describe("deriveGodViewState meaningful event lines", () => {
  it("records parsed night actions with stable seats and readable text", () => {
    const events = [
      ...eightPlayerEvents(),
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "night",
        payload: {
          active_players: [
            "1号 狼人A",
            "2号 女巫",
            "4号 预言家",
            "5号 守卫",
          ],
        },
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
      event({
        id: 4,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "5号 守卫",
        action: "protect",
        payload: { choice: "7号 平民C" },
      }),
      event({
        id: 5,
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
      event({
        id: 6,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_save",
        payload: { choice: "7号 平民C" },
      }),
      event({
        id: 7,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_poison",
        payload: { choice: "skip" },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");
    const texts = state.eventLines.map((line) => line.text);

    expect(texts).toEqual(
      expect.arrayContaining([
        "最终狼刀 -> 7号",
        "守卫守护 7号",
        "预言家查验 1号",
        "女巫救 7号",
        "女巫未使用毒药",
      ]),
    );
    // The seer investigation result is God-View knowledge shown on the center
    // card via nightActions, but it must not leak into the public rail text.
    const seerLine = state.eventLines.find((line) =>
      line.text.startsWith("预言家查验"),
    );
    expect(seerLine?.text).toBe("预言家查验 1号");
    expect(seerLine?.text).not.toContain("werewolf");
    expect(seerLine?.text).not.toContain("狼");
  });

  it("normalizes seat-only aliases in parsed targets", () => {
    const events = [
      ...eightPlayerEvents(),
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
        payload: { choice: "7号玩家" },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");
    const removeLine = state.eventLines.find((line) => line.id === 2);

    expect(removeLine?.text).toBe("最终狼刀 -> 7号");
    expect(removeLine?.text).not.toContain("玩家号");
  });

  it("records every wolf kill vote before the final team target", () => {
    const events = [
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "1号 狼人A", role: "werewolf", model: "test" },
            { name: "2号 狼人B", role: "werewolf", model: "test" },
            { name: "3号 平民A", role: "villager", model: "test" },
            { name: "4号 平民B", role: "villager", model: "test" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "werewolf_kill_vote",
        payload: { choice: "3号玩家", vote_round: 1 },
      }),
      event({
        id: 3,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 狼人B",
        action: "werewolf_kill_vote",
        payload: { choice: "4号玩家", vote_round: 1 },
      }),
      event({
        id: 4,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "werewolf_kill_vote",
        payload: { choice: "3号玩家", vote_round: 2 },
      }),
      event({
        id: 5,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 狼人B",
        action: "werewolf_kill_vote",
        payload: { choice: "3号玩家", vote_round: 2 },
      }),
      event({
        id: 6,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: null,
        action: "remove",
        payload: { choice: "3号玩家", vote_round: 2, final_target: true },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");
    const texts = state.eventLines.map((line) => line.text);

    expect(texts).toEqual(
      expect.arrayContaining([
        "1号 刀票 -> 3号",
        "2号 刀票 -> 4号",
        "2号 刀票 -> 3号",
        "最终狼刀 -> 3号",
      ]),
    );
    expect(
      state.eventLines.find((line) => line.id === 5)?.detail,
    ).toBe("第 2 轮 · 2号选择袭击 3号");
    expect(state.nightActions).toEqual(
      expect.arrayContaining([
        { label: "1号 狼刀", value: "投 3号", tone: "danger" },
        { label: "2号 狼刀", value: "投 4号", tone: "danger" },
        { label: "2号 狼刀", value: "投 3号", tone: "danger" },
        { label: "狼人目标", value: "击杀 3号玩家", tone: "danger" },
      ]),
    );
  });

  it("renders wolf private chat and tie-only judge cues in God View", () => {
    const events = [
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "1号 狼人A", role: "werewolf", model: "test" },
            { name: "2号 狼人B", role: "werewolf", model: "test" },
            { name: "3号 平民A", role: "villager", model: "test" },
            { name: "4号 平民B", role: "villager", model: "test" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "werewolf_discuss",
        payload: {
          choice: "3号玩家",
          message: "建议刀3号，他像预言家。",
          decision_stage: "proposal",
        },
      }),
      event({
        id: 3,
        type: "judge_cue",
        round: 1,
        phase: "night",
        action: "werewolf_tiebreak_start",
        payload: {
          visible_text: "狼队刀口出现平票。本夜由1号玩家行使归票权。",
        },
      }),
      event({
        id: 4,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "werewolf_kill_vote",
        payload: {
          choice: "3号玩家",
          message: "最终归票3号。",
          decision_stage: "tiebreak",
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");

    expect(state.eventLines.map((line) => line.text)).toEqual(
      expect.arrayContaining([
        "1号 密聊：建议刀3号，他像预言家。",
        "狼队刀口出现平票。本夜由1号玩家行使归票权。",
        "1号 归票 -> 3号",
      ]),
    );
    expect(state.nightActions).toEqual(
      expect.arrayContaining([
        { label: "1号 密聊", value: "建议刀3号，他像预言家。", tone: "info" },
        { label: "1号 归票", value: "定 3号", tone: "danger" },
      ]),
    );
  });

  it("keeps only spectator-meaningful action requests and state updates", () => {
    const events = [
      ...eightPlayerEvents(),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
      }),
      event({
        id: 3,
        type: "action_requested",
        round: 1,
        phase: "sheriff",
        actor: "2号 女巫",
        action: "sheriff_run",
      }),
      event({
        id: 4,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "2号 女巫",
        action: "debate",
      }),
      event({
        id: 5,
        type: "action_requested",
        round: 1,
        phase: "summary",
        actor: "2号 女巫",
        action: "summarize",
      }),
      event({
        id: 6,
        type: "action_requested",
        round: 1,
        phase: "vote",
        actor: "8号 猎人",
        action: "vote",
      }),
      event({
        id: 7,
        type: "state_updated",
        round: 1,
        phase: "day",
        payload: { active_players: ["1号 狼人A", "2号 女巫"] },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");
    const ids = state.eventLines.map((line) => line.id);

    expect(ids).toContain(2);
    expect(ids).toContain(6);
    expect(ids).not.toContain(3);
    expect(ids).not.toContain(4);
    expect(ids).not.toContain(5);
    expect(ids).not.toContain(7);
    expect(state.eventLines.map((line) => line.text)).not.toContain("局势更新");
  });

  it("records skip as an explicit unused action and never drops it", () => {
    const events = [
      ...eightPlayerEvents(),
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "night",
        payload: { active_players: ["2号 女巫"] },
      }),
      event({
        id: 3,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_save",
        payload: { choice: "skip" },
      }),
      event({
        id: 4,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_poison",
        payload: { choice: "skip" },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");
    const texts = state.eventLines.map((line) => line.text);

    expect(texts).toContain("女巫未使用解药");
    expect(texts).toContain("女巫未使用毒药");
  });

  it("records parsed votes with actor and target and keeps same-target votes distinct", () => {
    const events = [
      ...eightPlayerEvents(),
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "vote",
        payload: {
          active_players: [
            "1号 狼人A",
            "2号 女巫",
            "3号 平民A",
            "6号 平民B",
            "7号 平民C",
          ],
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
      event({
        id: 4,
        type: "action_parsed",
        round: 1,
        phase: "vote",
        actor: "6号 平民B",
        action: "vote",
        payload: { choice: "1号 狼人A" },
      }),
      event({
        id: 5,
        type: "action_parsed",
        round: 1,
        phase: "vote",
        actor: "7号 平民C",
        action: "vote",
        payload: { choice: "1号 狼人A" },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");
    const voteLines = state.eventLines.filter((line) =>
      line.text.includes("->"),
    );

    expect(voteLines.map((line) => line.text)).toEqual(
      expect.arrayContaining([
        "8号 -> 1号",
        "6号 -> 1号",
        "7号 -> 1号",
      ]),
    );
    // Distinct event IDs even though the choice text is identical.
    const ids = voteLines.map((line) => line.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(expect.arrayContaining([3, 4, 5]));
  });

  it("summarizes weighted and tied vote state updates", () => {
    const weighted = [
      ...eightPlayerEvents(),
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "vote",
        payload: { active_players: ["1号 狼人A", "2号 女巫", "3号 平民A"] },
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
    ];
    const weightedState = deriveGodViewState(
      weighted,
      deriveLiveSpectatorState(weighted),
      "暗夜古堡",
    );
    const weightedLine = weightedState.eventLines.find((line) =>
      line.text.includes("票"),
    );
    expect(weightedLine?.text).toContain("2号");
    expect(weightedLine?.text).toContain("2.5票");

    const tied = [
      ...eightPlayerEvents(),
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
    ];
    const tiedState = deriveGodViewState(
      tied,
      deriveLiveSpectatorState(tied),
      "暗夜古堡",
    );
    const tiedLine = tiedState.eventLines.find((line) =>
      line.text.startsWith("平票"),
    );
    expect(tiedLine?.text).toContain("平票");
    expect(tiedLine?.text).toContain("2票");
  });

  it("summarizes exile, night death, witch poison and peaceful night results", () => {
    const events = [
      ...eightPlayerEvents(),
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "night",
        payload: { active_players: ["1号 狼人A", "2号 女巫", "5号 守卫"] },
      }),
      event({
        id: 3,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_save",
        payload: { choice: "7号 平民C" },
      }),
      event({
        id: 4,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "2号 女巫",
        action: "witch_poison",
        payload: { choice: "6号 平民B" },
      }),
      event({
        id: 5,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          active_players: ["1号 狼人A", "2号 女巫", "5号 守卫", "7号 平民C"],
          attacked: "7号 平民C",
          protected: "7号 平民C",
          eliminated: null,
        },
      }),
      event({
        id: 6,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          active_players: ["1号 狼人A", "2号 女巫", "5号 守卫", "7号 平民C"],
          attacked: "3号 平民A",
          eliminated: "3号 平民A",
          poisoned: "6号 平民B",
          saved_by_witch: "7号 平民C",
        },
      }),
      event({
        id: 7,
        type: "phase_started",
        round: 1,
        phase: "vote",
        payload: { active_players: ["1号 狼人A", "2号 女巫"] },
      }),
      event({
        id: 8,
        type: "state_updated",
        round: 1,
        phase: "vote",
        payload: {
          active_players: ["2号 女巫"],
          exiled: "1号 狼人A",
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");
    const texts = state.eventLines.map((line) => line.text);

    expect(texts).toContain("平安夜");
    expect(texts).toContain("3号 夜晚死亡，6号 被毒杀");
    expect(texts).toContain("女巫毒 6号");
    expect(texts).toContain("女巫救 7号");
    expect(texts).toContain("1号 被放逐");
  });

  it("never leaks model ticks, deltas, raw payloads, prompts or private summaries", () => {
    const events = [
      ...eightPlayerEvents(),
      event({
        id: 2,
        type: "phase_started",
        round: 1,
        phase: "night",
        payload: { active_players: ["1号 狼人A"] },
      }),
      event({
        id: 3,
        type: "model_thinking_tick",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
        payload: { message: "正在思考", elapsed_ms: 1200, prompt: "secret prompt" },
      }),
      event({
        id: 4,
        type: "model_response_delta",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
        payload: { visible_text: "secret delta", raw_response: "raw" },
      }),
      event({
        id: 5,
        type: "action_parsed",
        round: 1,
        phase: "night",
        actor: "1号 狼人A",
        action: "remove",
        payload: {
          choice: "7号 平民C",
          raw_response: "raw",
          prompt: "secret prompt",
        },
      }),
      event({
        id: 6,
        type: "state_updated",
        round: 1,
        phase: "summary",
        payload: {
          public_summary: "第1轮：公开总结。",
          private_summaries: { "1号 狼人A": "我是狼人，准备刀9号。" },
        },
      }),
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");
    const blob = state.eventLines
      .map((line) => `${line.text} ${line.detail ?? ""}`)
      .join("\n");

    expect(state.eventLines.some((line) => line.id === 3)).toBe(false);
    expect(state.eventLines.some((line) => line.id === 4)).toBe(false);
    expect(blob).not.toContain("secret prompt");
    expect(blob).not.toContain("secret delta");
    expect(blob).not.toContain("raw_response");
    expect(blob).not.toContain("raw");
    expect(blob).not.toContain("准备刀9号");
    expect(blob).not.toContain("我是狼人");
  });

  it("annotates event lines with round and phase for grouping", () => {
    const events = [
      ...eightPlayerEvents(),
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
    ];
    const spectator = deriveLiveSpectatorState(events);
    const state = deriveGodViewState(events, spectator, "暗夜古堡");
    const removeLine = state.eventLines.find((line) =>
      line.text.startsWith("最终狼刀 ->"),
    );

    expect(removeLine?.round).toBe(1);
    expect(removeLine?.phase).toBe("night");
    expect(typeof removeLine?.detail).toBe("string");
    expect(removeLine?.detail).toContain("7号");
  });

  it("projects nested sheriff resolutions and preserves explicit empty voters", () => {
    const started = eightPlayerEvents();
    const elected = event({
      id: 2,
      type: "state_updated",
      round: 1,
      phase: "day",
      action: "sheriff_election_resolved",
      payload: {
        sheriff_election: {
          outcome: "elected",
          sheriff: "4号 预言家",
          candidates: ["4号 预言家", "1号 狼人A"],
          voters: ["2号 女巫"],
        },
      },
    });
    const lost = event({
      id: 3,
      type: "state_updated",
      round: 2,
      phase: "day",
      action: "sheriff_election_resolved",
      payload: {
        sheriff_election: {
          outcome: "badge_lost",
          sheriff: null,
          candidates: ["4号 预言家", "1号 狼人A"],
          voters: [],
        },
      },
    });

    const electedSpectator = deriveLiveSpectatorState([...started, elected]);
    const electedState = deriveGodViewState(
      [...started, elected],
      electedSpectator,
      "暗夜古堡",
    );
    expect(electedState.sheriff.current).toBe("4号 预言家");
    expect(electedState.sheriff.voters).toEqual(["2号 女巫"]);

    const lostSpectator = deriveLiveSpectatorState([...started, elected, lost]);
    const lostState = deriveGodViewState(
      [...started, elected, lost],
      lostSpectator,
      "暗夜古堡",
    );
    expect(lostState.sheriff.current).toBeNull();
    expect(lostState.sheriff.voters).toEqual([]);
    expect(lostState.sheriff.badgeFlow).toBe("警徽流失");
  });
});
