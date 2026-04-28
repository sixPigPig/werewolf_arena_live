import type {
  BidEntry,
  DebugItem,
  GameReplay,
  GameRound,
  RawActionLog,
  RawGameReplayResponse,
  RawRoundLog,
} from "../types";

const ACTION_TITLES: Record<string, string> = {
  remove: "狼人击杀",
  protect: "医生守护",
  investigate: "预言家查验",
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
    players: response.state.players,
    rounds: response.state.rounds.map(normalizeRound),
    logs: response.logs,
    debugItems: response.logs.flatMap(debugItemsFromRound),
  };
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
  const votes = round.votes.flatMap((entry) =>
    Object.entries(entry).map(([voter, target]) => ({ voter, target })),
  );

  return {
    ...round,
    attacked,
    eliminated,
    bids: bidGroups.flatMap((group) => group.bids),
    bidGroups,
    votes,
    voteTally: tallyVotes(votes.map((vote) => vote.target)),
    voteCount: votes.length,
    voteMajorityThreshold:
      votes.length > 0 ? Math.floor(votes.length / 2) + 1 : null,
  };
}

function selectedSpeakerFromBids(bids: BidEntry[]) {
  return (
    [...bids].sort((a, b) => b.score - a.score || a.actor.localeCompare(b.actor))[0]
      ?.actor ?? null
  );
}

function tallyVotes(targets: string[]) {
  const counts = new Map<string, number>();
  targets.forEach((target) => {
    counts.set(target, (counts.get(target) ?? 0) + 1);
  });

  return Array.from(counts.entries())
    .map(([target, count]) => ({ target, count }))
    .sort((a, b) => b.count - a.count || a.target.localeCompare(b.target));
}

function debugItemsFromRound(round: RawRoundLog): DebugItem[] {
  const items: DebugItem[] = [];

  pushAction(items, round.number, "night", "night-eliminate", round.eliminate);
  pushAction(items, round.number, "night", "night-protect", round.protect);
  pushAction(
    items,
    round.number,
    "night",
    "night-investigate",
    round.investigate,
  );

  round.bid.flat().forEach((action, index) => {
    pushAction(items, round.number, "day", `day-bid-${index}`, action);
  });
  round.debate.forEach((action, index) => {
    pushAction(items, round.number, "day", `day-debate-${index}`, action);
  });
  round.votes.flat().forEach((action, index) => {
    pushAction(items, round.number, "day", `day-vote-${index}`, action);
  });
  round.summaries.forEach((action, index) => {
    pushAction(items, round.number, "summary", `summary-${index}`, action);
  });

  return items;
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
