import type {
  BidEntry,
  DebugItem,
  GameReplay,
  GameRound,
  RawActionLog,
  RawGameReplayResponse,
  RawRoundState,
  RawRoundLog,
  VoteEntry,
} from "../types";
import { isSelfBadgeTransfer } from "../sheriffBadgeDisplay";

const ACTION_TITLES: Record<string, string> = {
  remove: "狼人击杀",
  werewolf_discuss: "狼人夜聊",
  werewolf_kill_vote: "狼刀投票",
  protect: "守卫保护",
  investigate: "预言家查验",
  witch_save: "女巫解药",
  witch_poison: "女巫毒药",
  hunter_shoot: "猎人开枪",
  sheriff_run: "上警选择",
  sheriff_speech: "警上发言",
  sheriff_withdraw: "退水选择",
  sheriff_vote: "警下投票",
  sheriff_pk_speech: "PK 发言",
  sheriff_runoff_vote: "警下二轮投票",
  werewolf_self_explosion: "狼人自爆",
  speech_order: "发言方向",
  sheriff_badge: "警徽处理",
  bid: "发言竞价",
  debate: "白天发言",
  vote: "放逐投票",
  summarize: "轮次总结",
};

export function normalizeGameReplay(
  response: RawGameReplayResponse,
): GameReplay {
  return {
    sessionId: response.session_id,
    status: response.status,
    winner: response.state.winner,
    errorMessage: response.state.error_message,
    ruleSet: response.state.rule_set ?? null,
    sheriff: response.state.sheriff ?? null,
    sheriffBadgeLost: response.state.sheriff_badge_lost ?? false,
    players: normalizePlayers(response.state.players),
    rounds: response.state.rounds.map(normalizeRound),
    logs: response.logs,
    debugItems: response.logs.flatMap((round) =>
      debugItemsFromRound(
        round,
        response.state.rounds.find(
          (stateRound) => stateRound.number === round.number,
        ),
      ),
    ),
  };
}

function normalizePlayers(players: RawGameReplayResponse["state"]["players"]) {
  return players.map((player) => ({
    ...player,
    personality_id: player.personality_id ?? "balanced",
    personality: player.personality ?? "",
    appearance_id: player.appearance_id ?? "default",
    avatar_prompt: player.avatar_prompt ?? "",
    avatar_image_url: player.avatar_image_url ?? "",
    profile_id: player.profile_id ?? null,
    tags: player.tags ?? [],
  }));
}

function normalizeRound(
  round: RawGameReplayResponse["state"]["rounds"][number],
): GameRound {
  const attacked = round.attacked ?? round.eliminated ?? null;
  const eliminated =
    round.attacked === undefined &&
    round.eliminated !== null &&
    round.eliminated === round.protected
      ? null
      : round.eliminated;
  const nightDeaths =
    round.night_deaths ??
    (eliminated
      ? [{ player: eliminated, cause: "legacy_night_elimination", source: null }]
      : []);
  const dayDeaths =
    round.day_deaths ??
    (round.exiled
      ? [{ player: round.exiled, cause: "legacy_vote_exile", source: null }]
      : []);
  const bidGroups = round.bids.map((entry, index) => {
    const bids = Object.entries(entry).map(([actor, score]) => ({
      actor,
      score,
    }));

    return {
      turn: index + 1,
      speaker: round.debate[index]?.speaker ?? selectedSpeakerFromBids(bids),
      bids,
    };
  });
  const voteWeights = round.vote_weights ?? {};
  const votes = round.votes.flatMap((entry) =>
    Object.entries(entry).map(([voter, target]) => ({
      voter,
      target,
      weight: voteWeights[voter] ?? 1,
    })),
  );
  const totalVoteWeight = votes.reduce((total, vote) => total + vote.weight, 0);

  return {
    ...round,
    attacked,
    eliminated,
    summaries: stringRecord(round.summaries),
    private_summaries: stringRecord(round.private_summaries),
    public_summary:
      typeof round.public_summary === "string" ? round.public_summary : "",
    public_facts: Array.isArray(round.public_facts)
      ? round.public_facts.filter(isRecord).map((fact) => ({
          round_number: Number(fact.round_number ?? 0),
          category: String(fact.category ?? "event"),
          text: String(fact.text ?? ""),
        }))
      : [],
    night_deaths: nightDeaths,
    day_deaths: dayDeaths,
    werewolf_discussion: round.werewolf_discussion ?? [],
    werewolf_vote_rounds: round.werewolf_vote_rounds ?? [],
    saved_by_witch: round.saved_by_witch ?? null,
    poisoned: round.poisoned ?? null,
    hunter_shot: round.hunter_shot ?? null,
    idiot_revealed: round.idiot_revealed ?? null,
    sheriff: round.sheriff ?? null,
    sheriff_candidates: round.sheriff_candidates ?? [],
    sheriff_speech_order: round.sheriff_speech_order ?? [],
    sheriff_speech_direction: round.sheriff_speech_direction ?? null,
    sheriff_speeches: round.sheriff_speeches ?? [],
    sheriff_withdrawn: round.sheriff_withdrawn ?? [],
    sheriff_final_candidates: round.sheriff_final_candidates ?? [],
    sheriff_voters: round.sheriff_voters ?? [],
    sheriff_votes: round.sheriff_votes ?? {},
    sheriff_pk_candidates: round.sheriff_pk_candidates ?? [],
    sheriff_pk_speeches: round.sheriff_pk_speeches ?? [],
    sheriff_runoff_votes: round.sheriff_runoff_votes ?? {},
    sheriff_elected: round.sheriff_elected ?? null,
    speech_order: round.speech_order ?? [],
    speech_order_choice: round.speech_order_choice ?? null,
    vote_weights: voteWeights,
    sheriff_badge_target: round.sheriff_badge_target ?? null,
    sheriff_badge_lost: round.sheriff_badge_lost ?? false,
    werewolf_self_exploded: round.werewolf_self_exploded ?? null,
    day_ended_by_self_explosion: round.day_ended_by_self_explosion ?? false,
    sheriff_pre_election_bomb_count:
      round.sheriff_pre_election_bomb_count ?? 0,
    sheriff_election_pending: round.sheriff_election_pending ?? false,
    sheriff_badge_lost_reason: round.sheriff_badge_lost_reason ?? null,
    bids: bidGroups.flatMap((group) => group.bids),
    bidGroups,
    votes,
    voteTally: tallyVotes(votes),
    voteCount: totalVoteWeight,
    voteMajorityThreshold: minimumWinningVoteWeight(votes),
  };
}

function selectedSpeakerFromBids(bids: BidEntry[]) {
  return (
    [...bids].sort((a, b) => b.score - a.score || a.actor.localeCompare(b.actor))[0]
      ?.actor ?? null
  );
}

function tallyVotes(votes: VoteEntry[]) {
  const counts = new Map<string, number>();
  votes.forEach(({ target, weight }) => {
    counts.set(target, (counts.get(target) ?? 0) + weight);
  });

  return Array.from(counts.entries())
    .map(([target, count]) => ({ target, count }))
    .sort((a, b) => b.count - a.count || a.target.localeCompare(b.target));
}

function minimumWinningVoteWeight(votes: VoteEntry[]): number | null {
  const totalVoteWeight = votes.reduce((total, vote) => total + vote.weight, 0);
  if (totalVoteWeight === 0) {
    return null;
  }

  const majority = totalVoteWeight / 2;
  const reachableWeights = new Set<number>([0]);
  votes.forEach(({ weight }) => {
    Array.from(reachableWeights).forEach((sum) => {
      reachableWeights.add(sum + weight);
    });
  });

  return (
    Array.from(reachableWeights)
      .filter((weight) => weight > majority)
      .sort((a, b) => a - b)[0] ?? null
  );
}

function debugItemsFromRound(
  round: RawRoundLog,
  stateRound?: RawRoundState,
): DebugItem[] {
  const items: DebugItem[] = [];
  const sheriffBadge =
    round.sheriff_badge &&
    !isSelfBadgeTransfer(round.sheriff_badge.actor, round.sheriff_badge.choice)
      ? round.sheriff_badge
      : null;
  const sheriffBadgePlacement = sheriffBadge
    ? placementForSheriffBadge(sheriffBadge, stateRound)
    : null;
  const selfExplosion = round.werewolf_self_explosion ?? null;
  const isDebatePhaseSelfExplosion =
    selfExplosion !== null &&
    (round.speech_order != null || (stateRound?.speech_order?.length ?? 0) > 0);

  if ((round.werewolf_votes ?? []).length === 0) {
    pushAction(items, round.number, "night", "night-eliminate", round.eliminate);
  }
  (round.werewolf_discussion ?? []).forEach((action, index) => {
    pushAction(
      items,
      round.number,
      "night",
      `night-werewolf-discussion-${index}`,
      action,
    );
  });
  (round.werewolf_votes ?? []).forEach((voteRound, roundIndex) => {
    voteRound.forEach((action, actionIndex) => {
      pushAction(
        items,
        round.number,
        "night",
        `night-werewolf-vote-${roundIndex}-${actionIndex}`,
        action,
      );
    });
  });
  pushAction(items, round.number, "night", "night-protect", round.protect);
  pushAction(
    items,
    round.number,
    "night",
    "night-investigate",
    round.investigate,
  );
  pushAction(
    items,
    round.number,
    "night",
    "night-witch-save",
    round.witch_save ?? null,
  );
  pushAction(
    items,
    round.number,
    "night",
    "night-witch-poison",
    round.witch_poison ?? null,
  );
  pushAction(
    items,
    round.number,
    "night",
    "night-hunter-shoot",
    round.hunter_shoot ?? null,
  );
  if (sheriffBadgePlacement === "night") {
    pushAction(
      items,
      round.number,
      "night",
      "night-sheriff-badge",
      sheriffBadge,
    );
  }

  round.bid.flat().forEach((action, index) => {
    pushAction(items, round.number, "day", `day-bid-${index}`, action);
  });
  (round.sheriff_run ?? []).forEach((action, index) => {
    pushAction(items, round.number, "day", `day-sheriff-run-${index}`, action);
  });
  (round.sheriff_speech ?? []).forEach((action, index) => {
    pushAction(items, round.number, "day", `day-sheriff-speech-${index}`, action);
  });
  (round.sheriff_withdraw ?? []).forEach((action, index) => {
    pushAction(
      items,
      round.number,
      "day",
      `day-sheriff-withdraw-${index}`,
      action,
    );
  });
  (round.sheriff_votes ?? []).forEach((action, index) => {
    pushAction(items, round.number, "day", `day-sheriff-vote-${index}`, action);
  });
  (round.sheriff_pk_speech ?? []).forEach((action, index) => {
    pushAction(
      items,
      round.number,
      "day",
      `day-sheriff-pk-speech-${index}`,
      action,
    );
  });
  (round.sheriff_runoff_votes ?? []).forEach((action, index) => {
    pushAction(
      items,
      round.number,
      "day",
      `day-sheriff-runoff-vote-${index}`,
      action,
    );
  });
  if (!isDebatePhaseSelfExplosion) {
    pushAction(
      items,
      round.number,
      "day",
      "day-werewolf-self-explosion",
      selfExplosion,
    );
  }
  pushAction(
    items,
    round.number,
    "day",
    "day-speech-order",
    round.speech_order ?? null,
  );
  if (sheriffBadgePlacement === "after_speech_order") {
    pushAction(items, round.number, "day", "day-sheriff-badge", sheriffBadge);
  }
  round.debate.forEach((action, index) => {
    pushAction(items, round.number, "day", `day-debate-${index}`, action);
  });
  if (isDebatePhaseSelfExplosion) {
    pushAction(
      items,
      round.number,
      "day",
      "day-werewolf-self-explosion",
      selfExplosion,
    );
  }
  round.votes.flat().forEach((action, index) => {
    pushAction(items, round.number, "day", `day-vote-${index}`, action);
  });
  if (sheriffBadgePlacement === "after_day_vote") {
    pushAction(items, round.number, "day", "day-sheriff-badge", sheriffBadge);
  }
  round.summaries.forEach((action, index) => {
    pushAction(items, round.number, "summary", `summary-${index}`, action);
  });

  return items;
}

function placementForSheriffBadge(
  action: RawActionLog,
  stateRound?: RawRoundState,
) {
  if (!stateRound) {
    return "after_speech_order";
  }

  if (
    (stateRound.night_deaths ?? []).some(
      (death) => death.player === action.actor,
    ) ||
    stateRound.eliminated === action.actor
  ) {
    return "night";
  }

  if (
    (stateRound.day_deaths ?? []).some(
      (death) => death.player === action.actor,
    ) ||
    stateRound.exiled === action.actor
  ) {
    return "after_day_vote";
  }

  return "after_speech_order";
}

function pushAction(
  items: DebugItem[],
  roundNumber: number,
  phase: DebugItem["phase"],
  suffix: string,
  action: RawActionLog | null,
) {
  if (!action) {
    return;
  }

  items.push({
    id: `round-${roundNumber}-${suffix}`,
    roundNumber,
    phase,
    title: ACTION_TITLES[action.action] ?? action.action,
    actor: action.actor,
    action: action.action,
    choice: action.choice,
    prompt: action.lm_log.prompt ?? "",
    rawResponse: action.lm_log.raw_response ?? "",
    parsed: action.lm_log.result,
  });
}

function stringRecord(value: unknown): Record<string, string> {
  if (!isRecord(value)) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, String(item)]),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
