import { describe, expect, it } from "vitest";

import { normalizeGameReplay } from "./adapters";
import type { RawGameReplayResponse } from "../types";

const rawReplay: RawGameReplayResponse = {
  session_id: "session_20260424_050950_66ea9f38",
  status: "complete",
  state: {
    session_id: "session_20260424_050950_66ea9f38",
    players: [
      { name: "张三", role: "狼人", model: "deepseek-chat", observations: [] },
      { name: "李四", role: "村民", model: "deepseek-chat", observations: [] },
    ],
    rounds: [
      {
        number: 1,
        players: ["张三", "李四"],
        eliminated: "李四",
        protected: null,
        investigated: "张三",
        exiled: null,
        debate: [{ speaker: "李四", message: "我不是狼。" }],
        bids: [{ 张三: 3 }, { 李四: 1 }],
        votes: [{ 张三: "李四" }],
        summaries: { 张三: "我需要继续伪装。" },
        success: true,
      },
    ],
    winner: "狼人阵营",
    error_message: "",
  },
  logs: [
    {
      number: 1,
      eliminate: {
        actor: "张三",
        action: "remove",
        options: ["李四"],
        choice: "李四",
        lm_log: {
          prompt: "请选择今晚击杀对象。",
          raw_response: '{"choice":"李四"}',
          result: { choice: "李四" },
        },
      },
      protect: null,
      investigate: null,
      bid: [],
      debate: [],
      votes: [],
      summaries: [],
    },
  ],
};

describe("normalizeGameReplay", () => {
  it("maps backend replay payload into stable UI fields", () => {
    const replay = normalizeGameReplay(rawReplay);

    expect(replay.sessionId).toBe("session_20260424_050950_66ea9f38");
    expect(replay.status).toBe("complete");
    expect(replay.winner).toBe("狼人阵营");
    expect(replay.players[0]).toMatchObject({ name: "张三", role: "狼人" });
    expect(replay.rounds[0].bids).toEqual([
      { actor: "张三", score: 3 },
      { actor: "李四", score: 1 },
    ]);
  });

  it("creates debug items for model actions", () => {
    const replay = normalizeGameReplay(rawReplay);

    expect(replay.debugItems).toHaveLength(1);
    expect(replay.debugItems[0]).toMatchObject({
      id: "round-1-night-eliminate",
      roundNumber: 1,
      phase: "night",
      title: "狼人击杀",
      actor: "张三",
      choice: "李四",
      prompt: "请选择今晚击杀对象。",
      parsed: { choice: "李四" },
    });
  });

  it("omits no-op sheriff badge debug items", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      state: {
        ...rawReplay.state,
        players: [
          { name: "Mason", role: "村民", model: "deepseek-chat" },
          { name: "Bert", role: "狼人", model: "deepseek-chat" },
        ],
        rounds: [
          {
            number: 1,
            players: ["Mason", "Bert"],
            eliminated: null,
            protected: null,
            investigated: null,
            exiled: "Bert",
            day_deaths: [{ player: "Bert", cause: "vote_exile", source: "投票" }],
            sheriff: "Mason",
            sheriff_badge_target: "Mason",
            debate: [],
            bids: [],
            votes: [],
            summaries: {},
            success: true,
          },
        ],
      },
      logs: [
        {
          number: 1,
          eliminate: null,
          protect: null,
          investigate: null,
          sheriff_badge: {
            actor: "Mason",
            action: "sheriff_badge",
            options: ["Mason", "撕毁警徽"],
            choice: "移交给 Mason",
            lm_log: {
              prompt: "请选择警徽处理方式。",
              raw_response: '{"badge":"Mason"}',
              result: { badge: "Mason" },
            },
          },
          bid: [],
          debate: [],
          votes: [],
          summaries: [],
        },
      ],
    });

    expect(
      replay.debugItems.some((item) => item.action === "sheriff_badge"),
    ).toBe(false);
  });

  it("labels guard protection actions with guard terminology", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      logs: [
        {
          ...rawReplay.logs[0],
          protect: {
            actor: "李四",
            action: "protect",
            options: ["张三", "李四"],
            choice: "李四",
            lm_log: {
              prompt: "请选择今晚守护对象。",
              raw_response: '{"protect":"李四"}',
              result: { protect: "李四" },
            },
          },
        },
      ],
    });

    expect(replay.debugItems[1]).toMatchObject({
      id: "round-1-night-protect",
      title: "守卫保护",
      actor: "李四",
      choice: "李四",
    });
  });

  it("normalizes protected legacy attacks without marking the target eliminated", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      state: {
        ...rawReplay.state,
        rounds: [
          {
            ...rawReplay.state.rounds[0],
            eliminated: "李四",
            protected: "李四",
          },
        ],
      },
    });

    expect(replay.rounds[0].attacked).toBe("李四");
    expect(replay.rounds[0].protected).toBe("李四");
    expect(replay.rounds[0].eliminated).toBeNull();
  });

  it("keeps confirmed eliminations when the attacked target is not protected", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      state: {
        ...rawReplay.state,
        rounds: [
          {
            ...rawReplay.state.rounds[0],
            attacked: "李四",
            eliminated: "李四",
            protected: "张三",
          },
        ],
      },
    });

    expect(replay.rounds[0].attacked).toBe("李四");
    expect(replay.rounds[0].eliminated).toBe("李四");
  });

  it("normalizes full sheriff election fields, speech order, and weighted votes", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      state: {
        ...rawReplay.state,
        sheriff: "Alice",
        sheriff_badge_lost: false,
        players: [
          {
            name: "Alice",
            role: "村民",
            model: "deepseek-chat",
            is_sheriff: true,
          },
          { name: "Bob", role: "狼人", model: "deepseek-chat" },
          { name: "Cora", role: "预言家", model: "deepseek-chat" },
        ],
        rounds: [
          {
            ...rawReplay.state.rounds[0],
            players: ["Alice", "Bob", "Cora"],
            sheriff: "Alice",
            sheriff_candidates: ["Alice", "Bob"],
            sheriff_speech_order: ["Bob", "Alice"],
            sheriff_speech_direction: "逆时针",
            sheriff_speeches: [
              { speaker: "Alice", message: "我是好人上警。" },
              { speaker: "Bob", message: "我竞选警长。" },
            ],
            sheriff_withdrawn: ["Bob"],
            sheriff_final_candidates: ["Alice"],
            sheriff_voters: ["Bob", "Cora"],
            sheriff_votes: { Bob: "Alice", Cora: "Alice" },
            sheriff_pk_candidates: ["Alice", "Cora"],
            sheriff_pk_speeches: [
              { speaker: "Cora", message: "我进入 PK。" },
            ],
            sheriff_runoff_votes: { Bob: "Cora" },
            sheriff_elected: "Alice",
            speech_order: ["Alice", "Bob", "Cora"],
            speech_order_choice: "clockwise",
            votes: [{ Alice: "Bob" }, { Cora: "Bob" }],
            vote_weights: { Alice: 1.5, Cora: 1 },
            sheriff_badge_target: "Cora",
            sheriff_badge_lost: false,
          },
        ],
      },
    });

    const round = replay.rounds[0];

    expect(replay.sheriff).toBe("Alice");
    expect(replay.sheriffBadgeLost).toBe(false);
    expect(round.sheriff).toBe("Alice");
    expect(round.sheriff_candidates).toEqual(["Alice", "Bob"]);
    expect(round.sheriff_speech_order).toEqual(["Bob", "Alice"]);
    expect(round.sheriff_speech_direction).toBe("逆时针");
    expect(round.sheriff_speeches).toEqual([
      { speaker: "Alice", message: "我是好人上警。" },
      { speaker: "Bob", message: "我竞选警长。" },
    ]);
    expect(round.sheriff_withdrawn).toEqual(["Bob"]);
    expect(round.sheriff_final_candidates).toEqual(["Alice"]);
    expect(round.sheriff_voters).toEqual(["Bob", "Cora"]);
    expect(round.sheriff_votes).toEqual({ Bob: "Alice", Cora: "Alice" });
    expect(round.sheriff_pk_candidates).toEqual(["Alice", "Cora"]);
    expect(round.sheriff_pk_speeches).toEqual([
      { speaker: "Cora", message: "我进入 PK。" },
    ]);
    expect(round.sheriff_runoff_votes).toEqual({ Bob: "Cora" });
    expect(round.sheriff_elected).toBe("Alice");
    expect(round.speech_order).toEqual(["Alice", "Bob", "Cora"]);
    expect(round.speech_order_choice).toBe("clockwise");
    expect(round.votes).toEqual([
      { voter: "Alice", target: "Bob", weight: 1.5 },
      { voter: "Cora", target: "Bob", weight: 1 },
    ]);
    expect(round.voteTally).toEqual([{ target: "Bob", count: 2.5 }]);
    expect(round.voteCount).toBe(2.5);
    expect(round.voteMajorityThreshold).toBe(1.5);
    expect(round.vote_weights).toEqual({ Alice: 1.5, Cora: 1 });
    expect(round.sheriff_badge_target).toBe("Cora");
    expect(round.sheriff_badge_lost).toBe(false);
  });

  it("defaults missing sheriff election fields to stable empty values", () => {
    const replay = normalizeGameReplay(rawReplay);
    const round = replay.rounds[0];

    expect(round.sheriff_speeches).toEqual([]);
    expect(round.sheriff_speech_order).toEqual([]);
    expect(round.sheriff_speech_direction).toBeNull();
    expect(round.sheriff_withdrawn).toEqual([]);
    expect(round.sheriff_final_candidates).toEqual([]);
    expect(round.sheriff_voters).toEqual([]);
    expect(round.sheriff_pk_candidates).toEqual([]);
    expect(round.sheriff_pk_speeches).toEqual([]);
    expect(round.sheriff_runoff_votes).toEqual({});
    expect(round.sheriff_elected).toBeNull();
  });

  it("preserves legacy normal vote majority display thresholds", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      state: {
        ...rawReplay.state,
        rounds: [
          {
            ...rawReplay.state.rounds[0],
            players: ["Alice", "Bob", "Cora", "Dan", "Eve"],
            votes: [
              { Alice: "Dan" },
              { Bob: "Dan" },
              { Cora: "Dan" },
              { Dan: "Alice" },
              { Eve: "Dan" },
            ],
          },
        ],
      },
    });

    const round = replay.rounds[0];

    expect(round.voteCount).toBe(5);
    expect(round.voteMajorityThreshold).toBe(3);
  });

  it("creates ordered debug items for sheriff election actions", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      logs: [
        {
          number: 1,
          eliminate: null,
          protect: null,
          investigate: null,
          sheriff_run: [
            {
              actor: "Alice",
              action: "sheriff_run",
              options: ["参选", "退选"],
              choice: "参选",
              lm_log: {
                prompt: "是否参与警长竞选？",
                raw_response: '{"choice":"参选"}',
                result: { choice: "参选" },
              },
            },
          ],
          sheriff_speech: [
            {
              actor: "Alice",
              action: "sheriff_speech",
              options: [],
              choice: "我是好人上警。",
              lm_log: {
                prompt: "请发表警上发言。",
                raw_response: '{"speech":"我是好人上警。"}',
                result: { speech: "我是好人上警。" },
              },
            },
          ],
          sheriff_withdraw: [
            {
              actor: "Cora",
              action: "sheriff_withdraw",
              options: ["退水", "继续竞选"],
              choice: "退水",
              lm_log: {
                prompt: "请选择是否退水。",
                raw_response: '{"withdraw":"退水"}',
                result: { withdraw: "退水" },
              },
            },
          ],
          sheriff_votes: [
            {
              actor: "Bob",
              action: "sheriff_vote",
              options: ["Alice", "Cora"],
              choice: "Alice",
              lm_log: {
                prompt: "请选择警长候选人。",
                raw_response: '{"choice":"Alice"}',
                result: { choice: "Alice" },
              },
            },
          ],
          sheriff_pk_speech: [
            {
              actor: "Cora",
              action: "sheriff_pk_speech",
              options: [],
              choice: "我进入 PK。",
              lm_log: {
                prompt: "请发表 PK 发言。",
                raw_response: '{"speech":"我进入 PK。"}',
                result: { speech: "我进入 PK。" },
              },
            },
          ],
          sheriff_runoff_votes: [
            {
              actor: "Bob",
              action: "sheriff_runoff_vote",
              options: ["Alice", "Cora"],
              choice: "Cora",
              lm_log: {
                prompt: "请选择二轮警长候选人。",
                raw_response: '{"sheriff_vote":"Cora"}',
                result: { sheriff_vote: "Cora" },
              },
            },
          ],
          speech_order: {
            actor: "Alice",
            action: "speech_order",
            options: ["clockwise", "counterclockwise"],
            choice: "clockwise",
            lm_log: {
              prompt: "请选择发言方向。",
              raw_response: '{"choice":"clockwise"}',
              result: { choice: "clockwise" },
            },
          },
          sheriff_badge: {
            actor: "Alice",
            action: "sheriff_badge",
            options: ["Bob", "Cora", "撕毁警徽"],
            choice: "Cora",
            lm_log: {
              prompt: "请选择警徽移交对象。",
              raw_response: '{"choice":"Cora"}',
              result: { choice: "Cora" },
            },
          },
          bid: [],
          debate: [],
          votes: [],
          summaries: [],
        },
      ],
    });

    expect(
      replay.debugItems.map(({ id, phase, title }) => ({ id, phase, title })),
    ).toEqual([
      {
        id: "round-1-day-sheriff-run-0",
        phase: "day",
        title: "上警选择",
      },
      {
        id: "round-1-day-sheriff-speech-0",
        phase: "day",
        title: "警上发言",
      },
      {
        id: "round-1-day-sheriff-withdraw-0",
        phase: "day",
        title: "退水选择",
      },
      {
        id: "round-1-day-sheriff-vote-0",
        phase: "day",
        title: "警下投票",
      },
      {
        id: "round-1-day-sheriff-pk-speech-0",
        phase: "day",
        title: "PK 发言",
      },
      {
        id: "round-1-day-sheriff-runoff-vote-0",
        phase: "day",
        title: "警下二轮投票",
      },
      {
        id: "round-1-day-speech-order",
        phase: "day",
        title: "发言方向",
      },
      {
        id: "round-1-day-sheriff-badge",
        phase: "day",
        title: "警徽处理",
      },
    ]);
  });

  it("creates ordered debug items for day and summary actions", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      logs: [
        {
          number: 2,
          eliminate: null,
          protect: null,
          investigate: null,
          bid: [
            [
              {
                actor: "张三",
                action: "bid",
                options: ["1", "2", "3"],
                choice: "3",
                lm_log: {
                  prompt: "请选择发言顺序出价。",
                  raw_response: '{"choice":"3"}',
                  result: { choice: "3" },
                },
              },
            ],
          ],
          debate: [
            {
              actor: "李四",
              action: "debate",
              options: [],
              choice: "我不是狼。",
              lm_log: {
                prompt: "请发表白天发言。",
                raw_response: '{"speech":"我不是狼。"}',
                result: { speech: "我不是狼。" },
              },
            },
          ],
          votes: [
            [
              {
                actor: "王五",
                action: "vote",
                options: ["张三", "李四"],
                choice: "张三",
                lm_log: {
                  prompt: "请选择放逐对象。",
                  raw_response: '{"choice":"张三"}',
                  result: { choice: "张三" },
                },
              },
            ],
          ],
          summaries: [
            {
              actor: "张三",
              action: "summarize",
              options: [],
              choice: null,
              lm_log: {
                prompt: "请总结本轮信息。",
                raw_response: '{"summary":"继续隐藏身份。"}',
                result: { summary: "继续隐藏身份。" },
              },
            },
          ],
        },
      ],
    });

    expect(
      replay.debugItems.map(({ id, phase, title }) => ({ id, phase, title })),
    ).toEqual([
      { id: "round-2-day-bid-0", phase: "day", title: "发言竞价" },
      { id: "round-2-day-debate-0", phase: "day", title: "白天发言" },
      { id: "round-2-day-vote-0", phase: "day", title: "放逐投票" },
      { id: "round-2-summary-0", phase: "summary", title: "轮次总结" },
    ]);
    expect(replay.debugItems[3]).toMatchObject({
      actor: "张三",
      prompt: "请总结本轮信息。",
      parsed: { summary: "继续隐藏身份。" },
    });
  });

  it("places sheriff badge handling after exile voting when the sheriff dies during the day", () => {
    const replay = normalizeGameReplay({
      ...rawReplay,
      state: {
        ...rawReplay.state,
        rounds: [
          {
            number: 1,
            players: ["Alice", "Bob", "Cora"],
            eliminated: null,
            protected: null,
            investigated: null,
            exiled: "Alice",
            day_deaths: [
              { player: "Alice", cause: "vote_exile", source: "投票" },
            ],
            debate: [{ speaker: "Bob", message: "先听发言。" }],
            bids: [],
            votes: [{ Bob: "Alice" }],
            summaries: { Bob: "Alice 出局后处理警徽。" },
            success: true,
          },
        ],
      },
      logs: [
        {
          number: 1,
          eliminate: null,
          protect: null,
          investigate: null,
          bid: [],
          speech_order: {
            actor: "Alice",
            action: "speech_order",
            options: ["警左发言", "警右发言"],
            choice: "警左发言",
            lm_log: {
              prompt: "请选择发言方向。",
              raw_response: '{"speech_order":"警左发言"}',
              result: { speech_order: "警左发言" },
            },
          },
          debate: [
            {
              actor: "Bob",
              action: "debate",
              options: [],
              choice: "先听发言。",
              lm_log: {
                prompt: "请发表白天发言。",
                raw_response: '{"say":"先听发言。"}',
                result: { say: "先听发言。" },
              },
            },
          ],
          votes: [
            [
              {
                actor: "Bob",
                action: "vote",
                options: ["Alice", "Cora"],
                choice: "Alice",
                lm_log: {
                  prompt: "请选择放逐对象。",
                  raw_response: '{"vote":"Alice"}',
                  result: { vote: "Alice" },
                },
              },
            ],
          ],
          sheriff_badge: {
            actor: "Alice",
            action: "sheriff_badge",
            options: ["Cora", "撕毁警徽"],
            choice: "撕毁警徽",
            lm_log: {
              prompt: "请选择警徽处理方式。",
              raw_response: '{"badge":"撕毁警徽"}',
              result: { badge: "撕毁警徽" },
            },
          },
          summaries: [
            {
              actor: "Bob",
              action: "summarize",
              options: [],
              choice: "Alice 出局后处理警徽。",
              lm_log: {
                prompt: "请总结本轮信息。",
                raw_response: '{"summary":"Alice 出局后处理警徽。"}',
                result: { summary: "Alice 出局后处理警徽。" },
              },
            },
          ],
        },
      ],
    });

    expect(
      replay.debugItems.map(({ id, phase, title }) => ({ id, phase, title })),
    ).toEqual([
      { id: "round-1-day-speech-order", phase: "day", title: "发言方向" },
      { id: "round-1-day-debate-0", phase: "day", title: "白天发言" },
      { id: "round-1-day-vote-0", phase: "day", title: "放逐投票" },
      { id: "round-1-day-sheriff-badge", phase: "day", title: "警徽处理" },
      { id: "round-1-summary-0", phase: "summary", title: "轮次总结" },
    ]);
  });

  it("normalizes witch hunter idiot round fields", () => {
    const replay = normalizeGameReplay({
      session_id: "session_20260428_120000_abcd1234",
      status: "complete",
      state: {
        session_id: "session_20260428_120000_abcd1234",
        winner: "好人阵营",
        error_message: "",
        rule_set: {
          id: "classic_12_seer_witch_hunter_idiot",
          version: "2026.04",
          name: "12 人预女猎白局",
          player_count: 12,
          roles: [],
        },
        players: [],
        rounds: [
          {
            number: 1,
            players: ["Alice", "Bob"],
            attacked: "Alice",
            eliminated: null,
            protected: null,
            investigated: "Bob",
            exiled: null,
            saved_by_witch: "Alice",
            poisoned: null,
            hunter_shot: null,
            idiot_revealed: "Bob",
            night_deaths: [],
            day_deaths: [],
            debate: [],
            bids: [],
            votes: [],
            summaries: {},
            success: true,
          },
        ],
      },
      logs: [
        {
          number: 1,
          eliminate: null,
          protect: null,
          investigate: null,
          witch_save: {
            actor: "Witch",
            action: "witch_save",
            options: ["Alice", "不使用解药"],
            choice: "Alice",
            lm_log: { prompt: "", raw_response: "", result: { save: "Alice" } },
          },
          witch_poison: null,
          hunter_shoot: null,
          bid: [],
          debate: [],
          votes: [],
          summaries: [],
        },
      ],
    });

    expect(replay.rounds[0].saved_by_witch).toBe("Alice");
    expect(replay.rounds[0].idiot_revealed).toBe("Bob");
    expect(replay.debugItems[0]).toMatchObject({
      title: "女巫解药",
      action: "witch_save",
      choice: "Alice",
    });
  });
});
