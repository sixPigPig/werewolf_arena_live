import type { LiveGameEvent } from "./types";

export type DirectorCueImportance = "normal" | "action" | "key" | "terminal";

export type DirectorCue = {
  eventId: number;
  type: string;
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  title: string;
  body: string;
  importance: DirectorCueImportance;
  durationMs: number;
  compressible: boolean;
};

export function toDirectorCue(event: LiveGameEvent): DirectorCue {
  const rawPayload = event.payload as unknown;
  const payload = isRecord(rawPayload) ? rawPayload : {};
  const base = cueBase(event);

  if (event.type === "run_created") {
    return {
      ...base,
      title: "运行已创建",
      body: readablePayload(rawPayload),
      durationMs: 2000,
    };
  }

  if (event.type === "run_started") {
    return {
      ...base,
      title: "运行已开始",
      body: readablePayload(rawPayload),
      durationMs: 2000,
    };
  }

  if (event.type === "game_started") {
    return {
      ...base,
      title: "对局开始",
      body: gameStartedBody(payload),
      importance: "key",
      durationMs: 5000,
      compressible: false,
    };
  }

  if (event.type === "round_started") {
    return {
      ...base,
      title: event.round === null ? "新回合开始" : `第 ${event.round} 轮开始`,
      body: readablePayload(rawPayload),
      durationMs: 2500,
    };
  }

  if (event.type === "phase_started") {
    return {
      ...base,
      title: `${phaseLabel(event.phase)}阶段开始`,
      body: activePlayersBody(payload),
      durationMs: 2500,
    };
  }

  if (event.type === "action_requested") {
    return {
      ...base,
      title: `${actorLabel(event)} 准备 ${actionLabel(event)}`,
      body: optionsBody(payload),
      importance: "action",
      durationMs: 2500,
      compressible: true,
    };
  }

  if (event.type === "model_request_started") {
    return {
      ...base,
      title: `${actorLabel(event)} 请求模型`,
      body: stringField(payload, "model"),
      importance: "action",
      durationMs: 2500,
      compressible: true,
    };
  }

  if (event.type === "model_response_received") {
    const body = stringField(payload, "raw_response") || readablePayload(rawPayload);
    return {
      ...base,
      title: `${actorLabel(event)} 的模型返回`,
      body,
      importance: "key",
      durationMs: longTextDuration(body),
      compressible: false,
    };
  }

  if (event.type === "action_parsed") {
    return {
      ...base,
      title: `${actorLabel(event)} 完成 ${actionLabel(event)}`,
      body: parsedActionBody(payload) || readablePayload(rawPayload),
      importance: "action",
      durationMs: 3500,
      compressible: true,
    };
  }

  if (event.type === "state_updated") {
    return stateUpdatedCue(event, rawPayload, payload, base);
  }

  if (event.type === "game_completed") {
    return {
      ...base,
      title: "对局完成",
      body: winnerBody(payload) || readablePayload(rawPayload),
      importance: "terminal",
      durationMs: 8000,
      compressible: false,
    };
  }

  if (event.type === "game_failed") {
    return {
      ...base,
      title: "对局失败",
      body: stringField(payload, "error") || readablePayload(rawPayload),
      importance: "terminal",
      durationMs: 8000,
      compressible: false,
    };
  }

  return {
    ...base,
    title: event.type,
    body: readablePayload(rawPayload),
    durationMs: 2000,
  };
}

function cueBase(event: LiveGameEvent): DirectorCue {
  return {
    eventId: event.id,
    type: event.type,
    round: event.round,
    phase: event.phase,
    actor: event.actor,
    action: event.action,
    title: event.type,
    body: "",
    importance: "normal",
    durationMs: 2000,
    compressible: true,
  };
}

function stateUpdatedCue(
  event: LiveGameEvent,
  rawPayload: unknown,
  payload: Record<string, unknown>,
  base: DirectorCue,
): DirectorCue {
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    const message =
      typeof debateEntry.message === "string" ? debateEntry.message : "";
    return {
      ...base,
      title: `${debateEntry.speaker} 发言`,
      body: `${debateEntry.speaker}：${message}`,
      importance: "key",
      durationMs: longTextDuration(message),
      compressible: false,
    };
  }

  const votes = payload.votes;
  if (isRecord(votes)) {
    return {
      ...base,
      title: "投票结果更新",
      body: Object.entries(votes)
        .map(([voter, target]) => `${voter} -> ${String(target)}`)
        .join("\n"),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    return {
      ...base,
      title: `${exiled} 被放逐`,
      body: activePlayersBody(payload),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  const eliminated = stringField(payload, "eliminated");
  const savedPlayer =
    (attacked && protectedPlayer === attacked ? attacked : "") ||
    (eliminated && protectedPlayer === eliminated ? eliminated : "");
  if (savedPlayer) {
    return {
      ...base,
      title: "平安夜",
      body: `${savedPlayer} 被袭击，但被医生守护。\n${activePlayersBody(payload)}`,
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  if (eliminated) {
    return {
      ...base,
      title: `${eliminated} 夜晚出局`,
      body: activePlayersBody(payload),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const summaries = payload.summaries;
  if (isRecord(summaries)) {
    return {
      ...base,
      title: "回合总结更新",
      body: Object.entries(summaries)
        .map(([actor, summary]) => `${actor}：${String(summary)}`)
        .join("\n"),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const winner = stringField(payload, "winner");
  if (winner) {
    return {
      ...base,
      title: "胜负已更新",
      body: `胜利阵营：${winner}`,
      importance: "terminal",
      durationMs: 8000,
      compressible: false,
    };
  }

  return {
    ...base,
    title: event.type,
    body: readablePayload(rawPayload),
    durationMs: 3000,
  };
}

function actorLabel(event: LiveGameEvent): string {
  return event.actor || "未知玩家";
}

function actionLabel(event: LiveGameEvent): string {
  return event.action || "行动";
}

function phaseLabel(phase: string | null): string {
  if (phase === "night") {
    return "夜晚";
  }
  if (phase === "day") {
    return "白天";
  }
  if (phase === "vote") {
    return "投票";
  }
  if (phase === "summary") {
    return "总结";
  }
  return phase ? `${phase} ` : "";
}

function gameStartedBody(payload: Record<string, unknown>): string {
  const players = payload.players;
  if (!Array.isArray(players)) {
    return readablePayload(payload);
  }

  const names = players
    .map((player) => (isRecord(player) ? stringField(player, "name") : ""))
    .filter(Boolean);
  return names.length > 0 ? `玩家：${names.join("、")}` : readablePayload(payload);
}

function optionsBody(payload: Record<string, unknown>): string {
  const options = payload.options;
  if (!Array.isArray(options) || options.length === 0) {
    return "";
  }
  return `可选目标：${options.map(String).join("、")}`;
}

function parsedActionBody(payload: Record<string, unknown>): string {
  const choice = stringField(payload, "choice");
  if (choice) {
    return choice;
  }

  const result = payload.result;
  if (isRecord(result)) {
    const say = stringField(result, "say");
    if (say) {
      return say;
    }
    const summary = stringField(result, "summary");
    if (summary) {
      return summary;
    }
  }

  return "";
}

function winnerBody(payload: Record<string, unknown>): string {
  const winner = stringField(payload, "winner");
  return winner ? `胜利阵营：${winner}` : "";
}

function activePlayersBody(payload: Record<string, unknown>): string {
  const activePlayers = payload.active_players;
  if (!Array.isArray(activePlayers)) {
    return "";
  }
  return `存活玩家：${activePlayers.map(String).join("、")}`;
}

function stringField(
  payload: Record<string, unknown>,
  field: string,
): string {
  const value = payload[field];
  return typeof value === "string" ? value : "";
}

function longTextDuration(text: string): number {
  return Math.min(12000, Math.max(6000, 3500 + text.length * 45));
}

function readablePayload(payload: unknown): string {
  if (payload === undefined || payload === null) {
    return "";
  }
  if (typeof payload === "string") {
    return payload;
  }

  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
