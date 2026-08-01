export type V2ModelInputFact = {
  authority: string | null;
  context: string | null;
  id: string;
  kind: string;
  recordSeq: number | null;
  summary: string | null;
  title: string;
};

export function extractV2ModelInputFacts(
  requestPayload: Record<string, unknown> | null,
): V2ModelInputFact[] {
  if (!requestPayload) return [];
  const prompt = structuredPromptFromPayload(requestPayload);
  if (!prompt) return [];

  const knownEvents = objectValue(prompt.known_events);
  const publicTimeline = objectValue(prompt.public_timeline);
  const history = objectValue(prompt.history);
  const historyTimeline = arrayValue(history?.timeline).filter(isRecord);
  const publicEvents = arrayValue(
    knownEvents?.events ?? publicTimeline?.events,
  ).filter(isRecord);

  if (publicEvents.length) {
    return publicEvents.map((event, index) =>
      publicEventFact(event, index),
    );
  }

  return historyTimeline.map((item, index) => historyFact(item, index));
}

function structuredPromptFromPayload(
  requestPayload: Record<string, unknown>,
): Record<string, unknown> | null {
  const input = Array.isArray(requestPayload.input)
    ? requestPayload.input
    : [];
  const messages = Array.isArray(requestPayload.messages)
    ? requestPayload.messages
    : [];
  const items = input.length ? input : messages;

  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (!isRecord(item)) continue;
    const text = messageText(item.content);
    const parsed = parseStructuredPrompt(text);
    if (parsed) return parsed;
  }
  return null;
}

function messageText(value: unknown): string {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return "";
  return value
    .map((part) => {
      if (typeof part === "string") return part;
      return isRecord(part) && typeof part.text === "string" ? part.text : "";
    })
    .filter(Boolean)
    .join("\n");
}

function parseStructuredPrompt(text: string): Record<string, unknown> | null {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    const value: unknown = JSON.parse(text.slice(start, end + 1));
    return isRecord(value) ? value : null;
  } catch {
    return null;
  }
}

function publicEventFact(
  event: Record<string, unknown>,
  index: number,
): V2ModelInputFact {
  const recordSeq =
    numberValue(event.known_at_seq) ?? numberValue(event.record_seq);
  const kind = textValue(event.kind) ?? "unknown";

  return {
    authority: textValue(event.authority),
    context: eventContext(event),
    id:
      textValue(event.event_ref) ??
      textValue(event.source_event_id) ??
      `${recordSeq ?? "unknown"}-${kind}-${index}`,
    kind,
    recordSeq,
    summary: eventSummary(event),
    title: eventTitle(kind),
  };
}

function historyFact(
  item: Record<string, unknown>,
  index: number,
): V2ModelInputFact {
  const recordSeq = numberValue(item.record_seq);
  return {
    authority: "player_claim_unverified",
    context: eventContext(item),
    id:
      textValue(item.source_event_id) ??
      textValue(item.statement_id) ??
      `history-${index}`,
    kind: "player_statement",
    recordSeq,
    summary: null,
    title: eventTitle("player_statement"),
  };
}

function eventTitle(kind: string): string {
  const labels: Record<string, string> = {
    day_vote: "白天投票",
    night_result: "夜间结果",
    player_eliminated: "玩家出局",
    player_statement: "玩家发言",
    sheriff_badge_transferred: "警徽移交",
    sheriff_elected: "警长当选",
    vote_result: "投票结果",
  };
  return labels[kind] ?? kind.replaceAll("_", " ");
}

function eventSummary(event: Record<string, unknown>): string | null {
  const kind = textValue(event.kind);
  if (kind === "player_statement") {
    return textValue(event.speech);
  }
  if (kind === "day_vote") {
    const voter = playerReference(event.voter_ref);
    const target = playerReference(event.target_ref);
    const action = actionLabel(textValue(event.action_type));
    const weight = numberValue(event.weight);
    return [
      voter && target ? `${voter}投给${target}` : null,
      action,
      weight !== null && weight !== 1 ? `票权 ${weight}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
  }
  if (kind === "vote_result") {
    const leaders = referenceList(event.leader_refs);
    const totals = voteTotals(event.totals);
    return [
      actionLabel(textValue(event.action_type)),
      totals ? `票型 ${totals}` : null,
      leaders ? `领先 ${leaders}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
  }
  if (kind === "night_result") {
    const eliminated = referenceList(event.eliminated_player_refs);
    const outcome = textValue(event.outcome);
    return eliminated
      ? `夜间出局：${eliminated}`
      : outcome === "peaceful"
        ? "平安夜"
        : `夜间结果：${outcome ?? "已公布"}`;
  }
  if (kind === "player_eliminated") {
    const player = playerReference(event.player_ref);
    const reason = eliminationReason(textValue(event.public_reason));
    return `${player ?? "玩家"}出局${reason ? ` · ${reason}` : ""}`;
  }
  if (kind === "sheriff_elected") {
    const player = playerReference(event.player_ref ?? event.sheriff_ref);
    return `${player ?? "玩家"}当选警长`;
  }
  if (kind === "sheriff_badge_transferred") {
    const payload = objectValue(event.payload);
    const from = playerReference(payload?.from_player_id);
    const to = playerReference(payload?.player_id);
    return `${from ?? "原警长"}将警徽移交给${to ?? "新警长"}`;
  }

  return stringifyFact(event) ?? "模型输入中已记录该事实";
}

function eventContext(event: Record<string, unknown>): string | null {
  const occurred = objectValue(event.occurred_in);
  const period = textValue(occurred?.period);
  const roundNo = numberValue(occurred?.round_no);
  const stage = textValue(event.stage);
  const pieces = [
    roundNo !== null
      ? `第 ${roundNo} ${period === "night" ? "夜" : "天"}`
      : period === "night"
        ? "夜间"
        : period === "day"
          ? "白天"
          : null,
    stage ? actionLabel(stage) : null,
  ].filter(Boolean);
  return pieces.length ? pieces.join(" · ") : null;
}

function playerReference(value: unknown): string | null {
  const reference = textValue(value);
  if (!reference) return null;
  const match = /^seat_(\d+)$/u.exec(reference);
  return match ? `${match[1]}号` : reference;
}

function referenceList(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  const items = value
    .map(playerReference)
    .filter((item): item is string => Boolean(item));
  return items.length ? items.join("、") : null;
}

function voteTotals(value: unknown): string | null {
  const totals = objectValue(value);
  if (!totals) return null;
  const items = Object.entries(totals).flatMap(([player, count]) => {
    const numericCount = numberValue(count);
    return numericCount === null
      ? []
      : [`${playerReference(player) ?? player} ${numericCount}票`];
  });
  return items.length ? items.join("，") : null;
}

function actionLabel(value: string | null): string | null {
  if (!value) return null;
  const labels: Record<string, string> = {
    day_debate_speech: "白天讨论",
    exile_last_words: "放逐遗言",
    exile_vote: "放逐投票",
    sheriff_campaign_speech: "警长竞选发言",
    sheriff_vote: "警长投票",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function eliminationReason(value: string | null): string | null {
  const labels: Record<string, string> = {
    exile: "被放逐",
    poison: "中毒",
    werewolf_attack: "遭狼人袭击",
  };
  return value ? labels[value] ?? value.replaceAll("_", " ") : null;
}

function stringifyFact(event: Record<string, unknown>): string | null {
  const excluded = new Set([
    "authority",
    "kind",
    "record_seq",
    "source_event_id",
    "timeline_index",
  ]);
  const detail = Object.fromEntries(
    Object.entries(event).filter(([key]) => !excluded.has(key)),
  );
  return Object.keys(detail).length ? JSON.stringify(detail) : null;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null;
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
