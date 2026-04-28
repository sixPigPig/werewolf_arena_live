import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { toDirectorCue } from "../liveDirector";
import type { DirectorCue } from "../liveDirector";
import type { LiveGameEvent } from "../types";

export type LiveDirectorSpeed = 1 | 1.5;

export type UseLiveDirectorResult = {
  cues: DirectorCue[];
  currentCue: DirectorCue | null;
  currentEventId: number | null;
  backlogCount: number;
  isCatchingUp: boolean;
  isPaused: boolean;
  speed: LiveDirectorSpeed;
  effectiveDurationMs: number;
  pause: () => void;
  resume: () => void;
  togglePaused: () => void;
  setSpeed: (speed: LiveDirectorSpeed) => void;
  advance: () => void;
  catchUpToLatest: () => void;
};

type UseLiveDirectorOptions = {
  resetKey?: string;
  startAtLatestTerminal?: boolean;
};

const CATCH_UP_BACKLOG_COUNT = 8;
const MIN_DURATION_MS = 500;

export function useLiveDirector(
  events: LiveGameEvent[],
  options: UseLiveDirectorOptions = {},
): UseLiveDirectorResult {
  const cues = useMemo(() => events.map(toDirectorCue), [events]);
  const [currentEventId, setCurrentEventId] = useState<number | null>(
    () => cues[0]?.eventId ?? null,
  );
  const [isPaused, setIsPaused] = useState(false);
  const [speed, setSpeedState] = useState<LiveDirectorSpeed>(1);
  const startedAtRef = useRef(0);
  const lastStartedEventIdRef = useRef<number | null>(null);
  const pausedAtRef = useRef<number | null>(null);
  const resetKeyRef = useRef(options.resetKey);

  const currentIndex = useMemo(() => {
    if (cues.length === 0) {
      return -1;
    }

    if (currentEventId === null) {
      return 0;
    }

    const matchingIndex = cues.findIndex((cue) => cue.eventId === currentEventId);
    return matchingIndex === -1 ? 0 : matchingIndex;
  }, [cues, currentEventId]);

  const currentCue = currentIndex === -1 ? null : cues[currentIndex];
  const resolvedCurrentEventId = currentCue?.eventId ?? null;
  const backlogCount =
    currentIndex >= 0 ? Math.max(0, cues.length - currentIndex - 1) : 0;
  const isCatchingUp = backlogCount >= CATCH_UP_BACKLOG_COUNT;
  const effectiveDurationMs = currentCue
    ? durationForCue(currentCue, speed, isCatchingUp)
    : 0;

  useEffect(() => {
    if (resetKeyRef.current === options.resetKey) {
      return;
    }

    resetKeyRef.current = options.resetKey;
    startedAtRef.current = Date.now();
    lastStartedEventIdRef.current = null;
    pausedAtRef.current = null;
    setCurrentEventId(null);
    setIsPaused(false);
    setSpeedState(1);
  }, [options.resetKey]);

  useEffect(() => {
    if (!options.startAtLatestTerminal) {
      return;
    }

    const latestTerminalCue = [...cues]
      .reverse()
      .find(
        (cue) => cue.type === "game_completed" || cue.type === "game_failed",
      );
    if (!latestTerminalCue || currentEventId === latestTerminalCue.eventId) {
      return;
    }

    setCurrentEventId(latestTerminalCue.eventId);
    startedAtRef.current = Date.now();
    lastStartedEventIdRef.current = latestTerminalCue.eventId;
  }, [cues, currentEventId, options.startAtLatestTerminal]);

  const moveToIndex = useCallback(
    (nextIndex: number) => {
      const nextCue = cues[nextIndex];
      startedAtRef.current = Date.now();
      if (isPaused) {
        pausedAtRef.current = startedAtRef.current;
      }
      setCurrentEventId(nextCue?.eventId ?? null);
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

  useEffect(() => {
    if (lastStartedEventIdRef.current === resolvedCurrentEventId) {
      return;
    }

    startedAtRef.current = Date.now();
    lastStartedEventIdRef.current = resolvedCurrentEventId;
  }, [resolvedCurrentEventId]);

  useEffect(() => {
    if (isPaused || currentCue === null || backlogCount === 0) {
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

  const catchUpToLatest = useCallback(() => {
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
    cues,
    currentCue,
    currentEventId: resolvedCurrentEventId,
    backlogCount,
    isCatchingUp,
    isPaused,
    speed,
    effectiveDurationMs,
    pause,
    resume,
    togglePaused,
    setSpeed,
    advance,
    catchUpToLatest,
  };
}

function durationForCue(
  cue: DirectorCue,
  speed: LiveDirectorSpeed,
  isCatchingUp: boolean,
): number {
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
