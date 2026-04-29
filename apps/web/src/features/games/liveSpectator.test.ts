import { describe, expect, it } from "vitest";

import { deriveLiveSpectatorState } from "./liveSpectator";
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

describe("deriveLiveSpectatorState", () => {
  it("initializes players from game_started", () => {
    const state = deriveLiveSpectatorState([
      event({
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "村民", model: "deepseek-chat" },
          ],
        },
      }),
    ]);

    expect(state.players.map((player) => player.name)).toEqual([
      "张三",
      "李四",
    ]);
    expect(state.players[0]).toMatchObject({
      role: "狼人",
      model: "deepseek-chat",
      status: "waiting",
      isAlive: true,
    });
  });

  it("focuses actor events and records latest action detail", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "狼人", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { options: [] },
      }),
      event({
        id: 3,
        type: "action_parsed",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { choice: "我不是狼" },
      }),
    ]);

    expect(state.activePlayerName).toBe("张三");
    expect(state.currentRound).toBe(1);
    expect(state.currentPhase).toBe("day");
    expect(state.players[0]).toMatchObject({
      status: "acted",
      lastAction: "debate",
      lastDetail: "我不是狼",
    });
  });

  it("marks players outside active_players as not alive", () => {
    const state = deriveLiveSpectatorState([
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
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: { active_players: ["张三"], eliminated: "李四" },
      }),
    ]);

    expect(state.players.find((player) => player.name === "李四")?.isAlive).toBe(
      false,
    );
  });

  it("keeps a protected attack target alive", () => {
    const state = deriveLiveSpectatorState([
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
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          attacked: "李四",
          protected: "李四",
          eliminated: null,
          active_players: ["张三", "李四"],
        },
      }),
    ]);

    expect(state.players.find((player) => player.name === "李四")).toMatchObject({
      isAlive: true,
      status: "waiting",
      lastAction: "remove",
      lastDetail: "被守护，未出局",
    });
  });

  it("keeps a protected eliminated target alive without attacked payload", () => {
    const state = deriveLiveSpectatorState([
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
        type: "state_updated",
        round: 1,
        phase: "night",
        payload: {
          protected: "李四",
          eliminated: "李四",
          active_players: ["张三"],
        },
      }),
    ]);

    expect(state.players.find((player) => player.name === "李四")).toMatchObject({
      isAlive: true,
      status: "waiting",
    });
  });

  it("clears no-detail pending actions when the game reaches a terminal event", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "村民", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "summary",
        actor: "张三",
        action: "summarize",
        payload: {},
      }),
      event({
        id: 3,
        type: "game_completed",
        payload: { winner: "好人阵营" },
      }),
    ]);

    expect(state.players[0]).toMatchObject({
      status: "waiting",
      lastAction: "",
      lastDetail: "",
    });
  });

  it("preserves non-pending action labels without details at terminal", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "村民", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "action_parsed",
        actor: "张三",
        action: "vote",
        round: 1,
        phase: "vote",
        payload: {},
      }),
      event({
        id: 3,
        type: "game_completed",
        payload: { winner: "好人阵营" },
      }),
    ]);

    expect(state.players[0]).toMatchObject({
      status: "acted",
      lastAction: "vote",
      lastDetail: "",
    });
  });

  it("accumulates streamed visible text for the active player", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "村民", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "model_request_started",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", model: "deepseek-chat" },
      }),
      event({
        id: 3,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", visible_text: "我", is_public: true },
      }),
      event({
        id: 4,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", visible_text: "不是狼", is_public: true },
      }),
    ]);

    expect(state.players[0]).toMatchObject({
      status: "streaming",
      lastAction: "debate",
      lastDetail: "我不是狼",
    });
  });

  it("replaces a thinking tick placeholder with the first response delta", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "村民", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "model_request_started",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", model: "deepseek-chat" },
      }),
      event({
        id: 3,
        type: "model_thinking_tick",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", message: "正在组织发言..." },
      }),
      event({
        id: 4,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", visible_text: "我不是狼" },
      }),
    ]);

    expect(state.players[0]).toMatchObject({
      status: "streaming",
      lastDetail: "我不是狼",
    });
  });

  it("keeps streamed detail when a later thinking tick arrives", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "村民", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", visible_text: "我不是狼" },
      }),
      event({
        id: 3,
        type: "model_thinking_tick",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", message: "仍在生成..." },
      }),
    ]);

    expect(state.players[0]).toMatchObject({
      status: "streaming",
      lastDetail: "我不是狼",
    });
  });

  it("resets streamed visible text when the request id changes", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "村民", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", visible_text: "旧请求" },
      }),
      event({
        id: 3,
        type: "model_response_delta",
        actor: "张三",
        action: "summarize",
        round: 1,
        phase: "summary",
        payload: { request_id: "req_456", visible_text: "新请求" },
      }),
    ]);

    expect(state.players[0]).toMatchObject({
      status: "streaming",
      lastAction: "summarize",
      lastDetail: "新请求",
    });
  });

  it("clears streaming request state when a parsed action arrives", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "村民", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", visible_text: "临时" },
      }),
      event({
        id: 3,
        type: "action_parsed",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { choice: "最终发言" },
      }),
    ]);

    expect(state.players[0]).toMatchObject({
      status: "acted",
      lastAction: "debate",
      lastDetail: "最终发言",
      activeRequestId: null,
    });
  });
});
