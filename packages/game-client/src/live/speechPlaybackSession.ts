export type SpeechPlaybackSessionState =
  | "collecting"
  | "buffering"
  | "playing"
  | "sealed"
  | "completed"
  | "interrupted"
  | "skipped"
  | "failed";

export type SpeechPlaybackSegmentState =
  | "received"
  | "ready"
  | "playing"
  | "played";

export type SpeechPlaybackTerminalStatus =
  | "completed"
  | "interrupted"
  | "skipped"
  | "failed";

export type SpeechSealStatus = "spoken" | "partial" | "interrupted";

export type SpeechPlaybackSegment = {
  utteranceId: string;
  segmentId: string;
  segmentIndex: number;
  sourceEventId: number;
  lastSourceEventId: number;
  durationMs: number;
  playedMs: number;
  state: SpeechPlaybackSegmentState;
};

export type SpeechPlaybackSession = {
  speechId: string;
  sourceEventId: number;
  lastSourceEventId: number;
  speaker: string;
  audience: "player_public" | "spectator_god_view";
  segments: SpeechPlaybackSegment[];
  highestContiguousIndex: number;
  finalSegmentIndex?: number;
  sealStatus?: SpeechSealStatus;
  sealedLastSourceEventId?: number;
  bufferedMs: number;
  playedMs: number;
  state: SpeechPlaybackSessionState;
  completionEmitted: boolean;
  preemptReason?: string;
  contractViolations: string[];
};

export type SpeechPlaybackShadowState = {
  sessions: Record<string, SpeechPlaybackSession>;
};

type SpeechOpenedAction = {
  type: "speech_opened";
  speechId: string;
  sourceEventId: number;
  speaker: string;
  audience: "player_public" | "spectator_god_view";
};

type SegmentReceivedAction = {
  type: "segment_received";
  speechId: string;
  utteranceId: string;
  segmentId: string;
  segmentIndex: number;
  sourceEventId: number;
  lastSourceEventId: number;
  speaker: string;
  audience: "player_public" | "spectator_god_view";
};

type SegmentReadyAction = {
  type: "segment_ready";
  utteranceId: string;
  durationMs: number;
};

type SegmentStartedAction = {
  type: "segment_started";
  utteranceId: string;
};

type SegmentFinishedAction = {
  type: "segment_finished";
  utteranceId: string;
  status: SpeechPlaybackTerminalStatus;
  playedMs?: number;
};

type SpeechSealedAction = {
  type: "speech_sealed";
  speechId: string;
  finalSegmentIndex: number;
  segmentCount: number;
  speechStatus: SpeechSealStatus;
  lastSourceEventId: number;
};

type SpeechPreemptedAction = {
  type: "speech_preempted";
  speechId: string;
  cutAfterSegmentIndex?: number;
  reason: string;
};

export type SpeechPlaybackShadowAction =
  | SpeechOpenedAction
  | SegmentReceivedAction
  | SegmentReadyAction
  | SegmentStartedAction
  | SegmentFinishedAction
  | SpeechSealedAction
  | SpeechPreemptedAction
  | { type: "reset" };

const TERMINAL_STATES = new Set<SpeechPlaybackSessionState>([
  "completed",
  "interrupted",
  "skipped",
  "failed",
]);

export function createSpeechPlaybackShadowState(): SpeechPlaybackShadowState {
  return { sessions: {} };
}

export function speechPlaybackSessionReducer(
  state: SpeechPlaybackShadowState,
  action: SpeechPlaybackShadowAction,
): SpeechPlaybackShadowState {
  if (action.type === "reset") {
    return Object.keys(state.sessions).length === 0
      ? state
      : createSpeechPlaybackShadowState();
  }

  if (action.type === "speech_opened") {
    return reduceSpeechOpened(state, action);
  }

  if (action.type === "segment_received") {
    return reduceSegmentReceived(state, action);
  }

  if (action.type === "speech_sealed") {
    const session = state.sessions[action.speechId];
    if (!session || isTerminal(session)) {
      return state;
    }
    if (
      !Number.isInteger(action.finalSegmentIndex) ||
      action.finalSegmentIndex < 0 ||
      action.segmentCount !== action.finalSegmentIndex + 1
    ) {
      return replaceSession(
        state,
        contractFailure(session, "invalid_speech_seal"),
      );
    }
    if (session.finalSegmentIndex !== undefined) {
      return session.finalSegmentIndex === action.finalSegmentIndex &&
        session.sealStatus === action.speechStatus &&
        session.sealedLastSourceEventId === action.lastSourceEventId
        ? state
        : replaceSession(
            state,
            contractFailure(session, "speech_seal_conflict"),
          );
    }
    if (
      session.segments.some(
        (segment) => segment.segmentIndex > action.finalSegmentIndex,
      )
    ) {
      return replaceSession(
        state,
        contractFailure(session, "segment_after_final_index"),
      );
    }
    return replaceSession(
      state,
      completeIfPossible(
        recalculate({
          ...session,
          finalSegmentIndex: action.finalSegmentIndex,
          sealStatus: action.speechStatus,
          sealedLastSourceEventId: action.lastSourceEventId,
          lastSourceEventId: Math.max(
            session.lastSourceEventId,
            action.lastSourceEventId,
          ),
          state: "sealed",
        }),
      ),
    );
  }

  if (action.type === "speech_preempted") {
    const session = state.sessions[action.speechId];
    if (!session || isTerminal(session)) {
      return state;
    }
    return replaceSession(state, {
      ...session,
      state: "interrupted",
      completionEmitted: true,
      preemptReason: action.reason,
    });
  }

  const located = findSessionByUtteranceId(state, action.utteranceId);
  if (!located || isTerminal(located.session)) {
    return state;
  }

  if (action.type === "segment_ready") {
    if (!Number.isFinite(action.durationMs) || action.durationMs < 0) {
      return replaceSession(
        state,
        contractFailure(located.session, "invalid_segment_duration"),
      );
    }
    const segment = located.session.segments[located.segmentArrayIndex];
    if (segment.state === "played") {
      return state;
    }
    return replaceSession(
      state,
      recalculate({
        ...located.session,
        state:
          located.session.state === "sealed"
            ? "sealed"
            : located.session.state,
        segments: replaceSegment(located, {
          ...segment,
          durationMs: action.durationMs,
          state: segment.state === "received" ? "ready" : segment.state,
        }),
      }),
    );
  }

  if (action.type === "segment_started") {
    const segment = located.session.segments[located.segmentArrayIndex];
    if (segment.state === "playing") {
      return state;
    }
    const next = nextSchedulableSpeechSegment(located.session);
    if (!next || next.utteranceId !== action.utteranceId) {
      return replaceSession(
        state,
        contractFailure(located.session, "segment_started_out_of_order"),
      );
    }
    return replaceSession(
      state,
      recalculate({
        ...located.session,
        state: "playing",
        segments: replaceSegment(located, {
          ...segment,
          state: "playing",
        }),
      }),
    );
  }

  const segment = located.session.segments[located.segmentArrayIndex];
  if (action.status !== "completed") {
    return replaceSession(
      state,
      recalculate({
        ...located.session,
        state: action.status,
        completionEmitted: true,
      }),
    );
  }
  if (segment.state !== "playing") {
    return replaceSession(
      state,
      contractFailure(located.session, "segment_finished_before_start"),
    );
  }
  return replaceSession(
    state,
    completeIfPossible(
      recalculate({
        ...located.session,
        state:
          located.session.finalSegmentIndex === undefined
            ? "buffering"
            : "sealed",
        segments: replaceSegment(located, {
          ...segment,
          state: "played",
          playedMs: Math.max(0, action.playedMs ?? segment.durationMs),
        }),
      }),
    ),
  );
}

export function nextSchedulableSpeechSegment(
  session: SpeechPlaybackSession,
): SpeechPlaybackSegment | null {
  if (isTerminal(session)) {
    return null;
  }
  for (let index = 0; index <= session.highestContiguousIndex; index += 1) {
    const segment = session.segments.find(
      (candidate) => candidate.segmentIndex === index,
    );
    if (!segment) {
      return null;
    }
    if (segment.state === "played") {
      continue;
    }
    return segment.state === "ready" ? segment : null;
  }
  return null;
}

function reduceSpeechOpened(
  state: SpeechPlaybackShadowState,
  action: SpeechOpenedAction,
) {
  const existing = state.sessions[action.speechId];
  if (!existing) {
    return replaceSession(state, createSession(action));
  }
  if (isTerminal(existing)) {
    return state;
  }
  if (
    existing.speaker !== action.speaker ||
    existing.audience !== action.audience
  ) {
    return replaceSession(
      state,
      contractFailure(existing, "speech_identity_conflict"),
    );
  }
  if (existing.sourceEventId === action.sourceEventId) {
    return state;
  }
  return replaceSession(state, {
    ...existing,
    sourceEventId: Math.min(existing.sourceEventId, action.sourceEventId),
  });
}

function reduceSegmentReceived(
  state: SpeechPlaybackShadowState,
  action: SegmentReceivedAction,
) {
  const initial =
    state.sessions[action.speechId] ??
    createSession({
      type: "speech_opened",
      speechId: action.speechId,
      sourceEventId: action.sourceEventId,
      speaker: action.speaker,
      audience: action.audience,
    });
  if (isTerminal(initial)) {
    return state;
  }
  if (!Number.isInteger(action.segmentIndex) || action.segmentIndex < 0) {
    return replaceSession(
      state,
      contractFailure(initial, "invalid_segment_index"),
    );
  }
  if (
    initial.speaker !== action.speaker ||
    initial.audience !== action.audience
  ) {
    return replaceSession(
      state,
      contractFailure(initial, "speech_identity_conflict"),
    );
  }
  if (
    initial.finalSegmentIndex !== undefined &&
    action.segmentIndex > initial.finalSegmentIndex
  ) {
    return replaceSession(
      state,
      contractFailure(initial, "segment_after_final_index"),
    );
  }
  const existing = initial.segments.find(
    (candidate) =>
      candidate.segmentIndex === action.segmentIndex ||
      candidate.utteranceId === action.utteranceId ||
      candidate.segmentId === action.segmentId,
  );
  if (existing) {
    return existing.segmentIndex === action.segmentIndex &&
      existing.utteranceId === action.utteranceId &&
      existing.segmentId === action.segmentId &&
      existing.sourceEventId === action.sourceEventId &&
      existing.lastSourceEventId === action.lastSourceEventId
      ? state
      : replaceSession(
          state,
          contractFailure(initial, "segment_identity_conflict"),
        );
  }
  const segments = [
    ...initial.segments,
    {
      utteranceId: action.utteranceId,
      segmentId: action.segmentId,
      segmentIndex: action.segmentIndex,
      sourceEventId: action.sourceEventId,
      lastSourceEventId: action.lastSourceEventId,
      durationMs: 0,
      playedMs: 0,
      state: "received" as const,
    },
  ].sort((left, right) => left.segmentIndex - right.segmentIndex);
  return replaceSession(
    state,
    recalculate({
      ...initial,
      sourceEventId: Math.min(initial.sourceEventId, action.sourceEventId),
      lastSourceEventId: Math.max(
        initial.lastSourceEventId,
        action.lastSourceEventId,
      ),
      segments,
      state: initial.state === "sealed" ? "sealed" : "buffering",
    }),
  );
}

function createSession(action: SpeechOpenedAction): SpeechPlaybackSession {
  return {
    speechId: action.speechId,
    sourceEventId: action.sourceEventId,
    lastSourceEventId: action.sourceEventId,
    speaker: action.speaker,
    audience: action.audience,
    segments: [],
    highestContiguousIndex: -1,
    bufferedMs: 0,
    playedMs: 0,
    state: "collecting",
    completionEmitted: false,
    contractViolations: [],
  };
}

function replaceSession(
  state: SpeechPlaybackShadowState,
  session: SpeechPlaybackSession,
) {
  if (state.sessions[session.speechId] === session) {
    return state;
  }
  return {
    sessions: {
      ...state.sessions,
      [session.speechId]: session,
    },
  };
}

function replaceSegment(
  located: {
    session: SpeechPlaybackSession;
    segmentArrayIndex: number;
  },
  segment: SpeechPlaybackSegment,
) {
  return located.session.segments.map((candidate, index) =>
    index === located.segmentArrayIndex ? segment : candidate,
  );
}

function findSessionByUtteranceId(
  state: SpeechPlaybackShadowState,
  utteranceId: string,
) {
  for (const session of Object.values(state.sessions)) {
    const segmentArrayIndex = session.segments.findIndex(
      (segment) => segment.utteranceId === utteranceId,
    );
    if (segmentArrayIndex !== -1) {
      return { session, segmentArrayIndex };
    }
  }
  return null;
}

function recalculate(session: SpeechPlaybackSession): SpeechPlaybackSession {
  const segmentsByIndex = new Map(
    session.segments.map((segment) => [segment.segmentIndex, segment]),
  );
  let highestContiguousIndex = -1;
  while (segmentsByIndex.has(highestContiguousIndex + 1)) {
    highestContiguousIndex += 1;
  }
  return {
    ...session,
    highestContiguousIndex,
    bufferedMs: session.segments
      .filter(
        (segment) =>
          segment.state === "ready" || segment.state === "playing",
      )
      .reduce((total, segment) => total + segment.durationMs, 0),
    playedMs: session.segments.reduce(
      (total, segment) => total + segment.playedMs,
      0,
    ),
  };
}

function completeIfPossible(
  session: SpeechPlaybackSession,
): SpeechPlaybackSession {
  if (session.finalSegmentIndex === undefined) {
    return session;
  }
  for (let index = 0; index <= session.finalSegmentIndex; index += 1) {
    const segment = session.segments.find(
      (candidate) => candidate.segmentIndex === index,
    );
    if (!segment || segment.state !== "played") {
      return session;
    }
  }
  return {
    ...session,
    state: "completed",
    completionEmitted: true,
  };
}

function contractFailure(
  session: SpeechPlaybackSession,
  violation: string,
): SpeechPlaybackSession {
  return {
    ...session,
    state: "failed",
    completionEmitted: true,
    contractViolations: [...session.contractViolations, violation],
  };
}

function isTerminal(session: SpeechPlaybackSession) {
  return TERMINAL_STATES.has(session.state);
}
