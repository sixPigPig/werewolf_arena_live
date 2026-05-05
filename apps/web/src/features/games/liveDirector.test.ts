import { describe, expect, it } from "vitest";

import { buildDirectorCues, toDirectorCue } from "./liveDirector";
import type { LiveGameEvent } from "./types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "game_started",
    run_id: "run_1234abcd",
    session_id: "session_20260424_120000_ab12cd34",
    created_at: "2026-04-24T12:00:00Z",
    round: partial.round ?? null,
    phase: partial.phase ?? null,
    actor: partial.actor ?? null,
    action: partial.action ?? null,
    payload: partial.payload ?? {},
  };
}

describe("toDirectorCue", () => {
  it("renders action request as a playable action cue", () => {
    const cue = toDirectorCue(
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: { options: ["李四"] },
      }),
    );

    expect(cue).toMatchObject({
      eventId: 2,
      title: "张三 正在公开发言",
      body: "可选目标：李四",
      importance: "action",
      compressible: true,
    });
  });

  it("renders sanitized model response receipts", () => {
    const cue = toDirectorCue(
      event({
        id: 3,
        type: "model_response_received",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          model: "deepseek-chat",
          message: "模型返回已接收，正在解析行动",
        },
      }),
    );

    expect(cue.title).toBe("张三 的模型返回已接收");
    expect(cue.body).toBe("模型返回已接收，正在解析行动");
    expect(cue.importance).toBe("action");
    expect(cue.compressible).toBe(true);
    expect(cue.durationMs).toBe(2500);
  });

  it("renders state updates for debate, votes, exile and completed games", () => {
    expect(
      toDirectorCue(
        event({
          type: "state_updated",
          actor: "李四",
          action: "debate",
          payload: {
            debate_entry: { speaker: "李四", message: "张三的发言很可疑。" },
          },
        }),
      ).body,
    ).toBe("李四：张三的发言很可疑。");

    expect(
      toDirectorCue(
        event({
          type: "state_updated",
          phase: "vote",
          action: "vote",
          payload: { votes: { 张三: "李四", 李四: "张三" } },
        }),
      ).body,
    ).toBe("张三 -> 李四\n李四 -> 张三");

    expect(
      toDirectorCue(
        event({
          type: "state_updated",
          payload: { exiled: "王五", active_players: ["张三", "李四"] },
        }),
      ).title,
    ).toBe("王五 被放逐");

    expect(
      toDirectorCue(
        event({
          type: "game_completed",
          payload: { winner: "好人阵营" },
        }),
      ),
    ).toMatchObject({
      title: "对局完成",
      body: "胜利阵营：好人阵营",
      importance: "terminal",
      compressible: false,
    });
  });

  it("renders protected night attacks as a peaceful night cue", () => {
    const cue = toDirectorCue(
      event({
        type: "state_updated",
        payload: {
          attacked: "李四",
          protected: "李四",
          eliminated: "李四",
          active_players: ["张三"],
        },
      }),
    );

    expect(cue).toMatchObject({
      title: "平安夜",
      importance: "key",
      durationMs: 6000,
      compressible: false,
    });
    expect(cue.body).toContain("李四 被袭击，但被守卫保护。");
    expect(cue.body).toContain("存活玩家：张三");
  });

  it("renders legacy protected eliminations as peaceful night cues", () => {
    const cue = toDirectorCue(
      event({
        type: "state_updated",
        payload: {
          protected: "李四",
          eliminated: "李四",
          active_players: ["张三", "李四"],
        },
      }),
    );

    expect(cue).toMatchObject({
      title: "平安夜",
      importance: "key",
      durationMs: 6000,
      compressible: false,
    });
    expect(cue.body).toContain("李四 被袭击，但被守卫保护。");
    expect(cue.body).toContain("存活玩家：张三、李四");
    expect(cue.title).not.toBe("李四 夜晚出局");
  });

  it("renders confirmed night eliminations when protection differs", () => {
    const cue = toDirectorCue(
      event({
        type: "state_updated",
        payload: {
          protected: "李四",
          eliminated: "王五",
          active_players: ["张三", "李四"],
        },
      }),
    );

    expect(cue).toMatchObject({
      title: "王五 夜晚出局",
      importance: "key",
      durationMs: 6000,
      compressible: false,
    });
  });

  it("falls back safely for unknown or malformed events", () => {
    const unknownCue = toDirectorCue(
      event({
        type: "custom_diagnostic",
        payload: { note: "debug value", count: 2 },
      }),
    );

    expect(unknownCue.title).toBe("custom_diagnostic");
    expect(unknownCue.body).toContain("debug value");
    expect(unknownCue.importance).toBe("normal");
    expect(unknownCue.compressible).toBe(true);

    const malformedCue = toDirectorCue(
      event({
        type: "state_updated",
        payload: "not an object" as unknown as Record<string, unknown>,
      }),
    );

    expect(malformedCue.title).toBe("state_updated");
    expect(malformedCue.body).toContain("not an object");
  });

  it("coalesces streaming deltas into the matching request cue", () => {
    const cues = buildDirectorCues([
      event({
        id: 2,
        type: "model_request_started",
        actor: "张三",
        action: "debate",
        payload: { request_id: "req_123", model: "deepseek-chat" },
      }),
      event({
        id: 3,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          visible_text: "我",
          is_public: true,
        },
      }),
      event({
        id: 4,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          visible_text: "不是狼",
          is_public: true,
        },
      }),
    ]);

    expect(cues).toHaveLength(1);
    expect(cues[0]).toMatchObject({
      eventId: 2,
      title: "张三 正在发言",
      body: "张三：我不是狼",
      importance: "key",
      compressible: false,
    });
  });

  it("coalesces thinking ticks with elapsed milliseconds into the matching request cue", () => {
    const cues = buildDirectorCues([
      event({
        id: 2,
        type: "model_request_started",
        actor: "张三",
        action: "debate",
        payload: { request_id: "req_123", model: "deepseek-chat" },
      }),
      event({
        id: 3,
        type: "model_thinking_tick",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          message: "正在组织发言",
          elapsed_ms: 3200,
        },
      }),
    ]);

    expect(cues).toHaveLength(1);
    expect(cues[0]).toMatchObject({
      eventId: 2,
      body: "正在组织发言（3 秒）",
    });
  });

  it("ignores orphan streaming deltas and thinking ticks", () => {
    const cues = buildDirectorCues([
      event({
        id: 3,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_missing",
          visible_text: "我不是狼",
        },
      }),
      event({
        id: 4,
        type: "model_thinking_tick",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_missing",
          message: "正在思考",
          elapsed_ms: 1000,
        },
      }),
    ]);

    expect(cues).toHaveLength(0);
  });

  it("ignores empty streaming deltas without promoting the request cue", () => {
    const cues = buildDirectorCues([
      event({
        id: 2,
        type: "model_request_started",
        actor: "张三",
        action: "debate",
        payload: { request_id: "req_123", model: "deepseek-chat" },
      }),
      event({
        id: 3,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          visible_text: "",
        },
      }),
      event({
        id: 4,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          visible_text: 42,
        },
      }),
    ]);

    expect(cues).toHaveLength(1);
    expect(cues[0]).toMatchObject({
      eventId: 2,
      title: "张三 正在思考",
      body: "deepseek-chat 正在生成下一步。",
      importance: "action",
      compressible: true,
    });
  });
});
