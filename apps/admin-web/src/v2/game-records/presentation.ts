import type {
  V2GamePresentation,
  V2GameRecordDetail,
  V2GameRecordEvent,
  V2ModelRequestSummary,
  V2PlayerIdentity,
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
  modelRequest: V2ModelRequestSummary | null;
  modelRequests: V2ModelRequestSummary[];
  templateRender: V2GameRecordEvent | null;
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

export type V2RoundSummary = {
  roundNo: number;
  reachedDay: boolean;
  status: "running" | "succeeded" | "failed" | "canceled";
  startedAt: string;
  endedAt: string | null;
  firstRecordSeq: number;
  lastRecordSeq: number;
  highlights: V2RoundHighlight[];
};

export type V2RoundHighlight = {
  id: string;
  kind:
    | "night"
    | "sheriff"
    | "vote"
    | "exile"
    | "ability"
    | "result"
    | "failure";
  label: string;
  recordSeq: number;
  tone: "neutral" | "success" | "warning" | "danger";
};

type V2RoundAccumulator = {
  roundNo: number;
  reachedDay: boolean;
  startedAt: string;
  lastEventAt: string;
  firstRecordSeq: number;
  lastRecordSeq: number;
  highlights: V2RoundHighlight[];
};

const lifecycleEventTypes = new Set([
  "judge_speech_rendered",
  "model_request_started",
  "model_first_token_received",
  "model_response_received",
  "model_request_failed",
  "model_binding_health_updated",
  "model_retry_scheduled",
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
  "action_skipped_technical",
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

const dayRoundEventTypes = new Set([
  "sheriff_election_started",
  "sheriff_elected",
  "sheriff_badge_destroyed",
  "sheriff_vote_resolved",
  "player_exiled",
  "exile_resolved",
]);

const actionLabels: Record<string, string> = {
  judge_opening_speech: "开场播报",
  judge_nightfall_announcement: "夜幕播报",
  judge_hunter_shot_announcement: "猎人开枪播报",
  judge_werewolf_self_explosion: "狼人自爆播报",
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
  guard_protect_wake: "守卫睁眼",
  guard_protect_sleep: "守卫闭眼",
  seer_investigate_wake: "预言家睁眼",
  seer_investigate_result: "预言家查验结果",
  seer_investigate_sleep: "预言家闭眼",
  witch_wake: "女巫睁眼",
  witch_attack_observation: "女巫查看袭击目标",
  witch_sleep: "女巫闭眼",
  first_night_last_words: "首夜遗言",
  sheriff_run: "上警决定",
  sheriff_campaign_speech: "竞选发言",
  sheriff_withdraw: "退水决定",
  sheriff_vote: "警长投票",
  sheriff_pk_speech: "警长平票发言",
  sheriff_runoff_vote: "警长加赛投票",
  sheriff_speech_order: "警长选择发言顺序",
  day_speech: "白天发言",
  day_debate_speech: "白天发言",
  exile_vote: "放逐投票",
  exile_pk_speech: "放逐平票发言",
  exile_runoff_vote: "放逐加赛投票",
  exile_last_words: "遗言",
  hunter_death_shot: "猎人开枪决定",
  sheriff_badge_resolution: "警徽去向决定",
  werewolf_self_explosion: "狼人自爆决定",
};

const abilityLabels: Record<string, string> = {
  "werewolf.attack": "狼人袭击",
  "guard.protect": "守卫守护",
  "seer.investigate": "预言家查验",
  "witch.heal": "女巫使用解药",
  "witch.poison": "女巫使用毒药",
  "hunter.death_shot": "猎人开枪",
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

export function buildV2RoundSummaries(
  events: V2GameRecordEvent[],
  identities: V2PlayerIdentity[],
  gameStatus: string,
): V2RoundSummary[] {
  const orderedEvents = [...events].sort(
    (left, right) => left.record_seq - right.record_seq,
  );
  const identityById = new Map(
    identities.map((identity) => [identity.player_id, identity]),
  );
  const rounds = new Map<number, V2RoundAccumulator>();
  const roundByWindowId = new Map<string, number>();
  let currentRound: number | null = null;

  const touchRound = (
    roundNo: number,
    event: V2GameRecordEvent,
  ): V2RoundAccumulator => {
    const existing = rounds.get(roundNo);
    if (existing) {
      existing.lastEventAt = event.created_at;
      existing.lastRecordSeq = event.record_seq;
      return existing;
    }
    const created = {
      roundNo,
      reachedDay: false,
      startedAt: event.created_at,
      lastEventAt: event.created_at,
      firstRecordSeq: event.record_seq,
      lastRecordSeq: event.record_seq,
      highlights: [],
    };
    rounds.set(roundNo, created);
    return created;
  };

  for (const event of orderedEvents) {
    const payloadRound = positiveInteger(event.payload.round_no);
    const transitionRound =
      event.event_type === "game_phase_changed"
        ? roundFromPhase(stringValue(event.payload.phase_id))
        : null;
    const actionContext =
      event.event_type === "action_opened"
        ? objectValue(event.payload.context)
        : {};
    const actionRound = roundFromPhase(stringValue(actionContext.phase_id));
    const windowId = stringValue(event.payload.window_id);
    const windowRound =
      windowId === null ? null : (roundByWindowId.get(windowId) ?? null);
    const roundNo: number | null =
      payloadRound ??
      transitionRound ??
      actionRound ??
      windowRound ??
      currentRound;

    if (roundNo === null) continue;
    currentRound = roundNo;
    const round = touchRound(roundNo, event);
    if (
      stringValue(event.payload.phase_id)?.startsWith("day_") ||
      stringValue(actionContext.phase_id)?.startsWith("day_") ||
      dayRoundEventTypes.has(event.event_type)
    ) {
      round.reachedDay = true;
    }

    if (event.event_type === "action_window_opened" && windowId) {
      roundByWindowId.set(windowId, roundNo);
    }

    for (const highlight of roundHighlights(
      event,
      round,
      identityById,
    )) {
      round.highlights.push(highlight);
    }
  }

  const orderedRounds = [...rounds.values()].sort(
    (left, right) => left.roundNo - right.roundNo,
  );
  return orderedRounds.map((round, index) => {
    const nextRound = orderedRounds[index + 1];
    const hasGameResult = round.highlights.some(
      (highlight) => highlight.id === `game_completed-${highlight.recordSeq}`,
    );
    const isLastRound = index === orderedRounds.length - 1;
    const status = !isLastRound || hasGameResult
      ? "succeeded"
      : gameStatus === "failed"
        ? "failed"
        : gameStatus === "canceled"
          ? "canceled"
          : "running";
    return {
      roundNo: round.roundNo,
      reachedDay: round.reachedDay,
      status,
      startedAt: round.startedAt,
      endedAt:
        status === "running"
          ? null
          : (nextRound?.startedAt ?? round.lastEventAt),
      firstRecordSeq: round.firstRecordSeq,
      lastRecordSeq: round.lastRecordSeq,
      highlights: round.highlights,
    };
  });
}

export function buildV2HistoricalIdentities(
  events: V2GameRecordEvent[],
  identities: V2PlayerIdentity[],
  recordSeq: number,
): V2PlayerIdentity[] {
  const latestRecordSeq = events.reduce(
    (latest, event) => Math.max(latest, event.record_seq),
    0,
  );
  if (recordSeq >= latestRecordSeq) {
    return identities.map((identity) => ({ ...identity }));
  }

  const snapshot = new Map<string, V2PlayerIdentity>(
    identities.map((identity) => [
      identity.player_id,
      {
        ...identity,
        alive: true,
        death_cause: null,
      },
    ]),
  );
  const markDead = (playerId: string | null, cause: string | null) => {
    if (!playerId) return;
    const identity = snapshot.get(playerId);
    if (!identity) return;
    identity.alive = false;
    identity.death_cause = cause ?? identity.death_cause;
  };

  for (const event of [...events].sort(
    (left, right) => left.record_seq - right.record_seq,
  )) {
    if (event.record_seq > recordSeq) break;
    const payload = event.payload;

    if (event.event_type === "action_window_closed") {
      const result = objectValue(payload.result);
      const deaths = Array.isArray(result.deaths)
        ? result.deaths.map(objectValue)
        : [];
      for (const death of deaths) {
        markDead(
          stringValue(death.player_id),
          stringValue(death.cause) ?? "night_resolution",
        );
      }
      continue;
    }

    if (event.event_type === "dawn_public_result") {
      const deadPlayerIds = Array.isArray(payload.dead_player_ids)
        ? payload.dead_player_ids
        : [];
      for (const playerId of deadPlayerIds) {
        markDead(stringValue(playerId), "night_resolution");
      }
      continue;
    }

    if (event.event_type === "player_exiled") {
      markDead(stringValue(payload.player_id), "exile");
      continue;
    }

    if (event.event_type === "werewolf_self_exploded") {
      markDead(stringValue(payload.player_id), "werewolf_self_explosion");
      continue;
    }

    if (
      event.event_type === "hunter_response_resolved" ||
      event.event_type === "hunter_shot_resolved"
    ) {
      markDead(stringValue(payload.target_player_id), "hunter_shot");
    }
  }

  return identities.map(
    (identity) => snapshot.get(identity.player_id) ?? { ...identity },
  );
}

export function buildV2Timeline(game: V2GameRecordDetail): V2TimelineItem[] {
  const actionIdByTtsAttempt = new Map<string, string>();
  for (const event of game.events) {
    if (event.event_type !== "tts_stream_started") continue;
    const attemptId = ttsAttemptId(event);
    const actionId = stringValue(event.payload.action_id);
    if (attemptId && actionId) actionIdByTtsAttempt.set(attemptId, actionId);
  }

  const eventsByAction = new Map<string, V2GameRecordEvent[]>();
  const actionOpenEvents: V2GameRecordEvent[] = [];
  for (const event of game.events) {
    const actionId =
      stringValue(event.payload.action_id) ??
      (event.event_type === "tts_stream_completed"
        ? actionIdByTtsAttempt.get(ttsAttemptId(event) ?? "")
        : undefined);
    if (actionId) {
      const items = eventsByAction.get(actionId) ?? [];
      items.push(event);
      eventsByAction.set(actionId, items);
    }
    if (event.event_type === "action_opened") {
      actionOpenEvents.push(event);
    }
  }

  const requestsByAction = new Map<string, V2ModelRequestSummary[]>();
  for (const request of game.model_requests) {
    const requests = requestsByAction.get(request.action_id) ?? [];
    requests.push(request);
    requestsByAction.set(request.action_id, requests);
  }
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
    const requests = requestsByAction.get(actionId) ?? [];
    const request = requests[requests.length - 1] ?? null;
    const templateRender =
      actionEvents.find((item) => item.event_type === "judge_speech_rendered") ??
      null;
    const presentation = presentationsByAction.get(actionId) ?? null;
    const voiceAsset = voicesByAction.get(actionId) ?? null;
    const eventAudience = actionEvents
      .map((item) => stringValue(item.payload.audience))
      .find((audience) => audience !== null);
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
      audience:
        presentation?.audience ??
        request?.audience ??
        eventAudience ??
        "legacy_unknown",
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
      modelRequests: requests,
      templateRender,
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
      audience: stringValue(event.payload.audience) ?? "legacy_unknown",
      status: "succeeded",
      startedAt: event.created_at,
      completedAt: event.created_at,
      durationMs: null,
      firstRecordSeq: event.record_seq,
      lastRecordSeq: event.record_seq,
      modelRequest: null,
      modelRequests: [],
      templateRender: null,
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
      modelRequestCount: phaseItems.reduce(
        (count, item) => count + item.modelRequests.length,
        0,
      ),
      failureCount: phaseItems.filter((item) => item.status === "failed").length,
      isCurrent: phaseId === currentPhaseId,
    };
  });
}

export function phaseLabel(phaseId: string): string {
  if (phaseId === "opening") return "开场";
  if (phaseId === "first_night") return "第 1 夜";
  const day = /^day_(\d+)$/.exec(phaseId);
  if (day) return `第 ${day[1]} 天`;
  const night = /^night_(\d+)$/.exec(phaseId);
  if (night) return `第 ${night[1]} 夜`;
  return humanize(phaseId);
}

export function actionLabel(actionType: string): string {
  if (actionLabels[actionType]) return actionLabels[actionType];
  if (actionType.startsWith("ability_") && actionType.endsWith("_decision")) {
    return `${abilityLabel(actionType.slice(8, -9))}决策`;
  }
  return humanize(actionType);
}

export function abilityLabel(abilityId: string): string {
  return abilityLabels[abilityId] ?? humanize(abilityId);
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

function roundHighlights(
  event: V2GameRecordEvent,
  round: V2RoundAccumulator,
  identities: Map<string, V2PlayerIdentity>,
): V2RoundHighlight[] {
  const payload = event.payload;
  const highlight = (
    kind: V2RoundHighlight["kind"],
    label: string,
    tone: V2RoundHighlight["tone"] = "neutral",
  ): V2RoundHighlight => ({
    id: `${event.event_type}-${event.record_seq}-${round.highlights.length}`,
    kind,
    label,
    recordSeq: event.record_seq,
    tone,
  });

  if (event.event_type === "action_window_closed") {
    const result = objectValue(payload.result);
    const deaths = Array.isArray(result.deaths)
      ? result.deaths.map(objectValue)
      : [];
    const deathHighlights = deaths.flatMap((death) => {
      const playerId = stringValue(death.player_id);
      if (!playerId) return [];
      return [
        highlight(
          "night",
          `夜间出局：${summaryPlayerLabel(playerId, identities)}（${summaryDeathCauseLabel(
            stringValue(death.cause),
          )}）`,
          "danger",
        ),
      ];
    });
    if (deathHighlights.length) return deathHighlights;
    if (result.peaceful === true) {
      const preventedBy = stringValue(result.attack_prevented_by);
      return [
        highlight(
          "night",
          preventedBy
            ? `平安夜 · 袭击被${summaryPreventionLabel(preventedBy)}阻止`
            : "平安夜",
          "success",
        ),
      ];
    }
    return [];
  }

  if (event.event_type === "dawn_public_result") {
    const hasNightResult = round.highlights.some(
      (item) => item.kind === "night",
    );
    if (hasNightResult) return [];
    const deadPlayerIds = Array.isArray(payload.dead_player_ids)
      ? payload.dead_player_ids.filter(
          (value): value is string => typeof value === "string" && Boolean(value),
        )
      : [];
    if (!deadPlayerIds.length) {
      return [highlight("night", "平安夜", "success")];
    }
    return deadPlayerIds.map((playerId) =>
      highlight(
        "night",
        `夜间出局：${summaryPlayerLabel(playerId, identities)}`,
        "danger",
      ),
    );
  }

  if (event.event_type === "sheriff_elected") {
    return playerHighlight(
      event,
      "sheriff",
      "警长产生",
      stringValue(payload.player_id),
      identities,
      "success",
    );
  }
  if (event.event_type === "sheriff_badge_transferred") {
    const fromPlayer = summaryPlayerLabel(
      stringValue(payload.from_player_id),
      identities,
    );
    const toPlayer = summaryPlayerLabel(
      stringValue(payload.player_id),
      identities,
    );
    return [
      highlight(
        "sheriff",
        `警徽移交：${fromPlayer} → ${toPlayer}`,
        "warning",
      ),
    ];
  }
  if (event.event_type === "sheriff_badge_destroyed") {
    return [highlight("sheriff", "警徽被销毁", "warning")];
  }

  if (event.event_type === "day_vote_resolved") {
    const leaders = Array.isArray(payload.leaders)
      ? payload.leaders.filter(
          (value): value is string => typeof value === "string" && Boolean(value),
        )
      : [];
    if (leaders.length === 1) return [];
    const voteLabel =
      stringValue(payload.action_type) === "sheriff_vote"
        ? "警长投票"
        : "放逐投票";
    return [
      highlight(
        "vote",
        leaders.length
          ? `${voteLabel}平票：${leaders
              .map((playerId) => summaryPlayerLabel(playerId, identities))
              .join("、")}`
          : `${voteLabel}无人领先`,
        "warning",
      ),
    ];
  }

  if (event.event_type === "player_exiled") {
    return playerHighlight(
      event,
      "exile",
      "投票放逐",
      stringValue(payload.player_id),
      identities,
      "danger",
    );
  }
  if (event.event_type === "idiot_revealed") {
    return playerHighlight(
      event,
      "ability",
      "白痴翻牌免于放逐",
      stringValue(payload.player_id),
      identities,
      "warning",
    );
  }
  if (event.event_type === "werewolf_self_exploded") {
    return playerHighlight(
      event,
      "ability",
      "狼人自爆",
      stringValue(payload.player_id),
      identities,
      "danger",
    );
  }
  if (event.event_type === "hunter_response_resolved") {
    const hunter = summaryPlayerLabel(
      stringValue(payload.hunter_player_id),
      identities,
    );
    const targetPlayerId = stringValue(payload.target_player_id);
    return [
      highlight(
        "ability",
        targetPlayerId
          ? `猎人开枪：${hunter} → ${summaryPlayerLabel(
              targetPlayerId,
              identities,
            )}`
          : `猎人未开枪：${hunter}`,
        targetPlayerId ? "danger" : "neutral",
      ),
    ];
  }

  if (event.event_type === "game_completed") {
    return [
      {
        ...highlight(
          "result",
          `对局结束：${summaryWinnerLabel(stringValue(payload.winner))}获胜`,
          "success",
        ),
        id: `game_completed-${event.record_seq}`,
      },
    ];
  }
  if (
    event.event_type === "match_runtime_failed" ||
    event.event_type === "ability_runtime_failed"
  ) {
    return [
      highlight(
        "failure",
        `运行异常：${
          stringValue(payload.failure_code) ??
          stringValue(payload.reason) ??
          event.event_type
        }`,
        "danger",
      ),
    ];
  }
  if (event.event_type === "game_canceled") {
    return [highlight("failure", "管理员已中止本局", "warning")];
  }
  return [];
}

function playerHighlight(
  event: V2GameRecordEvent,
  kind: V2RoundHighlight["kind"],
  label: string,
  playerId: string | null,
  identities: Map<string, V2PlayerIdentity>,
  tone: V2RoundHighlight["tone"],
): V2RoundHighlight[] {
  if (!playerId) return [];
  return [
    {
      id: `${event.event_type}-${event.record_seq}`,
      kind,
      label: `${label}：${summaryPlayerLabel(playerId, identities)}`,
      recordSeq: event.record_seq,
      tone,
    },
  ];
}

function summaryPlayerLabel(
  playerId: string | null,
  identities: Map<string, V2PlayerIdentity>,
): string {
  if (!playerId) return "无人";
  const identity = identities.get(playerId);
  if (!identity) return playerId;
  return `${identity.seat}号 ${identity.display_name}（${summaryRoleLabel(
    identity.role,
  )}）`;
}

function summaryRoleLabel(value: string): string {
  const labels: Record<string, string> = {
    werewolf: "狼人",
    villager: "村民",
    seer: "预言家",
    guard: "守卫",
    witch: "女巫",
    hunter: "猎人",
    idiot: "白痴",
  };
  return labels[value] ?? value;
}

function summaryDeathCauseLabel(value: string | null): string {
  const labels: Record<string, string> = {
    werewolf_attack: "狼人袭击",
    witch_poison: "女巫毒杀",
    poison: "女巫毒杀",
    hunter_shot: "猎人带走",
  };
  return value ? (labels[value] ?? value) : "夜间结算";
}

function summaryPreventionLabel(value: string): string {
  const labels: Record<string, string> = {
    guard: "守卫",
    protect: "守卫",
    heal: "女巫解药",
    guard_and_heal: "同守同救",
  };
  return labels[value] ?? value;
}

function summaryWinnerLabel(value: string | null): string {
  const labels: Record<string, string> = {
    werewolf: "狼人阵营",
    werewolves: "狼人阵营",
    village: "好人阵营",
    villagers: "好人阵营",
  };
  return value ? (labels[value] ?? value) : "未知阵营";
}

function roundFromPhase(phaseId: string | null): number | null {
  if (phaseId === "first_night") return 1;
  const match = /^(?:day|night)_(\d+)$/.exec(phaseId ?? "");
  return match ? positiveInteger(Number(match[1])) : null;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function ttsAttemptId(event: V2GameRecordEvent): string | null {
  return (
    stringValue(event.payload.tts_attempt_id) ??
    stringValue(event.payload.attempt_id)
  );
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function positiveInteger(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 1
    ? value
    : null;
}

function elapsedMs(start: string, end: string): number {
  return Math.max(0, Date.parse(end) - Date.parse(start));
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}
