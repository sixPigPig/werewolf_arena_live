import type { LivePlayer, LiveSpectatorState } from "./liveSpectator";
import { eventTypeLabel } from "./liveLabels";
import type { LiveGameEvent } from "../types";

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
  exitKind: LivePlayer["exitKind"];
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
  round?: number | null;
  phase?: string | null;
  detail?: string;
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
  nameToSeat: Map<string, number>;
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
    nameToSeat: buildNameToSeat(spectator.players),
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
    eventLines: view.eventLines.slice(-60).reverse(),
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
  const line = eventLineFor(event, view.nameToSeat);
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
        round: event.round,
        phase: event.phase,
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
    exitKind: player.exitKind,
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

function eventLineFor(
  event: LiveGameEvent,
  nameToSeat: Map<string, number>,
): GodViewEventLine | null {
  const payload = payloadForEvent(event);
  if (event.type === "model_response_delta" || event.type === "model_thinking_tick") {
    return null;
  }
  if (
    event.type === "action_requested" &&
    event.actor &&
    isMeaningfulActionRequest(event.action)
  ) {
    return {
      id: event.id,
      time: timeLabel(event),
      text: actionRequestText(event, nameToSeat),
      tone: "info",
      round: event.round,
      phase: event.phase,
    };
  }
  if (event.type === "action_parsed") {
    return actionParsedLine(event, payload, nameToSeat);
  }
  if (event.type === "state_updated") {
    const text = stateUpdatedReplayText(event, payload, nameToSeat);
    if (!text) {
      return null;
    }
    return {
      id: event.id,
      time: timeLabel(event),
      text,
      tone: stateUpdatedReplayTone(payload),
      round: event.round,
      phase: event.phase,
      detail: stateUpdatedReplayDetail(event, payload, nameToSeat),
    };
  }
  if (event.type === "phase_started") {
    return {
      id: event.id,
      time: timeLabel(event),
      text: phaseEventText(event.phase),
      tone: "default",
      round: event.round,
      phase: event.phase,
    };
  }
  if (event.type === "round_started") {
    return {
      id: event.id,
      time: timeLabel(event),
      text: event.round === null ? "新回合开始" : `第 ${event.round} 轮开始`,
      tone: "default",
      round: event.round,
      phase: event.phase,
    };
  }
  if (event.type === "game_completed") {
    return {
      id: event.id,
      time: timeLabel(event),
      text: `结算：${stringField(payload, "winner") || "对局完成"}`,
      tone: "success",
      round: event.round,
      phase: event.phase,
    };
  }
  return null;
}

function isMeaningfulActionRequest(action: string | null): boolean {
  return (
    action === "eliminate" ||
    action === "remove" ||
    action === "protect" ||
    action === "guard" ||
    action === "investigate" ||
    action === "witch_save" ||
    action === "witch_poison" ||
    action === "vote" ||
    action === "sheriff_vote" ||
    action === "sheriff_runoff_vote"
  );
}

function actionRequestText(
  event: LiveGameEvent,
  nameToSeat: Map<string, number>,
): string {
  if (event.action === "eliminate" || event.action === "remove") {
    return "狼人开始行动";
  }
  if (event.action === "protect" || event.action === "guard") {
    return "守卫开始行动";
  }
  if (event.action === "investigate") {
    return "预言家开始行动";
  }
  if (event.action === "witch_save") {
    return "女巫考虑使用解药";
  }
  if (event.action === "witch_poison") {
    return "女巫考虑使用毒药";
  }
  return `${seatLabel(event.actor ?? "未知行动者", nameToSeat)} 等待投票`;
}

function actionParsedLine(
  event: LiveGameEvent,
  payload: Record<string, unknown>,
  nameToSeat: Map<string, number>,
): GodViewEventLine | null {
  const action = event.action;
  if (
    !action ||
    action === "werewolf_discuss" ||
    action === "werewolf_kill_vote" ||
    action === "debate" ||
    action === "sheriff_speech" ||
    action === "sheriff_pk_speech" ||
    action === "summarize"
  ) {
    return null;
  }

  const choice = stringField(payload, "choice") || parsedChoice(payload);
  const targetSeat = choice ? seatLabel(choice, nameToSeat) : "";
  const base = {
    id: event.id,
    time: timeLabel(event),
    round: event.round,
    phase: event.phase,
  };

  if (action === "eliminate" || action === "remove") {
    if (!choice) {
      return null;
    }
    return {
      ...base,
      text: `狼人 -> ${targetSeat}`,
      detail: `狼人阵营选择袭击 ${targetSeat}`,
      tone: "danger",
    };
  }
  if (action === "protect" || action === "guard") {
    if (!choice) {
      return null;
    }
    return {
      ...base,
      text: `守卫守护 ${targetSeat}`,
      detail: `守卫守护 ${targetSeat}`,
      tone: "success",
    };
  }
  if (action === "investigate") {
    if (!choice) {
      return null;
    }
    return {
      ...base,
      text: `预言家查验 ${targetSeat}`,
      detail: `预言家查验 ${targetSeat}`,
      tone: "info",
    };
  }
  if (action === "witch_save") {
    const used = choice && choice !== "skip";
    return {
      ...base,
      text: used ? `女巫救 ${targetSeat}` : "女巫未使用解药",
      detail: used
        ? `女巫对 ${targetSeat} 使用解药`
        : "女巫未使用解药",
      tone: used ? "success" : "default",
    };
  }
  if (action === "witch_poison") {
    const used = choice && choice !== "skip";
    return {
      ...base,
      text: used ? `女巫毒 ${targetSeat}` : "女巫未使用毒药",
      detail: used
        ? `女巫对 ${targetSeat} 使用毒药`
        : "女巫未使用毒药",
      tone: used ? "danger" : "default",
    };
  }
  if (action === "vote" || action === "sheriff_vote" || action === "sheriff_runoff_vote") {
    if (!event.actor || !choice) {
      return null;
    }
    return {
      ...base,
      text: `${seatLabel(event.actor, nameToSeat)} -> ${targetSeat}`,
      detail: `${seatLabel(event.actor, nameToSeat)} 投给 ${targetSeat}`,
      tone: "warning",
    };
  }
  if (action === "sheriff_badge") {
    if (choice === "destroy" || choice === "撕毁") {
      return {
        ...base,
        text: "警徽撕毁",
        detail: "警徽被撕毁",
        tone: "warning",
      };
    }
    if (!choice) {
      return null;
    }
    return {
      ...base,
      text: `警徽移交 ${targetSeat}`,
      detail: `警徽移交给 ${targetSeat}`,
      tone: "success",
    };
  }
  return null;
}

function stateUpdatedReplayText(
  event: LiveGameEvent,
  payload: Record<string, unknown>,
  nameToSeat: Map<string, number>,
): string | null {
  const exiled = stringField(payload, "exiled");
  if (exiled) {
    return `${seatLabel(exiled, nameToSeat)} 被放逐`;
  }
  if (isNightResolution(event, payload)) {
    return nightResolutionText(payload, nameToSeat);
  }
  const votes = recordField(payload, "votes");
  if (votes) {
    return voteTallySummary(votes, recordField(payload, "vote_weights"), nameToSeat);
  }
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    return `${seatLabel(debateEntry.speaker, nameToSeat)} 发言`;
  }
  const winner = stringField(payload, "winner");
  if (winner) {
    return `胜负已更新：${winner}`;
  }
  const selfExploded = stringField(payload, "werewolf_self_exploded");
  if (selfExploded) {
    return `${seatLabel(selfExploded, nameToSeat)} 狼人自爆`;
  }
  const hunterShot = stringField(payload, "hunter_shot");
  if (hunterShot) {
    return `猎人带走 ${seatLabel(hunterShot, nameToSeat)}`;
  }
  const idiotRevealed = stringField(payload, "idiot_revealed");
  if (idiotRevealed) {
    return `${seatLabel(idiotRevealed, nameToSeat)} 白痴翻牌`;
  }
  const badgeTarget = stringField(payload, "sheriff_badge_target");
  if (badgeTarget) {
    return `警徽移交 ${seatLabel(badgeTarget, nameToSeat)}`;
  }
  if (payload.sheriff_badge_lost === true) {
    return "警徽撕毁";
  }
  return null;
}

function stateUpdatedReplayDetail(
  event: LiveGameEvent,
  payload: Record<string, unknown>,
  nameToSeat: Map<string, number>,
): string {
  const exiled = stringField(payload, "exiled");
  if (exiled) {
    return `${seatLabel(exiled, nameToSeat)} 被投票放逐`;
  }
  if (isNightResolution(event, payload)) {
    return nightResolutionDetail(payload, nameToSeat);
  }
  const votes = recordField(payload, "votes");
  if (votes) {
    return voteTallyDetail(votes, recordField(payload, "vote_weights"), nameToSeat);
  }
  return stateUpdatedReplayText(event, payload, nameToSeat) ?? "";
}

function isNightResolution(
  event: LiveGameEvent,
  payload: Record<string, unknown>,
): boolean {
  if (event.phase === "night") {
    return Boolean(
      stringField(payload, "attacked") ||
        stringField(payload, "eliminated") ||
        stringField(payload, "poisoned") ||
        stringField(payload, "protected") ||
        stringField(payload, "saved_by_witch") ||
        Array.isArray(payload.night_deaths),
    );
  }
  return Boolean(stringField(payload, "eliminated")) && !recordField(payload, "votes");
}

function nightResolutionText(
  payload: Record<string, unknown>,
  nameToSeat: Map<string, number>,
): string {
  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  const eliminated = stringField(payload, "eliminated");
  const poisoned = stringField(payload, "poisoned");
  const savedByWitch = stringField(payload, "saved_by_witch");
  const nightDeaths = stringArrayField(payload, "night_deaths");

  const deaths: string[] = [];
  if (eliminated) {
    deaths.push(`${seatLabel(eliminated, nameToSeat)} 夜晚死亡`);
  }
  if (poisoned && poisoned !== eliminated) {
    deaths.push(`${seatLabel(poisoned, nameToSeat)} 被毒杀`);
  }
  for (const death of nightDeaths) {
    if (death !== eliminated && death !== poisoned) {
      deaths.push(`${seatLabel(death, nameToSeat)} 夜晚死亡`);
    }
  }

  if (deaths.length > 0) {
    return deaths.join("，");
  }
  if (
    attacked ||
    savedByWitch ||
    protectedPlayer ||
    Array.isArray(payload.night_deaths)
  ) {
    return "平安夜";
  }
  return "局势更新";
}

function nightResolutionDetail(
  payload: Record<string, unknown>,
  nameToSeat: Map<string, number>,
): string {
  const text = nightResolutionText(payload, nameToSeat);
  if (text === "平安夜") {
    const attacked = stringField(payload, "attacked");
    const savedByWitch = stringField(payload, "saved_by_witch");
    const protectedPlayer = stringField(payload, "protected");
    const saved = attacked && (protectedPlayer === attacked || savedByWitch === attacked);
    return saved && attacked
      ? `${seatLabel(attacked, nameToSeat)} 被袭击，被守护或解药救下，无人出局`
      : "昨夜平安无事";
  }
  return text;
}

function voteTallySummary(
  votes: Record<string, unknown>,
  weights: Record<string, unknown> | null,
  nameToSeat: Map<string, number>,
): string {
  const tallies = computeTallies(votes, weights);
  if (tallies.length === 0) {
    return "投票结果更新";
  }
  const topCount = tallies[0].count;
  const tied = tallies.filter((entry) => entry.count === topCount);
  if (tied.length > 1) {
    return `平票 · ${tied
      .map((entry) => `${seatLabel(entry.target, nameToSeat)} ${formatVoteCount(entry.count)}票`)
      .join(" / ")}`;
  }
  return `${seatLabel(tallies[0].target, nameToSeat)} ${formatVoteCount(topCount)}票`;
}

function voteTallyDetail(
  votes: Record<string, unknown>,
  weights: Record<string, unknown> | null,
  nameToSeat: Map<string, number>,
): string {
  const tallies = computeTallies(votes, weights);
  if (tallies.length === 0) {
    return "投票结果更新";
  }
  return tallies
    .map(
      (entry) =>
        `${seatLabel(entry.target, nameToSeat)} ${formatVoteCount(entry.count)}票`,
    )
    .join("，");
}

type ComputedTally = {
  target: string;
  count: number;
  voters: string[];
};

function computeTallies(
  votes: Record<string, unknown>,
  weights: Record<string, unknown> | null,
): ComputedTally[] {
  const tallies = new Map<string, ComputedTally>();
  for (const [voter, target] of Object.entries(votes)) {
    if (typeof target !== "string") {
      continue;
    }
    const weight =
      weights && typeof weights[voter] === "number"
        ? (weights[voter] as number)
        : 1;
    const entry =
      tallies.get(target) ??
      tallies.set(target, { target, count: 0, voters: [] }).get(target)!;
    entry.count += weight;
    entry.voters.push(voter);
  }
  return Array.from(tallies.values()).sort(
    (a, b) => b.count - a.count || a.target.localeCompare(b.target),
  );
}

function formatVoteCount(value: number) {
  const rounded = Number(value.toFixed(2));
  return String(rounded);
}

function seatLabel(name: string, nameToSeat: Map<string, number>): string {
  const seat = nameToSeat.get(name) ?? seatNumberFromReference(name);
  return seat ? `${seat}号` : name;
}

function seatNumberFromReference(value: string): number | null {
  const match = value.trim().match(/^(\d+)\s*号/);
  if (!match) {
    return null;
  }
  const seat = Number(match[1]);
  return Number.isInteger(seat) && seat > 0 ? seat : null;
}

function stateUpdatedReplayTone(
  payload: Record<string, unknown>,
): GodViewEventLine["tone"] {
  if (stringField(payload, "exiled") || stringField(payload, "eliminated")) {
    return "danger";
  }
  if (stringField(payload, "poisoned")) {
    return "danger";
  }
  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  if (attacked && protectedPlayer === attacked) {
    return "success";
  }
  if (stringField(payload, "saved_by_witch")) {
    return "success";
  }
  if (recordField(payload, "votes")) {
    return "warning";
  }
  if (stringField(payload, "werewolf_self_exploded")) {
    return "danger";
  }
  if (
    stringField(payload, "hunter_shot") ||
    payload.sheriff_badge_lost === true
  ) {
    return "warning";
  }
  if (
    stringField(payload, "idiot_revealed") ||
    stringField(payload, "sheriff_badge_target")
  ) {
    return "info";
  }
  return "default";
}

function buildNameToSeat(players: { name: string }[]): Map<string, number> {
  const map = new Map<string, number>();
  players.forEach((player, index) => {
    if (player && typeof player.name === "string") {
      map.set(player.name, index + 1);
    }
  });
  return map;
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
  if (
    event.type === "game_completed" ||
    event.type === "game_failed" ||
    event.type === "game_canceled"
  ) {
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
    if (player.exitKind === "night") {
      return { kind: "out", label: "夜晚出局" };
    }
    if (player.exitKind === "day-exile") {
      return { kind: "out", label: "白天放逐" };
    }
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
