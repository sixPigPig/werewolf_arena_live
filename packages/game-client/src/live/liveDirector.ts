import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { LiveGameEvent } from "../types";
import { eventTypeLabel, liveEventTitle } from "./liveLabels";
import type { LiveDirectorSpeed } from "./liveNavStatus";
import type { VoicePlaybackCompletion } from "./liveVoiceStream";

export type DirectorCueImportance = "normal" | "action" | "key" | "terminal";

export type DirectorCue = {
  eventId: number;
  latestEventId: number;
  presentationId?: string;
  presentationOccurrenceKey?: string;
  type: string;
  round: number | null;
  phase: string | null;
  actor: string | null;
  action: string | null;
  title: string;
  body: string;
  importance: DirectorCueImportance;
  /** Visual display duration and no-voice fallback; TTS subtitles use audio timestamps. */
  durationMs: number;
  compressible: boolean;
  suppressSpeechSubtitle?: boolean;
};

export type UseLiveDirectorResult = {
  cues: DirectorCue[];
  currentCue: DirectorCue | null;
  currentEventId: number | null;
  cursorVersion: number;
  backlogCount: number;
  isCatchingUp: boolean;
  isPaused: boolean;
  speed: LiveDirectorSpeed;
  effectiveDurationMs: number;
  terminalKeepFromEventId: number | null;
  terminalEventId: number | null;
  pause: () => void;
  resume: () => void;
  togglePaused: () => void;
  setSpeed: (speed: LiveDirectorSpeed) => void;
  advance: () => void;
  seekToEventId: (eventId: number) => void;
  catchUpToLatest: () => void;
  completeVoicePlayback: (completion: VoicePlaybackCompletion | null) => void;
};

type UseLiveDirectorOptions = {
  holdAdvance?: boolean;
  preemptTerminalBacklog?: boolean;
  resetKey?: string;
  sessionKey?: string;
  startAtEventType?: string;
  startAtLatestEventType?: string;
  startAtLatestTerminal?: boolean;
};

type StreamedSpeechSignature = {
  actor: string | null;
  action: string | null;
  text: string;
};

export type TerminalPlaybackWindow = {
  keepFromEventId: number;
  terminalEventId: number;
};

type SheriffRunBatch = {
  cue: DirectorCue;
  requested: Set<string>;
  resolved: Set<string>;
  raised: string[];
  declined: string[];
  completed: boolean;
};

const CATCH_UP_BACKLOG_COUNT = 8;
const MIN_DURATION_MS = 500;
const SHERIFF_RUN_EVENT_TYPES = new Set([
  "action_requested",
  "model_request_started",
  "model_thinking_tick",
  "model_response_delta",
  "model_response_received",
  "model_retry_scheduled",
  "action_quality_warning",
  "action_parsed",
]);

export function buildDirectorCues(events: LiveGameEvent[]): DirectorCue[] {
  const cues: DirectorCue[] = [];
  const requestCueById = new Map<
    string,
    { cue: DirectorCue; visibleText: string }
  >();
  const streamedSpeechByRequestId = new Map<string, StreamedSpeechSignature>();
  const streamedSpeechByActorAction = new Map<
    string,
    StreamedSpeechSignature
  >();
  let sheriffRunBatch: SheriffRunBatch | null = null;

  for (const event of events) {
    const payload = payloadForEvent(event);
    const requestId = stringField(payload, "request_id");

    if (
      event.action === "sheriff_run" &&
      SHERIFF_RUN_EVENT_TYPES.has(event.type)
    ) {
      if (
        event.type === "action_requested" &&
        (!sheriffRunBatch || sheriffRunBatch.completed)
      ) {
        const cue = {
          ...cueBase(event),
          title: "玩家正在决定是否上警",
          body: "等待全部玩家返回上警意向（0/1）",
          importance: "action" as const,
          durationMs: 2500,
          compressible: true,
        };
        sheriffRunBatch = {
          cue,
          requested: new Set(),
          resolved: new Set(),
          raised: [],
          declined: [],
          completed: false,
        };
        cues.push(cue);
      }

      if (sheriffRunBatch) {
        updateSheriffRunBatch(sheriffRunBatch, event, payload);
        if (
          !sheriffRunBatch.completed &&
          sheriffRunBatch.requested.size > 0 &&
          sheriffRunBatch.resolved.size >= sheriffRunBatch.requested.size
        ) {
          sheriffRunBatch.completed = true;
          sheriffRunBatch.cue.durationMs = MIN_DURATION_MS;
          sheriffRunBatch.cue.compressible = true;
          cues.push(sheriffRunResultCue(event, sheriffRunBatch));
        }
        continue;
      }
    }

    if (
      event.type === "state_updated" &&
      stringField(payload, "narration_mode") === "explicit_v1"
    ) {
      continue;
    }

    if (event.type === "model_response_delta") {
      const requestCue = requestId ? requestCueById.get(requestId) : undefined;
      if (!requestCue) {
        continue;
      }

      const visibleText = stringField(payload, "visible_text");
      if (!visibleText) {
        continue;
      }

      requestCue.visibleText += visibleText;
      const actor = event.actor || requestCue.cue.actor || "未知玩家";
      const action = event.action || requestCue.cue.action;
      const body = `${actor}：${requestCue.visibleText}`;
      requestCue.cue.latestEventId = event.id;
      requestCue.cue.title = `${actor} 正在发言`;
      requestCue.cue.body = body;
      requestCue.cue.importance = "key";
      requestCue.cue.durationMs = longTextDuration(body);
      requestCue.cue.compressible = false;
      if (isPublicSpeechAction(action)) {
        const signature = {
          actor,
          action,
          text: normalizeSpeechText(requestCue.visibleText),
        };
        if (requestId) {
          streamedSpeechByRequestId.set(requestId, signature);
        }
        streamedSpeechByActorAction.set(
          streamedSpeechKey(actor, action),
          signature,
        );
      }
      continue;
    }

    if (event.type === "model_thinking_tick") {
      const requestCue = requestId ? requestCueById.get(requestId) : undefined;
      if (!requestCue || requestCue.visibleText) {
        continue;
      }

      const body = thinkingTickBody(payload);
      if (body) {
        requestCue.cue.body = body;
        requestCue.cue.durationMs = statusTextDuration(body);
      }
      continue;
    }

    const cue = toDirectorCue(event);
    const duplicateSpeech = duplicateStreamedSpeechForEvent(
      event,
      payload,
      streamedSpeechByRequestId,
      streamedSpeechByActorAction,
    );
    if (duplicateSpeech) {
      cue.suppressSpeechSubtitle = true;
      cue.title = duplicateSpeech.actor
        ? `${duplicateSpeech.actor} 发言已记录`
        : "发言已记录";
      cue.body = "公开发言已记录，继续等待下一步。";
      cue.importance = "action";
      cue.durationMs = 2000;
      cue.compressible = true;
    }
    cues.push(cue);

    if (event.type === "model_request_started" && requestId) {
      if (isPublicSpeechAction(event.action)) {
        streamedSpeechByActorAction.delete(
          streamedSpeechKey(event.actor, event.action),
        );
      }
      requestCueById.set(requestId, { cue, visibleText: "" });
    }

    if (duplicateSpeech && event.type === "state_updated") {
      streamedSpeechByActorAction.delete(
        streamedSpeechKey(duplicateSpeech.actor, duplicateSpeech.action),
      );
    }
  }

  return cues;
}

function updateSheriffRunBatch(
  batch: SheriffRunBatch,
  event: LiveGameEvent,
  payload: Record<string, unknown>,
) {
  batch.cue.latestEventId = event.id;
  if (event.type === "action_requested" && event.actor) {
    batch.requested.add(event.actor);
  }
  if (event.type === "action_parsed" && event.actor) {
    batch.requested.add(event.actor);
    batch.resolved.add(event.actor);
    const choice = stringField(payload, "choice");
    const raisedIndex = batch.raised.indexOf(event.actor);
    const declinedIndex = batch.declined.indexOf(event.actor);
    if (raisedIndex !== -1) {
      batch.raised.splice(raisedIndex, 1);
    }
    if (declinedIndex !== -1) {
      batch.declined.splice(declinedIndex, 1);
    }
    (choice === "上警" ? batch.raised : batch.declined).push(event.actor);
  }

  const raisedText = batch.raised.length
    ? `；已举手：${batch.raised.join("、")}`
    : "";
  batch.cue.body = `等待全部玩家返回上警意向（${batch.resolved.size}/${batch.requested.size}）${raisedText}`;
}

function sheriffRunResultCue(
  event: LiveGameEvent,
  batch: SheriffRunBatch,
): DirectorCue {
  const raisedText = batch.raised.length ? batch.raised.join("、") : "无人";
  const declinedText = batch.declined.length
    ? `\n不上警：${batch.declined.join("、")}`
    : "";
  return {
    ...cueBase(event),
    title: "上警结果",
    body: `举手上警：${raisedText}${declinedText}`,
    importance: "key",
    durationMs: 6000,
    compressible: false,
  };
}

export function useLiveDirector(
  events: LiveGameEvent[],
  options: UseLiveDirectorOptions = {},
): UseLiveDirectorResult {
  const usesExplicitSessionKey = Object.prototype.hasOwnProperty.call(
    options,
    "sessionKey",
  );
  const presentationScopeKey = usesExplicitSessionKey
    ? options.sessionKey
    : options.resetKey;
  const presentedPresentationOccurrencesRef = useRef<Map<string, string>>(
    new Map(),
  );
  const [presentationRevision, setPresentationRevision] = useState(0);
  const presentationScopeKeyRef = useRef(presentationScopeKey);
  const builtCues = useMemo(() => buildDirectorCues(events), [events]);
  const allCues = useMemo(() => {
    if (
      presentationScopeKey !== undefined &&
      presentationScopeKeyRef.current !== undefined &&
      presentationScopeKeyRef.current !== presentationScopeKey
    ) {
      return builtCues;
    }

    return builtCues.filter((cue) => {
      if (!cue.presentationId) {
        return true;
      }
      const presentedOccurrence =
        presentedPresentationOccurrencesRef.current.get(cue.presentationId);
      return (
        !presentedOccurrence ||
        presentedOccurrence === cue.presentationOccurrenceKey
      );
    });
  }, [builtCues, presentationRevision, presentationScopeKey]);
  useEffect(() => {
    if (presentationScopeKey === undefined) {
      return;
    }
    if (
      presentationScopeKeyRef.current !== undefined &&
      presentationScopeKeyRef.current !== presentationScopeKey
    ) {
      presentedPresentationOccurrencesRef.current.clear();
    }
    presentationScopeKeyRef.current = presentationScopeKey;
  }, [presentationScopeKey]);
  const terminalPlaybackWindow = useMemo(
    () => terminalPlaybackWindowForEvents(events),
    [events],
  );
  const terminalPreemptionWindow =
    options.preemptTerminalBacklog === false ? null : terminalPlaybackWindow;
  const cues = useMemo(
    () =>
      terminalPreemptionWindow
        ? allCues.filter(
            (cue) =>
              cue.latestEventId >= terminalPreemptionWindow.keepFromEventId &&
              cue.eventId <= terminalPreemptionWindow.terminalEventId,
          )
        : allCues,
    [allCues, terminalPreemptionWindow],
  );
  const latestTerminalCue = useMemo(
    () =>
      [...cues]
        .reverse()
        .find(
          (cue) =>
            cue.type === "game_completed" ||
            cue.type === "game_failed" ||
            cue.type === "game_canceled",
        ),
    [cues],
  );
  const firstRequestedStartCue = useMemo(
    () =>
      options.startAtEventType
        ? cues.find((cue) => cue.type === options.startAtEventType)
        : undefined,
    [cues, options.startAtEventType],
  );
  const latestRequestedStartCue = useMemo(
    () =>
      options.startAtLatestEventType
        ? [...cues]
            .reverse()
            .find((cue) => cue.type === options.startAtLatestEventType)
        : undefined,
    [cues, options.startAtLatestEventType],
  );
  const preferredStartCueId =
    options.startAtLatestTerminal && latestTerminalCue
      ? latestTerminalCue.eventId
      : (latestRequestedStartCue?.eventId ?? firstRequestedStartCue?.eventId ?? null);
  const [currentCueId, setCurrentCueId] = useState<number | null>(
    () => preferredStartCueId ?? cues[0]?.eventId ?? null,
  );
  const [isPaused, setIsPaused] = useState(false);
  const [speed, setSpeedState] = useState<LiveDirectorSpeed>(1);
  const [cursorVersion, setCursorVersion] = useState(0);
  const [voiceCompletedCueId, setVoiceCompletedCueId] = useState<number | null>(
    null,
  );
  const startedAtRef = useRef(0);
  const lastStartedCueIdRef = useRef<number | null>(null);
  const pausedAtRef = useRef<number | null>(null);
  const resetKeyRef = useRef(options.resetKey);
  const terminalStartRequestedAtResetRef = useRef(
    options.startAtLatestTerminal === true,
  );
  const autoStartedTerminalEventIdRef = useRef<number | null>(
    options.startAtLatestTerminal && latestTerminalCue
      ? latestTerminalCue.eventId
      : null,
  );
  const autoStartedEventTypeIdRef = useRef<number | null>(
    latestRequestedStartCue?.eventId ?? firstRequestedStartCue?.eventId ?? null,
  );
  const lastVoiceCompletionIdRef = useRef<string | null>(null);
  const appliedTerminalPreemptionEventIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (
      !terminalStartRequestedAtResetRef.current ||
      !options.startAtLatestTerminal ||
      !latestTerminalCue
    ) {
      return;
    }

    if (autoStartedTerminalEventIdRef.current === latestTerminalCue.eventId) {
      return;
    }

    autoStartedTerminalEventIdRef.current = latestTerminalCue.eventId;
    setCurrentCueId(latestTerminalCue.eventId);
  }, [latestTerminalCue, options.startAtLatestTerminal]);

  useEffect(() => {
    if (!options.startAtEventType || !firstRequestedStartCue) {
      return;
    }

    if (autoStartedEventTypeIdRef.current === firstRequestedStartCue.eventId) {
      return;
    }

    autoStartedEventTypeIdRef.current = firstRequestedStartCue.eventId;
    setCurrentCueId((current) =>
      current === null || current < firstRequestedStartCue.eventId
        ? firstRequestedStartCue.eventId
        : current,
    );
  }, [firstRequestedStartCue, options.startAtEventType]);

  useEffect(() => {
    if (!options.startAtLatestEventType || !latestRequestedStartCue) {
      return;
    }
    if (autoStartedEventTypeIdRef.current === latestRequestedStartCue.eventId) {
      return;
    }
    autoStartedEventTypeIdRef.current = latestRequestedStartCue.eventId;
    setCurrentCueId((current) =>
      current === null || current < latestRequestedStartCue.eventId
        ? latestRequestedStartCue.eventId
        : current,
    );
  }, [latestRequestedStartCue, options.startAtLatestEventType]);

  useEffect(() => {
    if (
      !terminalPreemptionWindow ||
      appliedTerminalPreemptionEventIdRef.current ===
        terminalPreemptionWindow.terminalEventId
    ) {
      return;
    }
    appliedTerminalPreemptionEventIdRef.current =
      terminalPreemptionWindow.terminalEventId;

    const currentCue =
      currentCueId === null
        ? null
        : cues.find((cue) => cue.eventId === currentCueId) ?? null;
    const currentCueIntersectsWindow =
      currentCue !== null &&
      currentCue.latestEventId >= terminalPreemptionWindow.keepFromEventId &&
      currentCue.eventId <= terminalPreemptionWindow.terminalEventId;
    if (
      currentCueIntersectsWindow ||
      (currentCue !== null &&
        currentCue.eventId > terminalPreemptionWindow.terminalEventId)
    ) {
      return;
    }

    const firstKeptCue =
      cues.find(
        (cue) =>
          cue.latestEventId >= terminalPreemptionWindow.keepFromEventId &&
          cue.eventId <= terminalPreemptionWindow.terminalEventId,
      ) ??
      cues.find(
        (cue) => cue.eventId === terminalPreemptionWindow.terminalEventId,
      );
    if (!firstKeptCue) {
      return;
    }

    startedAtRef.current = Date.now();
    pausedAtRef.current = isPaused ? startedAtRef.current : null;
    setVoiceCompletedCueId(null);
    setCurrentCueId(firstKeptCue.eventId);
  }, [cues, currentCueId, isPaused, terminalPreemptionWindow]);

  const currentIndex = useMemo(() => {
    if (cues.length === 0) {
      return -1;
    }

    if (currentCueId === null) {
      return 0;
    }

    const matchingIndex = cues.findIndex(
      (cue) => cue.eventId === currentCueId,
    );
    if (matchingIndex !== -1) {
      return matchingIndex;
    }

    const nextIndex = cues.findIndex(
      (cue) => cue.latestEventId >= currentCueId,
    );
    return nextIndex === -1 ? cues.length - 1 : nextIndex;
  }, [cues, currentCueId]);

  const currentCue = currentIndex === -1 ? null : cues[currentIndex];
  const resolvedCurrentCueId = currentCue?.eventId ?? null;
  const resolvedCurrentEventId = currentCue?.latestEventId ?? null;
  const backlogCount =
    currentIndex >= 0 ? Math.max(0, cues.length - currentIndex - 1) : 0;
  const isCatchingUp = backlogCount >= CATCH_UP_BACKLOG_COUNT;
  const effectiveDurationMs =
    currentCue && voiceCompletedCueId === currentCue.eventId
      ? 0
      : currentCue
        ? durationForCue(currentCue, speed, isCatchingUp)
        : 0;

  useEffect(() => {
    if (resetKeyRef.current === options.resetKey) {
      return;
    }

    resetKeyRef.current = options.resetKey;
    startedAtRef.current = Date.now();
    lastStartedCueIdRef.current = null;
    pausedAtRef.current = null;
    terminalStartRequestedAtResetRef.current =
      options.startAtLatestTerminal === true;
    autoStartedTerminalEventIdRef.current = null;
    appliedTerminalPreemptionEventIdRef.current = null;
    autoStartedEventTypeIdRef.current = null;
    setCurrentCueId(null);
    setIsPaused(false);
    setSpeedState(1);
    setCursorVersion((current) => current + 1);
    setVoiceCompletedCueId(null);
    lastVoiceCompletionIdRef.current = null;
  }, [options.resetKey, options.startAtLatestTerminal]);

  useEffect(() => {
    if (
      !currentCue?.presentationId ||
      !currentCue.presentationOccurrenceKey ||
      presentedPresentationOccurrencesRef.current.has(
        currentCue.presentationId,
      )
    ) {
      return;
    }
    presentedPresentationOccurrencesRef.current.set(
      currentCue.presentationId,
      currentCue.presentationOccurrenceKey,
    );
    setPresentationRevision((current) => current + 1);
  }, [currentCue]);

  const moveToIndex = useCallback(
    (nextIndex: number) => {
      const nextCue = cues[nextIndex];
      startedAtRef.current = Date.now();
      if (isPaused) {
        pausedAtRef.current = startedAtRef.current;
      }
      setCurrentCueId(nextCue?.eventId ?? null);
    },
    [cues, isPaused],
  );

  const advance = useCallback(() => {
    if (cues.length === 0) {
      moveToIndex(-1);
      return;
    }

    moveToIndex(Math.min(currentIndex + 1, cues.length - 1));
  }, [cues.length, currentIndex, moveToIndex]);

  const seekToEventId = useCallback(
    (eventId: number) => {
      setCursorVersion((current) => current + 1);
      setVoiceCompletedCueId(null);
      if (cues.length === 0) {
        moveToIndex(-1);
        return;
      }

      const matchingIndex = cues.findIndex(
        (cue) => cue.latestEventId >= eventId,
      );
      moveToIndex(matchingIndex === -1 ? cues.length - 1 : matchingIndex);
    },
    [cues, moveToIndex],
  );

  useEffect(() => {
    if (
      currentCueId === null ||
      resolvedCurrentCueId === null ||
      currentCueId === resolvedCurrentCueId
    ) {
      return;
    }

    setCurrentCueId(resolvedCurrentCueId);
  }, [currentCueId, resolvedCurrentCueId]);

  useEffect(() => {
    if (lastStartedCueIdRef.current === resolvedCurrentCueId) {
      return;
    }

    startedAtRef.current = Date.now();
    lastStartedCueIdRef.current = resolvedCurrentCueId;
  }, [resolvedCurrentCueId]);

  useEffect(() => {
    if (
      isPaused ||
      options.holdAdvance ||
      currentCue === null ||
      backlogCount === 0
    ) {
      return;
    }

    const elapsedMs = Date.now() - startedAtRef.current;
    const remainingMs = Math.max(0, effectiveDurationMs - elapsedMs);
    const timeoutId = window.setTimeout(() => {
      advance();
    }, remainingMs);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [
    advance,
    backlogCount,
    currentCue,
    effectiveDurationMs,
    isPaused,
    options.holdAdvance,
  ]);

  const pause = useCallback(() => {
    setIsPaused((wasPaused) => {
      if (!wasPaused) {
        pausedAtRef.current = Date.now();
      }
      return true;
    });
  }, []);

  const resume = useCallback(() => {
    setIsPaused((wasPaused) => {
      if (wasPaused && pausedAtRef.current !== null) {
        startedAtRef.current += Date.now() - pausedAtRef.current;
        pausedAtRef.current = null;
      }
      return false;
    });
  }, []);

  const togglePaused = useCallback(() => {
    if (isPaused) {
      resume();
    } else {
      pause();
    }
  }, [isPaused, pause, resume]);

  const setSpeed = useCallback((nextSpeed: LiveDirectorSpeed) => {
    setSpeedState(nextSpeed);
  }, []);

  const completeVoicePlayback = useCallback(
    (completion: VoicePlaybackCompletion | null) => {
      if (
        !completion ||
        completion.id === lastVoiceCompletionIdRef.current
      ) {
        return;
      }
      lastVoiceCompletionIdRef.current = completion.id;
      if (
        currentCue &&
        completion.sourceEventId <= currentCue.latestEventId &&
        completion.lastSourceEventId >= currentCue.eventId
      ) {
        setVoiceCompletedCueId(currentCue.eventId);
      }
    },
    [currentCue],
  );

  const catchUpToLatest = useCallback(() => {
    setCursorVersion((current) => current + 1);
    setVoiceCompletedCueId(null);
    if (cues.length === 0) {
      moveToIndex(-1);
      return;
    }

    const latestCriticalIndex = findLatestUncompressibleCueIndex(
      cues,
      currentIndex + 1,
    );
    moveToIndex(
      latestCriticalIndex === -1 ? cues.length - 1 : latestCriticalIndex,
    );
  }, [cues, currentIndex, moveToIndex]);

  return {
    cues: allCues,
    currentCue,
    currentEventId: resolvedCurrentEventId,
    cursorVersion,
    backlogCount,
    isCatchingUp,
    isPaused,
    speed,
    effectiveDurationMs,
    terminalKeepFromEventId:
      terminalPlaybackWindow?.keepFromEventId ?? null,
    terminalEventId: terminalPlaybackWindow?.terminalEventId ?? null,
    pause,
    resume,
    togglePaused,
    setSpeed,
    advance,
    seekToEventId,
    catchUpToLatest,
    completeVoicePlayback,
  };
}

export function terminalPlaybackWindowForEvents(
  events: LiveGameEvent[],
): TerminalPlaybackWindow | null {
  const terminalEvent = [...events]
    .reverse()
    .find((event) => event.type === "game_completed");
  if (!terminalEvent) {
    return null;
  }

  const sourceKeepFromEventId = numberField(
    payloadForEvent(terminalEvent),
    "terminal_keep_from_event_id",
  );
  const terminalSourceEventId =
    terminalEvent.source_event_id ?? terminalEvent.id;
  if (
    sourceKeepFromEventId === null ||
    !Number.isInteger(sourceKeepFromEventId) ||
    sourceKeepFromEventId < 1 ||
    sourceKeepFromEventId > terminalSourceEventId
  ) {
    return null;
  }

  const terminalSourceRunId =
    terminalEvent.source_run_id ?? terminalEvent.run_id;
  const keepFromEvent = events.find(
    (event) =>
      (event.source_run_id ?? event.run_id) === terminalSourceRunId &&
      (event.source_event_id ?? event.id) === sourceKeepFromEventId,
  );
  if (!keepFromEvent || keepFromEvent.id > terminalEvent.id) {
    return null;
  }

  return {
    keepFromEventId: keepFromEvent.id,
    terminalEventId: terminalEvent.id,
  };
}

export function toDirectorCue(event: LiveGameEvent): DirectorCue {
  const rawPayload = event.payload as unknown;
  const payload = payloadForEvent(event);
  const base = cueBase(event);

  if (event.type === "run_created") {
    return {
      ...base,
      title: "运行已创建",
      body: "对局运行已创建，正在准备玩家、规则和实时事件流。",
      durationMs: 2000,
    };
  }

  if (event.type === "run_started") {
    return {
      ...base,
      title: "运行已开始",
      body: "后台对局已开始，观赛事件会按导播节奏播放。",
      durationMs: 2000,
    };
  }

  if (event.type === "game_started") {
    return {
      ...base,
      title: "对局开始",
      body: gameStartedBody(payload),
      importance: "key",
      durationMs: 5000,
      compressible: false,
    };
  }

  if (event.type === "game_resumed") {
    return {
      ...base,
      title: "对局继续",
      body: "已恢复到上次中断的回合，本局游戏继续。",
      importance: "key",
      durationMs: 3000,
      compressible: false,
    };
  }

  if (event.type === "round_started") {
    return {
      ...base,
      title: event.round === null ? "新回合开始" : `第 ${event.round} 轮开始`,
      body: event.round === null ? "新的回合即将展开。" : `第 ${event.round} 轮开始。`,
      durationMs: 2500,
    };
  }

  if (event.type === "phase_started") {
    return {
      ...base,
      title: liveEventTitle(event),
      body: activePlayersBody(payload),
      durationMs: 2500,
    };
  }

  if (event.type === "judge_cue") {
    const cueId = stringField(payload, "cue_id") || event.action || "";
    const uncompressible = new Set([
      "werewolf_self_explosion",
      "self_explosion_skip",
      "hunter_shot_result",
      "idiot_reveal",
      "idiot_stays",
      "exile_result",
      "badge_transfer",
      "badge_destroyed",
      "werewolf_tiebreak_start",
      "werewolf_tiebreak_result",
      "sheriff_no_voters",
      "sheriff_runoff_tied",
      "exile_tie",
      "exile_pk_start",
      "exile_runoff_vote",
      "exile_runoff_tied",
      "exile_no_votes",
      "exile_no_result",
      "exile_no_runoff_voters",
    ]).has(cueId);
    return {
      ...base,
      title: "法官提示",
      body: stringField(payload, "visible_text") || "请听法官提示。",
      importance: uncompressible ? "key" : "action",
      durationMs: uncompressible ? 4500 : 2200,
      compressible: !uncompressible,
    };
  }

  if (event.type === "action_requested") {
    return {
      ...base,
      title: liveEventTitle(event),
      body: optionsBody(payload),
      importance: "action",
      durationMs: 2500,
      compressible: true,
    };
  }

  if (event.type === "model_retry_scheduled") {
    const attempt = Number(payload.attempt ?? 0);
    return {
      ...base,
      title: `${event.actor ?? "玩家"} 正在重试行动`,
      body: `${stringField(payload, "message") || "模型输出不在候选项中，正在重试。"}${attempt ? `第 ${attempt} 次尝试。` : ""}`,
      importance: "action",
      durationMs: 3000,
      compressible: true,
    };
  }

  if (event.type === "action_quality_warning") {
    const fallbackChoice = stringField(payload, "fallback_choice");
    return {
      ...base,
      title: "行动质量提示",
      body: fallbackChoice
        ? `已使用安全兜底：${fallbackChoice}`
        : readablePayload(rawPayload),
      importance: "action",
      durationMs: 3500,
      compressible: true,
    };
  }

  if (event.type === "model_request_started") {
    return {
      ...base,
      title: liveEventTitle(event),
      body:
        stringField(payload, "message") ||
        `${stringField(payload, "model") || "模型"} 正在生成下一步。`,
      importance: "action",
      durationMs: 2500,
      compressible: true,
    };
  }

  if (event.type === "model_response_received") {
    const body =
      stringField(payload, "visible_text") ||
      stringField(payload, "message") ||
      "模型返回已接收，正在解析行动";
    return {
      ...base,
      title: liveEventTitle(event),
      body,
      importance: "action",
      durationMs: stringField(payload, "visible_text") ? longTextDuration(body) : 2500,
      compressible: !stringField(payload, "visible_text"),
    };
  }

  if (event.type === "action_parsed") {
    const parsedBody = parsedActionBody(payload);
    return {
      ...base,
      title: liveEventTitle(event),
      body: parsedBody || readablePayload(rawPayload),
      importance: "action",
      durationMs: parsedBody ? longTextDuration(parsedBody) : 3500,
      compressible: !parsedBody,
    };
  }

  if (event.type === "public_action_cancelled") {
    return {
      ...base,
      title: liveEventTitle(event),
      body: "狼人自爆已生效，原公开行动不再播出。",
      importance: "action",
      durationMs: MIN_DURATION_MS,
      compressible: true,
    };
  }

  if (event.type === "state_updated") {
    return stateUpdatedCue(event, rawPayload, payload, base);
  }

  if (event.type === "game_completed") {
    return {
      ...base,
      title: "对局完成",
      body: winnerBody(payload) || readablePayload(rawPayload),
      importance: "terminal",
      durationMs: 8000,
      compressible: false,
    };
  }

  if (event.type === "game_failed") {
    return {
      ...base,
      title: "对局失败",
      body: stringField(payload, "error") || readablePayload(rawPayload),
      importance: "terminal",
      durationMs: 8000,
      compressible: false,
    };
  }

  return {
    ...base,
    title: eventTypeLabel(event.type),
    body: readablePayload(rawPayload),
    durationMs: 2000,
  };
}

function durationForCue(
  cue: DirectorCue,
  speed: LiveDirectorSpeed,
  isCatchingUp: boolean,
): number {
  // Speed and catch-up compression apply only while the cue is using its
  // visual/no-voice fallback clock. A completed TTS range sets the cue to 0.
  if (isCatchingUp && cue.compressible) {
    return MIN_DURATION_MS;
  }

  return Math.max(MIN_DURATION_MS, Math.round(cue.durationMs / speed));
}

function findLatestUncompressibleCueIndex(
  cues: DirectorCue[],
  firstIndex: number,
): number {
  for (let index = cues.length - 1; index >= 0; index -= 1) {
    if (index >= firstIndex && !cues[index].compressible) {
      return index;
    }
  }

  return -1;
}

function payloadForEvent(event: LiveGameEvent): Record<string, unknown> {
  return isRecord(event.payload) ? event.payload : {};
}

function duplicateStreamedSpeechForEvent(
  event: LiveGameEvent,
  payload: Record<string, unknown>,
  streamedSpeechByRequestId: ReadonlyMap<string, StreamedSpeechSignature>,
  streamedSpeechByActorAction: ReadonlyMap<string, StreamedSpeechSignature>,
): StreamedSpeechSignature | null {
  const candidate = publicSpeechCandidateForEvent(event, payload);
  if (!candidate) {
    return null;
  }

  const requestId = stringField(payload, "request_id");
  const requestSignature = requestId
    ? streamedSpeechByRequestId.get(requestId)
    : undefined;
  if (requestSignature && speechSignatureMatches(requestSignature, candidate)) {
    return requestSignature;
  }

  const actorActionSignature = streamedSpeechByActorAction.get(
    streamedSpeechKey(candidate.actor, candidate.action),
  );
  if (
    actorActionSignature &&
    speechSignatureMatches(actorActionSignature, candidate)
  ) {
    return actorActionSignature;
  }

  return null;
}

function publicSpeechCandidateForEvent(
  event: LiveGameEvent,
  payload: Record<string, unknown>,
): StreamedSpeechSignature | null {
  if (!isPublicSpeechAction(event.action)) {
    return null;
  }

  if (event.type === "model_response_received") {
    return speechCandidate(
      event.actor,
      event.action,
      stringField(payload, "visible_text"),
    );
  }

  if (event.type === "action_parsed") {
    return speechCandidate(
      event.actor,
      event.action,
      visibleSpeechText(payload),
    );
  }

  if (event.type === "state_updated") {
    const debateEntry = payload.debate_entry;
    if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
      return speechCandidate(
        debateEntry.speaker,
        event.action,
        typeof debateEntry.message === "string" ? debateEntry.message : "",
      );
    }
  }

  return null;
}

function speechCandidate(
  actor: string | null,
  action: string | null,
  text: string,
): StreamedSpeechSignature | null {
  const normalizedText = normalizeSpeechText(text);
  return normalizedText ? { actor, action, text: normalizedText } : null;
}

function speechSignatureMatches(
  streamed: StreamedSpeechSignature,
  candidate: StreamedSpeechSignature,
): boolean {
  return (
    streamed.actor === candidate.actor &&
    streamed.action === candidate.action &&
    streamed.text === candidate.text
  );
}

function streamedSpeechKey(actor: string | null, action: string | null): string {
  return `${actor ?? ""}:${action ?? ""}`;
}

function normalizeSpeechText(text: string): string {
  return text.replace(/\s+/g, "");
}

function cueBase(event: LiveGameEvent): DirectorCue {
  const presentationId = stringField(
    payloadForEvent(event),
    "presentation_id",
  );
  return {
    eventId: event.id,
    latestEventId: event.id,
    ...(presentationId
      ? {
          presentationId,
          presentationOccurrenceKey: `${event.source_run_id ?? event.run_id}:${event.source_event_id ?? event.id}`,
        }
      : {}),
    type: event.type,
    round: event.round,
    phase: event.phase,
    actor: event.actor,
    action: event.action,
    title: eventTypeLabel(event.type),
    body: "",
    importance: "normal",
    durationMs: 2000,
    compressible: true,
  };
}

function stateUpdatedCue(
  event: LiveGameEvent,
  rawPayload: unknown,
  payload: Record<string, unknown>,
  base: DirectorCue,
): DirectorCue {
  if (event.action === "hunter_shot_resolved") {
    const status = stringField(payload, "hunter_shot_status");
    const target = stringField(payload, "hunter_shot");
    if (status === "shot" && target) {
      return {
        ...base,
        title: "猎人开枪结算",
        body: `${target} 被猎人带走出局。\n${activePlayersBody(payload)}`,
        importance: "key",
        durationMs: 6000,
        compressible: false,
      };
    }
    if (status === "skipped") {
      return {
        ...base,
        title: "猎人技能结算",
        body: "猎人选择不发动技能。",
        importance: "key",
        durationMs: 4500,
        compressible: false,
      };
    }
  }

  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    const message =
      typeof debateEntry.message === "string" ? debateEntry.message : "";
    const body = `${debateEntry.speaker}：${message}`;
    return {
      ...base,
      title: `${debateEntry.speaker} 发言`,
      body,
      importance: "key",
      durationMs: longTextDuration(body),
      compressible: false,
    };
  }

  const votes = payload.votes;
  if (isRecord(votes)) {
    return {
      ...base,
      title: "投票结果更新",
      body: Object.entries(votes)
        .map(([voter, target]) => `${voter} -> ${String(target)}`)
        .join("\n"),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const exileRunoffVotes = payload.exile_runoff_votes;
  if (isRecord(exileRunoffVotes)) {
    return {
      ...base,
      title: "放逐二轮票型",
      body: Object.entries(exileRunoffVotes)
        .map(([voter, target]) => `${voter} -> ${String(target)}`)
        .join("\n"),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    return {
      ...base,
      title: `${exiled} 被放逐`,
      body: activePlayersBody(payload),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  const eliminated = stringField(payload, "eliminated");
  const savedPlayer =
    (attacked && protectedPlayer === attacked ? attacked : "") ||
    (eliminated && protectedPlayer === eliminated ? eliminated : "");
  if (savedPlayer) {
    return {
      ...base,
      title: "平安夜",
      body: `${savedPlayer} 被袭击，但被守卫保护。\n${activePlayersBody(payload)}`,
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  if (eliminated) {
    return {
      ...base,
      title: `${eliminated} 夜晚出局`,
      body: activePlayersBody(payload),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const publicSummary = stringField(payload, "public_summary");
  if (publicSummary) {
    return {
      ...base,
      title: "回合公开总结",
      body: publicSummary,
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const summaries = payload.summaries;
  if (isRecord(summaries) && !isRecord(payload.private_summaries)) {
    return {
      ...base,
      title: "回合总结更新",
      body: Object.entries(summaries)
        .map(([actor, summary]) => `${actor}：${String(summary)}`)
        .join("\n"),
      importance: "key",
      durationMs: 6000,
      compressible: false,
    };
  }

  const winner = stringField(payload, "winner");
  if (winner) {
    return {
      ...base,
      title: "胜负已更新",
      body: `胜利阵营：${winner}`,
      importance: "terminal",
      durationMs: 8000,
      compressible: false,
    };
  }

  return {
    ...base,
    title: eventTypeLabel(event.type),
    body: readablePayload(rawPayload),
    durationMs: 3000,
  };
}

function gameStartedBody(payload: Record<string, unknown>): string {
  const players = payload.players;
  if (!Array.isArray(players)) {
    return readablePayload(payload);
  }

  const names = players
    .map((player) => (isRecord(player) ? stringField(player, "name") : ""))
    .filter(Boolean);
  return names.length > 0 ? `玩家：${names.join("、")}` : readablePayload(payload);
}

function optionsBody(payload: Record<string, unknown>): string {
  const options = payload.options;
  if (!Array.isArray(options) || options.length === 0) {
    return "";
  }
  return `可选目标：${options.map(String).join("、")}`;
}

function parsedActionBody(payload: Record<string, unknown>): string {
  const choice = stringField(payload, "choice");
  if (choice) {
    return choice;
  }

  const visibleResult = payload.visible_result;
  if (isRecord(visibleResult)) {
    const say = stringField(visibleResult, "say");
    if (say) {
      return say;
    }
    const summary = stringField(visibleResult, "summary");
    if (summary) {
      return summary;
    }
  }

  const result = payload.result;
  if (isRecord(result)) {
    const say = stringField(result, "say");
    if (say) {
      return say;
    }
    const summary = stringField(result, "summary");
    if (summary) {
      return summary;
    }
  }

  return "";
}

function visibleSpeechText(payload: Record<string, unknown>): string {
  const visibleResult = payload.visible_result;
  if (isRecord(visibleResult)) {
    return (
      stringField(visibleResult, "say") ||
      stringField(visibleResult, "summary")
    );
  }
  return stringField(payload, "visible_text");
}

function isPublicSpeechAction(action: string | null): boolean {
  return (
    action === "debate" ||
    action === "sheriff_speech" ||
    action === "sheriff_pk_speech" ||
    action === "exile_pk_speech" ||
    action === "exile_last_words" ||
    action === "summarize"
  );
}

function winnerBody(payload: Record<string, unknown>): string {
  const winner = stringField(payload, "winner");
  return winner ? `胜利阵营：${winner}` : "";
}

function activePlayersBody(payload: Record<string, unknown>): string {
  const activePlayers = payload.active_players;
  if (!Array.isArray(activePlayers)) {
    return "";
  }
  return `存活玩家：${activePlayers.map(String).join("、")}`;
}

function stringField(
  payload: Record<string, unknown>,
  field: string,
): string {
  const value = payload[field];
  return typeof value === "string" ? value : "";
}

function numberField(
  payload: Record<string, unknown>,
  field: string,
): number | null {
  const value = payload[field];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function thinkingTickBody(payload: Record<string, unknown>): string {
  const message = stringField(payload, "message");
  if (!message) {
    return "";
  }

  const elapsedMs = numberField(payload, "elapsed_ms");
  return elapsedMs === null
    ? message
    : `${message}（${Math.round(elapsedMs / 1000)} 秒）`;
}

const NORMAL_CHARS_PER_SECOND = 4;
const NORMAL_WORDS_PER_MINUTE = 150;
const LONG_TEXT_LEAD_IN_MS = 1000;
const MIN_TEXT_DURATION_MS = 6000;
const MAX_TEXT_DURATION_MS = 20000;

function longTextDuration(text: string): number {
  // This reading estimate is intentionally retained only for missing,
  // disabled, or failed voice playback. TTS subtitles never use this clock.
  const cjkChars = Array.from(text).filter(isCjkSpeechChar).length;
  const words = text.match(/[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*/g)?.length ?? 0;
  const chineseMs = (cjkChars / NORMAL_CHARS_PER_SECOND) * 1000;
  const wordMs = (words / NORMAL_WORDS_PER_MINUTE) * 60 * 1000;
  const estimatedMs = Math.round(
    LONG_TEXT_LEAD_IN_MS + Math.max(chineseMs, wordMs),
  );

  return Math.min(
    MAX_TEXT_DURATION_MS,
    Math.max(MIN_TEXT_DURATION_MS, estimatedMs),
  );
}

function statusTextDuration(text: string): number {
  return Math.min(12000, Math.max(6000, 3500 + text.length * 45));
}

function isCjkSpeechChar(char: string): boolean {
  return /[\u3400-\u9fff]|\p{Script=Han}|\p{Script=Hiragana}|\p{Script=Katakana}|\p{Script=Hangul}/u.test(
    char,
  );
}

function readablePayload(payload: unknown): string {
  if (payload === undefined || payload === null) {
    return "";
  }
  if (typeof payload === "string") {
    return payload;
  }

  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
