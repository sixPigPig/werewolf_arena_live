import { describe, expect, it } from "vitest";

import { toDirectorCue } from "./liveDirector";
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
      title: "张三 准备 debate",
      body: "可选目标：李四",
      importance: "action",
      compressible: true,
    });
  });

  it("keeps model responses readable for longer", () => {
    const cue = toDirectorCue(
      event({
        id: 3,
        type: "model_response_received",
        actor: "张三",
        action: "debate",
        payload: { raw_response: "我不是狼人，我建议今天先听李四发言。" },
      }),
    );

    expect(cue.title).toBe("张三 的模型返回");
    expect(cue.body).toContain("我不是狼人");
    expect(cue.importance).toBe("key");
    expect(cue.compressible).toBe(false);
    expect(cue.durationMs).toBeGreaterThanOrEqual(6000);
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
});
