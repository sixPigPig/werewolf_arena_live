import { actionLabel, liveEventTitle, phaseLabel } from "./liveLabels";
import type { LiveGameEvent } from "./types";

export type LiveDebugTraceStatus = "ok" | "warning" | "error" | "system";
export type LiveDebugTraceNodeKind =
  | "request"
  | "model"
  | "parsed"
  | "state"
  | "stage"
  | "system";

export type LiveDebugTraceNode = {
  kind: LiveDebugTraceNodeKind;
  eventId: number;
  label: string;
  status: "ok" | "warning" | "error" | "muted";
};

export type LiveDebugStateDiff = {
  label: string;
  before: string;
  after: string;
};

export type LiveDebugTrace = {
  id: string;
  eventIds: number[];
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  choice: string | null;
  title: string;
  status: LiveDebugTraceStatus;
  nodes: LiveDebugTraceNode[];
  impactSummary: string[];
  warnings: string[];
  prompt?: string;
  rawResponse?: string;
  parsed?: unknown;
  payloads: Array<{ eventId: number; type: string; payload: unknown }>;
  stateDiff: LiveDebugStateDiff[];
  relatedPlayers: string[];
};

const STREAM_ONLY_EVENT_TYPES = new Set([
  "model_response_delta",
  "model_thinking_tick",
]);

const SYSTEM_EVENT_TYPES = new Set([
  "run_created",
  "run_started",
  "game_started",
  "round_started",
  "phase_started",
  "game_completed",
  "game_failed",
]);

const NODE_ORDER: LiveDebugTraceNodeKind[] = [
  "request",
  "model",
  "parsed",
  "state",
  "stage",
  "system",
];

const STATE_PLAYER_KEYS = [
  "active_player",
  "exiled",
  "eliminated",
  "attacked",
  "protected",
  "investigated",
];

const STATE_DIFF_LABELS: Record<string, string> = {
  active_player: "当前发言",
  votes: "票型",
  exiled: "放逐",
  eliminated: "出局",
  attacked: "袭击",
  protected: "守护",
  investigated: "查验",
};

export function buildLiveDebugTraces(
  events: LiveGameEvent[],
): LiveDebugTrace[] {
  const traces: LiveDebugTrace[] = [];

  for (const event of events) {
    if (STREAM_ONLY_EVENT_TYPES.has(event.type)) {
      markStreamingModelNode(traces, event);
      continue;
    }

    if (SYSTEM_EVENT_TYPES.has(event.type) && !event.actor) {
      traces.push(createSystemTrace(event));
      continue;
    }

    if (event.type === "action_requested") {
      traces.push(createActionTrace(event));
      continue;
    }

    const existingTrace = findActionTrace(traces, event);
    if (existingTrace) {
      appendEvent(existingTrace, event);
    } else {
      traces.push(createActionTrace(event));
    }
  }

  return traces.map(finalizeTrace);
}

function createActionTrace(event: LiveGameEvent): LiveDebugTrace {
  const trace: LiveDebugTrace = {
    id: `trace-${event.id}-${event.id}`,
    eventIds: [event.id],
    round: event.round,
    phase: event.phase,
    actor: event.actor,
    action: event.action,
    choice: choiceFromPayload(event.payload),
    title: `${event.actor ?? "系统"} · ${actionLabel(event.action)}`,
    status: "ok",
    nodes: [],
    impactSummary: [],
    warnings: [],
    payloads: [{ eventId: event.id, type: event.type, payload: event.payload }],
    stateDiff: [],
    relatedPlayers: uniqueStrings([
      event.actor,
      choiceFromPayload(event.payload),
      ...playersFromStatePayload(event.payload),
    ]),
  };

  if (event.type === "action_requested") {
    upsertNode(trace, {
      kind: "request",
      eventId: event.id,
      label: "行动请求",
      status: "ok",
    });
  } else {
    appendEventDetails(trace, event);
  }

  return trace;
}

function createSystemTrace(event: LiveGameEvent): LiveDebugTrace {
  return {
    id: `system-${event.id}`,
    eventIds: [event.id],
    round: event.round,
    phase: event.phase,
    actor: null,
    action: null,
    choice: null,
    title: systemTitle(event),
    status: "system",
    nodes: [
      {
        kind: "system",
        eventId: event.id,
        label: eventTypeLabel(event.type),
        status: "muted",
      },
    ],
    impactSummary: impactSummary(event.payload),
    warnings: [],
    payloads: [{ eventId: event.id, type: event.type, payload: event.payload }],
    stateDiff: stateDiff(event.payload),
    relatedPlayers: playersFromStatePayload(event.payload),
  };
}

function appendEvent(trace: LiveDebugTrace, event: LiveGameEvent) {
  trace.eventIds = uniqueNumbers([...trace.eventIds, event.id]);
  trace.id = `trace-${trace.eventIds[0]}-${trace.eventIds.at(-1)}`;
  trace.payloads.push({ eventId: event.id, type: event.type, payload: event.payload });
  appendEventDetails(trace, event);
}

function appendEventDetails(trace: LiveDebugTrace, event: LiveGameEvent) {
  const choice = choiceFromPayload(event.payload);
  trace.choice = choice || trace.choice;
  trace.relatedPlayers = uniqueStrings([
    ...trace.relatedPlayers,
    event.actor,
    choice,
    ...playersFromStatePayload(event.payload),
  ]);

  if (event.type === "model_request_started") {
    upsertNode(trace, {
      kind: "model",
      eventId: event.id,
      label: "模型请求",
      status: "ok",
    });
    trace.prompt = stringField(event.payload, "prompt") || trace.prompt;
    return;
  }

  if (event.type === "model_response_received") {
    upsertNode(trace, {
      kind: "model",
      eventId: event.id,
      label: "模型返回",
      status: "ok",
    });
    trace.rawResponse =
      stringField(event.payload, "raw_response") ||
      stringField(event.payload, "visible_text") ||
      stringField(event.payload, "message") ||
      trace.rawResponse;
    return;
  }

  if (event.type === "action_parsed") {
    upsertNode(trace, {
      kind: "parsed",
      eventId: event.id,
      label: "解析完成",
      status: "ok",
    });
    trace.parsed =
      event.payload.parsed ?? event.payload.result ?? event.payload.visible_result;
    return;
  }

  if (event.type === "state_updated") {
    upsertNode(trace, {
      kind: "state",
      eventId: event.id,
      label: "状态更新",
      status: "ok",
    });
    upsertNode(trace, {
      kind: "stage",
      eventId: event.id,
      label: "舞台同步",
      status: "ok",
    });
    trace.impactSummary = uniqueStrings([
      ...trace.impactSummary,
      ...impactSummary(event.payload),
    ]);
    trace.stateDiff = [...trace.stateDiff, ...stateDiff(event.payload)];
  }
}

function finalizeTrace(trace: LiveDebugTrace): LiveDebugTrace {
  if (trace.status === "system") {
    return trace;
  }

  const warnings = new Set(trace.warnings);
  if (!trace.nodes.some((node) => node.kind === "model")) {
    warnings.add("模型返回缺失");
  }
  if (!trace.nodes.some((node) => node.kind === "parsed")) {
    warnings.add("解析结果缺失");
  }
  if (trace.choice && !trace.nodes.some((node) => node.kind === "state")) {
    warnings.add("选择未影响状态");
  }
  if (
    trace.choice &&
    hasStateTargetConflict(trace.choice, trace.actor, trace.payloads)
  ) {
    warnings.add("解析与状态不一致");
  }

  const warningList = Array.from(warnings);
  return {
    ...trace,
    nodes: sortNodes(trace.nodes),
    warnings: warningList,
    status: warningList.includes("解析与状态不一致")
      ? "error"
      : warningList.length > 0
        ? "warning"
        : "ok",
  };
}

function findActionTrace(traces: LiveDebugTrace[], event: LiveGameEvent) {
  return [...traces].reverse().find((trace) => {
    if (trace.status === "system") {
      return false;
    }

    const sameRoundPhase = trace.round === event.round && trace.phase === event.phase;
    if (!sameRoundPhase) {
      return false;
    }

    if (event.actor) {
      return trace.actor === event.actor && trace.action === event.action;
    }

    if (isActorVoteStateEvent(event, trace.actor)) {
      return trace.action === event.action;
    }

    return false;
  });
}

function isActorVoteStateEvent(
  event: LiveGameEvent,
  actor: string | null,
) {
  if (!actor || event.type !== "state_updated") {
    return false;
  }

  const votes = recordField(event.payload, "votes");
  return Boolean(votes && actor in votes);
}

function markStreamingModelNode(traces: LiveDebugTrace[], event: LiveGameEvent) {
  const trace = findActionTrace(traces, event);
  if (!trace) {
    return;
  }

  const existingModelNode = trace.nodes.find((node) => node.kind === "model");
  upsertNode(trace, {
    kind: "model",
    eventId: existingModelNode?.eventId ?? event.id,
    label: "模型流式返回",
    status: "ok",
  });
}

function upsertNode(trace: LiveDebugTrace, node: LiveDebugTraceNode) {
  const existingIndex = trace.nodes.findIndex((item) => item.kind === node.kind);
  if (existingIndex >= 0) {
    trace.nodes[existingIndex] = node;
  } else {
    trace.nodes.push(node);
  }
}

function sortNodes(nodes: LiveDebugTraceNode[]) {
  return [...nodes].sort(
    (left, right) =>
      NODE_ORDER.indexOf(left.kind) - NODE_ORDER.indexOf(right.kind),
  );
}

function systemTitle(event: LiveGameEvent) {
  if (event.type === "round_started") {
    return event.round === null ? "新回合开始" : `第 ${event.round} 轮开始`;
  }
  if (event.type === "phase_started") {
    const label = phaseLabel(event.phase);
    return label ? `${label}阶段开始` : "阶段开始";
  }
  return liveEventTitle(event);
}

function eventTypeLabel(type: string) {
  const labels: Record<string, string> = {
    run_created: "运行已创建",
    run_started: "运行已开始",
    game_started: "对局开始",
    round_started: "回合开始",
    phase_started: "阶段开始",
    action_requested: "行动请求",
    model_request_started: "模型请求",
    model_response_received: "模型返回",
    action_parsed: "解析完成",
    state_updated: "状态更新",
    game_completed: "对局完成",
    game_failed: "对局失败",
  };
  return labels[type] ?? type;
}

function impactSummary(payload: Record<string, unknown>) {
  const summary: string[] = [];
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    summary.push(`${debateEntry.speaker} 新增公开发言`);
  }

  if (recordField(payload, "votes")) {
    summary.push("票型更新");
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    summary.push(`${exiled} 被放逐`);
  }

  const eliminated = stringField(payload, "eliminated");
  if (eliminated) {
    summary.push(`${eliminated} 夜晚出局`);
  }

  return summary;
}

function stateDiff(payload: Record<string, unknown>): LiveDebugStateDiff[] {
  const diffs: LiveDebugStateDiff[] = [];

  const activePlayer = stringField(payload, "active_player");
  if (activePlayer) {
    diffs.push({
      label: STATE_DIFF_LABELS.active_player,
      before: "未记录",
      after: activePlayer,
    });
  }

  const votes = recordField(payload, "votes");
  if (votes) {
    diffs.push({
      label: STATE_DIFF_LABELS.votes,
      before: "未记录",
      after: JSON.stringify(votes),
    });
  }

  for (const key of [
    "exiled",
    "eliminated",
    "attacked",
    "protected",
    "investigated",
  ]) {
    const value = stringField(payload, key);
    if (value) {
      diffs.push({
        label: STATE_DIFF_LABELS[key],
        before: "未记录",
        after: value,
      });
    }
  }

  return diffs;
}

function choiceFromPayload(payload: Record<string, unknown>) {
  return (
    stringField(payload, "choice") ||
    stringField(payload, "target") ||
    stringField(payload, "vote")
  );
}

function playersFromStatePayload(payload: Record<string, unknown>) {
  const players = STATE_PLAYER_KEYS.map((key) => stringField(payload, key));

  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    players.push(debateEntry.speaker);
  }

  return uniqueStrings(players);
}

function hasStateTargetConflict(
  choice: string,
  actor: string | null,
  payloads: LiveDebugTrace["payloads"],
) {
  if (!actor) {
    return false;
  }

  return payloads.some((item) => {
    if (item.type !== "state_updated" || !isRecord(item.payload)) {
      return false;
    }

    const votes = recordField(item.payload, "votes");
    if (!votes) {
      return false;
    }

    if (!(actor in votes)) {
      return false;
    }

    return String(votes[actor]) !== choice;
  });
}

function stringField(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

function recordField(
  payload: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  const value = payload[key];
  return isRecord(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(
    new Set(values.filter((value): value is string => Boolean(value))),
  );
}

function uniqueNumbers(values: number[]) {
  return Array.from(new Set(values));
}
