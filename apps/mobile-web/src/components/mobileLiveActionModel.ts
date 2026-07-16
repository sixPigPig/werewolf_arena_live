import type {
  GodViewPlayer,
  GodViewState,
  LiveGameEvent,
} from "@werewolf-arena/game-client";

export type MobileLiveFocusKind =
  | "waiting"
  | "speech"
  | "night-action"
  | "night-result"
  | "vote-action"
  | "vote-result"
  | "skill"
  | "terminal";

export type MobileLiveFocusTone =
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "danger";

export type MobileLiveFocusPresentation = {
  eventId: number | null;
  kind: MobileLiveFocusKind;
  tone: MobileLiveFocusTone;
  actorName: string | null;
  actorSeat: number | null;
  actorRole: string | null;
  targetName: string | null;
  eyebrow: string;
  title: string;
  detail: string;
  progress: string | null;
  accessibleText: string;
};

const ACTIVE_ACTOR_KINDS = new Set<GodViewPlayer["stageStatus"]["kind"]>([
  "preparing-speech",
  "speaking",
  "voting",
  "acting",
  "summarizing",
]);

const SPEECH_ACTIONS = new Set([
  "debate",
  "sheriff_speech",
  "sheriff_pk_speech",
  "summarize",
]);

export function getActiveTheaterPlayer(
  state: GodViewState,
): GodViewPlayer | null {
  const speaker = state.speakerFlow.current;
  if (speaker && speaker.isAlive && ACTIVE_ACTOR_KINDS.has(speaker.stageStatus.kind)) {
    return speaker;
  }
  for (const player of state.players) {
    if (player.isAlive && ACTIVE_ACTOR_KINDS.has(player.stageStatus.kind)) {
      return player;
    }
  }
  return null;
}

export function deriveMobileLiveFocusPresentation(
  currentEvent: LiveGameEvent | null,
  state: GodViewState,
): MobileLiveFocusPresentation {
  if (!currentEvent) {
    return waitingPresentation(null, "等待对局进展");
  }

  const event = currentEvent;
  const payload = isRecord(event.payload) ? event.payload : {};

  if (
    event.type === "game_completed" ||
    event.type === "game_failed" ||
    event.type === "game_canceled"
  ) {
    return terminalPresentation(event, payload);
  }

  if (isSpeechAction(event.action) && isSpeechEventType(event.type)) {
    return speechPresentation(event, state);
  }

  const lifecycle = lifecyclePresentation(event);
  if (lifecycle) {
    return lifecycle;
  }

  if (event.type === "phase_started") {
    return phaseStartPresentation(event, state);
  }

  if (event.type === "judge_cue") {
    const visibleText = stringField(payload, "visible_text") || "请听法官提示";
    const target = stringField(payload, "target");
    const cueId = stringField(payload, "cue_id") || event.action || "";
    const params = recordField(payload, "params");
    const pendingActors = params ? stringArrayField(params, "pending_actors") : [];
    const interrupted = cueId === "self_explosion_skip";
    return {
      eventId: event.id,
      kind: interrupted ? "skill" : event.phase === "night" ? "night-action" : "waiting",
      tone:
        event.action === "witch_death" || interrupted || cueId === "exile_result"
          ? "danger"
          : "neutral",
      actorName: "法官",
      actorSeat: null,
      actorRole: null,
      targetName: target ? canonicalPlayerName(target, state) : null,
      eyebrow: "法官提示",
      title: visibleText,
      detail: interrupted
        ? `剩余 ${pendingActors.length} 名玩家未发言，放逐投票取消`
        : event.phase === "night"
          ? "夜间流程"
          : "白天流程",
      progress: null,
      accessibleText: visibleText,
    };
  }

  if (
    event.type === "action_requested" ||
    isModelActionProgressEvent(event.type)
  ) {
    return actionRequestedPresentation(event, state, payload);
  }

  if (event.type === "action_parsed") {
    return actionParsedPresentation(event, state, payload);
  }

  if (event.type === "state_updated") {
    return stateUpdatedPresentation(event, state, payload);
  }

  return waitingPresentation(event.id, "等待对局进展");
}

function lifecyclePresentation(
  event: LiveGameEvent,
): MobileLiveFocusPresentation | null {
  if (event.type === "game_started") {
    return {
      eventId: event.id,
      kind: "waiting",
      tone: "neutral",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: null,
      eyebrow: "开局",
      title: "对局开始",
      detail: "",
      progress: null,
      accessibleText: "对局开始",
    };
  }
  if (event.type === "round_started") {
    return {
      eventId: event.id,
      kind: "waiting",
      tone: "neutral",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: null,
      eyebrow: "回合",
      title: event.round === null ? "新回合开始" : `第 ${event.round} 轮开始`,
      detail: "",
      progress: null,
      accessibleText:
        event.round === null ? "新回合开始" : `第 ${event.round} 轮开始`,
    };
  }
  if (event.type === "run_created" || event.type === "run_started") {
    return waitingPresentation(event.id, "对局准备中");
  }
  return null;
}

function phaseStartPresentation(
  event: LiveGameEvent,
  state: GodViewState,
): MobileLiveFocusPresentation {
  const round = event.round;
  const roundLabel = round === null ? "" : `第 ${round} ${event.phase === "night" ? "夜" : "天"}`;

  if (event.phase === "night") {
    return {
      eventId: event.id,
      kind: "night-action",
      tone: "neutral",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: null,
      eyebrow: roundLabel || "夜间行动",
      title: "夜间行动开始",
      detail: "夜幕降临",
      progress: null,
      accessibleText: `${roundLabel || "夜间"}行动开始`,
    };
  }

  if (event.phase === "vote") {
    const alive = state.progress.totalAlive;
    const voted = countVotedPlayers(state);
    return {
      eventId: event.id,
      kind: "vote-action",
      tone: "warning",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: null,
      eyebrow: "白天投票",
      title: "白天投票开始",
      detail: "",
      progress: `${voted}/${alive}`,
      accessibleText: `白天投票开始，当前 ${voted}/${alive}`,
    };
  }

  if (event.phase === "day") {
    return {
      eventId: event.id,
      kind: "speech",
      tone: "neutral",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: null,
      eyebrow: "白天发言",
      title: "白天发言开始",
      detail: "",
      progress: null,
      accessibleText: "白天发言开始",
    };
  }

  if (event.phase === "summary") {
    return waitingPresentation(event.id, "结算阶段开始");
  }

  return waitingPresentation(event.id, "阶段开始");
}

function actionRequestedPresentation(
  event: LiveGameEvent,
  state: GodViewState,
  payload: Record<string, unknown>,
): MobileLiveFocusPresentation {
  const action = event.action;
  const base = {
    eventId: event.id,
    targetName: null as string | null,
    progress: null as string | null,
  };

  if (action === "remove" || action === "eliminate") {
    return {
      ...base,
      kind: "night-action",
      tone: "danger",
      actorName: "狼人阵营",
      actorSeat: null,
      actorRole: null,
      eyebrow: "狼人阵营",
      title: "正在选择袭击目标",
      detail: "夜间行动中",
      accessibleText: "狼人阵营正在选择袭击目标",
    };
  }

  if (action === "protect" || action === "guard") {
    return singleActorNight(event, state, payload, "守卫", "正在选择守护目标", "success");
  }
  if (action === "investigate") {
    return singleActorNight(event, state, payload, "预言家", "正在选择查验目标", "info");
  }
  if (action === "witch_save") {
    return singleActorNight(event, state, payload, "女巫", "正在决定是否使用解药", "neutral");
  }
  if (action === "witch_poison") {
    return singleActorNight(event, state, payload, "女巫", "正在决定是否使用毒药", "neutral");
  }

  if (action === "vote" || action === "sheriff_vote" || action === "sheriff_runoff_vote") {
    const actor = resolveActor(event, state);
    const voted = countVotedPlayers(state);
    const alive = state.progress.totalAlive;
    return {
      ...base,
      kind: "vote-action",
      tone: "warning",
      actorName: actor.name,
      actorSeat: actor.seat,
      actorRole: actor.role,
      eyebrow: "白天投票",
      title: "等待投票",
      detail: `${voted}/${alive}`,
      progress: `${voted}/${alive}`,
      accessibleText: `${actor.label}等待投票，当前 ${voted}/${alive}`,
    };
  }

  if (action === "sheriff_badge") {
    return {
      ...base,
      kind: "skill",
      tone: "warning",
      actorName: resolveActor(event, state).name,
      actorSeat: null,
      actorRole: null,
      eyebrow: "警徽",
      title: "正在移交警徽",
      detail: "",
      accessibleText: "正在移交警徽",
    };
  }

  if (action === "sheriff_run") {
    return sheriffRunPresentation(event, state);
  }

  if (isSpeechAction(action)) {
    return speechPresentation(event, state);
  }

  const actor = resolveActor(event, state);
  const title = genericActionTitle(action);
  return {
    ...base,
    kind:
      event.phase === "night"
        ? "night-action"
        : event.phase === "vote"
          ? "vote-action"
          : "waiting",
    tone: "neutral",
    actorName: actor.name,
    actorSeat: actor.seat,
    actorRole: actor.role,
    eyebrow: event.phase === "night" ? "夜间行动" : "玩家行动",
    title,
    detail: "行动中",
    accessibleText: `${actor.label}${title}`,
  };
}

function singleActorNight(
  event: LiveGameEvent,
  state: GodViewState,
  _payload: Record<string, unknown>,
  roleLabel: string,
  title: string,
  tone: MobileLiveFocusTone,
): MobileLiveFocusPresentation {
  const actor = resolveActor(event, state);
  return {
    eventId: event.id,
    kind: "night-action",
    tone,
    actorName: actor.name,
    actorSeat: actor.seat,
    actorRole: actor.role ?? roleLabel,
    targetName: null,
    eyebrow: roleLabel,
    title,
    detail: "夜间行动中",
    progress: null,
    accessibleText: `${actor.label}${title}`,
  };
}

function actionParsedPresentation(
  event: LiveGameEvent,
  state: GodViewState,
  payload: Record<string, unknown>,
): MobileLiveFocusPresentation {
  const action = event.action;
  const base = {
    eventId: event.id,
    progress: null as string | null,
  };

  if (action === "sheriff_run") {
    return sheriffRunPresentation(event, state);
  }

  if (action === "werewolf_kill_vote") {
    const choice = readChoice(payload);
    if (!choice) {
      return malformedNight(event, state, "狼人刀票");
    }
    const actor = resolveActor(event, state);
    const seat = seatLabel(choice, state);
    const voteRound = integerField(payload, "vote_round");
    const roundLabel = voteRound > 1 ? `第 ${voteRound} 轮 · ` : "";
    return {
      ...base,
      kind: "night-action",
      tone: "danger",
      actorName: actor.name,
      actorSeat: actor.seat,
      actorRole: actor.role ?? "狼人",
      targetName: canonicalPlayerName(choice, state),
      eyebrow: "狼人刀票",
      title: "选择袭击目标",
      detail: `${roundLabel}投 ${seat}号`,
      accessibleText: `${actor.label}${roundLabel}选择袭击 ${seat}号 ${choice}`,
    };
  }

  if (action === "remove" || action === "eliminate") {
    const choice = readChoice(payload);
    if (!choice) {
      return malformedNight(event, state, "狼人最终目标");
    }
    const seat = seatLabel(choice, state);
    return {
      ...base,
      kind: "night-action",
      tone: "danger",
      actorName: "狼人阵营",
      actorSeat: null,
      actorRole: null,
      targetName: canonicalPlayerName(choice, state),
      eyebrow: "狼人阵营",
      title: "狼人最终目标",
      detail: `袭击 ${seat}号`,
      accessibleText: `狼人阵营最终决定袭击 ${seat}号 ${choice}`,
    };
  }

  if (action === "protect" || action === "guard") {
    return witchLikeParsed(event, state, payload, "守卫", "守卫守护", "守护", "success");
  }
  if (action === "investigate") {
    return seerParsed(event, state, payload);
  }
  if (action === "witch_save") {
    return witchParsed(event, state, payload, "女巫解药", "女巫", "救", "success");
  }
  if (action === "witch_poison") {
    return witchParsed(event, state, payload, "女巫毒药", "女巫", "毒", "danger");
  }
  if (action === "vote" || action === "sheriff_vote" || action === "sheriff_runoff_vote") {
    return voteParsed(event, state, payload);
  }

  if (action === "sheriff_badge") {
    const choice = readChoice(payload);
    const destroyed = choice === "destroy" || choice === "撕毁";
    return {
      ...base,
      kind: "skill",
      tone: destroyed ? "warning" : "success",
      actorName: resolveActor(event, state).name,
      actorSeat: null,
      actorRole: null,
      targetName:
        destroyed || !choice ? null : canonicalPlayerName(choice, state),
      eyebrow: "警徽",
      title: destroyed ? "警徽撕毁" : "警徽移交",
      detail: destroyed ? "警徽被撕毁" : choice ? `移交 ${seatLabel(choice, state)}号` : "",
      accessibleText: destroyed ? "警徽被撕毁" : `警徽移交给 ${choice ? seatLabel(choice, state) + "号" : "未知"}`,
    };
  }

  if (isSpeechAction(action)) {
    return speechPresentation(event, state);
  }

  return waitingPresentation(event.id, "等待行动");
}

function sheriffRunPresentation(
  event: LiveGameEvent,
  state: GodViewState,
): MobileLiveFocusPresentation {
  const signUp = state.sheriffSignUp;
  const completed =
    signUp.requestedCount > 0 && signUp.resolvedCount >= signUp.requestedCount;
  const raised = signUp.raised.length ? signUp.raised.join("、") : "无人";
  const progress = `${signUp.resolvedCount}/${signUp.requestedCount}`;
  return {
    eventId: event.id,
    kind: "waiting",
    tone: "warning",
    actorName: null,
    actorSeat: null,
    actorRole: null,
    targetName: null,
    eyebrow: "警长竞选",
    title: completed ? "上警结果" : "正在决定是否上警",
    detail: completed ? `举手上警：${raised}` : `已返回 ${progress}`,
    progress,
    accessibleText: completed
      ? `上警结果，举手上警：${raised}`
      : `正在决定是否上警，已返回 ${progress}`,
  };
}

function witchLikeParsed(
  event: LiveGameEvent,
  state: GodViewState,
  payload: Record<string, unknown>,
  roleLabel: string,
  title: string,
  verb: string,
  tone: MobileLiveFocusTone,
): MobileLiveFocusPresentation {
  const choice = readChoice(payload);
  if (!choice) {
    return malformedNight(event, state, title);
  }
  const seat = seatLabel(choice, state);
  const actor = resolveActor(event, state);
  return {
    eventId: event.id,
    kind: "night-action",
    tone,
    actorName: actor.name,
    actorSeat: actor.seat,
    actorRole: actor.role ?? roleLabel,
    targetName: canonicalPlayerName(choice, state),
    eyebrow: roleLabel,
    title,
    detail: `${verb} ${seat}号`,
    progress: null,
    accessibleText: `${roleLabel}${verb} ${seat}号 ${choice}`,
  };
}

function seerParsed(
  event: LiveGameEvent,
  state: GodViewState,
  payload: Record<string, unknown>,
): MobileLiveFocusPresentation {
  const choice = readChoice(payload);
  if (!choice) {
    return malformedNight(event, state, "预言家查验");
  }
  const seat = seatLabel(choice, state);
  const result = readSeerResult(payload);
  const actor = resolveActor(event, state);
  const detail = result ? `查验 ${seat}号 · ${result}` : `查验 ${seat}号`;
  return {
    eventId: event.id,
    kind: "night-action",
    tone: "info",
    actorName: actor.name,
    actorSeat: actor.seat,
    actorRole: actor.role ?? "预言家",
    targetName: canonicalPlayerName(choice, state),
    eyebrow: "预言家",
    title: "预言家查验",
    detail,
    progress: null,
    accessibleText: `预言家查验 ${seat}号 ${choice}${result ? `，结果 ${result}` : ""}`,
  };
}

function witchParsed(
  event: LiveGameEvent,
  state: GodViewState,
  payload: Record<string, unknown>,
  title: string,
  roleLabel: string,
  verb: string,
  usedTone: MobileLiveFocusTone,
): MobileLiveFocusPresentation {
  const choice = readChoice(payload);
  const actor = resolveActor(event, state);
  if (!choice || choice === "skip") {
    return {
      eventId: event.id,
      kind: "night-action",
      tone: "neutral",
      actorName: actor.name,
      actorSeat: actor.seat,
      actorRole: actor.role ?? roleLabel,
      targetName: null,
      eyebrow: roleLabel,
      title,
      detail: "未使用",
      progress: null,
      accessibleText: `${roleLabel}未使用${title.includes("解药") ? "解药" : "毒药"}`,
    };
  }
  const seat = seatLabel(choice, state);
  return {
    eventId: event.id,
    kind: "night-action",
    tone: usedTone,
    actorName: actor.name,
    actorSeat: actor.seat,
    actorRole: actor.role ?? roleLabel,
    targetName: canonicalPlayerName(choice, state),
    eyebrow: roleLabel,
    title,
    detail: `${verb} ${seat}号`,
    progress: null,
    accessibleText: `${roleLabel}${verb} ${seat}号 ${choice}`,
  };
}

function voteParsed(
  event: LiveGameEvent,
  state: GodViewState,
  payload: Record<string, unknown>,
): MobileLiveFocusPresentation {
  const choice = readChoice(payload);
  const actor = resolveActor(event, state);
  if (!choice) {
    return {
      eventId: event.id,
      kind: "vote-action",
      tone: "neutral",
      actorName: actor.name,
      actorSeat: actor.seat,
      actorRole: actor.role,
      targetName: null,
      eyebrow: "白天投票",
      title: "投票待确认",
      detail: "行动结果待确认",
      progress: null,
      accessibleText: `${actor.label}投票结果待确认`,
    };
  }
  const voterSeat = actor.seat ? `${actor.seat}号` : actor.label;
  const targetSeat = seatLabel(choice, state);
  const voted = countVotedPlayers(state);
  const alive = state.progress.totalAlive;
  return {
    eventId: event.id,
    kind: "vote-action",
    tone: "warning",
    actorName: actor.name,
    actorSeat: actor.seat,
    actorRole: actor.role,
    targetName: canonicalPlayerName(choice, state),
    eyebrow: "白天投票",
    title: `${voterSeat} -> ${targetSeat}号`,
    detail: "已投票",
    progress: `${voted}/${alive}`,
    accessibleText: `${actor.label}投给 ${targetSeat}号 ${choice}，已投票`,
  };
}

function stateUpdatedPresentation(
  event: LiveGameEvent,
  state: GodViewState,
  payload: Record<string, unknown>,
): MobileLiveFocusPresentation {
  const sheriffElection = recordField(payload, "sheriff_election");
  const sheriffElected =
    stringField(payload, "sheriff_elected") ||
    (sheriffElection ? stringField(sheriffElection, "sheriff") : "");
  if (sheriffElected) {
    const sheriff = findPlayer(state, sheriffElected);
    const seat = seatLabel(sheriffElected, state);
    const electionVotes = sheriffElectionVotes(payload, sheriffElected);
    const voteDetail = electionVotes > 0 ? `${electionVotes}票当选 · ` : "";
    return {
      eventId: event.id,
      kind: "skill",
      tone: "success",
      actorName: sheriff?.name ?? sheriffElected,
      actorSeat: sheriff?.seatNumber ?? null,
      actorRole: sheriff?.role ?? null,
      targetName: null,
      eyebrow: "警长竞选",
      title: `${seat}号 当选警长`,
      detail: `${voteDetail}获得警徽`,
      progress: null,
      accessibleText: `${seat}号玩家当选警长，${voteDetail}获得警徽`,
    };
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    const seat = seatLabel(exiled, state);
    const count = tallyCountFor(state, exiled);
    const countText = count !== null ? `${formatCount(count)}票` : "投票放逐";
    return {
      eventId: event.id,
      kind: "vote-result",
      tone: "danger",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: canonicalPlayerName(exiled, state),
      eyebrow: "投票结算",
      title: `${seat}号 被放逐`,
      detail: countText,
      progress: null,
      accessibleText: `${seat}号被放逐，${countText}`,
    };
  }

  const skill = readSkillTrigger(event, payload, state);
  if (skill) {
    return skill;
  }

  if (isNightResolutionEvent(event, payload)) {
    return nightResultPresentation(event, state, payload);
  }

  const votes = recordField(payload, "votes");
  if (votes) {
    return voteTallyPresentation(event, state, votes, recordField(payload, "vote_weights"));
  }

  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    const seat = seatLabel(debateEntry.speaker, state);
    return {
      eventId: event.id,
      kind: "speech",
      tone: "neutral",
      actorName: debateEntry.speaker,
      actorSeat: findPlayer(state, debateEntry.speaker)?.seatNumber ?? null,
      actorRole: findPlayer(state, debateEntry.speaker)?.role ?? null,
      targetName: null,
      eyebrow: "公开发言",
      title: `${seat}号 发言`,
      detail: "",
      progress: null,
      accessibleText: `${seat}号发言`,
    };
  }

  const winner = stringField(payload, "winner");
  if (winner) {
    return {
      eventId: event.id,
      kind: "terminal",
      tone: "success",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: null,
      eyebrow: "终局",
      title: `胜负：${winner}`,
      detail: "",
      progress: null,
      accessibleText: `对局完成，${winner}获胜`,
    };
  }

  return waitingPresentation(event.id, "局势更新");
}

function sheriffElectionVotes(
  payload: Record<string, unknown>,
  sheriff: string,
): number {
  const runoffVotes = recordField(payload, "sheriff_runoff_votes");
  const firstRoundVotes = recordField(payload, "sheriff_votes");
  const votes =
    runoffVotes && Object.keys(runoffVotes).length > 0
      ? runoffVotes
      : firstRoundVotes;
  if (!votes) {
    return 0;
  }
  return Object.values(votes).filter((target) => target === sheriff).length;
}

function nightResultPresentation(
  event: LiveGameEvent,
  state: GodViewState,
  payload: Record<string, unknown>,
): MobileLiveFocusPresentation {
  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  const eliminated = stringField(payload, "eliminated");
  const poisoned = stringField(payload, "poisoned");
  const savedByWitch = stringField(payload, "saved_by_witch");
  const nightDeaths = deathPlayerArrayField(payload, "night_deaths");

  const deaths: string[] = [];
  if (eliminated) {
    deaths.push(`${seatLabel(eliminated, state)}号 夜晚死亡`);
  }
  if (poisoned && poisoned !== eliminated) {
    deaths.push(`${seatLabel(poisoned, state)}号 被毒杀`);
  }
  for (const death of nightDeaths) {
    if (death !== eliminated && death !== poisoned) {
      deaths.push(`${seatLabel(death, state)}号 夜晚死亡`);
    }
  }

  const isPeaceful =
    deaths.length === 0 &&
    Boolean(
      attacked ||
        protectedPlayer ||
        savedByWitch ||
        Array.isArray(payload.night_deaths),
    );
  if (isPeaceful) {
    const savedTarget = attacked ?? savedByWitch ?? protectedPlayer;
    const detail = savedTarget
      ? `${seatLabel(savedTarget, state)}号被袭击，被守护或解药救下，无人出局`
      : "昨夜平安无事";
    return {
      eventId: event.id,
      kind: "night-result",
      tone: "success",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: null,
      eyebrow: "夜间结算",
      title: "平安夜",
      detail,
      progress: null,
      accessibleText: "昨夜平安夜",
    };
  }

  if (deaths.length > 0) {
    const target = eliminated ?? poisoned ?? null;
    return {
      eventId: event.id,
      kind: "night-result",
      tone: "danger",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: target ? canonicalPlayerName(target, state) : null,
      eyebrow: "夜间结算",
      title: deaths[0],
      detail: deaths.length > 1 ? deaths.slice(1).join("，") : "昨夜结算",
      progress: null,
      accessibleText: `昨夜${deaths.join("，")}`,
    };
  }

  return waitingPresentation(event.id, "夜间结算");
}

function voteTallyPresentation(
  event: LiveGameEvent,
  state: GodViewState,
  votes: Record<string, unknown>,
  weights: Record<string, unknown> | null,
): MobileLiveFocusPresentation {
  const tallies = computeTallies(votes, weights);
  if (tallies.length === 0) {
    return waitingPresentation(event.id, "投票结果更新");
  }
  const topCount = tallies[0].count;
  const tied = tallies.filter((entry) => entry.count === topCount);
  const top3 = tallies.slice(0, 3);
  const detailParts = top3.map(
    (entry) => `${seatLabel(entry.target, state)}号 ${formatCount(entry.count)}票`,
  );
  const isTie = tied.length > 1;
  const title = isTie
    ? "平票"
    : `${seatLabel(tallies[0].target, state)}号 领先 ${formatCount(topCount)}票`;
  const detail = detailParts.join(" / ");
  return {
    eventId: event.id,
    kind: "vote-result",
    tone: "warning",
    actorName: null,
    actorSeat: null,
    actorRole: null,
    targetName: canonicalPlayerName(tallies[0].target, state),
    eyebrow: "投票结果",
    title,
    detail,
    progress: null,
    accessibleText: `${isTie ? "平票，" : ""}${detailParts.join("，")}`,
  };
}

function readSkillTrigger(
  event: LiveGameEvent,
  payload: Record<string, unknown>,
  state: GodViewState,
): MobileLiveFocusPresentation | null {
  const selfExploded = stringField(payload, "werewolf_self_exploded");
  if (selfExploded) {
    const seat = seatLabel(selfExploded, state);
    return {
      eventId: event.id,
      kind: "skill",
      tone: "danger",
      actorName: selfExploded,
      actorSeat: findPlayer(state, selfExploded)?.seatNumber ?? null,
      actorRole: "狼人",
      targetName: canonicalPlayerName(selfExploded, state),
      eyebrow: "技能",
      title: "狼人自爆",
      detail: `${seat}号 发动自爆`,
      progress: null,
      accessibleText: `${seat}号发动自爆`,
    };
  }
  const hunterShot = stringField(payload, "hunter_shot");
  if (hunterShot) {
    const actor = resolveActor(event, state);
    const targetSeat = seatLabel(hunterShot, state);
    return {
      eventId: event.id,
      kind: "skill",
      tone: "warning",
      actorName: actor.name,
      actorSeat: actor.seat,
      actorRole: actor.role ?? "猎人",
      targetName: canonicalPlayerName(hunterShot, state),
      eyebrow: "技能",
      title: "猎人带走",
      detail: `${actor.label}带走 ${targetSeat}号`,
      progress: null,
      accessibleText: `${actor.label}带走 ${targetSeat}号 ${hunterShot}`,
    };
  }
  const idiotRevealed = stringField(payload, "idiot_revealed");
  if (idiotRevealed) {
    const seat = seatLabel(idiotRevealed, state);
    return {
      eventId: event.id,
      kind: "skill",
      tone: "info",
      actorName: idiotRevealed,
      actorSeat: findPlayer(state, idiotRevealed)?.seatNumber ?? null,
      actorRole: "白痴",
      targetName: canonicalPlayerName(idiotRevealed, state),
      eyebrow: "技能",
      title: "白痴翻牌",
      detail: `${seat}号 留在场上`,
      progress: null,
      accessibleText: `${seat}号翻牌留在场上`,
    };
  }
  const badgeResolution = recordField(payload, "sheriff_badge");
  const badgeTarget =
    stringField(payload, "sheriff_badge_target") ||
    (badgeResolution ? stringField(badgeResolution, "to_player") : "");
  if (badgeTarget) {
    const seat = seatLabel(badgeTarget, state);
    return {
      eventId: event.id,
      kind: "skill",
      tone: "success",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: canonicalPlayerName(badgeTarget, state),
      eyebrow: "警徽",
      title: "警徽移交",
      detail: `移交给 ${seat}号`,
      progress: null,
      accessibleText: `警徽移交给 ${seat}号`,
    };
  }
  const badgeOutcome = badgeResolution
    ? stringField(badgeResolution, "outcome")
    : "";
  const electionOutcome = recordField(payload, "sheriff_election");
  if (
    payload.sheriff_badge_lost === true ||
    badgeOutcome === "destroyed" ||
    badgeOutcome === "lost_no_target" ||
    (electionOutcome && stringField(electionOutcome, "outcome") === "badge_lost")
  ) {
    const destroyed = badgeOutcome === "destroyed";
    return {
      eventId: event.id,
      kind: "skill",
      tone: "warning",
      actorName: null,
      actorSeat: null,
      actorRole: null,
      targetName: null,
      eyebrow: "警徽",
      title: destroyed ? "警徽撕毁" : "警徽流失",
      detail: destroyed ? "警徽被撕毁" : "本局不再产生警长",
      progress: null,
      accessibleText: destroyed ? "警徽被撕毁" : "警徽流失",
    };
  }
  return null;
}

function terminalPresentation(
  event: LiveGameEvent,
  payload: Record<string, unknown>,
): MobileLiveFocusPresentation {
  const winner = stringField(payload, "winner");
  const isError = event.type === "game_failed" || event.type === "game_canceled";
  return {
    eventId: event.id,
    kind: "terminal",
    tone: isError ? "danger" : "success",
    actorName: null,
    actorSeat: null,
    actorRole: null,
    targetName: null,
    eyebrow: "终局",
    title: isError ? "对局中断" : "对局完成",
    detail: winner ? `胜利阵营：${winner}` : "",
    progress: null,
    accessibleText: winner
      ? `对局完成，${winner}获胜`
      : isError
        ? "对局中断"
        : "对局完成",
  };
}

function speechPresentation(
  event: LiveGameEvent,
  state: GodViewState,
): MobileLiveFocusPresentation {
  const actor = resolveActor(event, state);
  const label = speechLabel(event.action);
  const actorLabel = speechActorLabel(actor);
  return {
    eventId: event.id,
    kind: "speech",
    tone: "info",
    actorName: actor.name,
    actorSeat: actor.seat,
    actorRole: actor.role,
    targetName: null,
    eyebrow: label,
    title: actor.name ? `${actorLabel}${label}` : label,
    detail: "",
    progress: null,
    accessibleText: `${actorLabel}${label}`,
  };
}

function speechActorLabel(actor: ResolvedActor): string {
  if (actor.name && seatNumberFromReference(actor.name) !== null) {
    return actor.name;
  }
  return actor.label;
}

function speechLabel(action: string | null): string {
  if (action === "sheriff_speech") {
    return "警长竞选发言";
  }
  if (action === "sheriff_pk_speech") {
    return "警长竞选 PK 发言";
  }
  return "白天发言";
}

function waitingPresentation(
  eventId: number | null,
  title: string,
): MobileLiveFocusPresentation {
  return {
    eventId,
    kind: "waiting",
    tone: "neutral",
    actorName: null,
    actorSeat: null,
    actorRole: null,
    targetName: null,
    eyebrow: "待命",
    title,
    detail: "",
    progress: null,
    accessibleText: title,
  };
}

function malformedNight(
  event: LiveGameEvent,
  state: GodViewState,
  title: string,
): MobileLiveFocusPresentation {
  const actor = resolveActor(event, state);
  return malformedNightFull(event, title, actor);
}

function malformedNightFull(
  event: LiveGameEvent,
  title: string,
  actor: ResolvedActor,
): MobileLiveFocusPresentation {
  const actorName = actor.name ?? "未知行动者";
  return {
    eventId: event.id,
    kind: "night-action",
    tone: "neutral",
    actorName,
    actorSeat: actor.seat,
    actorRole: actor.role,
    targetName: null,
    eyebrow: title,
    title,
    detail: "行动结果待确认",
    progress: null,
    accessibleText: `${actor.label}${title}待确认`,
  };
}

type ResolvedActor = {
  name: string | null;
  seat: number | null;
  role: string | null;
  label: string;
};

function resolveActor(
  event: LiveGameEvent,
  state: GodViewState,
): ResolvedActor {
  const actorName = event.actor;
  if (!actorName) {
    return { name: null, seat: null, role: null, label: "未知行动者" };
  }
  const player = findPlayer(state, actorName);
  if (!player) {
    return { name: actorName, seat: null, role: null, label: actorName };
  }
  return {
    name: player.name,
    seat: player.seatNumber,
    role: player.role,
    label: `${player.seatNumber}号 ${player.name}`,
  };
}

function findPlayer(
  state: GodViewState,
  name: string | null,
): GodViewPlayer | undefined {
  if (!name) {
    return undefined;
  }
  const normalized = name.trim();
  const exact = state.players.find((player) => player.name === normalized);
  if (exact) {
    return exact;
  }
  const seatNumber = seatNumberFromReference(normalized);
  if (seatNumber !== null) {
    return state.players.find((player) => player.seatNumber === seatNumber);
  }
  return state.players.find(
    (player) => stripSeatPrefix(player.name) === stripSeatPrefix(normalized),
  );
}

function seatLabel(name: string, state: GodViewState): string {
  const player = findPlayer(state, name);
  if (player) {
    return String(player.seatNumber);
  }
  const seatNumber = seatNumberFromReference(name);
  return seatNumber === null ? name : String(seatNumber);
}

function canonicalPlayerName(name: string, state: GodViewState): string {
  return findPlayer(state, name)?.name ?? name;
}

function seatNumberFromReference(value: string): number | null {
  const match = value.trim().match(/^(\d+)\s*号/);
  if (!match) {
    return null;
  }
  const seatNumber = Number(match[1]);
  return Number.isInteger(seatNumber) && seatNumber > 0 ? seatNumber : null;
}

function stripSeatPrefix(value: string): string {
  return value.trim().replace(/^\d+\s*号\s*/, "").replace(/玩家$/, "").trim();
}

function countVotedPlayers(state: GodViewState): number {
  return state.players.filter(
    (player) => player.voteTarget !== null && player.voteTarget !== "",
  ).length;
}

function tallyCountFor(
  state: GodViewState,
  targetName: string,
): number | null {
  const tally = state.vote.tallies.find((entry) => entry.target === targetName);
  return tally ? tally.count : null;
}

function readChoice(payload: Record<string, unknown>): string | null {
  const direct = stringField(payload, "choice");
  if (direct) {
    return direct;
  }
  const result = payload.result;
  if (isRecord(result)) {
    for (const field of ["target", "choice", "player", "vote"]) {
      const value = result[field];
      if (typeof value === "string") {
        return value;
      }
    }
  }
  return null;
}

function readSeerResult(payload: Record<string, unknown>): string | null {
  const result = payload.result;
  if (!isRecord(result)) {
    return null;
  }
  const alignment = stringField(result, "alignment") || stringField(result, "result");
  if (!alignment) {
    return null;
  }
  const normalized = normalizeRole(alignment);
  return normalized;
}

function normalizeRole(role: string): string {
  const lower = role.toLowerCase();
  const map: Record<string, string> = {
    werewolf: "狼人",
    villager: "好人",
    seer: "预言家",
    guard: "守卫",
    doctor: "医生",
    witch: "女巫",
    hunter: "猎人",
    idiot: "白痴",
    good: "好人",
    evil: "狼人",
  };
  return map[lower] ?? role;
}

function computeTallies(
  votes: Record<string, unknown>,
  weights: Record<string, unknown> | null,
): Array<{ target: string; count: number; voters: string[] }> {
  const tallies = new Map<string, { target: string; count: number; voters: string[] }>();
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

function formatCount(value: number): string {
  return String(Number(value.toFixed(2)));
}

function isNightResolutionEvent(
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

function isSpeechAction(action: string | null): boolean {
  return Boolean(action) && SPEECH_ACTIONS.has(action as string);
}

function isSpeechEventType(type: string): boolean {
  return (
    type === "action_requested" ||
    type === "model_request_started" ||
    type === "model_thinking_tick" ||
    type === "model_response_delta" ||
    type === "model_response_received"
  );
}

function isModelActionProgressEvent(type: string): boolean {
  return (
    type === "model_request_started" ||
    type === "model_thinking_tick" ||
    type === "model_response_delta" ||
    type === "model_response_received"
  );
}

function genericActionTitle(action: string | null): string {
  const labels: Record<string, string> = {
    hunter_shoot: "正在选择猎人目标",
    sheriff_run: "正在选择是否上警",
    sheriff_withdraw: "正在选择是否退水",
    werewolf_self_explosion: "正在决定是否自爆",
  };
  return action ? labels[action] ?? "正在行动" : "正在行动";
}

function stringField(payload: Record<string, unknown>, field: string): string {
  const value = payload[field];
  return typeof value === "string" ? value : "";
}

function integerField(payload: Record<string, unknown>, field: string): number {
  const value = payload[field];
  return typeof value === "number" && Number.isInteger(value) ? value : 0;
}

function stringArrayField(
  payload: Record<string, unknown>,
  field: string,
): string[] {
  const value = payload[field];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function deathPlayerArrayField(
  payload: Record<string, unknown>,
  field: string,
): string[] {
  const value = payload[field];
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (typeof item === "string") {
        return item;
      }
      return isRecord(item) && typeof item.player === "string" ? item.player : "";
    })
    .filter(Boolean);
}

function recordField(
  payload: Record<string, unknown>,
  field: string,
): Record<string, unknown> | null {
  const value = payload[field];
  return isRecord(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
