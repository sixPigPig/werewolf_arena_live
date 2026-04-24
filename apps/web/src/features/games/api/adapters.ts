import type {
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
    players: response.state.players,
    rounds: response.state.rounds.map(normalizeRound),
    logs: response.logs,
    debugItems: response.logs.flatMap(debugItemsFromRound),
  };
}

function normalizeRound(
  round: RawGameReplayResponse["state"]["rounds"][number],
): GameRound {
  return {
    ...round,
    bids: round.bids.flatMap((entry) =>
      Object.entries(entry).map(([actor, score]) => ({ actor, score })),
    ),
    votes: round.votes.flatMap((entry) =>
      Object.entries(entry).map(([voter, target]) => ({ voter, target })),
    ),
  };
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
