import { describe, expect, it } from "vitest";

import { buildLiveDebugTraces } from "./liveDebugTrace";
import type { LiveGameEvent } from "./types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "action_requested",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: partial.created_at ?? "2026-04-24T12:00:00Z",
    round: partial.round ?? 1,
    phase: partial.phase ?? "day",
    actor: "actor" in partial ? (partial.actor ?? null) : "Sam",
    action: "action" in partial ? (partial.action ?? null) : "debate",
    payload: partial.payload ?? {},
  };
}

describe("buildLiveDebugTraces", () => {
  it("groups request model parsed and state events into one action trace", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 10,
        type: "action_requested",
        payload: { options: ["Isaac"] },
      }),
      event({
        id: 11,
        type: "model_request_started",
        payload: { request_id: "req_1", prompt: "请公开发言。" },
      }),
      event({
        id: 12,
        type: "model_response_received",
        payload: { raw_response: "{\"say\":\"我怀疑 Isaac\"}" },
      }),
      event({
        id: 13,
        type: "action_parsed",
        payload: {
          choice: "Isaac",
          visible_result: { say: "我怀疑 Isaac" },
        },
      }),
      event({
        id: 14,
        type: "state_updated",
        payload: {
          active_player: "Sam",
          debate_entry: { speaker: "Sam", message: "我怀疑 Isaac" },
        },
      }),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces[0]).toMatchObject({
      id: "trace-10",
      eventIds: [10, 11, 12, 13, 14],
      actor: "Sam",
      action: "debate",
      choice: "Isaac",
      status: "ok",
      title: "Sam · 公开发言",
      relatedPlayers: ["Sam", "Isaac"],
    });
    expect(traces[0].nodes.map((node) => node.kind)).toEqual([
      "request",
      "model",
      "parsed",
      "state",
      "stage",
    ]);
    expect(traces[0].impactSummary).toContain("Sam 新增公开发言");
    expect(traces[0].stateDiff).toContainEqual({
      label: "当前发言",
      before: "未记录",
      after: "Sam",
    });
  });

  it("keeps action trace ids stable as later events are appended", () => {
    const initial = buildLiveDebugTraces([
      event({ id: 10, type: "action_requested" }),
    ]);
    const withModel = buildLiveDebugTraces([
      event({ id: 10, type: "action_requested" }),
      event({ id: 11, type: "model_response_received" }),
    ]);
    const withState = buildLiveDebugTraces([
      event({ id: 10, type: "action_requested" }),
      event({ id: 11, type: "model_response_received" }),
      event({ id: 12, type: "action_parsed", payload: { choice: "Isaac" } }),
      event({
        id: 13,
        type: "state_updated",
        payload: { active_player: "Sam" },
      }),
    ]);

    expect(initial[0].id).toBe("trace-10");
    expect(withModel[0].id).toBe("trace-10");
    expect(withState[0].id).toBe("trace-10");
    expect(withState[0].eventIds).toEqual([10, 11, 12, 13]);
  });

  it("keeps streaming deltas out of the trace list but records model streaming status", () => {
    const traces = buildLiveDebugTraces([
      event({ id: 1, type: "action_requested" }),
      event({
        id: 2,
        type: "model_response_delta",
        payload: { request_id: "req_1", visible_text: "我" },
      }),
      event({
        id: 3,
        type: "model_thinking_tick",
        payload: { request_id: "req_1", message: "思考中" },
      }),
      event({ id: 4, type: "model_response_received" }),
      event({ id: 5, type: "action_parsed", payload: { choice: "skip" } }),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces[0].eventIds).toEqual([1, 4, 5]);
    expect(traces[0].nodes.some((node) => node.eventId === 2)).toBe(false);
    expect(traces[0].nodes.some((node) => node.eventId === 3)).toBe(false);
    expect(traces[0].nodes.find((node) => node.kind === "model")?.label).toBe(
      "模型返回",
    );
  });

  it("creates system traces for non actor flow events", () => {
    const traces = buildLiveDebugTraces([
      event({ id: 1, type: "round_started", actor: null, action: null, round: 2 }),
      event({
        id: 2,
        type: "phase_started",
        actor: null,
        action: null,
        phase: "night",
      }),
    ]);

    expect(traces).toHaveLength(2);
    expect(traces[0]).toMatchObject({
      id: "system-1",
      status: "system",
      title: "第 2 轮开始",
    });
    expect(traces[1]).toMatchObject({
      id: "system-2",
      status: "system",
      title: "夜晚阶段开始",
    });
  });

  it("marks missing parsed results as warnings", () => {
    const traces = buildLiveDebugTraces([
      event({ id: 1, type: "action_requested" }),
      event({ id: 2, type: "model_response_received" }),
    ]);

    expect(traces[0].status).toBe("warning");
    expect(traces[0].warnings).toContain("解析结果缺失");
  });

  it("marks parsed choice and state target conflicts as errors", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
        action: "vote",
        payload: { options: ["Isaac", "Bert"] },
      }),
      event({
        id: 2,
        type: "action_parsed",
        action: "vote",
        payload: { choice: "Isaac" },
      }),
      event({
        id: 3,
        type: "state_updated",
        action: "vote",
        payload: { votes: { Sam: "Bert" } },
      }),
    ]);

    expect(traces[0].status).toBe("error");
    expect(traces[0].warnings).toContain("解析与状态不一致");
  });

  it("attaches action quality fallback warnings to action traces", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
        actor: "1号玩家",
        action: "witch_poison",
        payload: { options: ["不使用毒药"] },
      }),
      event({
        id: 2,
        type: "action_quality_warning",
        actor: "1号玩家",
        action: "witch_poison",
        payload: {
          warnings: ["off_option_fallback"],
          invalid_value: "10号玩家",
          fallback_choice: "不使用毒药",
        },
      }),
    ]);

    expect(traces[0].status).toBe("warning");
    expect(traces[0].warnings).toContain("off_option_fallback");
    expect(traces[0].impactSummary.join(" ")).toContain("不使用毒药");
  });

  it("compares vote conflicts only against the trace actor vote", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
        action: "vote",
        payload: { options: ["Isaac", "Carl"] },
      }),
      event({
        id: 2,
        type: "model_response_received",
        action: "vote",
      }),
      event({
        id: 3,
        type: "action_parsed",
        action: "vote",
        payload: { choice: "Isaac" },
      }),
      event({
        id: 4,
        type: "state_updated",
        action: "vote",
        payload: { votes: { Sam: "Isaac", Bert: "Carl" } },
      }),
    ]);

    expect(traces[0].status).toBe("ok");
    expect(traces[0].warnings).not.toContain("解析与状态不一致");
  });

  it("attaches null actor vote state updates to the trace actor vote and detects conflict", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
        action: "vote",
        payload: { options: ["Isaac", "Bert"] },
      }),
      event({
        id: 2,
        type: "model_response_received",
        action: "vote",
      }),
      event({
        id: 3,
        type: "action_parsed",
        action: "vote",
        payload: { choice: "Isaac" },
      }),
      event({
        id: 4,
        type: "state_updated",
        actor: null,
        action: "vote",
        payload: { votes: { Sam: "Bert" } },
      }),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces[0].eventIds).toEqual([1, 2, 3, 4]);
    expect(traces[0].status).toBe("error");
    expect(traces[0].warnings).toContain("解析与状态不一致");
  });

  it("does not flag null actor vote state updates when the trace actor vote matches", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
        action: "vote",
        payload: { options: ["Isaac", "Carl"] },
      }),
      event({
        id: 2,
        type: "model_response_received",
        action: "vote",
      }),
      event({
        id: 3,
        type: "action_parsed",
        action: "vote",
        payload: { choice: "Isaac" },
      }),
      event({
        id: 4,
        type: "state_updated",
        actor: null,
        action: "vote",
        payload: { votes: { Sam: "Isaac", Bert: "Carl" } },
      }),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces[0].eventIds).toEqual([1, 2, 3, 4]);
    expect(traces[0].status).toBe("ok");
    expect(traces[0].warnings).not.toContain("解析与状态不一致");
  });

  it("fans out actorless vote state updates to every affected voter trace", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
        actor: "Sam",
        action: "vote",
        phase: "vote",
        payload: { options: ["Isaac", "Carl"] },
      }),
      event({
        id: 2,
        type: "model_response_received",
        actor: "Sam",
        action: "vote",
        phase: "vote",
      }),
      event({
        id: 3,
        type: "action_parsed",
        actor: "Sam",
        action: "vote",
        phase: "vote",
        payload: { choice: "Isaac" },
      }),
      event({
        id: 4,
        type: "action_requested",
        actor: "Bert",
        action: "vote",
        phase: "vote",
        payload: { options: ["Isaac", "Carl"] },
      }),
      event({
        id: 5,
        type: "model_response_received",
        actor: "Bert",
        action: "vote",
        phase: "vote",
      }),
      event({
        id: 6,
        type: "action_parsed",
        actor: "Bert",
        action: "vote",
        phase: "vote",
        payload: { choice: "Carl" },
      }),
      event({
        id: 7,
        type: "state_updated",
        actor: null,
        action: "vote",
        phase: "vote",
        payload: { votes: { Sam: "Isaac", Bert: "Carl" } },
      }),
    ]);

    expect(traces).toHaveLength(2);
    expect(traces.map((trace) => trace.eventIds)).toEqual([
      [1, 2, 3, 7],
      [4, 5, 6, 7],
    ]);
    expect(traces.map((trace) => trace.status)).toEqual(["ok", "ok"]);
    expect(traces[0].warnings).not.toContain("选择未影响状态");
    expect(traces[1].warnings).not.toContain("选择未影响状态");
  });

  it("attaches real playback phase state updates back to debate traces", () => {
    const traces = buildLiveDebugTraces([
      event({ id: 1, type: "action_requested", action: "debate" }),
      event({ id: 2, type: "model_response_received", action: "debate" }),
      event({
        id: 3,
        type: "action_parsed",
        action: "debate",
        payload: {
          choice: "Isaac",
          visible_result: { say: "我怀疑 Isaac" },
        },
      }),
      event({
        id: 4,
        type: "state_updated",
        actor: null,
        action: null,
        payload: {
          debate: [{ speaker: "Sam", message: "我怀疑 Isaac" }],
          votes: {},
        },
      }),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces[0].eventIds).toEqual([1, 2, 3, 4]);
    expect(traces[0].status).toBe("ok");
    expect(traces[0].impactSummary).toContain("Sam 新增公开发言");
  });

  it("marks model request failures as direct trace errors", () => {
    const traces = buildLiveDebugTraces([
      event({ id: 1, type: "action_requested" }),
      event({
        id: 2,
        type: "model_request_failed",
        payload: { message: "模型请求失败，请稍后重试" },
      }),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces[0].status).toBe("error");
    expect(traces[0].nodes.find((node) => node.kind === "model")).toMatchObject({
      label: "模型请求失败",
      status: "error",
    });
    expect(traces[0].warnings).toContain("模型请求失败，请稍后重试");
  });

  it("attaches actorless night aggregate state to matching protect and investigate traces", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
        actor: "Guard",
        action: "protect",
        phase: "night",
        payload: { options: ["Sam"] },
      }),
      event({
        id: 2,
        type: "model_response_received",
        actor: "Guard",
        action: "protect",
        phase: "night",
      }),
      event({
        id: 3,
        type: "action_parsed",
        actor: "Guard",
        action: "protect",
        phase: "night",
        payload: { choice: "Sam" },
      }),
      event({
        id: 4,
        type: "action_requested",
        actor: "Seer",
        action: "investigate",
        phase: "night",
        payload: { options: ["Isaac"] },
      }),
      event({
        id: 5,
        type: "model_response_received",
        actor: "Seer",
        action: "investigate",
        phase: "night",
      }),
      event({
        id: 6,
        type: "action_parsed",
        actor: "Seer",
        action: "investigate",
        phase: "night",
        payload: { choice: "Isaac" },
      }),
      event({
        id: 7,
        type: "state_updated",
        actor: null,
        action: null,
        phase: "night",
        payload: {
          protected: "Sam",
          investigated: "Isaac",
          active_players: ["Guard", "Seer", "Sam", "Isaac"],
        },
      }),
    ]);

    expect(traces).toHaveLength(2);
    expect(traces.map((trace) => trace.eventIds)).toEqual([
      [1, 2, 3, 7],
      [4, 5, 6, 7],
    ]);
    expect(traces.map((trace) => trace.status)).toEqual(["ok", "ok"]);
  });

  it("matches actorless sheriff vote fields without crossing into regular vote traces", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
        actor: "Sam",
        action: "sheriff_vote",
        payload: { options: ["Isaac"] },
      }),
      event({
        id: 2,
        type: "model_response_received",
        actor: "Sam",
        action: "sheriff_vote",
      }),
      event({
        id: 3,
        type: "action_parsed",
        actor: "Sam",
        action: "sheriff_vote",
        payload: { choice: "Isaac" },
      }),
      event({
        id: 4,
        type: "action_requested",
        actor: "Sam",
        action: "vote",
        payload: { options: ["Bert"] },
      }),
      event({
        id: 5,
        type: "model_response_received",
        actor: "Sam",
        action: "vote",
      }),
      event({
        id: 6,
        type: "action_parsed",
        actor: "Sam",
        action: "vote",
        payload: { choice: "Bert" },
      }),
      event({
        id: 7,
        type: "state_updated",
        actor: null,
        action: null,
        payload: {
          sheriff_votes: { Sam: "Isaac" },
          votes: { Sam: "Bert" },
        },
      }),
    ]);

    expect(traces).toHaveLength(2);
    expect(traces[0]).toMatchObject({
      action: "sheriff_vote",
      eventIds: [1, 2, 3, 7],
      status: "ok",
    });
    expect(traces[1]).toMatchObject({
      action: "vote",
      eventIds: [4, 5, 6, 7],
      status: "ok",
    });
  });

  it("does not attach unrelated null actor state updates to a previous actor trace", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "action_requested",
      }),
      event({
        id: 2,
        type: "state_updated",
        actor: null,
        action: null,
        payload: { eliminated: "Bert" },
      }),
    ]);

    expect(traces).toHaveLength(2);
    expect(traces[0]).toMatchObject({
      id: "trace-1",
      eventIds: [1],
      actor: "Sam",
    });
    expect(traces[1]).toMatchObject({
      id: "trace-2",
      eventIds: [2],
      actor: null,
    });
  });

  it("does not duplicate payloads state diffs or impact summaries for orphan non-request events", () => {
    const traces = buildLiveDebugTraces([
      event({
        id: 1,
        type: "state_updated",
        actor: null,
        action: null,
        payload: {
          active_player: "Sam",
          debate_entry: { speaker: "Sam", message: "继续发言" },
        },
      }),
    ]);

    expect(traces).toHaveLength(1);
    expect(traces[0].eventIds).toEqual([1]);
    expect(traces[0].payloads).toHaveLength(1);
    expect(traces[0].stateDiff).toHaveLength(1);
    expect(traces[0].impactSummary).toEqual(["Sam 新增公开发言"]);
  });
});
