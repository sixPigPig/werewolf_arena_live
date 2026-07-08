import type { DirectorCue } from "./liveDirector";
import type { GodViewPlayer, GodViewState } from "./liveGodView";
import type { LiveSpectatorState } from "./liveSpectator";
import type { LiveGameEvent } from "../types";

export type NarrativeCueKind =
  | "judge"
  | "player-thinking"
  | "player-speaking"
  | "player-action"
  | "vote"
  | "death"
  | "terminal"
  | "fallback";

export type NarrativeCueTone =
  | "neutral"
  | "night"
  | "day"
  | "danger"
  | "safe"
  | "vote"
  | "terminal";

export type NarrativeCue = {
  eventId: number | null;
  kind: NarrativeCueKind;
  tone: NarrativeCueTone;
  judgeLine: string;
  performerLine: string;
  detailLine: string;
  actorName: string | null;
  action: string | null;
  speechText: string;
};

export type NarrativeSpeaker = {
  name: string;
  seatNumber: number | null;
  role: string;
  camp: string;
  appearanceId: string;
  avatarImageUrl: string;
};

export type LiveNarrativeState = {
  cue: NarrativeCue;
  speaker: NarrativeSpeaker | null;
  nextSpeakerName: string | null;
  judgeLine: string;
  performerLine: string;
  detailLine: string;
};

type DeriveLiveNarrativeStateArgs = {
  cue: DirectorCue | null;
  events: LiveGameEvent[];
  godViewState: GodViewState;
  spectatorState: LiveSpectatorState;
};

export function deriveLiveNarrativeState({
  cue,
  events,
  godViewState,
  spectatorState,
}: DeriveLiveNarrativeStateArgs): LiveNarrativeState {
  const event = cue
    ? events.find((item) => item.id === cue.eventId) ?? null
    : null;
  const payload = event ? payloadForEvent(event) : {};
  const actorName =
    cue?.actor ??
    event?.actor ??
    godViewState.speakerFlow.current?.name ??
    spectatorState.activePlayerName ??
    null;
  const nextSpeakerName = godViewState.speakerFlow.next?.name ?? null;
  const narrativeCue = cueForEvent({
    cue,
    event,
    payload,
    actorName,
    nextSpeakerName,
    godViewState,
  });
  const speaker = speakerFor(narrativeCue.actorName, godViewState);

  return {
    cue: narrativeCue,
    speaker,
    nextSpeakerName,
    judgeLine: narrativeCue.judgeLine,
    performerLine: narrativeCue.performerLine,
    detailLine: narrativeCue.detailLine,
  };
}

function cueForEvent({
  cue,
  event,
  payload,
  actorName,
  nextSpeakerName,
  godViewState,
}: {
  cue: DirectorCue | null;
  event: LiveGameEvent | null;
  payload: Record<string, unknown>;
  actorName: string | null;
  nextSpeakerName: string | null;
  godViewState: GodViewState;
}): NarrativeCue {
  if (!cue) {
    return makeCue({
      eventId: null,
      kind: "fallback",
      tone: "neutral",
      judgeLine: "等待导播事件",
      performerLine: "等待玩家行动。",
      detailLine: "实时事件到达后，法官旁白会在这里展开。",
      actorName,
      action: null,
      speechText: "",
    });
  }

  if (cue.suppressSpeechSubtitle) {
    return recordedSpeechCue(cue, actorName, nextSpeakerName);
  }

  if (isPublicSpeechAction(cue.action) && cue.importance === "key") {
    const speechText = speechTextFromCue(cue.body, cue.actor);
    if (speechText) {
      const actor = cue.actor ?? actorName ?? "当前玩家";
      return makeCue({
        eventId: cue.eventId,
        kind: "player-speaking",
        tone: "day",
        judgeLine: `请听 ${actor} 的发言。`,
        performerLine: `${actor} 正在发言。`,
        detailLine: nextLine(nextSpeakerName),
        actorName: cue.actor ?? actorName,
        action: cue.action,
        speechText,
      });
    }
  }

  if (!event) {
    return fallbackCue(cue, actorName);
  }

  if (event.type === "phase_started") {
    return phaseCue(cue, event.phase, godViewState, actorName);
  }

  if (event.type === "action_requested") {
    return actionRequestedCue(cue, actorName, nextSpeakerName);
  }

  if (
    event.type === "model_request_started" ||
    event.type === "model_thinking_tick"
  ) {
    return modelWaitingCue(cue, payload, actorName, nextSpeakerName);
  }

  if (event.type === "model_request_failed") {
    return modelRequestFailedCue(cue, payload, actorName);
  }

  if (event.type === "model_response_received") {
    return modelResponseReceivedCue(cue, payload, actorName, nextSpeakerName);
  }

  if (event.type === "action_parsed") {
    return parsedActionCue(cue, payload, actorName, nextSpeakerName);
  }

  if (event.type === "state_updated") {
    return stateUpdatedCue(cue, payload, actorName, nextSpeakerName, godViewState);
  }

  if (event.type === "game_completed") {
    const winner = stringField(payload, "winner") || "胜利阵营";
    return makeCue({
      eventId: cue.eventId,
      kind: "terminal",
      tone: "terminal",
      judgeLine: `对局结束，${winner}获胜。`,
      performerLine: "胜负已经揭晓。",
      detailLine: `胜利阵营：${winner}`,
      actorName: null,
      action: cue.action,
      speechText: "",
    });
  }

  if (event.type === "game_failed") {
    return makeCue({
      eventId: cue.eventId,
      kind: "terminal",
      tone: "danger",
      judgeLine: "对局异常中断。",
      performerLine: "本局无法继续播放。",
      detailLine: "失败原因已记录，公开舞台已停止播放。",
      actorName: null,
      action: cue.action,
      speechText: "",
    });
  }

  return fallbackCue(cue, actorName);
}

function phaseCue(
  cue: DirectorCue,
  phase: string | null,
  godViewState: GodViewState,
  actorName: string | null,
): NarrativeCue {
  if (phase === "night") {
    return makeCue({
      eventId: cue.eventId,
      kind: "judge",
      tone: "night",
      judgeLine: "天黑请闭眼。",
      performerLine: "夜间角色开始行动。",
      detailLine: "夜间行动开始，存活玩家请依次行动。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  if (phase === "day") {
    return makeCue({
      eventId: cue.eventId,
      kind: "judge",
      tone: "day",
      judgeLine: dayJudgeLine(godViewState),
      performerLine: "进入白天发言。",
      detailLine: godViewState.speakerFlow.current?.name
        ? `当前发言：${godViewState.speakerFlow.current.name}`
        : "等待首位玩家发言。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  if (phase === "vote") {
    return makeCue({
      eventId: cue.eventId,
      kind: "vote",
      tone: "vote",
      judgeLine: "发言结束，进入放逐投票。",
      performerLine: "所有拥有投票权的玩家开始投票。",
      detailLine: "投票结果会在票型公布后揭晓。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  if (phase === "summary") {
    return makeCue({
      eventId: cue.eventId,
      kind: "judge",
      tone: "neutral",
      judgeLine: "本轮进入总结，玩家整理自己的判断。",
      performerLine: "总结阶段进行中。",
      detailLine: "玩家会记录本轮观察，供后续回合参考。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  return fallbackCue(cue, actorName);
}

function actionRequestedCue(
  cue: DirectorCue,
  actorName: string | null,
  nextSpeakerName: string | null,
): NarrativeCue {
  const actor = actorName ?? "当前玩家";

  if (isPublicSpeechAction(cue.action)) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-thinking",
      tone: "day",
      judgeLine: `请 ${actor} 发言。`,
      performerLine: `${actor} 正在整理公开发言。`,
      detailLine: nextLine(nextSpeakerName),
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  if (isVoteAction(cue.action)) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-thinking",
      tone: "vote",
      judgeLine: "请玩家投票。",
      performerLine: `${actor} 正在权衡投票。`,
      detailLine: "投票目标将在公开结果中公布。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  return makeCue({
    eventId: cue.eventId,
    kind: "player-action",
    tone: cue.phase === "night" ? "night" : "neutral",
    judgeLine: cue.phase === "night" ? "夜间行动进行中。" : "玩家行动进行中。",
    performerLine: `${actor} 正在行动。`,
    detailLine: cue.body || "等待模型返回行动结果。",
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function modelWaitingCue(
  cue: DirectorCue,
  payload: Record<string, unknown>,
  actorName: string | null,
  nextSpeakerName: string | null,
): NarrativeCue {
  const actor = actorName ?? "当前玩家";
  const message = stringField(payload, "message") || cue.body;

  if (isPublicSpeechAction(cue.action)) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-thinking",
      tone: "day",
      judgeLine: `请听 ${actor} 的发言。`,
      performerLine: `${actor} 正在组织发言。`,
      detailLine: message || nextLine(nextSpeakerName),
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  return makeCue({
    eventId: cue.eventId,
    kind: "player-action",
    tone: cue.phase === "night" ? "night" : "neutral",
    judgeLine: cue.phase === "night" ? "夜间行动进行中。" : "玩家正在思考。",
    performerLine: `${actor} 正在等待模型返回。`,
    detailLine: message,
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function modelRequestFailedCue(
  cue: DirectorCue,
  payload: Record<string, unknown>,
  actorName: string | null,
): NarrativeCue {
  const actor = actorName ?? "当前玩家";
  const publicMessage = stringField(payload, "message");

  return makeCue({
    eventId: cue.eventId,
    kind: "player-action",
    tone: "danger",
    judgeLine: "模型请求暂时失败。",
    performerLine: `${actor} 的行动暂时中断。`,
    detailLine: publicMessage || "等待系统重试或进入后续公开结算。",
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function modelResponseReceivedCue(
  cue: DirectorCue,
  payload: Record<string, unknown>,
  actorName: string | null,
  nextSpeakerName: string | null,
): NarrativeCue {
  const actor = actorName ?? "当前玩家";
  const visibleText = stringField(payload, "visible_text");

  if (visibleText && isPublicSpeechAction(cue.action)) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-speaking",
      tone: "day",
      judgeLine: `请听 ${actor} 的发言。`,
      performerLine: `${actor} 完成发言。`,
      detailLine: nextLine(nextSpeakerName),
      actorName,
      action: cue.action,
      speechText: visibleText,
    });
  }

  return makeCue({
    eventId: cue.eventId,
    kind: "player-action",
    tone: cue.phase === "night" ? "night" : "neutral",
    judgeLine: "模型返回已接收。",
    performerLine: `${actor} 的行动正在解析。`,
    detailLine: "行动结果等待公开结算。",
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function parsedActionCue(
  cue: DirectorCue,
  payload: Record<string, unknown>,
  actorName: string | null,
  nextSpeakerName: string | null,
): NarrativeCue {
  const visibleText = visibleSpeechText(payload);
  if (visibleText && isPublicSpeechAction(cue.action)) {
    const actor = actorName ?? "当前玩家";
    return makeCue({
      eventId: cue.eventId,
      kind: "player-speaking",
      tone: "day",
      judgeLine: `请听 ${actor} 的发言。`,
      performerLine: `${actor} 完成发言。`,
      detailLine: nextLine(nextSpeakerName),
      actorName,
      action: cue.action,
      speechText: visibleText,
    });
  }

  return makeCue({
    eventId: cue.eventId,
    kind: isVoteAction(cue.action) ? "vote" : "player-action",
    tone: parsedActionTone(cue),
    judgeLine: isVoteAction(cue.action) ? "投票选择已记录。" : "玩家行动已解析。",
    performerLine: actorName ? `${actorName} 已完成行动。` : "行动已完成。",
    detailLine: parsedActionDetailLine(cue),
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function stateUpdatedCue(
  cue: DirectorCue,
  payload: Record<string, unknown>,
  actorName: string | null,
  nextSpeakerName: string | null,
  godViewState: GodViewState,
): NarrativeCue {
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    const message =
      typeof debateEntry.message === "string" ? debateEntry.message : "";
    return makeCue({
      eventId: cue.eventId,
      kind: "player-speaking",
      tone: "day",
      judgeLine: `请听 ${debateEntry.speaker} 的发言。`,
      performerLine: `${debateEntry.speaker} 完成发言。`,
      detailLine: nextLine(nextSpeakerName),
      actorName: debateEntry.speaker,
      action: cue.action,
      speechText: message,
    });
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    return makeCue({
      eventId: cue.eventId,
      kind: "death",
      tone: "danger",
      judgeLine: `${exiled} 被放逐出局。`,
      performerLine: "放逐结果已经生效。",
      detailLine: activePlayersLine(payload),
      actorName: exiled,
      action: cue.action,
      speechText: "",
    });
  }

  if (isPeacefulNightPayload(payload)) {
    return makeCue({
      eventId: cue.eventId,
      kind: "judge",
      tone: "safe",
      judgeLine: "天亮了，昨夜平安无事。",
      performerLine: "昨夜没有玩家出局。",
      detailLine: activePlayersLine(payload),
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  const deathNames = deathNamesFromPayload(payload);
  if (deathNames.length > 0) {
    return makeCue({
      eventId: cue.eventId,
      kind: "death",
      tone: "danger",
      judgeLine: `天亮了，昨夜 ${deathNames.join("、")} 出局。`,
      performerLine: "夜间结算公布。",
      detailLine: activePlayersLine(payload),
      actorName: deathNames[0],
      action: cue.action,
      speechText: "",
    });
  }

  if (isRecord(payload.votes)) {
    const topTarget = godViewState.vote.topTarget;
    const topTally = godViewState.vote.tallies.find(
      (item) => item.target === topTarget,
    );
    return makeCue({
      eventId: cue.eventId,
      kind: "vote",
      tone: "vote",
      judgeLine: "投票结果公布。",
      performerLine: "票型已经更新。",
      detailLine:
        topTally && topTarget
          ? `当前最高票：${topTarget}，${topTally.count} 票。`
          : "本轮暂未形成有效票型。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  const selfExploded = stringField(payload, "werewolf_self_exploded");
  if (selfExploded && payload.sheriff_election_pending === true) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-action",
      tone: "danger",
      judgeLine: `${selfExploded} 发动狼人自爆。`,
      performerLine: "技能效果已经公开。",
      detailLine: selfExplosionInterruptionLine(payload),
      actorName: selfExploded,
      action: cue.action,
      speechText: "",
    });
  }

  const skillLine = skillJudgeLine(payload);
  if (skillLine) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-action",
      tone: "danger",
      judgeLine: skillLine,
      performerLine: "技能效果已经公开。",
      detailLine: activePlayersLine(payload),
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  return fallbackCue(cue, actorName);
}

function fallbackCue(cue: DirectorCue, actorName: string | null): NarrativeCue {
  return makeCue({
    eventId: cue.eventId,
    kind: "fallback",
    tone: toneFromDirectorCue(cue),
    judgeLine: cue.title,
    performerLine: actorName ? `${actorName} 的事件更新。` : "对局事件更新。",
    detailLine: "收到未分类事件，等待后续公开结算。",
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function recordedSpeechCue(
  cue: DirectorCue,
  actorName: string | null,
  nextSpeakerName: string | null,
): NarrativeCue {
  const actor = actorName ?? cue.actor ?? "当前玩家";
  return makeCue({
    eventId: cue.eventId,
    kind: "player-action",
    tone: "day",
    judgeLine: `${actor} 的发言已记录。`,
    performerLine: "公开发言已进入记录。",
    detailLine: nextLine(nextSpeakerName),
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function makeCue(cue: NarrativeCue): NarrativeCue {
  return cue;
}

function speakerFor(
  actorName: string | null,
  godViewState: GodViewState,
): NarrativeSpeaker | null {
  if (!actorName) {
    return null;
  }
  const player = godViewState.players.find((item) => item.name === actorName);
  if (!player) {
    return null;
  }
  return playerToSpeaker(player);
}

function playerToSpeaker(player: GodViewPlayer): NarrativeSpeaker {
  return {
    name: player.name,
    seatNumber: player.seatNumber,
    role: player.role,
    camp: player.camp,
    appearanceId: player.appearanceId,
    avatarImageUrl: player.avatarImageUrl,
  };
}

function dayJudgeLine(godViewState: GodViewState): string {
  if (godViewState.nightResolution.label === "平安夜") {
    return "天亮了，昨夜平安无事。";
  }
  if (godViewState.nightResolution.tone === "danger") {
    const deathNames = godViewState.deaths
      .filter((death) => death.publicText === "天亮公布")
      .map((death) => death.player);
    if (deathNames.length > 0) {
      return `天亮了，昨夜 ${deathNames.join("、")} 出局。`;
    }
  }
  return "天亮了，进入白天发言。";
}

function visibleSpeechText(payload: Record<string, unknown>): string {
  const visibleResult = payload.visible_result;
  if (isRecord(visibleResult)) {
    return stringField(visibleResult, "say") || stringField(visibleResult, "summary");
  }
  return "";
}

function speechTextFromCue(body: string, actorName: string | null): string {
  if (actorName && body.startsWith(`${actorName}：`)) {
    return body.slice(actorName.length + 1);
  }
  return body;
}

function deathNamesFromPayload(payload: Record<string, unknown>): string[] {
  const deaths = payload.night_deaths;
  if (Array.isArray(deaths)) {
    return deaths
      .map((death) =>
        isRecord(death) && typeof death.player === "string" ? death.player : "",
      )
      .filter(Boolean);
  }
  const eliminated = stringField(payload, "eliminated");
  return eliminated ? [eliminated] : [];
}

function isPeacefulNightPayload(payload: Record<string, unknown>): boolean {
  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  const eliminated = payload.eliminated;
  return Boolean(
    (attacked && protectedPlayer === attacked) ||
      (typeof eliminated === "string" && protectedPlayer === eliminated) ||
      (protectedPlayer && eliminated === null),
  );
}

function skillJudgeLine(payload: Record<string, unknown>): string {
  const selfExploded = stringField(payload, "werewolf_self_exploded");
  if (selfExploded) {
    return `${selfExploded} 发动狼人自爆。`;
  }
  const hunterShot = stringField(payload, "hunter_shot");
  if (hunterShot) {
    return `猎人开枪带走 ${hunterShot}。`;
  }
  const idiotRevealed = stringField(payload, "idiot_revealed");
  if (idiotRevealed) {
    return `${idiotRevealed} 翻牌，继续留在场上。`;
  }
  const badgeTarget = stringField(payload, "sheriff_badge_target");
  if (badgeTarget) {
    return `警徽移交给 ${badgeTarget}。`;
  }
  if (payload.sheriff_badge_lost === true) {
    return "警徽被撕毁。";
  }
  return "";
}

function selfExplosionInterruptionLine(payload: Record<string, unknown>): string {
  const reason =
    stringField(payload, "sheriff_badge_lost_reason") || "首爆中断警长竞选";
  const activePlayers = activePlayersLine(payload);
  const line = `${reason}；警徽未流失，次日继续竞选。`;
  return activePlayers ? `${line}\n${activePlayers}` : line;
}

function activePlayersLine(payload: Record<string, unknown>): string {
  const activePlayers = payload.active_players;
  return Array.isArray(activePlayers)
    ? `存活玩家：${activePlayers.map(String).join("、")}`
    : "";
}

function nextLine(nextSpeakerName: string | null): string {
  return nextSpeakerName ? `下一位：${nextSpeakerName}` : "等待后续发言。";
}

function parsedActionDetailLine(cue: DirectorCue): string {
  if (isVoteAction(cue.action)) {
    return cue.body;
  }
  return "行动结果等待公开结算。";
}

function parsedActionTone(cue: DirectorCue): NarrativeCueTone {
  if (isVoteAction(cue.action)) {
    return "vote";
  }
  return cue.phase === "night" ? "night" : "neutral";
}

function toneFromDirectorCue(cue: DirectorCue): NarrativeCueTone {
  if (cue.importance === "terminal") {
    return "terminal";
  }
  if (cue.phase === "night") {
    return "night";
  }
  if (cue.phase === "vote") {
    return "vote";
  }
  if (cue.phase === "day") {
    return "day";
  }
  return "neutral";
}

function isPublicSpeechAction(action: string | null): boolean {
  return (
    action === "debate" ||
    action === "sheriff_speech" ||
    action === "sheriff_pk_speech" ||
    action === "summarize"
  );
}

function isVoteAction(action: string | null): boolean {
  return (
    action === "vote" ||
    action === "sheriff_vote" ||
    action === "sheriff_runoff_vote"
  );
}

function payloadForEvent(event: LiveGameEvent): Record<string, unknown> {
  return isRecord(event.payload) ? event.payload : {};
}

function stringField(payload: Record<string, unknown>, field: string): string {
  const value = payload[field];
  return typeof value === "string" ? value : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
