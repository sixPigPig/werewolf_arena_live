import type { LivePlayer, LiveSpectatorState } from "./liveSpectator";
import { actionLabel, eventTypeLabel } from "./liveLabels";
import type { LiveGameEvent } from "./types";

export type GodViewIdentityGroup = "狼人" | "神职" | "平民" | "未知";

export type GodViewPlayerStageStatusKind =
  | "idle"
  | "preparing-speech"
  | "speaking"
  | "summarizing"
  | "voting"
  | "acting"
  | "resolved"
  | "affected"
  | "out";

export type GodViewPlayerStageStatus = {
  kind: GodViewPlayerStageStatusKind;
  label: string;
};

export type GodViewPlayer = {
  seatNumber: number;
  name: string;
  role: string;
  camp: "狼人阵营" | "好人阵营";
  identityGroup: GodViewIdentityGroup;
  isAlive: boolean;
  statusLabel: string;
  stageStatus: GodViewPlayerStageStatus;
  isSheriff: boolean;
  isSpeaking: boolean;
  voteTarget: string | null;
  receivedVotes: number;
  suspicionScore: number;
  clueTags: string[];
  model: string;
  personalityId: string;
  appearanceId: string;
  avatarImageUrl: string;
};

export type GodViewEventLine = {
  id: number;
  time: string;
  text: string;
  tone: "default" | "danger" | "info" | "success" | "warning";
};

export type GodViewActionLine = {
  label: string;
  value: string;
  tone: "danger" | "info" | "success" | "warning" | "muted";
};

export type GodViewNightActionOrderLine = GodViewActionLine & {
  order: number;
};

export type GodViewSkillTrigger = {
  id: number;
  label: string;
  detail: string;
  tone: "danger" | "info" | "success" | "warning" | "muted";
};

export type GodViewDeathInfo = {
  player: string;
  cause: string;
  time: string;
  publicText: string;
};

export type GodViewVoteTally = {
  target: string;
  count: number;
  voters: string[];
};

export type GodViewState = {
  boardName: string;
  dayNightLabel: string;
  phaseLabel: string;
  currentSeatLabel: string;
  countdownLabel: string;
  aliveLabel: string;
  winMode: string;
  winnerLabel: string;
  players: GodViewPlayer[];
  progress: {
    wolvesAlive: number;
    godsAlive: number;
    villagersAlive: number;
    totalAlive: number;
    totalPlayers: number;
  };
  nightActions: GodViewActionLine[];
  nightResolution: {
    label: string;
    detail: string;
    tone: "safe" | "danger" | "neutral";
  };
  nightActionOrder: GodViewNightActionOrderLine[];
  deaths: GodViewDeathInfo[];
  isPeacefulNight: boolean;
  vote: {
    stageLabel: string;
    tallies: GodViewVoteTally[];
    totalVotes: number;
    topTarget: string | null;
  };
  sheriff: {
    current: string | null;
    badgeFlow: string;
    callTarget: string | null;
    candidates: string[];
    voters: string[];
  };
  sheriffRuleState: {
    enabled: boolean;
    label: string;
  };
  speechOrder: string[];
  speakerFlow: {
    previous: GodViewPlayer | null;
    current: GodViewPlayer | null;
    next: GodViewPlayer | null;
    modeLabel: string;
  };
  eventLines: GodViewEventLine[];
  publicFacts: string[];
  replayMarks: GodViewEventLine[];
  skillTriggers: GodViewSkillTrigger[];
  winPressure: {
    label: string;
    detail: string;
    tone: "danger" | "warning" | "safe" | "neutral";
  };
};

export type GodViewOptions = {
  sheriffEnabled?: boolean;
};

type MutableGodView = {
  currentRound: number | null;
  currentPhase: string | null;
  stageFocus: GodViewStageFocus;
  voteTargets: Map<string, string>;
  voteWeights: Map<string, number>;
  nightActions: GodViewActionLine[];
  latestNightPayload: Record<string, unknown> | null;
  deaths: GodViewDeathInfo[];
  isPeacefulNight: boolean;
  sheriff: GodViewState["sheriff"];
  speechOrder: string[];
  winnerLabel: string;
  eventLines: GodViewEventLine[];
  publicFacts: string[];
  replayMarks: GodViewEventLine[];
  skillTriggers: GodViewSkillTrigger[];
  suppressedNightActionFallbackScope: {
    round: number | null;
    phase: string | null;
  } | null;
};

type GodViewStageFocusKind =
  | "waiting"
  | "speech"
  | "vote"
  | "summary"
  | "action"
  | "resolution"
  | "terminal";

type GodViewStageFocus = {
  kind: GodViewStageFocusKind;
  actorName: string | null;
  speakerName: string | null;
  actorStatus: GodViewPlayerStageStatus | null;
  affectedStatuses: Map<string, GodViewPlayerStageStatus>;
  resolutionName: string | null;
  countdownLabel: string;
};

export function deriveGodViewState(
  events: LiveGameEvent[],
  spectator: LiveSpectatorState,
  boardName: string,
  options: GodViewOptions = {},
): GodViewState {
  const view: MutableGodView = {
    currentRound: spectator.currentRound,
    currentPhase: spectator.currentPhase,
    stageFocus: waitingStageFocus(),
    voteTargets: new Map(),
    voteWeights: new Map(),
    nightActions: [],
    latestNightPayload: null,
    deaths: [],
    isPeacefulNight: false,
    sheriff: {
      current: null,
      badgeFlow: "未移交",
      callTarget: null,
      candidates: [],
      voters: [],
    },
    speechOrder: [],
    winnerLabel: "未结算",
    eventLines: [],
    publicFacts: [],
    replayMarks: [],
    skillTriggers: [],
    suppressedNightActionFallbackScope: null,
  };

  for (const event of events) {
    if (event.round !== null) {
      view.currentRound = event.round;
    }
    if (event.phase) {
      view.currentPhase = event.phase;
    }

    collectActionLine(view, event);
    collectStateUpdate(view, event);
    collectTerminal(view, event);
    collectEventLine(view, event);
    view.stageFocus = stageFocusForEvent(event);
  }

  const players = spectator.players.map((player, index) =>
    toGodViewPlayer(player, index, view),
  );
  const totalAlive = players.filter((player) => player.isAlive).length;
  const wolvesAlive = players.filter(
    (player) => player.isAlive && player.identityGroup === "狼人",
  ).length;
  const godsAlive = players.filter(
    (player) => player.isAlive && player.identityGroup === "神职",
  ).length;
  const villagersAlive = players.filter(
    (player) => player.isAlive && player.identityGroup === "平民",
  ).length;
  const tallies = buildVoteTallies(view.voteTargets, view.voteWeights);
  const speechOrder =
    view.speechOrder.length > 0
      ? view.speechOrder
      : players.map((player) => player.name);
  const progress = {
    wolvesAlive,
    godsAlive,
    villagersAlive,
    totalAlive,
    totalPlayers: players.length,
  };

  return {
    boardName,
    dayNightLabel: roundLabel(view.currentRound, view.currentPhase),
    phaseLabel: phaseDisplay(view.currentPhase),
    currentSeatLabel: currentSeatLabel(players, view.stageFocus),
    countdownLabel: view.stageFocus.countdownLabel,
    aliveLabel: `存活 ${totalAlive}/${players.length}`,
    winMode: "屠边",
    winnerLabel: view.winnerLabel,
    players,
    progress,
    nightActions: fallbackNightActions(
      view.nightActions,
      shouldSuppressNightActionFallback(view),
    ),
    nightResolution: buildNightResolution(view.latestNightPayload),
    nightActionOrder: buildNightActionOrder(view.nightActions),
    deaths: view.deaths.slice(-3).reverse(),
    isPeacefulNight: view.isPeacefulNight,
    vote: {
      stageLabel: view.currentPhase === "vote" ? "当前投票阶段" : "最近票型",
      tallies,
      totalVotes: Array.from(view.voteWeights.values()).reduce(
        (total, weight) => total + weight,
        0,
      ),
      topTarget: tallies[0]?.target ?? null,
    },
    sheriff: view.sheriff,
    sheriffRuleState: buildSheriffRuleState(options.sheriffEnabled),
    speechOrder,
    speakerFlow: buildSpeakerFlow(players, speechOrder, view.stageFocus.speakerName),
    eventLines: view.eventLines.slice(-7).reverse(),
    publicFacts: dedupe(view.publicFacts).slice(-6).reverse(),
    replayMarks: view.replayMarks.slice(-5).reverse(),
    skillTriggers: view.skillTriggers.slice(-5),
    winPressure: buildWinPressure(progress),
  };
}

function buildSpeakerFlow(
  players: GodViewPlayer[],
  speechOrder: string[],
  activePlayerName: string | null,
): GodViewState["speakerFlow"] {
  const currentSpeakerIndex = speechOrder.findIndex(
    (name) => name === activePlayerName,
  );
  if (currentSpeakerIndex < 0 || speechOrder.length === 0) {
    return {
      previous: null,
      current: null,
      next: null,
      modeLabel: "等待发言",
    };
  }

  return {
    previous: playerByName(
      players,
      speechOrder.at(currentSpeakerIndex - 1) ?? speechOrder.at(-1),
    ),
    current: playerByName(players, speechOrder[currentSpeakerIndex]),
    next: playerByName(
      players,
      speechOrder[(currentSpeakerIndex + 1) % speechOrder.length],
    ),
    modeLabel: "顺序发言",
  };
}

function playerByName(players: GodViewPlayer[], name: string | undefined) {
  return name ? players.find((player) => player.name === name) ?? null : null;
}

function collectActionLine(view: MutableGodView, event: LiveGameEvent) {
  if (event.type !== "action_parsed") {
    return;
  }

  const payload = payloadForEvent(event);
  if (
    event.phase === "night" &&
    (event.action === "werewolf_discuss" ||
      event.action === "werewolf_kill_vote")
  ) {
    view.suppressedNightActionFallbackScope = {
      round: event.round,
      phase: event.phase,
    };
    return;
  }
  const choice = stringField(payload, "choice") || parsedChoice(payload);
  if (event.action === "vote" && event.actor && choice) {
    view.voteTargets.set(event.actor, choice);
  }
  if (!choice) {
    return;
  }

  if (event.action === "eliminate" || event.action === "remove") {
    pushUniqueAction(view, {
      label: "狼人目标",
      value: `击杀 ${choice}`,
      tone: "danger",
    });
  } else if (event.action === "protect" || event.action === "guard") {
    pushUniqueAction(view, {
      label: "守卫守护",
      value: `守护 ${choice}`,
      tone: "success",
    });
  } else if (event.action === "investigate") {
    pushUniqueAction(view, {
      label: "预言家查验",
      value: `查验 ${choice}${parsedResult(payload)}`,
      tone: "info",
    });
  } else if (event.action === "witch_save") {
    pushUniqueAction(view, {
      label: "女巫解药",
      value: choice === "skip" ? "未使用" : `救 ${choice}`,
      tone: choice === "skip" ? "muted" : "success",
    });
  } else if (event.action === "witch_poison") {
    pushUniqueAction(view, {
      label: "女巫毒药",
      value: choice === "skip" ? "未使用" : `毒 ${choice}`,
      tone: choice === "skip" ? "muted" : "danger",
    });
  } else if (event.action === "sheriff_badge") {
    view.sheriff.badgeFlow =
      choice === "destroy" || choice === "撕毁" ? "撕毁警徽" : `移交 ${choice}`;
  }
}

function collectStateUpdate(view: MutableGodView, event: LiveGameEvent) {
  if (event.type !== "state_updated") {
    return;
  }

  const payload = payloadForEvent(event);
  const votes = recordField(payload, "votes");
  if (votes) {
    view.voteTargets = new Map(
      Object.entries(votes).map(([voter, target]) => [voter, String(target)]),
    );
  }
  const weights = recordField(payload, "vote_weights");
  if (weights) {
    view.voteWeights = new Map(
      Object.entries(weights).map(([voter, weight]) => [
        voter,
        typeof weight === "number" ? weight : 1,
      ]),
    );
  }

  const speechOrder = stringArrayField(payload, "speech_order");
  if (speechOrder.length > 0) {
    view.speechOrder = speechOrder;
  }

  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  const savedByWitch = stringField(payload, "saved_by_witch");
  const poisoned = stringField(payload, "poisoned");
  const investigated = stringField(payload, "investigated");
  const eliminated = stringField(payload, "eliminated");
  const exiled = stringField(payload, "exiled");

  if (
    event.phase === "night" ||
    attacked ||
    protectedPlayer ||
    savedByWitch ||
    poisoned ||
    investigated ||
    eliminated
  ) {
    view.latestNightPayload = payload;
  }

  if (attacked) {
    pushUniqueAction(view, {
      label: "狼人目标",
      value: `击杀 ${attacked}`,
      tone: "danger",
    });
  }
  if (protectedPlayer) {
    pushUniqueAction(view, {
      label: "守卫守护",
      value: `守护 ${protectedPlayer}`,
      tone: "success",
    });
  }
  if (savedByWitch) {
    pushUniqueAction(view, {
      label: "女巫解药",
      value: `救 ${savedByWitch}`,
      tone: "success",
    });
  }
  if (poisoned) {
    pushUniqueAction(view, {
      label: "女巫毒药",
      value: `毒 ${poisoned}`,
      tone: "danger",
    });
  }
  if (investigated) {
    pushUniqueAction(view, {
      label: "预言家查验",
      value: `查验 ${investigated}`,
      tone: "info",
    });
  }

  view.isPeacefulNight = Boolean(
    (attacked || protectedPlayer || savedByWitch) && !eliminated && !poisoned,
  );
  collectDeaths(view, event, payload, eliminated, exiled);
  collectSheriff(view, payload);
  collectFacts(view, payload);
  collectSkillTriggers(view, event, payload);
}

function collectDeaths(
  view: MutableGodView,
  event: LiveGameEvent,
  payload: Record<string, unknown>,
  eliminated: string,
  exiled: string,
) {
  for (const field of ["night_deaths", "day_deaths"]) {
    const deaths = payload[field];
    if (!Array.isArray(deaths)) {
      continue;
    }

    for (const death of deaths) {
      if (!isRecord(death) || typeof death.player !== "string") {
        continue;
      }
      pushUniqueDeath(view, {
        player: death.player,
        cause: causeDisplay(String(death.cause ?? "")),
        time: timeLabel(event),
        publicText: field === "night_deaths" ? "天亮公布" : "白天公布",
      });
    }
  }

  if (eliminated) {
    pushUniqueDeath(view, {
      player: eliminated,
      cause: "狼人击杀",
      time: timeLabel(event),
      publicText: "天亮公布",
    });
  }
  if (exiled) {
    pushUniqueDeath(view, {
      player: exiled,
      cause: "投票放逐",
      time: timeLabel(event),
      publicText: "白天公开",
    });
  }
}

function collectSheriff(view: MutableGodView, payload: Record<string, unknown>) {
  const sheriff =
    stringField(payload, "sheriff") || stringField(payload, "sheriff_elected");
  if (sheriff) {
    view.sheriff.current = sheriff;
  }

  const badgeTarget = stringField(payload, "sheriff_badge_target");
  if (badgeTarget) {
    view.sheriff.badgeFlow = `移交 ${badgeTarget}`;
  }
  if (payload.sheriff_badge_lost === true) {
    view.sheriff.badgeFlow = "警徽撕毁";
  }

  const candidates = stringArrayField(payload, "sheriff_candidates");
  if (candidates.length > 0) {
    view.sheriff.candidates = candidates;
  }
  const voters = stringArrayField(payload, "sheriff_voters");
  if (voters.length > 0) {
    view.sheriff.voters = voters;
  }

  view.sheriff.callTarget = stringField(payload, "sheriff_call_target") || null;
}

function collectFacts(view: MutableGodView, payload: Record<string, unknown>) {
  const sheriff =
    stringField(payload, "sheriff") || stringField(payload, "sheriff_elected");
  if (sheriff) {
    view.publicFacts.push(`警长：${sheriff}`);
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    view.publicFacts.push(`${exiled} 被放逐`);
  }

  const eliminated = stringField(payload, "eliminated");
  if (eliminated) {
    view.publicFacts.push(`${eliminated} 夜晚死亡`);
  }

  const selfExploded = stringField(payload, "werewolf_self_exploded");
  if (selfExploded) {
    view.publicFacts.push(`${selfExploded} 自爆`);
  }
}

function collectSkillTriggers(
  view: MutableGodView,
  event: LiveGameEvent,
  payload: Record<string, unknown>,
) {
  const selfExploded = stringField(payload, "werewolf_self_exploded");
  if (selfExploded) {
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "狼人自爆",
      detail: `${selfExploded} 发动自爆。`,
      tone: "danger",
    });
  }

  const hunterShot = stringField(payload, "hunter_shot");
  if (hunterShot) {
    const hunter = event.actor || "猎人";
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "猎人带走",
      detail: `${hunter} 带走 ${hunterShot}。`,
      tone: "warning",
    });
  }

  const idiotRevealed = stringField(payload, "idiot_revealed");
  if (idiotRevealed) {
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "白痴翻牌",
      detail: `${idiotRevealed} 翻牌留在场上。`,
      tone: "info",
    });
  }

  const badgeTarget = stringField(payload, "sheriff_badge_target");
  if (badgeTarget) {
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "警徽移交",
      detail: `警徽移交给 ${badgeTarget}。`,
      tone: "success",
    });
  }

  if (payload.sheriff_badge_lost === true) {
    pushUniqueSkillTrigger(view, {
      id: event.id,
      label: "警徽撕毁",
      detail: "警徽被撕毁。",
      tone: "muted",
    });
  }
}

function collectTerminal(view: MutableGodView, event: LiveGameEvent) {
  if (event.type !== "game_completed" && event.type !== "state_updated") {
    return;
  }

  const winner = stringField(payloadForEvent(event), "winner");
  if (winner) {
    view.winnerLabel = winner;
  }
}

function collectEventLine(view: MutableGodView, event: LiveGameEvent) {
  const line = eventLineFor(event);
  if (line) {
    view.eventLines.push(line);
  }
  if (
    event.type === "phase_started" ||
    event.type === "state_updated" ||
    event.type === "game_completed"
  ) {
    view.replayMarks.push(
      line ?? {
        id: event.id,
        time: timeLabel(event),
        text: eventTypeLabel(event.type),
        tone: "default",
      },
    );
  }
}

function toGodViewPlayer(
  player: LivePlayer,
  index: number,
  view: MutableGodView,
): GodViewPlayer {
  const role = normalizeRole(player.role);
  const receivedVotes = Array.from(view.voteTargets.entries()).reduce(
    (total, [voter, target]) =>
      target === player.name ? total + (view.voteWeights.get(voter) ?? 1) : total,
    0,
  );
  const stageStatus = stageStatusForPlayer(player, view.stageFocus);
  const isSpeaking = stageStatus.kind === "speaking" && player.isAlive;

  return {
    seatNumber: index + 1,
    name: player.name,
    role,
    camp: roleCamp(role),
    identityGroup: identityGroup(role),
    isAlive: player.isAlive,
    statusLabel: statusLabel(player, stageStatus),
    stageStatus,
    isSheriff: view.sheriff.current === player.name,
    isSpeaking,
    voteTarget: view.voteTargets.get(player.name) ?? null,
    receivedVotes,
    suspicionScore: suspicionScore(player, index, receivedVotes),
    clueTags: clueTags(player, role),
    model: player.model,
    personalityId: player.personalityId,
    appearanceId: player.appearanceId,
    avatarImageUrl: player.avatarImageUrl,
  };
}

function buildVoteTallies(
  voteTargets: Map<string, string>,
  voteWeights: Map<string, number>,
): GodViewVoteTally[] {
  const tallies = new Map<string, GodViewVoteTally>();
  for (const [voter, target] of voteTargets.entries()) {
    const item =
      tallies.get(target) ??
      tallies
        .set(target, { target, count: 0, voters: [] })
        .get(target)!;
    item.count += voteWeights.get(voter) ?? 1;
    item.voters.push(voter);
  }

  return Array.from(tallies.values()).sort((a, b) => b.count - a.count);
}

function eventLineFor(event: LiveGameEvent): GodViewEventLine | null {
  const payload = payloadForEvent(event);
  if (event.type === "model_response_delta") {
    return null;
  }
  if (event.type === "action_requested" && event.actor) {
    return {
      id: event.id,
      time: timeLabel(event),
      text: `${event.actor} 开始${actionDisplay(event.action)}`,
      tone: "info",
    };
  }
  if (event.type === "state_updated") {
    return {
      id: event.id,
      time: timeLabel(event),
      text: stateUpdatedReplayText(payload),
      tone: stateUpdatedReplayTone(payload),
    };
  }
  if (event.type === "phase_started") {
    return {
      id: event.id,
      time: timeLabel(event),
      text: phaseEventText(event.phase),
      tone: "default",
    };
  }
  if (event.type === "round_started") {
    return {
      id: event.id,
      time: timeLabel(event),
      text: event.round === null ? "新回合开始" : `第 ${event.round} 轮开始`,
      tone: "default",
    };
  }
  if (event.type === "game_completed") {
    return {
      id: event.id,
      time: timeLabel(event),
      text: `结算：${stringField(payload, "winner") || "对局完成"}`,
      tone: "success",
    };
  }
  return null;
}

function stateUpdatedReplayText(payload: Record<string, unknown>) {
  const exiled = stringField(payload, "exiled");
  if (exiled) {
    return `放逐 ${exiled}`;
  }
  const eliminated = stringField(payload, "eliminated");
  if (eliminated) {
    return `夜晚死亡 ${eliminated}`;
  }
  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  if (attacked && protectedPlayer === attacked) {
    return "平安夜";
  }
  if (recordField(payload, "votes")) {
    return "投票结果更新";
  }
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    return `${debateEntry.speaker} 发言`;
  }
  return "局势更新";
}

function stateUpdatedReplayTone(
  payload: Record<string, unknown>,
): GodViewEventLine["tone"] {
  if (stringField(payload, "exiled") || stringField(payload, "eliminated")) {
    return "danger";
  }
  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  if (attacked && protectedPlayer === attacked) {
    return "success";
  }
  if (recordField(payload, "votes")) {
    return "warning";
  }
  return "default";
}

function shouldSuppressNightActionFallback(view: MutableGodView) {
  const scope = view.suppressedNightActionFallbackScope;
  return (
    scope !== null &&
    scope.round === view.currentRound &&
    scope.phase === view.currentPhase
  );
}

function fallbackNightActions(
  actions: GodViewActionLine[],
  suppressFallback: boolean,
) {
  if (actions.length > 0) {
    return actions.slice(-5).reverse();
  }
  if (suppressFallback) {
    return [];
  }
  return [
    { label: "狼人目标", value: "等待夜间行动", tone: "muted" },
    { label: "预言家查验", value: "暂无记录", tone: "muted" },
    { label: "女巫药剂", value: "暂无记录", tone: "muted" },
    { label: "守卫守护", value: "暂无记录", tone: "muted" },
  ] satisfies GodViewActionLine[];
}

function buildNightResolution(
  payload: Record<string, unknown> | null,
): GodViewState["nightResolution"] {
  if (!payload) {
    return {
      label: "等待夜间结算",
      detail: "暂无夜间结论",
      tone: "neutral",
    };
  }

  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  const eliminated = stringField(payload, "eliminated");
  const poisoned = stringField(payload, "poisoned");

  if (eliminated) {
    return {
      label: "昨夜死亡",
      detail: `${eliminated} 夜晚出局。`,
      tone: "danger",
    };
  }
  if (poisoned) {
    return {
      label: "昨夜死亡",
      detail: `${poisoned} 被女巫毒杀。`,
      tone: "danger",
    };
  }
  if (attacked && protectedPlayer === attacked) {
    return {
      label: "平安夜",
      detail: `${attacked} 被狼人袭击，但被守卫守护。`,
      tone: "safe",
    };
  }
  if (attacked) {
    return {
      label: "夜间结算",
      detail: `${attacked} 遭到狼人袭击，暂无死亡公布。`,
      tone: "neutral",
    };
  }
  return {
    label: "夜间结算",
    detail: "暂无死亡玩家。",
    tone: "neutral",
  };
}

function buildNightActionOrder(
  actions: GodViewActionLine[],
): GodViewNightActionOrderLine[] {
  const preferredOrder = [
    "狼人目标",
    "守卫守护",
    "预言家查验",
    "女巫解药",
    "女巫毒药",
  ];
  const orderedActions = preferredOrder
    .map((label) => actions.find((action) => action.label === label))
    .filter((action): action is GodViewActionLine => Boolean(action));

  if (orderedActions.length === 0) {
    return [
      {
        order: 1,
        label: "狼人目标",
        value: "等待夜间行动",
        tone: "muted",
      },
    ];
  }

  return orderedActions.map((action, index) => ({
    ...action,
    order: index + 1,
  }));
}

function buildSheriffRuleState(
  sheriffEnabled: boolean | undefined,
): GodViewState["sheriffRuleState"] {
  if (sheriffEnabled === false) {
    return {
      enabled: false,
      label: "本局无警长规则",
    };
  }
  return {
    enabled: true,
    label: "警长规则开启",
  };
}

function buildWinPressure(
  progress: GodViewState["progress"],
): GodViewState["winPressure"] {
  const goodAlive = progress.godsAlive + progress.villagersAlive;
  if (progress.totalPlayers === 0) {
    return {
      label: "局势未到临界",
      detail: "等待玩家和身份信息。",
      tone: "neutral",
    };
  }
  if (progress.wolvesAlive === 0) {
    return {
      label: "好人胜势",
      detail: "狼人已清零。",
      tone: "safe",
    };
  }
  if (progress.wolvesAlive >= goodAlive) {
    return {
      label: "狼人压制",
      detail: "狼人数量已达到或超过好人数量。",
      tone: "danger",
    };
  }
  if (progress.godsAlive === 0 || progress.villagersAlive === 0) {
    return {
      label: "接近屠边",
      detail: "神职或平民阵线已到临界。",
      tone: "warning",
    };
  }
  return {
    label: "局势未到临界",
    detail: "双方仍需通过发言和投票推进。",
    tone: "neutral",
  };
}

function pushUniqueAction(view: MutableGodView, action: GodViewActionLine) {
  const key = `${action.label}:${action.value}`;
  if (view.nightActions.some((item) => `${item.label}:${item.value}` === key)) {
    return;
  }
  view.nightActions.push(action);
}

function pushUniqueDeath(view: MutableGodView, death: GodViewDeathInfo) {
  const key = `${death.player}:${death.cause}:${death.time}`;
  if (
    view.deaths.some(
      (item) => `${item.player}:${item.cause}:${item.time}` === key,
    )
  ) {
    return;
  }
  view.deaths.push(death);
}

function pushUniqueSkillTrigger(
  view: MutableGodView,
  trigger: GodViewSkillTrigger,
) {
  const key = `${trigger.id}:${trigger.label}:${trigger.detail}`;
  if (
    view.skillTriggers.some(
      (item) => `${item.id}:${item.label}:${item.detail}` === key,
    )
  ) {
    return;
  }
  view.skillTriggers.push(trigger);
}

function roundLabel(round: number | null, phase: string | null) {
  if (round === null) {
    return "等待开局";
  }
  return phase === "night" ? `第 ${round} 夜` : `第 ${round} 天`;
}

function currentSeatLabel(
  players: GodViewPlayer[],
  focus: GodViewStageFocus,
) {
  if (focus.kind === "terminal") {
    return "对局结束";
  }
  if (focus.kind === "waiting") {
    return "等待";
  }
  if (focus.kind === "resolution") {
    return focus.resolutionName ? `结算：${focus.resolutionName}` : "结算中";
  }

  const player = players.find((item) => item.name === focus.actorName);
  const seat = player ? `${player.seatNumber} 号` : "等待";
  const map: Record<
    Exclude<GodViewStageFocusKind, "waiting" | "resolution" | "terminal">,
    string
  > = {
    action: "行动席",
    speech: "发言席",
    summary: "总结席",
    vote: "投票席",
  };
  return `${map[focus.kind]}：${seat}`;
}

function waitingStageFocus(): GodViewStageFocus {
  return {
    kind: "waiting",
    actorName: null,
    speakerName: null,
    actorStatus: null,
    affectedStatuses: new Map(),
    resolutionName: null,
    countdownLabel: "待命",
  };
}

function stageFocusForEvent(event: LiveGameEvent): GodViewStageFocus {
  if (event.type === "game_completed" || event.type === "game_failed") {
    return {
      ...waitingStageFocus(),
      kind: "terminal",
      countdownLabel: "已结束",
    };
  }

  if (event.type === "state_updated") {
    return stageFocusForStateUpdate(event);
  }

  if (event.actor) {
    return stageFocusForActorEvent(event);
  }

  if (event.type === "phase_started") {
    return stageFocusForPhase(event.phase);
  }

  return waitingStageFocus();
}

function stageFocusForStateUpdate(event: LiveGameEvent): GodViewStageFocus {
  const payload = payloadForEvent(event);
  const affectedStatuses = affectedStatusesForPayload(payload);
  if (affectedStatuses.size > 0) {
    return {
      ...waitingStageFocus(),
      kind: "resolution",
      affectedStatuses,
      resolutionName: affectedStatuses.keys().next().value ?? null,
      countdownLabel: "结算中",
    };
  }

  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    return actorStageFocus({
      kind: "speech",
      actorName: debateEntry.speaker,
      speakerName: debateEntry.speaker,
      actorStatus: { kind: "resolved", label: "已发言" },
      countdownLabel: "已记录",
    });
  }

  if (recordField(payload, "votes")) {
    return {
      ...waitingStageFocus(),
      kind: "resolution",
      resolutionName: "投票结果",
      countdownLabel: "结算中",
    };
  }

  if (event.actor) {
    return stageFocusForActorEvent(event);
  }

  return stageFocusForPhase(event.phase);
}

function stageFocusForPhase(phase: string | null): GodViewStageFocus {
  if (phase === "night") {
    return {
      ...waitingStageFocus(),
      kind: "action",
      countdownLabel: "夜间行动中",
    };
  }
  if (phase === "vote") {
    return {
      ...waitingStageFocus(),
      kind: "vote",
      countdownLabel: "投票中",
    };
  }
  if (phase === "summary") {
    return {
      ...waitingStageFocus(),
      kind: "summary",
      countdownLabel: "总结中",
    };
  }
  return waitingStageFocus();
}

function stageFocusForActorEvent(event: LiveGameEvent): GodViewStageFocus {
  const actorName = event.actor;
  if (!actorName) {
    return stageFocusForPhase(event.phase);
  }

  if (isPublicSpeechAction(event.action)) {
    if (event.type === "model_response_delta") {
      return actorStageFocus({
        kind: "speech",
        actorName,
        speakerName: actorName,
        actorStatus: { kind: "speaking", label: "发言中" },
        countdownLabel: "00:45",
      });
    }
    if (isResolvedActorEvent(event.type)) {
      return actorStageFocus({
        kind: "speech",
        actorName,
        speakerName: actorName,
        actorStatus: { kind: "resolved", label: "已发言" },
        countdownLabel: "已记录",
      });
    }
    return actorStageFocus({
      kind: "speech",
      actorName,
      speakerName: actorName,
      actorStatus: { kind: "preparing-speech", label: "准备发言" },
      countdownLabel: "准备中",
    });
  }

  if (isVoteAction(event.action)) {
    return actorStageFocus({
      kind: "vote",
      actorName,
      speakerName: null,
      actorStatus: isResolvedActorEvent(event.type)
        ? { kind: "resolved", label: "已投票" }
        : { kind: "voting", label: "投票中" },
      countdownLabel: isResolvedActorEvent(event.type) ? "已投票" : "投票中",
    });
  }

  if (isSummaryAction(event.action)) {
    return actorStageFocus({
      kind: "summary",
      actorName,
      speakerName: null,
      actorStatus: isResolvedActorEvent(event.type)
        ? { kind: "resolved", label: "已总结" }
        : { kind: "summarizing", label: "总结中" },
      countdownLabel: isResolvedActorEvent(event.type) ? "已总结" : "总结中",
    });
  }

  return actorStageFocus({
    kind: "action",
    actorName,
    speakerName: null,
    actorStatus: isResolvedActorEvent(event.type)
      ? { kind: "resolved", label: "已行动" }
      : {
          kind: "acting",
          label: event.phase === "night" ? "夜间行动中" : "行动中",
        },
    countdownLabel: event.phase === "night" ? "夜间行动中" : "行动中",
  });
}

function actorStageFocus({
  actorName,
  actorStatus,
  countdownLabel,
  kind,
  speakerName,
}: {
  actorName: string;
  actorStatus: GodViewPlayerStageStatus;
  countdownLabel: string;
  kind: Exclude<
    GodViewStageFocusKind,
    "waiting" | "resolution" | "terminal"
  >;
  speakerName: string | null;
}): GodViewStageFocus {
  return {
    kind,
    actorName,
    speakerName,
    actorStatus,
    affectedStatuses: new Map(),
    resolutionName: null,
    countdownLabel,
  };
}

function stageStatusForPlayer(
  player: LivePlayer,
  focus: GodViewStageFocus,
): GodViewPlayerStageStatus {
  if (!player.isAlive) {
    return { kind: "out", label: player.lastDetail || "出局" };
  }

  const affected = focus.affectedStatuses.get(player.name);
  if (affected) {
    return affected;
  }

  if (focus.actorName === player.name && focus.actorStatus) {
    return focus.actorStatus;
  }

  return { kind: "idle", label: "存活" };
}

function affectedStatusesForPayload(
  payload: Record<string, unknown>,
): Map<string, GodViewPlayerStageStatus> {
  const statuses = new Map<string, GodViewPlayerStageStatus>();
  for (const field of ["night_deaths", "day_deaths"]) {
    const deaths = payload[field];
    if (!Array.isArray(deaths)) {
      continue;
    }
    for (const death of deaths) {
      if (!isRecord(death) || typeof death.player !== "string") {
        continue;
      }
      statuses.set(death.player, {
        kind: "out",
        label: field === "night_deaths" ? "夜晚出局" : "白天出局",
      });
    }
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    statuses.set(exiled, { kind: "out", label: "白天放逐" });
  }

  const eliminated = stringField(payload, "eliminated");
  if (eliminated) {
    statuses.set(eliminated, { kind: "out", label: "夜晚出局" });
  }

  const selfExploded = stringField(payload, "werewolf_self_exploded");
  if (selfExploded) {
    statuses.set(selfExploded, { kind: "affected", label: "自爆公开" });
  }

  const hunterShot = stringField(payload, "hunter_shot");
  if (hunterShot) {
    statuses.set(hunterShot, { kind: "affected", label: "被带走" });
  }

  const protectedPlayer = stringField(payload, "protected");
  if (protectedPlayer && statuses.size === 0) {
    statuses.set(protectedPlayer, { kind: "affected", label: "被守护" });
  }

  return statuses;
}

function isPublicSpeechAction(action: string | null) {
  return (
    action === "debate" ||
    action === "sheriff_speech" ||
    action === "sheriff_pk_speech"
  );
}

function isVoteAction(action: string | null) {
  return (
    action === "vote" ||
    action === "sheriff_vote" ||
    action === "sheriff_runoff_vote"
  );
}

function isSummaryAction(action: string | null) {
  return action === "summarize";
}

function isResolvedActorEvent(type: string) {
  return (
    type === "model_response_received" ||
    type === "action_parsed" ||
    type === "state_updated"
  );
}

export function phaseDisplay(phase: string | null) {
  const map: Record<string, string> = {
    night: "夜晚",
    day: "白天发言",
    vote: "投票",
    summary: "结算",
    sheriff: "警长竞选",
  };
  return phase ? map[phase] ?? phase : "阶段未开始";
}

function actionDisplay(action: string | null) {
  const map: Record<string, string> = {
    debate: "发言",
    vote: "投票",
    eliminate: "刀人",
    remove: "刀人",
    guard: "守护",
    protect: "守护",
    investigate: "查验",
    summarize: "总结",
    sheriff_speech: "警上发言",
    sheriff_pk_speech: "警长 PK 发言",
    sheriff_vote: "警长投票",
    sheriff_runoff_vote: "警长 PK 投票",
    werewolf_self_explosion: "考虑自爆",
  };
  return action ? map[action] ?? actionLabel(action) : "行动";
}

function phaseEventText(phase: string | null) {
  const map: Record<string, string> = {
    night: "夜晚阶段开始",
    day: "白天阶段开始",
    vote: "投票阶段开始",
    summary: "总结阶段开始",
    sheriff: "警长竞选开始",
  };
  return phase ? map[phase] ?? `进入${phase}` : "阶段开始";
}

function statusLabel(
  player: LivePlayer,
  stageStatus: GodViewPlayerStageStatus,
) {
  if (!player.isAlive) {
    return stageStatus.label || player.lastDetail || "死亡";
  }
  return stageStatus.label;
}

function normalizeRole(role: string) {
  const lower = role.toLowerCase();
  const map: Record<string, string> = {
    werewolf: "狼人",
    villager: "平民",
    seer: "预言家",
    guard: "守卫",
    doctor: "医生",
    witch: "女巫",
    hunter: "猎人",
    idiot: "白痴",
  };
  return map[lower] ?? role;
}

function roleCamp(role: string): GodViewPlayer["camp"] {
  return role.includes("狼") ? "狼人阵营" : "好人阵营";
}

function identityGroup(role: string): GodViewIdentityGroup {
  if (role.includes("狼")) {
    return "狼人";
  }
  if (
    role.includes("预言家") ||
    role.includes("女巫") ||
    role.includes("守卫") ||
    role.includes("医生") ||
    role.includes("猎人") ||
    role.includes("白痴")
  ) {
    return "神职";
  }
  if (role.includes("平民") || role.includes("村民")) {
    return "平民";
  }
  return "未知";
}

function suspicionScore(
  player: LivePlayer,
  index: number,
  receivedVotes: number,
) {
  if (!player.isAlive) {
    return 0;
  }
  const roleWeight = roleCamp(normalizeRole(player.role)) === "狼人阵营" ? 54 : 18;
  const activityWeight =
    player.status === "streaming" || player.status === "thinking" ? 7 : 0;
  return Math.min(
    99,
    roleWeight + receivedVotes * 12 + ((index * 7) % 11) + activityWeight,
  );
}

function clueTags(player: LivePlayer, role: string) {
  const tags: string[] = [roleCamp(role), identityGroup(role)];
  tags.push(player.isAlive ? "存活" : "出局");
  return tags;
}

function causeDisplay(cause: string) {
  const map: Record<string, string> = {
    werewolf_attack: "狼人击杀",
    legacy_werewolf_attack: "狼人击杀",
    vote_exile: "投票放逐",
    legacy_vote_exile: "投票放逐",
    witch_poison: "女巫毒杀",
    hunter_shot: "猎人带走",
  };
  return map[cause] ?? (cause || "未知原因");
}

function parsedChoice(payload: Record<string, unknown>) {
  const result = payload.result;
  if (!isRecord(result)) {
    return "";
  }
  for (const field of ["target", "choice", "player", "vote"]) {
    const value = result[field];
    if (typeof value === "string") {
      return value;
    }
  }
  return "";
}

function parsedResult(payload: Record<string, unknown>) {
  const result = payload.result;
  if (!isRecord(result)) {
    return "";
  }
  const alignment = stringField(result, "alignment") || stringField(result, "result");
  return alignment ? `，结果 ${alignment}` : "";
}

function payloadForEvent(event: LiveGameEvent): Record<string, unknown> {
  return isRecord(event.payload) ? event.payload : {};
}

function recordField(payload: Record<string, unknown>, field: string) {
  const value = payload[field];
  return isRecord(value) ? value : null;
}

function stringField(payload: Record<string, unknown>, field: string) {
  const value = payload[field];
  return typeof value === "string" ? value : "";
}

function stringArrayField(payload: Record<string, unknown>, field: string) {
  const value = payload[field];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function timeLabel(event: LiveGameEvent) {
  const date = new Date(event.created_at);
  if (Number.isNaN(date.getTime())) {
    return `#${event.id}`;
  }
  return date.toISOString().slice(14, 19);
}

function dedupe(values: string[]) {
  return Array.from(new Set(values));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
