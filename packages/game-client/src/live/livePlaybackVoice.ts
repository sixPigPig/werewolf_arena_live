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

export function usePlaybackVoice(
  voices: PlaybackVoiceUtterance[],
  {
    currentEventId,
    enabled,
    isPaused,
  }: {
    currentEventId: number | null;
    enabled: boolean;
    isPaused: boolean;
  },
) {
  const sortedVoices = useMemo(
    () =>
      voices
        .filter(isPlayablePlaybackVoice)
        .slice()
        .sort(comparePlaybackVoices),
    [voices],
  );
  const voicesKey = useMemo(
    () =>
      sortedVoices
        .map(
          (voice) =>
            [
              voice.utterance_id,
              voice.source_event_id,
              voice.last_source_event_id,
              voice.chunks.length,
              subtitleTimingsKey(voice),
            ].join(":"),
        )
        .join("|"),
    [sortedVoices],
  );
  const [errors, setErrors] = useState<string[]>([]);
  const [currentItem, setCurrentItem] = useState<LiveVoiceQueueItem | null>(null);
  const [subtitleClock, setSubtitleClock] =
    useState<LiveVoiceSubtitleClock>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const blobCleanupRef = useRef<(() => void) | null>(null);
  const schedulerRef = useRef<PcmAudioScheduler | null>(null);
  const pcmSubtitleStartTimesRef = useRef<Map<string, number>>(new Map());
  const consumedUtteranceIdsRef = useRef<Set<string>>(new Set());
  const activeUtteranceIdsRef = useRef<Set<string>>(new Set());
  const previousVoicesKeyRef = useRef(voicesKey);
  const completionTimeoutsRef = useRef<Set<ReturnType<typeof globalThis.setTimeout>>>(
    new Set(),
  );

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
    pcmSubtitleStartTimesRef.current.clear();
    setSubtitleClock(null);
    for (const timeoutId of completionTimeoutsRef.current) {
      globalThis.clearTimeout(timeoutId);
    }
    completionTimeoutsRef.current.clear();
    void scheduler?.close().catch(() => undefined);
  }, []);

  const releaseBlobAudio = useCallback(() => {
    const cleanup = blobCleanupRef.current;
    blobCleanupRef.current = null;
    cleanup?.();
  }, []);

  const unlockAudio = useCallback(async () => {
    if (sortedVoices.length === 0) {
      pushUniqueError(setErrors, PLAYBACK_VOICE_EMPTY_MESSAGE);
      return false;
    }

    if (!hasPcmVoice) {
      return true;
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

  useEffect(() => {
    if (previousVoicesKeyRef.current === voicesKey) {
      return;
    }
    previousVoicesKeyRef.current = voicesKey;
    releaseBlobAudio();
    closeScheduler();
    consumedUtteranceIdsRef.current.clear();
    activeUtteranceIdsRef.current.clear();
    setCurrentItem(null);
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

    const nextVoice = sortedVoices.find(
      (voice) =>
        voice.last_source_event_id <= currentEventId &&
        !consumedUtteranceIdsRef.current.has(voice.utterance_id) &&
        !activeUtteranceIdsRef.current.has(voice.utterance_id),
    );
    if (!nextVoice) {
      return;
    }

    activeUtteranceIdsRef.current.add(nextVoice.utterance_id);

    if (!isPcmAudioFormat(nextVoice.audio_format)) {
      const utteranceId = nextVoice.utterance_id;
      try {
        releaseBlobAudio();
        const chunks = nextVoice.chunks
          .slice()
          .sort(compareChunks)
          .map((chunk) => chunk.data);
        const blob = base64ToBlob(chunks, nextVoice.mime_type);
        const objectUrl = createAudioObjectUrl(blob);
        const audio = createAudioElement();
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
          pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
        }

        audio.addEventListener("ended", handleEnded);
        audio.addEventListener("error", handleError);
        audio.src = objectUrl;
        audioElementRef.current = audio;
        blobCleanupRef.current = releaseCurrentAudio;
        setCurrentItem(toQueueItem(nextVoice));
      } catch {
        releaseBlobAudio();
        markVoiceFailed(utteranceId, activeUtteranceIdsRef, consumedUtteranceIdsRef);
        setSubtitleClock(null);
        setCurrentItem(null);
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

    let isActive = true;
    void (async () => {
      try {
        if (audio.context.state !== "running") {
          await audio.context.resume();
        }
        await audio.scheduler.resume();
        const chunks = nextVoice.chunks.slice().sort(compareChunks);
        let latestEndTime = audio.context.currentTime;
        for (const chunk of chunks) {
          if (!isActive) {
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
        if (!isActive) {
          return;
        }
        setCurrentItem(toQueueItem(nextVoice));
        const delayMs = Math.max(
          PCM_COMPLETION_POLL_INTERVAL_MS,
          (latestEndTime - audio.context.currentTime) * 1000,
        );
        const timeoutId = globalThis.setTimeout(() => {
          completionTimeoutsRef.current.delete(timeoutId);
          activeUtteranceIdsRef.current.delete(nextVoice.utterance_id);
          consumedUtteranceIdsRef.current.add(nextVoice.utterance_id);
          pcmSubtitleStartTimesRef.current.delete(nextVoice.utterance_id);
          setSubtitleClock((current) =>
            current?.utteranceId === nextVoice.utterance_id ? null : current,
          );
          setCurrentItem((current) =>
            current?.utteranceId === nextVoice.utterance_id ? null : current,
          );
        }, delayMs);
        completionTimeoutsRef.current.add(timeoutId);
      } catch {
        markVoiceFailed(nextVoice.utterance_id, activeUtteranceIdsRef, consumedUtteranceIdsRef);
        pcmSubtitleStartTimesRef.current.delete(nextVoice.utterance_id);
        setCurrentItem(null);
        setSubtitleClock(null);
        pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
      }
    })();

    return () => {
      isActive = false;
    };
  }, [
    currentEventId,
    currentItem,
    enabled,
    ensureScheduler,
    isPaused,
    releaseBlobAudio,
    sortedVoices,
  ]);

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
      pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
    });
  }, [currentItem, enabled, isPaused, releaseBlobAudio]);

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
    releaseBlobAudio();
    closeScheduler();
  }, [closeScheduler, enabled, releaseBlobAudio]);

  useEffect(
    () => () => {
      releaseBlobAudio();
      closeScheduler();
    },
    [closeScheduler, releaseBlobAudio],
  );

  return {
    connectionState,
    currentItem,
    currentSpeakerName: isPaused ? null : currentItem?.speakerName ?? null,
    currentSubtitle,
    errors,
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
    .find((item) => item.last_source_event_id === currentEventId);
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
    speakerKind: voice.speaker_kind,
    speakerName: voice.speaker_name,
    utteranceId: voice.utterance_id,
  };
}

function isPlayablePlaybackVoice(voice: PlaybackVoiceUtterance) {
  return (
    (voice.speaker_kind === "player" || voice.speaker_kind === "judge") &&
    voice.audio_format.trim().length > 0 &&
    voice.mime_type.trim().length > 0 &&
    voice.sample_rate > 0 &&
    voice.chunks.length > 0
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
  const chunkMetadata = voice.chunks.slice().sort(compareChunks).map((chunk) => ({
    audioFormat: voice.audio_format,
    chunkIndex: chunk.chunk_index,
    data: chunk.data,
    sampleRate: voice.sample_rate,
  }));

  return {
    utteranceId: voice.utterance_id,
    sourceEventId: voice.source_event_id,
    lastSourceEventId: voice.last_source_event_id,
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
