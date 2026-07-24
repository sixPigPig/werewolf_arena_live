import type {
  V2GamePresentation,
  V2GameRecordDetail,
  V2GameRecordEvent,
  V2ModelRequest,
  V2VoiceAsset,
} from "@/v2/game-records/types";

export type V2TimelineItem = {
  id: string;
  kind: "action" | "milestone";
  actionId: string | null;
  actionType: string;
  label: string;
  objective: string | null;
  phaseId: string;
  actorKind: string;
  actorId: string;
  actorLabel: string;
  audience: string;
  status: "running" | "succeeded" | "failed";
  startedAt: string;
  completedAt: string | null;
  durationMs: number | null;
  firstRecordSeq: number;
  lastRecordSeq: number;
  modelRequest: V2ModelRequest | null;
  presentation: V2GamePresentation | null;
  voiceAsset: V2VoiceAsset | null;
  events: V2GameRecordEvent[];
};

export type V2PhaseGroup = {
  phaseId: string;
  label: string;
  items: V2TimelineItem[];
  modelRequestCount: number;
  failureCount: number;
  isCurrent: boolean;
};

const lifecycleEventTypes = new Set([
  "model_request_started",
  "model_first_token_received",
  "model_response_received",
  "model_request_failed",
  "model_decision_target_normalized",
  "speech_opened",
  "speech_segment_committed",
  "speech_sealed",
  "tts_stream_started",
  "tts_first_chunk_received",
  "voice_recording_started",
  "audio_broadcast_started",
  "tts_stream_completed",
  "voice_asset_saved",
  "audio_drained",
  "speech_closed",
  "action_succeeded",
  "action_failed",
]);

const milestoneEventTypes = new Set([
  "game_created",
  "roles_assigned",
  "ability_runtime_compiled",
  "game_started",
  "game_phase_changed",
  "action_window_opened",
  "action_window_closed",
  "night_resolved",
  "dawn_public_result",
  "sheriff_election_started",
  "sheriff_elected",
  "sheriff_badge_destroyed",
  "sheriff_vote_resolved",
  "exile_resolved",
  "game_completed",
]);

const actionLabels: Record<string, string> = {
  judge_opening_speech: "开场播报",
  judge_nightfall_announcement: "夜幕播报",
  werewolf_attack_wake: "狼人睁眼",
  werewolf_attack_sleep: "狼人闭眼",
  judge_dawn_announcement: "天亮播报",
  judge_public_discussion_opening: "白天讨论开场",
  judge_sheriff_election_opening: "警长竞选开场",
  judge_sheriff_elected: "警长产生播报",
  judge_sheriff_badge_result: "警徽去向播报",
  judge_sheriff_badge_destroyed: "警徽流失播报",
  judge_exile_result: "放逐结果播报",
  judge_no_exile: "无人放逐播报",
  judge_day_summary: "日间总结",
  judge_game_completed: "对局结束播报",
  sheriff_run: "竞选发言",
  sheriff_withdraw: "退水决定",
  sheriff_vote: "警长投票",
  day_speech: "白天发言",
  exile_vote: "放逐投票",
  werewolf_self_explosion: "狼人自爆决定",
};

const eventLabels: Record<string, string> = {
  game_created: "游戏创建",
  roles_assigned: "角色分配",
  ability_runtime_compiled: "能力编译",
  game_started: "游戏开始",
  game_phase_changed: "阶段推进",
  action_window_opened: "行动窗口开启",
  action_window_closed: "行动窗口关闭",
  night_resolved: "夜间结算",
  dawn_public_result: "天亮结果",
  sheriff_election_started: "警长竞选开始",
  sheriff_elected: "警长产生",
  sheriff_badge_destroyed: "警徽流失",
  sheriff_vote_resolved: "警长投票结算",
  exile_resolved: "放逐结算",
  game_completed: "对局结束",
};

export function buildV2Timeline(game: V2GameRecordDetail): V2TimelineItem[] {
  const eventsByAction = new Map<string, V2GameRecordEvent[]>();
  const actionOpenEvents: V2GameRecordEvent[] = [];
  for (const event of game.events) {
    const actionId = stringValue(event.payload.action_id);
    if (actionId) {
      const items = eventsByAction.get(actionId) ?? [];
      items.push(event);
      eventsByAction.set(actionId, items);
    }
    if (event.event_type === "action_opened") {
      actionOpenEvents.push(event);
    }
  }

  const requestsByAction = new Map(
    game.model_requests.map((request) => [request.action_id, request]),
  );
  const presentationsByAction = new Map(
    game.presentations
      .filter((item) => item.action_id)
      .map((item) => [item.action_id as string, item]),
  );
  const voicesByAction = new Map(
    game.voice_assets.map((item) => [item.action_id, item]),
  );
  const actions = actionOpenEvents.map((event) => {
    const actionId = stringValue(event.payload.action_id) ?? `event-${event.event_id}`;
    const context = objectValue(event.payload.context);
    const actor = objectValue(context.actor);
    const actionEvents = eventsByAction.get(actionId) ?? [event];
    const request = requestsByAction.get(actionId) ?? null;
    const presentation = presentationsByAction.get(actionId) ?? null;
    const voiceAsset = voicesByAction.get(actionId) ?? null;
    const failed = actionEvents.find((item) => item.event_type === "action_failed");
    const succeeded = actionEvents.find(
      (item) => item.event_type === "action_succeeded",
    );
    const completedAt = (failed ?? succeeded)?.created_at ?? null;
    const actionType = stringValue(context.action_type) ?? "unknown";
    const actorKind = stringValue(actor.kind) ?? request?.actor_kind ?? "system";
    const actorId = stringValue(actor.id) ?? request?.actor_id ?? "system";
    return {
      id: actionId,
      kind: "action" as const,
      actionId,
      actionType,
      label: actionLabel(actionType),
      objective: stringValue(context.objective),
      phaseId: stringValue(context.phase_id) ?? request?.phase_id ?? "opening",
      actorKind,
      actorId,
      actorLabel: actorLabel(game, actorKind, actorId),
      audience: request?.audience ?? presentation?.audience ?? "all",
      status: failed
        ? ("failed" as const)
        : succeeded
          ? ("succeeded" as const)
          : ("running" as const),
      startedAt: event.created_at,
      completedAt,
      durationMs: completedAt ? elapsedMs(event.created_at, completedAt) : null,
      firstRecordSeq: actionEvents[0]?.record_seq ?? event.record_seq,
      lastRecordSeq:
        actionEvents[actionEvents.length - 1]?.record_seq ?? event.record_seq,
      modelRequest: request,
      presentation,
      voiceAsset,
      events: actionEvents,
    };
  });

  const milestones: V2TimelineItem[] = [];
  let phaseId = "opening";
  for (const event of game.events) {
    if (event.event_type === "game_phase_changed") {
      phaseId = stringValue(event.payload.phase_id) ?? phaseId;
    }
    if (
      !milestoneEventTypes.has(event.event_type) ||
      lifecycleEventTypes.has(event.event_type)
    ) {
      continue;
    }
    const eventPhase =
      event.event_type === "game_phase_changed"
        ? stringValue(event.payload.phase_id) ?? phaseId
        : phaseId;
    milestones.push({
      id: `event-${event.event_id}`,
      kind: "milestone",
      actionId: null,
      actionType: event.event_type,
      label: eventLabels[event.event_type] ?? humanize(event.event_type),
      objective: milestoneSummary(event),
      phaseId: eventPhase,
      actorKind: "system",
      actorId: "system",
      actorLabel: "系统",
      audience: "private",
      status: "succeeded",
      startedAt: event.created_at,
      completedAt: event.created_at,
      durationMs: null,
      firstRecordSeq: event.record_seq,
      lastRecordSeq: event.record_seq,
      modelRequest: null,
      presentation: null,
      voiceAsset: null,
      events: [event],
    });
  }

  return [...actions, ...milestones].sort(
    (left, right) => left.firstRecordSeq - right.firstRecordSeq,
  );
}

export function groupV2Phases(
  items: V2TimelineItem[],
  currentPhaseId: string,
): V2PhaseGroup[] {
  const order: string[] = [];
  const grouped = new Map<string, V2TimelineItem[]>();
  for (const item of items) {
    if (!grouped.has(item.phaseId)) {
      order.push(item.phaseId);
      grouped.set(item.phaseId, []);
    }
    grouped.get(item.phaseId)?.push(item);
  }
  return order.map((phaseId) => {
    const phaseItems = grouped.get(phaseId) ?? [];
    return {
      phaseId,
      label: phaseLabel(phaseId),
      items: phaseItems,
      modelRequestCount: phaseItems.filter((item) => item.modelRequest).length,
      failureCount: phaseItems.filter((item) => item.status === "failed").length,
      isCurrent: phaseId === currentPhaseId,
    };
  });
}

export function phaseLabel(phaseId: string): string {
  if (phaseId === "opening") return "开场";
  if (phaseId === "first_night") return "第一夜";
  const day = /^day_(\d+)$/.exec(phaseId);
  if (day) return `第 ${day[1]} 天`;
  const night = /^night_(\d+)$/.exec(phaseId);
  if (night) return `第 ${Number(night[1]) + 1} 夜`;
  return humanize(phaseId);
}

export function actionLabel(actionType: string): string {
  if (actionLabels[actionType]) return actionLabels[actionType];
  if (actionType.startsWith("ability_") && actionType.endsWith("_decision")) {
    return `${humanize(actionType.slice(8, -9))} 决策`;
  }
  return humanize(actionType);
}

export function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null) return "—";
  if (milliseconds < 1000) return `${milliseconds} ms`;
  return `${(milliseconds / 1000).toFixed(milliseconds < 10_000 ? 2 : 1)} s`;
}

export function formatClock(input: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(input));
}

export function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function actorLabel(
  game: V2GameRecordDetail,
  actorKind: string,
  actorId: string,
): string {
  if (actorKind === "judge") return "法官";
  if (actorKind !== "player") return "系统";
  const state = game.player_states.find(
    (item) => item.player_id === actorId,
  );
  const seat = numberValue(state?.seat);
  const snapshot = game.players_snapshot.find(
    (item) => numberValue(item.seat) === seat,
  );
  const name = stringValue(snapshot?.name);
  if (seat !== null && name) return `${seat}号 ${name}`;
  if (seat !== null) return `${seat}号玩家`;
  return actorId;
}

function milestoneSummary(event: V2GameRecordEvent): string | null {
  if (event.event_type === "game_phase_changed") {
    return `${phaseLabel(
      stringValue(event.payload.previous_phase_id) ?? "unknown",
    )} → ${phaseLabel(stringValue(event.payload.phase_id) ?? "unknown")}`;
  }
  if (event.event_type === "game_created") {
    const playerCount = numberValue(event.payload.player_count);
    return playerCount === null ? null : `${playerCount} 名玩家`;
  }
  if (event.event_type === "roles_assigned") {
    const count = numberValue(event.payload.assigned_count);
    return count === null ? null : `${count} 个身份已密封分配`;
  }
  return null;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function elapsedMs(start: string, end: string): number {
  return Math.max(0, Date.parse(end) - Date.parse(start));
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}
