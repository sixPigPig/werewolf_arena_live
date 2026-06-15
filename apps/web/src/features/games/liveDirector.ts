import type { LiveGameEvent } from "./types";
import { eventTypeLabel, liveEventTitle } from "./liveLabels";

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

export function buildDirectorCues(events: LiveGameEvent[]): DirectorCue[] {
  const cues: DirectorCue[] = [];
  const requestCueById = new Map<
    string,
    { cue: DirectorCue; visibleText: string }
  >();

  for (const event of events) {
    const payload = payloadForEvent(event);
    const requestId = stringField(payload, "request_id");

    if (event.type === "model_response_delta") {
      const requestCue = requestId ? requestCueById.get(requestId) : undefined;
      if (!requestCue) {
        continue;
      }

      const visibleText = stringField(payload, "visible_text");
      if (!visibleText) {
        continue;
      }

      requestCue.visibleText += visibleText;
      const actor = event.actor || requestCue.cue.actor || "未知玩家";
      const body = `${actor}：${requestCue.visibleText}`;
      requestCue.cue.title = `${actor} 正在发言`;
      requestCue.cue.body = body;
      requestCue.cue.importance = "key";
      requestCue.cue.durationMs = longTextDuration(body);
      requestCue.cue.compressible = false;
      continue;
    }

    if (event.type === "model_thinking_tick") {
      const requestCue = requestId ? requestCueById.get(requestId) : undefined;
      if (!requestCue || requestCue.visibleText) {
        continue;
      }

      const body = thinkingTickBody(payload);
      if (body) {
        requestCue.cue.body = body;
        requestCue.cue.durationMs = statusTextDuration(body);
      }
      continue;
    }

    const cue = toDirectorCue(event);
    cues.push(cue);

    if (event.type === "model_request_started" && requestId) {
      requestCueById.set(requestId, { cue, visibleText: "" });
    }
  }

  return cues;
}

export function toDirectorCue(event: LiveGameEvent): DirectorCue {
  const rawPayload = event.payload as unknown;
  const payload = payloadForEvent(event);
  const base = cueBase(event);

  if (event.type === "run_created") {
    return {
      ...base,
      title: "运行已创建",
      body: "对局运行已创建，正在准备玩家、规则和实时事件流。",
      durationMs: 2000,
    };
  }

  if (event.type === "run_started") {
    return {
      ...base,
      title: "运行已开始",
      body: "后台对局已开始，观赛事件会按导播节奏播放。",
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
      body: event.round === null ? "新的回合即将展开。" : `第 ${event.round} 轮开始。`,
      durationMs: 2500,
    };
  }

  if (event.type === "phase_started") {
    return {
      ...base,
      title: liveEventTitle(event),
      body: activePlayersBody(payload),
      durationMs: 2500,
    };
  }

  if (event.type === "action_requested") {
    return {
      ...base,
      title: liveEventTitle(event),
      body: optionsBody(payload),
      importance: "action",
      durationMs: 2500,
      compressible: true,
    };
  }

  if (event.type === "model_retry_scheduled") {
    const attempt = Number(payload.attempt ?? 0);
    return {
      ...base,
      title: `${event.actor ?? "玩家"} 正在重试行动`,
      body: `${stringField(payload, "message") || "模型输出不在候选项中，正在重试。"}${attempt ? `第 ${attempt} 次尝试。` : ""}`,
      importance: "action",
      durationMs: 3000,
      compressible: true,
    };
  }

  if (event.type === "action_quality_warning") {
    const fallbackChoice = stringField(payload, "fallback_choice");
    return {
      ...base,
      title: "行动质量提示",
      body: fallbackChoice
        ? `已使用安全兜底：${fallbackChoice}`
        : readablePayload(rawPayload),
      importance: "action",
      durationMs: 3500,
      compressible: true,
    };
  }

  if (event.type === "model_request_started") {
    return {
      ...base,
      title: liveEventTitle(event),
      body:
        stringField(payload, "message") ||
        `${stringField(payload, "model") || "模型"} 正在生成下一步。`,
      importance: "action",
      durationMs: 2500,
      compressible: true,
    };
  }

  if (event.type === "model_response_received") {
    const body =
      stringField(payload, "visible_text") ||
      stringField(payload, "message") ||
      "模型返回已接收，正在解析行动";
    return {
      ...base,
      title: liveEventTitle(event),
      body,
      importance: "action",
      durationMs: stringField(payload, "visible_text") ? longTextDuration(body) : 2500,
      compressible: !stringField(payload, "visible_text"),
    };
  }

  if (event.type === "action_parsed") {
    const parsedBody = parsedActionBody(payload);
    return {
      ...base,
      title: liveEventTitle(event),
      body: parsedBody || readablePayload(rawPayload),
      importance: "action",
      durationMs: parsedBody ? longTextDuration(parsedBody) : 3500,
      compressible: !parsedBody,
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
    title: eventTypeLabel(event.type),
    body: readablePayload(rawPayload),
    durationMs: 2000,
  };
}

function payloadForEvent(event: LiveGameEvent): Record<string, unknown> {
  return isRecord(event.payload) ? event.payload : {};
}

function cueBase(event: LiveGameEvent): DirectorCue {
  return {
    eventId: event.id,
    type: event.type,
    round: event.round,
    phase: event.phase,
    actor: event.actor,
    action: event.action,
    title: eventTypeLabel(event.type),
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
    const body = `${debateEntry.speaker}：${message}`;
    return {
      ...base,
      title: `${debateEntry.speaker} 发言`,
      body,
      importance: "key",
      durationMs: longTextDuration(body),
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
      body: `${savedPlayer} 被袭击，但被守卫保护。\n${activePlayersBody(payload)}`,
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

  const publicSummary = stringField(payload, "public_summary");
  if (publicSummary) {
    return {
      ...base,
      title: "回合公开总结",
      body: publicSummary,
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const summaries = payload.summaries;
  if (isRecord(summaries) && !isRecord(payload.private_summaries)) {
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
    title: eventTypeLabel(event.type),
    body: readablePayload(rawPayload),
    durationMs: 3000,
  };
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

  const visibleResult = payload.visible_result;
  if (isRecord(visibleResult)) {
    const say = stringField(visibleResult, "say");
    if (say) {
      return say;
    }
    const summary = stringField(visibleResult, "summary");
    if (summary) {
      return summary;
    }
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

function numberField(
  payload: Record<string, unknown>,
  field: string,
): number | null {
  const value = payload[field];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function thinkingTickBody(payload: Record<string, unknown>): string {
  const message = stringField(payload, "message");
  if (!message) {
    return "";
  }

  const elapsedMs = numberField(payload, "elapsed_ms");
  return elapsedMs === null
    ? message
    : `${message}（${Math.round(elapsedMs / 1000)} 秒）`;
}

const NORMAL_CHARS_PER_SECOND = 4;
const NORMAL_WORDS_PER_MINUTE = 150;
const LONG_TEXT_LEAD_IN_MS = 1000;
const MIN_TEXT_DURATION_MS = 6000;
const MAX_TEXT_DURATION_MS = 20000;

function longTextDuration(text: string): number {
  const cjkChars = Array.from(text).filter(isCjkSpeechChar).length;
  const words = text.match(/[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*/g)?.length ?? 0;
  const chineseMs = (cjkChars / NORMAL_CHARS_PER_SECOND) * 1000;
  const wordMs = (words / NORMAL_WORDS_PER_MINUTE) * 60 * 1000;
  const estimatedMs = Math.round(
    LONG_TEXT_LEAD_IN_MS + Math.max(chineseMs, wordMs),
  );

  return Math.min(
    MAX_TEXT_DURATION_MS,
    Math.max(MIN_TEXT_DURATION_MS, estimatedMs),
  );
}

function statusTextDuration(text: string): number {
  return Math.min(12000, Math.max(6000, 3500 + text.length * 45));
}

function isCjkSpeechChar(char: string): boolean {
  return /[\u3400-\u9fff]|\p{Script=Han}|\p{Script=Hiragana}|\p{Script=Katakana}|\p{Script=Hangul}/u.test(
    char,
  );
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
