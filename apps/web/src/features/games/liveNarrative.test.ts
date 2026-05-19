import { describe, expect, it } from "vitest";

import { buildDirectorCues, toDirectorCue } from "./liveDirector";
import { deriveGodViewState } from "./liveGodView";
import { deriveLiveNarrativeState } from "./liveNarrative";
import { deriveLiveSpectatorState } from "./liveSpectator";
import type { LiveGameEvent } from "./types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "game_started",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: partial.created_at ?? "2026-05-19T00:00:00Z",
    round: partial.round ?? null,
    phase: partial.phase ?? null,
    actor: partial.actor ?? null,
    action: partial.action ?? null,
    payload: partial.payload ?? {},
  };
}

function narrativeFor(
  events: LiveGameEvent[],
  cue = toDirectorCue(events.at(-1) ?? event({})),
) {
  const spectatorState = deriveLiveSpectatorState(events);
  const godViewState = deriveGodViewState(
    events,
    spectatorState,
    "经典 8 人局",
    { sheriffEnabled: false },
  );

  return deriveLiveNarrativeState({
    cue,
    events,
    godViewState,
    spectatorState,
  });
}

describe("deriveLiveNarrativeState", () => {
  it("narrates core phase transitions like a judge", () => {
    expect(
      narrativeFor([
        event({
          id: 1,
          type: "phase_started",
          round: 1,
          phase: "night",
          payload: { active_players: ["Sam", "Isaac"] },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "judge",
      tone: "night",
      judgeLine: "天黑请闭眼。",
      detailLine: "夜间行动开始，存活玩家请依次行动。",
    });

    expect(
      narrativeFor([
        event({
          id: 2,
          type: "state_updated",
          round: 1,
          phase: "night",
          payload: {
            attacked: "Isaac",
            protected: "Isaac",
            eliminated: null,
            active_players: ["Sam", "Isaac"],
          },
        }),
        event({
          id: 3,
          type: "phase_started",
          round: 1,
          phase: "day",
          payload: { active_players: ["Sam", "Isaac"] },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "judge",
      tone: "day",
      judgeLine: "天亮了，昨夜平安无事。",
    });

    expect(
      narrativeFor([
        event({
          id: 4,
          type: "phase_started",
          round: 1,
          phase: "vote",
          payload: { active_players: ["Sam", "Isaac"] },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "vote",
      tone: "vote",
      judgeLine: "发言结束，进入放逐投票。",
    });

    expect(
      narrativeFor([
        event({
          id: 5,
          type: "phase_started",
          round: 1,
          phase: "summary",
          payload: { active_players: ["Sam", "Isaac"] },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "judge",
      tone: "neutral",
      judgeLine: "本轮进入总结，玩家整理自己的判断。",
    });
  });

  it("turns action requests into player performance states", () => {
    const state = narrativeFor([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "Sam", role: "村民", model: "deepseek-chat" },
            { name: "Isaac", role: "狼人", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "Sam",
        action: "debate",
        payload: { options: [] },
      }),
    ]);

    expect(state.speaker).toMatchObject({
      name: "Sam",
      seatNumber: 1,
      role: "村民",
    });
    expect(state.cue).toMatchObject({
      kind: "player-thinking",
      actorName: "Sam",
      action: "debate",
      judgeLine: "请 Sam 发言。",
      performerLine: "Sam 正在整理公开发言。",
      detailLine: "下一位：Isaac",
    });
  });

  it("uses model waiting events as player performance states", () => {
    expect(
      narrativeFor([
        event({
          id: 1,
          type: "game_started",
          payload: {
            players: [
              { name: "Sam", role: "村民", model: "deepseek-chat" },
              { name: "Isaac", role: "狼人", model: "deepseek-chat" },
            ],
          },
        }),
        event({
          id: 2,
          type: "model_request_started",
          round: 1,
          phase: "day",
          actor: "Sam",
          action: "debate",
          payload: {
            request_id: "req_123",
            message: "玩家正在组织公开发言...",
            is_public: true,
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "player-thinking",
      tone: "day",
      judgeLine: "请听 Sam 的发言。",
      performerLine: "Sam 正在组织发言。",
      detailLine: "玩家正在组织公开发言...",
    });
  });

  it("uses coalesced streaming cue text as live player speech", () => {
    const events = [
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "村民", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "model_request_started",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          model: "deepseek-chat",
          message: "玩家正在组织公开发言...",
          stream_field: "say",
          is_public: true,
        },
      }),
      event({
        id: 3,
        type: "model_response_delta",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          visible_text: "我不是狼",
          is_public: true,
        },
      }),
    ];
    const cues = buildDirectorCues(events);
    const speechCue = cues.find((cue) => cue.eventId === 2);

    expect(speechCue).toBeDefined();
    expect(narrativeFor(events, speechCue).cue).toMatchObject({
      kind: "player-speaking",
      tone: "day",
      judgeLine: "请听 张三 的发言。",
      performerLine: "张三 正在发言。",
      speechText: "我不是狼",
    });
  });

  it("uses visible parsed say and summary text as public speech", () => {
    expect(
      narrativeFor([
        event({
          id: 1,
          type: "action_parsed",
          round: 1,
          phase: "day",
          actor: "Sam",
          action: "debate",
          payload: {
            visible_result: { say: "我觉得今天应该先听 Isaac 发言。" },
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "player-speaking",
      judgeLine: "请听 Sam 的发言。",
      performerLine: "Sam 完成发言。",
      speechText: "我觉得今天应该先听 Isaac 发言。",
    });

    expect(
      narrativeFor([
        event({
          id: 2,
          type: "action_parsed",
          round: 1,
          phase: "summary",
          actor: "Leah",
          action: "summarize",
          payload: {
            visible_result: { summary: "Isaac 的票型需要重点复盘。" },
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "player-speaking",
      judgeLine: "请听 Leah 的发言。",
      speechText: "Isaac 的票型需要重点复盘。",
    });
  });

  it("does not expose parsed result speech without visible_result", () => {
    const state = narrativeFor([
      event({
        id: 1,
        type: "action_parsed",
        round: 1,
        phase: "day",
        actor: "Sam",
        action: "debate",
        payload: {
          result: { say: "这段只在内部解析结果里，不应该公开。" },
        },
      }),
    ]);

    expect(state.cue).toMatchObject({
      kind: "player-action",
      judgeLine: "玩家行动已解析。",
      speechText: "",
    });
    expect(state.cue.detailLine).not.toContain("这段只在内部解析结果里");
  });

  it("announces vote, exile, night death, and terminal results", () => {
    expect(
      narrativeFor([
        event({
          id: 1,
          type: "state_updated",
          round: 1,
          phase: "vote",
          payload: {
            votes: { Sam: "Isaac", Isaac: "Sam", Leah: "Isaac" },
            vote_weights: {},
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "vote",
      tone: "vote",
      judgeLine: "投票结果公布。",
      detailLine: "当前最高票：Isaac，2 票。",
    });

    expect(
      narrativeFor([
        event({
          id: 2,
          type: "state_updated",
          round: 1,
          phase: "vote",
          payload: {
            exiled: "Isaac",
            day_deaths: [{ player: "Isaac", cause: "vote_exile" }],
            active_players: ["Sam"],
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "death",
      tone: "danger",
      judgeLine: "Isaac 被放逐出局。",
    });

    expect(
      narrativeFor([
        event({
          id: 3,
          type: "state_updated",
          round: 2,
          phase: "night",
          payload: {
            eliminated: "Sam",
            night_deaths: [{ player: "Sam", cause: "werewolf_attack" }],
            active_players: ["Isaac"],
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "death",
      tone: "danger",
      judgeLine: "天亮了，昨夜 Sam 出局。",
    });

    expect(
      narrativeFor([
        event({
          id: 4,
          type: "game_completed",
          payload: { winner: "狼人阵营" },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "terminal",
      tone: "terminal",
      judgeLine: "对局结束，狼人阵营获胜。",
    });
  });

  it("announces peaceful nights and public skill updates", () => {
    expect(
      narrativeFor([
        event({
          id: 1,
          type: "state_updated",
          round: 1,
          phase: "night",
          payload: {
            attacked: "Sam",
            protected: "Sam",
            eliminated: null,
            active_players: ["Sam", "Isaac"],
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "judge",
      tone: "safe",
      judgeLine: "天亮了，昨夜平安无事。",
      performerLine: "昨夜没有玩家出局。",
    });

    const peacefulCue = narrativeFor([
      event({
        id: 1,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          attacked: "Sam",
          protected: "Sam",
          eliminated: null,
          active_players: ["Sam", "Isaac"],
        },
      }),
    ]).cue;

    expect(peacefulCue.performerLine).not.toContain("Sam");
    expect(peacefulCue.performerLine).not.toContain("守卫");
    expect(peacefulCue.detailLine).toBe("存活玩家：Sam、Isaac");

    const legacyProtectedCue = narrativeFor([
      event({
        id: 2,
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          protected: "李四",
          eliminated: "李四",
          active_players: ["张三", "李四"],
        },
      }),
    ]).cue;

    expect(legacyProtectedCue).toMatchObject({
      kind: "judge",
      tone: "safe",
      judgeLine: "天亮了，昨夜平安无事。",
      performerLine: "昨夜没有玩家出局。",
    });
    expect(legacyProtectedCue.judgeLine).not.toContain("李四 出局");
    expect(legacyProtectedCue.detailLine).toBe("存活玩家：张三、李四");

    expect(
      narrativeFor([
        event({
          id: 2,
          type: "state_updated",
          round: 1,
          phase: "day",
          actor: "Sam",
          payload: {
            hunter_shot: "Isaac",
            active_players: ["Sam", "Leah"],
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "player-action",
      tone: "danger",
      judgeLine: "猎人开枪带走 Isaac。",
      performerLine: "技能效果已经公开。",
    });
  });

  it("turns failed games into terminal narration", () => {
    expect(
      narrativeFor([
        event({
          id: 1,
          type: "game_failed",
          payload: { error: "模型服务不可用" },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "terminal",
      tone: "danger",
      judgeLine: "对局异常中断。",
      detailLine: "模型服务不可用",
    });
  });

  it("aligns the top-level speaker with affected-player cues", () => {
    const state = narrativeFor([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "Sam", role: "村民", model: "deepseek-chat" },
            { name: "Isaac", role: "狼人", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "Sam",
        action: "debate",
        payload: { options: [] },
      }),
      event({
        id: 3,
        type: "state_updated",
        round: 1,
        phase: "vote",
        payload: {
          exiled: "Isaac",
          active_players: ["Sam"],
        },
      }),
    ]);

    expect(state.cue.actorName).toBe("Isaac");
    expect(state.speaker?.name).toBe("Isaac");
  });

  it("does not keep a stale speaker for terminal cues", () => {
    const state = narrativeFor([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "Sam", role: "村民", model: "deepseek-chat" },
            { name: "Isaac", role: "狼人", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "Sam",
        action: "debate",
        payload: { options: [] },
      }),
      event({
        id: 3,
        type: "game_completed",
        payload: { winner: "好人阵营" },
      }),
    ]);

    expect(state.cue.actorName).toBeNull();
    expect(state.speaker).toBeNull();
  });

  it("does not fall back to the current speaker for unknown cue actors", () => {
    const events = [
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "Sam", role: "村民", model: "deepseek-chat" },
            { name: "Isaac", role: "狼人", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "Sam",
        action: "debate",
        payload: { options: [] },
      }),
    ];
    const unknownActorCue = toDirectorCue(
      event({
        id: 99,
        type: "custom_diagnostic",
        actor: "Ghost",
        payload: { note: "diagnostic" },
      }),
    );
    const state = narrativeFor(events, unknownActorCue);

    expect(state.cue.actorName).toBe("Ghost");
    expect(state.speaker).toBeNull();
  });

  it("uses generic fallback text for unknown events without payload internals", () => {
    const state = narrativeFor([
      event({
        id: 5,
        type: "custom_diagnostic",
        payload: {
          note: "debug value",
          prompt: "private prompt",
          raw_response: "private raw response",
        },
      }),
    ]);

    expect(state.cue).toMatchObject({
      kind: "fallback",
      judgeLine: "custom_diagnostic",
      detailLine: "收到未分类事件，等待后续公开结算。",
    });
    expect(state.cue.detailLine).not.toContain("debug value");
    expect(state.cue.detailLine).not.toContain("private prompt");
    expect(state.cue.detailLine).not.toContain("private raw response");
  });

  it("narrates model request failures without exposing private payload fields", () => {
    const state = narrativeFor([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "Sam", role: "村民", model: "deepseek-chat" },
            { name: "Isaac", role: "狼人", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "model_request_failed",
        round: 1,
        phase: "day",
        actor: "Sam",
        action: "debate",
        payload: {
          message: "模型请求超时，等待重试。",
          prompt: "private prompt",
          raw_response: "private raw response",
          error: "provider stack trace",
        },
      }),
    ]);

    expect(state.cue).toMatchObject({
      kind: "player-action",
      tone: "danger",
      actorName: "Sam",
      judgeLine: "模型请求暂时失败。",
      performerLine: "Sam 的行动暂时中断。",
      detailLine: "模型请求超时，等待重试。",
    });
    expect(state.cue.detailLine).not.toContain("private prompt");
    expect(state.cue.detailLine).not.toContain("private raw response");
    expect(state.cue.detailLine).not.toContain("provider stack trace");
  });
});
