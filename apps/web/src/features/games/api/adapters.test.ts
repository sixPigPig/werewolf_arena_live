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

  it("normalizes sheriff speech order and weighted votes", () => {
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
          { name: "Carol", role: "预言家", model: "deepseek-chat" },
        ],
        rounds: [
          {
            ...rawReplay.state.rounds[0],
            players: ["Alice", "Bob", "Carol"],
            sheriff: "Alice",
            sheriff_candidates: ["Alice", "Bob"],
            sheriff_votes: { Bob: "Alice", Carol: "Alice" },
            speech_order: ["Alice", "Bob", "Carol"],
            speech_order_choice: "clockwise",
            votes: [{ Alice: "Bob" }, { Carol: "Bob" }],
            vote_weights: { Alice: 1.5, Carol: 1 },
            sheriff_badge_target: "Carol",
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
    expect(round.sheriff_votes).toEqual({ Bob: "Alice", Carol: "Alice" });
    expect(round.speech_order).toEqual(["Alice", "Bob", "Carol"]);
    expect(round.speech_order_choice).toBe("clockwise");
    expect(round.votes).toEqual([
      { voter: "Alice", target: "Bob", weight: 1.5 },
      { voter: "Carol", target: "Bob", weight: 1 },
    ]);
    expect(round.voteTally).toEqual([{ target: "Bob", count: 2.5 }]);
    expect(round.voteCount).toBe(2.5);
    expect(round.voteMajorityThreshold).toBe(1.25);
    expect(round.vote_weights).toEqual({ Alice: 1.5, Carol: 1 });
    expect(round.sheriff_badge_target).toBe("Carol");
    expect(round.sheriff_badge_lost).toBe(false);
  });

  it("creates debug items for sheriff actions", () => {
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
          sheriff_votes: [
            {
              actor: "Bob",
              action: "sheriff_vote",
              options: ["Alice", "Carol"],
              choice: "Alice",
              lm_log: {
                prompt: "请选择警长候选人。",
                raw_response: '{"choice":"Alice"}',
                result: { choice: "Alice" },
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
            options: ["Bob", "Carol", "撕毁警徽"],
            choice: "Carol",
            lm_log: {
              prompt: "请选择警徽移交对象。",
              raw_response: '{"choice":"Carol"}',
              result: { choice: "Carol" },
            },
          },
          bid: [],
          debate: [],
          votes: [],
          summaries: [],
        },
      ],
    });

    expect(replay.debugItems.map((item) => item.title)).toEqual([
      "警长竞选",
      "警长投票",
      "发言方向",
      "警徽移交",
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
