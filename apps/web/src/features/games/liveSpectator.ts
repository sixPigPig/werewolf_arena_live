import type { LiveGameEvent } from "./types";

export type LivePlayerStatus =
  | "waiting"
  | "thinking"
  | "requesting"
  | "streaming"
  | "responded"
  | "acted"
  | "out";

export type LivePlayer = {
  name: string;
  role: string;
  model: string;
  status: LivePlayerStatus;
  isAlive: boolean;
  lastAction: string;
  lastDetail: string;
  activeRequestId: string | null;
  hasVisibleStreamText: boolean;
};

export type LiveSpectatorState = {
  players: LivePlayer[];
  activePlayerName: string | null;
  currentRound: number | null;
  currentPhase: string | null;
  latestActorEvent: LiveGameEvent | null;
  latestStateEvent: LiveGameEvent | null;
};

type MutableLiveSpectatorState = Omit<LiveSpectatorState, "players"> & {
  playersByName: Map<string, LivePlayer>;
  playerOrder: string[];
};

export function deriveLiveSpectatorState(
  events: LiveGameEvent[],
): LiveSpectatorState {
  const state: MutableLiveSpectatorState = {
    playersByName: new Map(),
    playerOrder: [],
    activePlayerName: null,
    currentRound: null,
    currentPhase: null,
    latestActorEvent: null,
    latestStateEvent: null,
  };

  for (const event of events) {
    if (event.round !== null) {
      state.currentRound = event.round;
    }
    if (event.phase) {
      state.currentPhase = event.phase;
    }

    if (event.type === "game_started") {
      initializePlayers(state, event);
    }

    if (event.actor) {
      const player = ensurePlayer(state, event.actor);
      const payload = payloadForEvent(event);
      const requestId =
        typeof payload.request_id === "string" ? payload.request_id : null;
      state.activePlayerName = event.actor;
      state.latestActorEvent = event;
      player.lastAction = event.action ?? event.type;

      if (event.type === "model_request_started") {
        player.activeRequestId = requestId;
        player.lastDetail = "";
        player.hasVisibleStreamText = false;
        player.status = "requesting";
      } else if (event.type === "model_response_delta") {
        if (requestId !== player.activeRequestId) {
          player.activeRequestId = requestId;
          player.hasVisibleStreamText = false;
        }
        const visibleText = payload.visible_text;
        if (typeof visibleText === "string") {
          player.lastDetail = player.hasVisibleStreamText
            ? player.lastDetail + visibleText
            : visibleText;
          player.hasVisibleStreamText = true;
        }
        player.status = "streaming";
      } else if (event.type === "model_thinking_tick") {
        if (requestId && requestId !== player.activeRequestId) {
          player.activeRequestId = requestId;
          player.hasVisibleStreamText = false;
        }
        if (!player.hasVisibleStreamText) {
          player.lastDetail = detailForEvent(event);
          player.status = "requesting";
        }
      } else {
        player.lastDetail = detailForEvent(event);
        player.hasVisibleStreamText = false;
        if (event.type === "action_parsed") {
          player.activeRequestId = null;
        }
        player.status = statusForActorEvent(event.type);
      }
    }

    if (event.type === "state_updated") {
      state.latestStateEvent = event;
      applyStateUpdate(state, event);
    }

    if (event.type === "game_completed" || event.type === "game_failed") {
      clearPendingPlayerStates(state);
    }
  }

  return {
    players: state.playerOrder
      .map((name) => state.playersByName.get(name))
      .filter((player): player is LivePlayer => Boolean(player)),
    activePlayerName: state.activePlayerName,
    currentRound: state.currentRound,
    currentPhase: state.currentPhase,
    latestActorEvent: state.latestActorEvent,
    latestStateEvent: state.latestStateEvent,
  };
}

function initializePlayers(state: MutableLiveSpectatorState, event: LiveGameEvent) {
  const players = payloadForEvent(event).players;
  if (!Array.isArray(players)) {
    return;
  }

  for (const player of players) {
    if (!isRecord(player) || typeof player.name !== "string") {
      continue;
    }
    const existing = ensurePlayer(state, player.name);
    existing.role = typeof player.role === "string" ? player.role : existing.role;
    existing.model =
      typeof player.model === "string" ? player.model : existing.model;
  }
}

function applyStateUpdate(
  state: MutableLiveSpectatorState,
  event: LiveGameEvent,
) {
  const payload = payloadForEvent(event);
  const attacked = payload.attacked;
  const eliminated = payload.eliminated;
  const protectedPlayer =
    typeof payload.protected === "string" ? payload.protected : null;
  const protectedAttack =
    typeof attacked === "string" && protectedPlayer === attacked
      ? attacked
      : null;
  const protectedElimination =
    typeof eliminated === "string" && protectedPlayer === eliminated
      ? eliminated
      : null;
  const protectedSurvival = protectedAttack ?? protectedElimination;

  const activePlayers = payload.active_players;
  if (Array.isArray(activePlayers)) {
    const activeNames = new Set(
      activePlayers.filter((name): name is string => typeof name === "string"),
    );
    for (const player of state.playersByName.values()) {
      player.isAlive =
        player.name === protectedSurvival || activeNames.has(player.name);
      if (!player.isAlive) {
        player.status = "out";
        player.activeRequestId = null;
        player.hasVisibleStreamText = false;
        if (!isOutDetail(player.lastDetail)) {
          player.lastAction = "";
          player.lastDetail = "出局";
        }
      }
    }
  }

  if (protectedSurvival) {
    const player = ensurePlayer(state, protectedSurvival);
    player.isAlive = true;
    player.status = "waiting";
    player.lastAction = "remove";
    player.lastDetail = "被守护，未出局";
    player.hasVisibleStreamText = false;
  }

  if (typeof eliminated === "string" && eliminated !== protectedSurvival) {
    const player = ensurePlayer(state, eliminated);
    player.isAlive = false;
    player.status = "out";
    player.lastAction = "";
    player.lastDetail = "夜晚出局";
    player.hasVisibleStreamText = false;
  }

  const exiled = payload.exiled;
  if (typeof exiled === "string") {
    const player = ensurePlayer(state, exiled);
    player.isAlive = false;
    player.status = "out";
    player.lastAction = "";
    player.lastDetail = "白天放逐";
    player.hasVisibleStreamText = false;
  }

  const debate = payload.debate;
  if (isRecord(debate) && typeof debate.speaker === "string") {
    const player = ensurePlayer(state, debate.speaker);
    player.lastAction = "debate";
    player.lastDetail =
      typeof debate.message === "string" ? debate.message : player.lastDetail;
    player.hasVisibleStreamText = false;
  }
}

function clearPendingPlayerStates(state: MutableLiveSpectatorState) {
  for (const player of state.playersByName.values()) {
    const isPending =
      player.status === "thinking" ||
      player.status === "requesting" ||
      player.status === "streaming";
    if (isPending) {
      if (!player.lastDetail) {
        player.status = "waiting";
        player.lastAction = "";
      }
      player.activeRequestId = null;
      player.hasVisibleStreamText = false;
    }
  }
}

function ensurePlayer(
  state: MutableLiveSpectatorState,
  name: string,
): LivePlayer {
  const existing = state.playersByName.get(name);
  if (existing) {
    return existing;
  }

  const player: LivePlayer = {
    name,
    role: "未知",
    model: "未知模型",
    status: "waiting",
    isAlive: true,
    lastAction: "",
    lastDetail: "",
    activeRequestId: null,
    hasVisibleStreamText: false,
  };
  state.playersByName.set(name, player);
  state.playerOrder.push(name);
  return player;
}

function statusForActorEvent(type: string): LivePlayerStatus {
  if (type === "action_requested") {
    return "thinking";
  }
  if (type === "model_request_started") {
    return "requesting";
  }
  if (type === "model_thinking_tick") {
    return "requesting";
  }
  if (type === "model_response_delta") {
    return "streaming";
  }
  if (type === "model_response_received") {
    return "responded";
  }
  if (type === "action_parsed") {
    return "acted";
  }
  return "waiting";
}

function detailForEvent(event: LiveGameEvent): string {
  const payload = payloadForEvent(event);
  const visibleText = payload.visible_text;
  if (typeof visibleText === "string") {
    return visibleText;
  }

  const message = payload.message;
  if (typeof message === "string") {
    return message;
  }

  const choice = payload.choice;
  if (typeof choice === "string") {
    return choice;
  }

  const visibleResult = payload.visible_result;
  if (isRecord(visibleResult)) {
    if (typeof visibleResult.say === "string") {
      return visibleResult.say;
    }
    if (typeof visibleResult.summary === "string") {
      return visibleResult.summary;
    }
  }

  const result = payload.result;
  if (isRecord(result)) {
    if (typeof result.say === "string") {
      return result.say;
    }
    if (typeof result.summary === "string") {
      return result.summary;
    }
  }

  const error = payload.error;
  if (typeof error === "string") {
    return error;
  }

  const winner = payload.winner;
  if (typeof winner === "string") {
    return winner;
  }

  return "";
}

function payloadForEvent(event: LiveGameEvent): Record<string, unknown> {
  return isRecord(event.payload) ? event.payload : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isOutDetail(value: string) {
  return value === "出局" || value === "夜晚出局" || value === "白天放逐";
}
