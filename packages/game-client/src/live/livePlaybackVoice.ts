import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";

import {
  createPcmAudioScheduler,
  type PcmAudioScheduler,
} from "./livePcmPlayer";
import type {
  LiveVoiceConnectionState,
  LiveVoiceQueueItem,
  LiveVoiceSubtitleCue,
  LiveVoiceSubtitle,
  VoicePlaybackCompletion,
} from "./liveVoiceStream";
import {
  SUBTITLE_CLOCK_POLL_INTERVAL_MS,
  currentSubtitleForItem,
  isPcmAudioFormat,
  subtitleDisplayForElapsedMs,
  subtitleElapsedMsForItem,
  type LiveVoiceSubtitleClock,
} from "./liveVoiceSubtitleClock";
import type { PlaybackVoiceChunk, PlaybackVoiceUtterance } from "../types";

const PLAYBACK_VOICE_EMPTY_MESSAGE = "这局回放没有保存的语音。";
const PLAYBACK_VOICE_ERROR_MESSAGE = "Unable to play saved replay voice audio.";
const PCM_COMPLETION_POLL_INTERVAL_MS = 25;
const BLOB_PLAYBACK_STALL_POLL_INTERVAL_MS = 1000;
const BLOB_PLAYBACK_STALL_TIMEOUT_MS = 30_000;
const SILENT_AUDIO_UNLOCK_DATA_URL =
  "data:audio/wav;base64,UklGRnQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YVAAAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==";

export function usePlaybackVoice(
  voices: PlaybackVoiceUtterance[],
  {
    currentEventId,
    cursorVersion = 0,
    enabled,
    isPaused,
    loadVoice,
  }: {
    currentEventId: number | null;
    cursorVersion?: number;
    enabled: boolean;
    isPaused: boolean;
    loadVoice?: (utteranceId: string) => Promise<PlaybackVoiceUtterance>;
  },
) {
  const sourceVoices = useMemo(
    () =>
      voices
        .filter(isPlaybackVoiceMetadata)
        .slice()
        .sort(comparePlaybackVoices),
    [voices],
  );
  const voicesKey = useMemo(
    () =>
      sourceVoices
        .map(
          (voice) =>
            [
              voice.utterance_id,
              voice.source_event_id,
              voice.last_source_event_id,
              voice.chunks?.length ?? 0,
              subtitleTimingsKey(voice),
            ].join(":"),
        )
        .join("|"),
    [sourceVoices],
  );
  const [loadedVoicesById, setLoadedVoicesById] = useState<
    Map<string, PlaybackVoiceUtterance>
  >(new Map());
  const sortedVoices = useMemo(
    () =>
      sourceVoices.map(
        (voice) => loadedVoicesById.get(voice.utterance_id) ?? voice,
      ),
    [loadedVoicesById, sourceVoices],
  );
  const [errors, setErrors] = useState<string[]>([]);
  const [currentItem, setCurrentItem] = useState<LiveVoiceQueueItem | null>(null);
  const [pendingItem, setPendingItem] = useState<LiveVoiceQueueItem | null>(null);
  const [subtitleClock, setSubtitleClock] =
    useState<LiveVoiceSubtitleClock>(null);
  const [lastCompletedPlayback, setLastCompletedPlayback] =
    useState<VoicePlaybackCompletion | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const blobCleanupRef = useRef<(() => void) | null>(null);
  const schedulerRef = useRef<PcmAudioScheduler | null>(null);
  const pcmEndTimesRef = useRef<Map<string, number>>(new Map());
  const pcmSubtitleStartTimesRef = useRef<Map<string, number>>(new Map());
  const consumedUtteranceIdsRef = useRef<Set<string>>(new Set());
  const activeUtteranceIdsRef = useRef<Set<string>>(new Set());
  const latestCurrentEventIdRef = useRef(currentEventId);
  latestCurrentEventIdRef.current = currentEventId;
  const sourceVoicesRef = useRef(sourceVoices);
  sourceVoicesRef.current = sourceVoices;
  const previousVoicesKeyRef = useRef(voicesKey);
  const playbackAttemptRef = useRef(0);
  const completionTimeoutsRef = useRef<Set<ReturnType<typeof globalThis.setTimeout>>>(
    new Set(),
  );
  const playbackCompletionSequenceRef = useRef(0);

  const connectionState = useMemo<LiveVoiceConnectionState>(() => {
    if (!enabled) {
      return "idle";
    }
    if (sortedVoices.length === 0) {
      return "unavailable";
    }
    if (errors.includes(PLAYBACK_VOICE_ERROR_MESSAGE)) {
      return "error";
    }
    return "open";
  }, [enabled, errors, sortedVoices.length]);
  const hasPcmVoice = useMemo(
    () => sortedVoices.some((voice) => isPcmAudioFormat(voice.audio_format)),
    [sortedVoices],
  );

  const ensureScheduler = useCallback(() => {
    if (audioContextRef.current && schedulerRef.current) {
      return {
        context: audioContextRef.current,
        scheduler: schedulerRef.current,
      };
    }

    const AudioContextConstructor =
      globalThis.AudioContext ??
      (globalThis as typeof globalThis & {
        webkitAudioContext?: typeof AudioContext;
      }).webkitAudioContext;
    if (typeof AudioContextConstructor !== "function") {
      return null;
    }

    const context = new AudioContextConstructor();
    const scheduler = createPcmAudioScheduler(context);
    audioContextRef.current = context;
    schedulerRef.current = scheduler;

    return { context, scheduler };
  }, []);

  const closeScheduler = useCallback(() => {
    const scheduler = schedulerRef.current;
    audioContextRef.current = null;
    schedulerRef.current = null;
    pcmEndTimesRef.current.clear();
    pcmSubtitleStartTimesRef.current.clear();
    setSubtitleClock(null);
    for (const timeoutId of completionTimeoutsRef.current) {
      globalThis.clearTimeout(timeoutId);
    }
    completionTimeoutsRef.current.clear();
    void scheduler?.close().catch(() => undefined);
  }, []);

  const recordPlaybackCompletion = useCallback((item: LiveVoiceQueueItem) => {
    playbackCompletionSequenceRef.current += 1;
    setLastCompletedPlayback({
      id: `${item.utteranceId}:${playbackCompletionSequenceRef.current}`,
      sourceEventId: item.sourceEventId,
      lastSourceEventId: item.lastSourceEventId,
    });
  }, []);

  const releaseLoadedVoice = useCallback((utteranceId: string) => {
    setLoadedVoicesById((current) => {
      if (!current.has(utteranceId)) {
        return current;
      }
      const next = new Map(current);
      next.delete(utteranceId);
      return next;
    });
  }, []);

  const finishPcmVoice = useCallback((item: LiveVoiceQueueItem) => {
    activeUtteranceIdsRef.current.delete(item.utteranceId);
    consumedUtteranceIdsRef.current.add(item.utteranceId);
    pcmEndTimesRef.current.delete(item.utteranceId);
    pcmSubtitleStartTimesRef.current.delete(item.utteranceId);
    setSubtitleClock((current) =>
      current?.utteranceId === item.utteranceId ? null : current,
    );
    setCurrentItem((current) =>
      current?.utteranceId === item.utteranceId ? null : current,
    );
    releaseLoadedVoice(item.utteranceId);
    recordPlaybackCompletion(item);
  }, [recordPlaybackCompletion, releaseLoadedVoice]);

  const releaseBlobAudio = useCallback(() => {
    const cleanup = blobCleanupRef.current;
    blobCleanupRef.current = null;
    cleanup?.();
  }, []);

  useEffect(() => {
    const targetEventId = latestCurrentEventIdRef.current;
    playbackAttemptRef.current += 1;
    releaseBlobAudio();
    closeScheduler();
    activeUtteranceIdsRef.current.clear();
    consumedUtteranceIdsRef.current = new Set(
      targetEventId === null
        ? []
        : sourceVoicesRef.current
            .filter((voice) => voice.last_source_event_id < targetEventId)
            .map((voice) => voice.utterance_id),
    );
    setLoadedVoicesById(new Map());
    setCurrentItem(null);
    setPendingItem(null);
    setLastCompletedPlayback(null);
    setSubtitleClock(null);
  }, [closeScheduler, cursorVersion, releaseBlobAudio]);

  const unlockAudio = useCallback(async () => {
    if (sortedVoices.length === 0) {
      pushUniqueError(setErrors, PLAYBACK_VOICE_EMPTY_MESSAGE);
      return false;
    }

    if (!hasPcmVoice) {
      const audio = audioElementRef.current ?? createAudioElement();
      audioElementRef.current = audio;
      try {
        audio.src = SILENT_AUDIO_UNLOCK_DATA_URL;
        await Promise.resolve(audio.play());
        audio.pause();
        audio.currentTime = 0;
        return true;
      } catch {
        pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
        return false;
      }
    }

    const audio = ensureScheduler();
    if (!audio) {
      pushError(setErrors, "当前浏览器不支持语音播放。");
      return false;
    }

    try {
      if (audio.context.state !== "running") {
        await audio.context.resume();
      }
      await audio.scheduler.resume();
      return true;
    } catch {
      pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
      return false;
    }
  }, [ensureScheduler, hasPcmVoice, sortedVoices.length]);

  const retryAudio = useCallback(async () => {
    if (!(await unlockAudio())) {
      return false;
    }

    const targetEventId = latestCurrentEventIdRef.current;
    playbackAttemptRef.current += 1;
    activeUtteranceIdsRef.current.clear();
    consumedUtteranceIdsRef.current = new Set(
      targetEventId === null
        ? []
        : sourceVoicesRef.current
            .filter((voice) => voice.last_source_event_id < targetEventId)
            .map((voice) => voice.utterance_id),
    );
    setLoadedVoicesById(new Map());
    setCurrentItem(null);
    setPendingItem(null);
    setLastCompletedPlayback(null);
    setSubtitleClock(null);
    setErrors([]);
    return true;
  }, [unlockAudio]);

  useEffect(() => {
    if (previousVoicesKeyRef.current === voicesKey) {
      return;
    }
    previousVoicesKeyRef.current = voicesKey;
    playbackAttemptRef.current += 1;
    releaseBlobAudio();
    closeScheduler();
    consumedUtteranceIdsRef.current.clear();
    activeUtteranceIdsRef.current.clear();
    playbackCompletionSequenceRef.current = 0;
    setLoadedVoicesById(new Map());
    setCurrentItem(null);
    setPendingItem(null);
    setLastCompletedPlayback(null);
    setSubtitleClock(null);
    setErrors([]);
  }, [closeScheduler, releaseBlobAudio, voicesKey]);

  useEffect(() => {
    if (!enabled || sortedVoices.length > 0) {
      return;
    }
    pushUniqueError(setErrors, PLAYBACK_VOICE_EMPTY_MESSAGE);
  }, [enabled, sortedVoices.length]);

  useEffect(() => {
    if (!enabled || isPaused || currentEventId === null || currentItem !== null) {
      return;
    }

    let nextVoice: PlaybackVoiceUtterance | undefined;
    if (pendingItem) {
      if (!voiceCoversEvent(pendingItem, currentEventId)) {
        playbackAttemptRef.current += 1;
        markVoiceFailed(
          pendingItem.utteranceId,
          activeUtteranceIdsRef,
          consumedUtteranceIdsRef,
        );
        releaseLoadedVoice(pendingItem.utteranceId);
        setPendingItem(null);
        return;
      }
      if (pendingItem.status !== "receiving") {
        return;
      }
      nextVoice = sortedVoices.find(
        (voice) => voice.utterance_id === pendingItem.utteranceId,
      );
      if (!nextVoice || (nextVoice.chunks?.length ?? 0) === 0) {
        return;
      }
    } else {
      nextVoice = sortedVoices.find(
        (voice) =>
          voice.source_event_id <= currentEventId &&
          voice.last_source_event_id >= currentEventId &&
          !consumedUtteranceIdsRef.current.has(voice.utterance_id) &&
          !activeUtteranceIdsRef.current.has(voice.utterance_id),
      );
    }
    if (!nextVoice) {
      return;
    }

    if (!pendingItem) {
      activeUtteranceIdsRef.current.add(nextVoice.utterance_id);
    }

    if ((nextVoice.chunks?.length ?? 0) === 0) {
      const utteranceId = nextVoice.utterance_id;
      if (!loadVoice) {
        markVoiceFailed(
          utteranceId,
          activeUtteranceIdsRef,
          consumedUtteranceIdsRef,
        );
        pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
        return;
      }
      const attempt = ++playbackAttemptRef.current;
      setPendingItem({ ...toQueueItem(nextVoice), status: "receiving" });
      void loadVoice(utteranceId)
        .then((loadedVoice) => {
          if (playbackAttemptRef.current !== attempt) {
            return;
          }
          if (
            loadedVoice.utterance_id !== utteranceId ||
            (loadedVoice.chunks?.length ?? 0) === 0
          ) {
            throw new Error("Playback voice has no audio chunks");
          }
          setLoadedVoicesById((current) => {
            const next = new Map(current);
            next.set(utteranceId, loadedVoice);
            return next;
          });
        })
        .catch(() => {
          if (playbackAttemptRef.current !== attempt) {
            return;
          }
          markVoiceFailed(
            utteranceId,
            activeUtteranceIdsRef,
            consumedUtteranceIdsRef,
          );
          setPendingItem((current) =>
            current?.utteranceId === utteranceId ? null : current,
          );
          pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
        });
      return;
    }

    if (!isPcmAudioFormat(nextVoice.audio_format)) {
      const utteranceId = nextVoice.utterance_id;
      try {
        releaseBlobAudio();
        const chunks = (nextVoice.chunks ?? [])
          .slice()
          .sort(compareChunks)
          .map((chunk) => chunk.data);
        const blob = base64ToBlob(chunks, nextVoice.mime_type);
        const objectUrl = createAudioObjectUrl(blob);
        const audio = audioElementRef.current ?? createAudioElement();
        let isReleased = false;

        const releaseCurrentAudio = () => {
          if (isReleased) {
            return;
          }
          isReleased = true;
          audio.removeEventListener("ended", handleEnded);
          audio.removeEventListener("error", handleError);
          try {
            audio.pause();
          } catch {
            // Pause cleanup is best-effort.
          }
          revokeAudioObjectUrl(objectUrl);
          if (audioElementRef.current === audio) {
            audioElementRef.current = null;
          }
        };
        const finishVoice = () => {
          releaseBlobAudio();
          activeUtteranceIdsRef.current.delete(utteranceId);
          consumedUtteranceIdsRef.current.add(utteranceId);
          setSubtitleClock((current) =>
            current?.utteranceId === utteranceId ? null : current,
          );
          setCurrentItem((current) =>
            current?.utteranceId === utteranceId ? null : current,
          );
          releaseLoadedVoice(utteranceId);
          recordPlaybackCompletion(toQueueItem(nextVoice));
        };
        function handleEnded() {
          finishVoice();
        }
        function handleError() {
          releaseBlobAudio();
          markVoiceFailed(
            utteranceId,
            activeUtteranceIdsRef,
            consumedUtteranceIdsRef,
          );
          setSubtitleClock((current) =>
            current?.utteranceId === utteranceId ? null : current,
          );
          setCurrentItem((current) =>
            current?.utteranceId === utteranceId ? null : current,
          );
          releaseLoadedVoice(utteranceId);
          pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
        }

        audio.addEventListener("ended", handleEnded);
        audio.addEventListener("error", handleError);
        audio.src = objectUrl;
        audioElementRef.current = audio;
        blobCleanupRef.current = releaseCurrentAudio;
        setCurrentItem(toQueueItem(nextVoice));
        setPendingItem(null);
      } catch {
        releaseBlobAudio();
        markVoiceFailed(utteranceId, activeUtteranceIdsRef, consumedUtteranceIdsRef);
        setSubtitleClock(null);
        setCurrentItem(null);
        setPendingItem(null);
        releaseLoadedVoice(utteranceId);
        pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
      }
      return;
    }

    const audio = ensureScheduler();
    if (!audio) {
      markVoiceFailed(nextVoice.utterance_id, activeUtteranceIdsRef, consumedUtteranceIdsRef);
      pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
      return;
    }

    const attempt = ++playbackAttemptRef.current;
    const queueItem = toQueueItem(nextVoice);
    setPendingItem({ ...queueItem, status: "ready" });
    void (async () => {
      try {
        if (audio.context.state !== "running") {
          await audio.context.resume();
        }
        await audio.scheduler.resume();
        const chunks = (nextVoice.chunks ?? []).slice().sort(compareChunks);
        let latestEndTime = audio.context.currentTime;
        for (const chunk of chunks) {
          if (playbackAttemptRef.current !== attempt) {
            return;
          }
          const scheduledChunk = await audio.scheduler.schedule(
            chunk.data,
            nextVoice.sample_rate,
          );
          if (!pcmSubtitleStartTimesRef.current.has(nextVoice.utterance_id)) {
            pcmSubtitleStartTimesRef.current.set(
              nextVoice.utterance_id,
              scheduledChunk.startTime,
            );
            setSubtitleClock({
              elapsedMs: Math.max(
                0,
                Math.round(
                  (audio.context.currentTime - scheduledChunk.startTime) * 1000,
                ),
              ),
              utteranceId: nextVoice.utterance_id,
            });
          }
          latestEndTime = Math.max(latestEndTime, scheduledChunk.endTime);
        }
        if (playbackAttemptRef.current !== attempt) {
          return;
        }
        pcmEndTimesRef.current.set(nextVoice.utterance_id, latestEndTime);
        setCurrentItem(queueItem);
        setPendingItem(null);
      } catch {
        if (playbackAttemptRef.current !== attempt) {
          return;
        }
        markVoiceFailed(nextVoice.utterance_id, activeUtteranceIdsRef, consumedUtteranceIdsRef);
        pcmEndTimesRef.current.delete(nextVoice.utterance_id);
        pcmSubtitleStartTimesRef.current.delete(nextVoice.utterance_id);
        setCurrentItem(null);
        setPendingItem(null);
        setSubtitleClock(null);
        releaseLoadedVoice(nextVoice.utterance_id);
        pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
      }
    })();
  }, [
    currentEventId,
    cursorVersion,
    currentItem,
    enabled,
    ensureScheduler,
    errors.length,
    isPaused,
    loadVoice,
    pendingItem,
    recordPlaybackCompletion,
    releaseLoadedVoice,
    releaseBlobAudio,
    sortedVoices,
  ]);

  useEffect(() => {
    if (
      !enabled ||
      isPaused ||
      !currentItem ||
      !isPcmAudioFormat(currentItem.audioFormat)
    ) {
      return;
    }

    const context = audioContextRef.current;
    const endTime = pcmEndTimesRef.current.get(currentItem.utteranceId);
    if (!context || endTime === undefined) {
      return;
    }

    let timeoutId: ReturnType<typeof globalThis.setTimeout> | null = null;
    const pollForCompletion = () => {
      if (timeoutId !== null) {
        completionTimeoutsRef.current.delete(timeoutId);
      }
      if (context.state === "running" && context.currentTime >= endTime) {
        finishPcmVoice(currentItem);
        return;
      }
      timeoutId = globalThis.setTimeout(
        pollForCompletion,
        PCM_COMPLETION_POLL_INTERVAL_MS,
      );
      completionTimeoutsRef.current.add(timeoutId);
    };

    timeoutId = globalThis.setTimeout(
      pollForCompletion,
      PCM_COMPLETION_POLL_INTERVAL_MS,
    );
    completionTimeoutsRef.current.add(timeoutId);

    return () => {
      if (timeoutId !== null) {
        globalThis.clearTimeout(timeoutId);
        completionTimeoutsRef.current.delete(timeoutId);
      }
    };
  }, [currentItem, enabled, finishPcmVoice, isPaused]);

  const currentSubtitle = useMemo<LiveVoiceSubtitle | null>(
    () =>
      currentSubtitleForItem({
        isPaused,
        item: currentItem,
        subtitleClock,
      }),
    [currentItem, isPaused, subtitleClock],
  );

  useEffect(() => {
    if (
      !enabled ||
      isPaused ||
      !currentItem ||
      currentItem.status !== "playing" ||
      currentItem.subtitleCues.length === 0
    ) {
      return;
    }

    const updateSubtitleClock = () => {
      const elapsedMs = subtitleElapsedMsForItem({
        audio: audioElementRef.current,
        context: audioContextRef.current,
        item: currentItem,
        pcmStartTimes: pcmSubtitleStartTimesRef.current,
      });
      if (elapsedMs === null) {
        return;
      }
      setSubtitleClock({
        elapsedMs,
        utteranceId: currentItem.utteranceId,
      });
    };

    updateSubtitleClock();
    const intervalId = globalThis.setInterval(
      updateSubtitleClock,
      SUBTITLE_CLOCK_POLL_INTERVAL_MS,
    );

    return () => {
      globalThis.clearInterval(intervalId);
    };
  }, [currentItem, enabled, isPaused]);

  useEffect(() => {
    const audio = audioElementRef.current;
    const utteranceId =
      currentItem && !isPcmAudioFormat(currentItem.audioFormat)
        ? currentItem.utteranceId
        : null;
    if (!enabled || !audio || utteranceId === null) {
      return;
    }

    if (isPaused) {
      try {
        audio.pause();
      } catch {
        // Pause is best-effort; resume still owns playback state.
      }
      return;
    }

    void Promise.resolve(audio.play()).catch(() => {
      releaseBlobAudio();
      markVoiceFailed(utteranceId, activeUtteranceIdsRef, consumedUtteranceIdsRef);
      setCurrentItem((current) =>
        current?.utteranceId === utteranceId ? null : current,
      );
      setSubtitleClock((current) =>
        current?.utteranceId === utteranceId ? null : current,
      );
      releaseLoadedVoice(utteranceId);
      pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
    });
  }, [
    currentItem,
    enabled,
    isPaused,
    releaseBlobAudio,
    releaseLoadedVoice,
  ]);

  useEffect(() => {
    if (
      !enabled ||
      isPaused ||
      !currentItem ||
      isPcmAudioFormat(currentItem.audioFormat) ||
      !audioElementRef.current
    ) {
      return;
    }

    const audio = audioElementRef.current;
    const utteranceId = currentItem.utteranceId;
    let lastCurrentTime = audio.currentTime;
    let lastProgressAt = Date.now();
    const intervalId = globalThis.setInterval(() => {
      if (audio.currentTime > lastCurrentTime) {
        lastCurrentTime = audio.currentTime;
        lastProgressAt = Date.now();
        return;
      }
      if (Date.now() - lastProgressAt < BLOB_PLAYBACK_STALL_TIMEOUT_MS) {
        return;
      }

      releaseBlobAudio();
      markVoiceFailed(
        utteranceId,
        activeUtteranceIdsRef,
        consumedUtteranceIdsRef,
      );
      setSubtitleClock((current) =>
        current?.utteranceId === utteranceId ? null : current,
      );
      setCurrentItem((current) =>
        current?.utteranceId === utteranceId ? null : current,
      );
      releaseLoadedVoice(utteranceId);
      pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
    }, BLOB_PLAYBACK_STALL_POLL_INTERVAL_MS);

    return () => {
      globalThis.clearInterval(intervalId);
    };
  }, [
    currentItem,
    enabled,
    isPaused,
    releaseBlobAudio,
    releaseLoadedVoice,
  ]);

  useEffect(() => {
    const scheduler = schedulerRef.current;
    if (!enabled || !scheduler) {
      return;
    }

    if (isPaused) {
      void scheduler.suspend().catch(() => {
        pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
      });
      return;
    }

    void scheduler.resume().catch(() => {
      pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
    });
  }, [enabled, isPaused]);

  useEffect(() => {
    if (enabled) {
      return;
    }
    playbackAttemptRef.current += 1;
    if (pendingItem) {
      markVoiceFailed(
        pendingItem.utteranceId,
        activeUtteranceIdsRef,
        consumedUtteranceIdsRef,
      );
      setPendingItem(null);
      releaseLoadedVoice(pendingItem.utteranceId);
    }
    if (currentItem) {
      markVoiceFailed(
        currentItem.utteranceId,
        activeUtteranceIdsRef,
        consumedUtteranceIdsRef,
      );
      pcmEndTimesRef.current.delete(currentItem.utteranceId);
      pcmSubtitleStartTimesRef.current.delete(currentItem.utteranceId);
      setCurrentItem(null);
      setSubtitleClock(null);
      releaseLoadedVoice(currentItem.utteranceId);
    }
    releaseBlobAudio();
    closeScheduler();
  }, [
    closeScheduler,
    currentItem,
    enabled,
    pendingItem,
    releaseBlobAudio,
    releaseLoadedVoice,
  ]);

  useEffect(
    () => () => {
      playbackAttemptRef.current += 1;
      releaseBlobAudio();
      closeScheduler();
    },
    [closeScheduler, releaseBlobAudio],
  );

  const visibleCurrentItem = currentItem ?? pendingItem;

  return {
    connectionState,
    currentItem: visibleCurrentItem,
    currentSpeakerName: isPaused ? null : visibleCurrentItem?.speakerName ?? null,
    currentSubtitle,
    errors,
    lastCompletedPlayback,
    retryAudio,
    unlockAudio,
  };
}

export function currentSubtitleForPlaybackVoices({
  currentEventId,
  elapsedMs,
  isPaused,
  voices,
}: {
  currentEventId: number | null;
  elapsedMs: number;
  isPaused: boolean;
  voices: PlaybackVoiceUtterance[];
}): LiveVoiceSubtitle | null {
  if (isPaused || currentEventId === null) {
    return null;
  }

  const voice = voices
    .filter(isSubtitlePlaybackVoice)
    .slice()
    .sort(comparePlaybackVoices)
    .find(
      (item) =>
        item.source_event_id <= currentEventId &&
        item.last_source_event_id >= currentEventId,
    );
  if (!voice) {
    return null;
  }

  const display = subtitleDisplayForElapsedMs(
    playbackSubtitleCues(voice),
    elapsedMs,
  );
  if (!display) {
    return null;
  }

  return {
    ...display,
    audience: voice.audience ?? "player_public",
    speakerKind: voice.speaker_kind,
    speakerName: voice.speaker_name,
    utteranceId: voice.utterance_id,
  };
}

function isPlaybackVoiceMetadata(voice: PlaybackVoiceUtterance) {
  return (
    (voice.speaker_kind === "player" || voice.speaker_kind === "judge") &&
    voice.audio_format.trim().length > 0 &&
    voice.mime_type.trim().length > 0 &&
    voice.sample_rate > 0
  );
}

function isSubtitlePlaybackVoice(voice: PlaybackVoiceUtterance) {
  return (
    (voice.speaker_kind === "player" || voice.speaker_kind === "judge") &&
    voice.subtitle_timings.length > 0
  );
}

function comparePlaybackVoices(left: PlaybackVoiceUtterance, right: PlaybackVoiceUtterance) {
  return (
    left.source_event_id - right.source_event_id ||
    left.utterance_id.localeCompare(right.utterance_id)
  );
}

function voiceCoversEvent(
  item: Pick<LiveVoiceQueueItem, "lastSourceEventId" | "sourceEventId">,
  eventId: number,
) {
  return item.sourceEventId <= eventId && item.lastSourceEventId >= eventId;
}

function compareChunks(left: PlaybackVoiceChunk, right: PlaybackVoiceChunk) {
  return left.chunk_index - right.chunk_index;
}

function subtitleTimingsKey(voice: PlaybackVoiceUtterance) {
  return (voice.subtitle_timings ?? [])
    .map((cue) => `${cue.start_ms}-${cue.end_ms}-${cue.text}`)
    .join(",");
}

function playbackSubtitleCues(
  voice: PlaybackVoiceUtterance,
): LiveVoiceSubtitleCue[] {
  const timings = voice.subtitle_timings ?? [];
  const starts = timings
    .map((cue) => cue.start_ms)
    .filter((startMs) => Number.isFinite(startMs));
  const offsetMs = starts.length > 0 ? Math.min(...starts) : 0;

  return timings.map((cue) => ({
    endMs: Math.max(0, Math.round(cue.end_ms - offsetMs)),
    startMs: Math.max(0, Math.round(cue.start_ms - offsetMs)),
    text: cue.text,
  }));
}

function toQueueItem(voice: PlaybackVoiceUtterance): LiveVoiceQueueItem {
  const chunkMetadata = (voice.chunks ?? []).slice().sort(compareChunks).map((chunk) => ({
    audioFormat: voice.audio_format,
    chunkIndex: chunk.chunk_index,
    data: chunk.data,
    sampleRate: voice.sample_rate,
  }));

  return {
    utteranceId: voice.utterance_id,
    sourceEventId: voice.source_event_id,
    lastSourceEventId: voice.last_source_event_id,
    audience: voice.audience ?? "player_public",
    speakerKind: voice.speaker_kind,
    speakerName: voice.speaker_name,
    mimeType: voice.mime_type,
    audioFormat: voice.audio_format,
    sampleRate: voice.sample_rate,
    chunks: chunkMetadata.map((chunk) => chunk.data),
    chunkMetadata,
    subtitleCues: playbackSubtitleCues(voice),
    isEnded: true,
    status: "playing",
  };
}

function base64ToBlob(chunks: string[], mimeType: string) {
  if (typeof globalThis.atob !== "function") {
    throw new Error("Base64 decoding is unavailable.");
  }
  if (typeof globalThis.Blob !== "function") {
    throw new Error("Blob creation is unavailable.");
  }

  const bytes = chunks.flatMap((chunk) =>
    Array.from(globalThis.atob(chunk), (character) =>
      character.charCodeAt(0),
    ),
  );
  return new globalThis.Blob([new Uint8Array(bytes)], { type: mimeType });
}

function createAudioObjectUrl(blob: Blob) {
  if (typeof globalThis.URL?.createObjectURL !== "function") {
    throw new Error("Object URL creation is unavailable.");
  }

  return globalThis.URL.createObjectURL(blob);
}

function revokeAudioObjectUrl(objectUrl: string) {
  if (typeof globalThis.URL?.revokeObjectURL !== "function") {
    return;
  }

  try {
    globalThis.URL.revokeObjectURL(objectUrl);
  } catch {
    // Cleanup is best-effort; playback progression should not depend on revoke.
  }
}

function createAudioElement() {
  if (typeof globalThis.document?.createElement !== "function") {
    throw new Error("Audio element creation is unavailable.");
  }

  const audio = globalThis.document.createElement("audio");
  if (typeof audio.play !== "function") {
    throw new Error("Audio playback is unavailable.");
  }

  return audio;
}

function markVoiceFailed(
  utteranceId: string,
  activeRef: MutableRefObject<Set<string>>,
  consumedRef: MutableRefObject<Set<string>>,
) {
  activeRef.current.delete(utteranceId);
  consumedRef.current.add(utteranceId);
}

function pushError(
  setErrors: Dispatch<SetStateAction<string[]>>,
  message: string,
) {
  setErrors((current) => [...current, message]);
}

function pushUniqueError(
  setErrors: Dispatch<SetStateAction<string[]>>,
  message: string,
) {
  setErrors((current) => (current.includes(message) ? current : [...current, message]));
}
