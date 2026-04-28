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
