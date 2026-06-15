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
  "poisoned",
  "saved_by_witch",
];

const STATE_DIFF_LABELS: Record<string, string> = {
  active_player: "当前发言",
  votes: "票型",
  sheriff_votes: "警长票型",
  sheriff_runoff_votes: "PK 票型",
  exiled: "放逐",
  eliminated: "出局",
  attacked: "袭击",
  protected: "守护",
  investigated: "查验",
  poisoned: "毒杀",
  saved_by_witch: "女巫救人",
};

const VOTE_STATE_FIELDS: Record<string, string> = {
  sheriff_runoff_vote: "sheriff_runoff_votes",
  sheriff_vote: "sheriff_votes",
  vote: "votes",
  werewolf_kill_vote: "werewolf_votes",
};

const TARGET_STATE_FIELDS: Record<string, string> = {
  investigate: "investigated",
  protect: "protected",
  remove: "attacked",
  werewolf_kill_vote: "attacked",
  witch_poison: "poisoned",
  witch_save: "saved_by_witch",
};

const STATE_KEYS_BY_ACTION: Record<string, string[]> = {
  debate: ["active_player", "debate_entry", "debate"],
  hunter_shoot: ["hunter_shot"],
  investigate: ["investigated"],
  protect: ["protected"],
  remove: ["attacked", "eliminated"],
  sheriff_pk_speech: ["sheriff_pk_speeches"],
  sheriff_runoff_vote: ["sheriff_runoff_votes"],
  sheriff_speech: ["sheriff_speeches"],
  sheriff_vote: ["sheriff_votes"],
  vote: ["votes", "exiled"],
  werewolf_kill_vote: ["attacked"],
  witch_poison: ["poisoned", "eliminated"],
  witch_save: ["saved_by_witch"],
};

const SPEECH_STATE_FIELDS: Array<{ key: string; action: string }> = [
  { key: "debate", action: "debate" },
  { key: "sheriff_speeches", action: "sheriff_speech" },
  { key: "sheriff_pk_speeches", action: "sheriff_pk_speech" },
];

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

    const existingTraces = findActionTraces(traces, event);
    if (existingTraces.length > 0) {
      existingTraces.forEach((trace) => appendEvent(trace, event));
    } else {
      traces.push(createActionTrace(event));
    }
  }

  return traces.map(finalizeTrace);
}

function createActionTrace(event: LiveGameEvent): LiveDebugTrace {
  const trace: LiveDebugTrace = {
    id: `trace-${event.id}`,
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
  trace.payloads.push({ eventId: event.id, type: event.type, payload: event.payload });
  appendEventDetails(trace, event);
}

function appendEventDetails(trace: LiveDebugTrace, event: LiveGameEvent) {
  const statePayload =
    event.type === "state_updated"
      ? statePayloadForTrace(event.payload, trace.action)
      : event.payload;
  const choice = choiceFromPayload(event.payload);
  trace.choice = choice || trace.choice;
  trace.relatedPlayers = uniqueStrings([
    ...trace.relatedPlayers,
    event.actor,
    choice,
    ...playersFromStatePayload(statePayload),
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

  if (event.type === "model_request_failed") {
    const message = stringField(event.payload, "message") || "模型请求失败";
    upsertNode(trace, {
      kind: "model",
      eventId: event.id,
      label: "模型请求失败",
      status: "error",
    });
    trace.rawResponse = message;
    trace.warnings = uniqueStrings([...trace.warnings, message]);
    return;
  }

  if (event.type === "action_quality_warning") {
    upsertNode(trace, {
      kind: "stage",
      eventId: event.id,
      label: "质量提示",
      status: "warning",
    });
    const warnings = arrayStrings(event.payload, "warnings");
    trace.warnings = uniqueStrings([...trace.warnings, ...warnings]);
    const fallbackChoice = stringField(event.payload, "fallback_choice");
    if (fallbackChoice) {
      trace.impactSummary = uniqueStrings([
        ...trace.impactSummary,
        `安全兜底：${fallbackChoice}`,
      ]);
      trace.choice = fallbackChoice;
    }
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
      ...impactSummary(statePayload),
    ]);
    trace.stateDiff = [...trace.stateDiff, ...stateDiff(statePayload)];
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
    hasStateTargetConflict(trace.choice, trace.actor, trace.action, trace.payloads)
  ) {
    warnings.add("解析与状态不一致");
  }

  const warningList = Array.from(warnings);
  const hasErrorNode = trace.nodes.some((node) => node.status === "error");
  return {
    ...trace,
    nodes: sortNodes(trace.nodes),
    warnings: warningList,
    status: warningList.includes("解析与状态不一致") || hasErrorNode
      ? "error"
      : warningList.length > 0
        ? "warning"
        : "ok",
  };
}

function findActionTraces(traces: LiveDebugTrace[], event: LiveGameEvent) {
  const candidates = traces.filter((trace) => isSameTraceScope(trace, event));
  if (event.actor) {
    const latestActorTrace = [...candidates]
      .reverse()
      .find(
        (trace) => trace.actor === event.actor && trace.action === event.action,
      );
    return latestActorTrace ? [latestActorTrace] : [];
  }

  if (event.type === "state_updated") {
    return candidates.filter((trace) => stateEventAffectsTrace(event, trace));
  }

  return [];
}

function findActionTrace(traces: LiveDebugTrace[], event: LiveGameEvent) {
  return findActionTraces(traces, event).at(-1) ?? null;
}

function isSameTraceScope(trace: LiveDebugTrace, event: LiveGameEvent) {
  return (
    trace.status !== "system" &&
    trace.round === event.round &&
    trace.phase === event.phase
  );
}

function isActorVoteStateEvent(
  event: LiveGameEvent,
  trace: LiveDebugTrace,
) {
  const actor = trace.actor;
  const voteField = trace.action ? VOTE_STATE_FIELDS[trace.action] : undefined;
  if (!actor || !voteField || event.type !== "state_updated") {
    return false;
  }

  if (event.action && event.action !== trace.action) {
    return false;
  }

  const votes = recordField(event.payload, voteField);
  if (!votes || !(actor in votes)) {
    return false;
  }

  return true;
}

function stateEventAffectsTrace(
  event: LiveGameEvent,
  trace: LiveDebugTrace,
) {
  return (
    isActorVoteStateEvent(event, trace) ||
    isActionTargetStateEvent(event, trace) ||
    isActorSpeechStateEvent(event, trace) ||
    isActivePlayerStateEvent(event, trace)
  );
}

function isActionTargetStateEvent(
  event: LiveGameEvent,
  trace: LiveDebugTrace,
) {
  const stateField = trace.action ? TARGET_STATE_FIELDS[trace.action] : undefined;
  if (!stateField || !trace.choice || event.type !== "state_updated") {
    return false;
  }

  if (event.action && event.action !== trace.action) {
    return false;
  }

  return stringField(event.payload, stateField) === trace.choice;
}

function isActorSpeechStateEvent(
  event: LiveGameEvent,
  trace: LiveDebugTrace,
) {
  if (!trace.actor || event.type !== "state_updated") {
    return false;
  }

  return SPEECH_STATE_FIELDS.some(
    ({ action, key }) =>
      trace.action === action &&
      speakerNamesFromField(event.payload[key]).includes(trace.actor ?? ""),
  );
}

function isActivePlayerStateEvent(
  event: LiveGameEvent,
  trace: LiveDebugTrace,
) {
  if (!trace.actor || event.type !== "state_updated") {
    return false;
  }

  return (
    trace.action === "debate" &&
    stringField(event.payload, "active_player") === trace.actor
  );
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
    model_request_failed: "模型请求失败",
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
  for (const speaker of speakerNamesFromPayload(payload)) {
    summary.push(`${speaker} 新增公开发言`);
  }

  if (recordField(payload, "votes")) {
    summary.push("票型更新");
  }
  if (recordField(payload, "sheriff_votes")) {
    summary.push("警长票型更新");
  }
  if (recordField(payload, "sheriff_runoff_votes")) {
    summary.push("PK 票型更新");
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    summary.push(`${exiled} 被放逐`);
  }

  const eliminated = stringField(payload, "eliminated");
  if (eliminated) {
    summary.push(`${eliminated} 夜晚出局`);
  }

  return uniqueStrings(summary);
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

  for (const key of ["votes", "sheriff_votes", "sheriff_runoff_votes"]) {
    const votes = recordField(payload, key);
    if (votes) {
      diffs.push({
        label: STATE_DIFF_LABELS[key],
        before: "未记录",
        after: JSON.stringify(votes),
      });
    }
  }

  for (const key of [
    "exiled",
    "eliminated",
    "attacked",
    "protected",
    "investigated",
    "poisoned",
    "saved_by_witch",
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
  players.push(...speakerNamesFromPayload(payload));

  return uniqueStrings(players);
}

function speakerNamesFromPayload(payload: Record<string, unknown>) {
  return uniqueStrings(
    SPEECH_STATE_FIELDS.flatMap(({ key }) => speakerNamesFromField(payload[key])),
  );
}

function speakerNamesFromField(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) =>
    isRecord(item) && typeof item.speaker === "string" ? [item.speaker] : [],
  );
}

function statePayloadForTrace(
  payload: Record<string, unknown>,
  action: string | null,
) {
  if (!action) {
    return payload;
  }

  const keys = STATE_KEYS_BY_ACTION[action];
  if (!keys) {
    return payload;
  }

  const scopedPayload: Record<string, unknown> = {};
  for (const key of keys) {
    if (key in payload) {
      scopedPayload[key] = payload[key];
    }
  }
  return scopedPayload;
}

function hasStateTargetConflict(
  choice: string,
  actor: string | null,
  action: string | null,
  payloads: LiveDebugTrace["payloads"],
) {
  if (!actor) {
    return false;
  }

  const voteField = action ? VOTE_STATE_FIELDS[action] : undefined;
  if (!voteField) {
    return false;
  }

  return payloads.some((item) => {
    if (item.type !== "state_updated" || !isRecord(item.payload)) {
      return false;
    }

    const votes = recordField(item.payload, voteField);
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

function arrayStrings(payload: Record<string, unknown>, key: string): string[] {
  const value = payload[key];
  return Array.isArray(value) ? value.map(String) : [];
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
