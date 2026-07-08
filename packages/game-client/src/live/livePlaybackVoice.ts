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
} from "./liveVoiceStream";
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
        .map((voice) => `${voice.utterance_id}:${voice.source_event_id}:${voice.chunks.length}`)
        .join("|"),
    [sortedVoices],
  );
  const [errors, setErrors] = useState<string[]>([]);
  const [currentItem, setCurrentItem] = useState<LiveVoiceQueueItem | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const schedulerRef = useRef<PcmAudioScheduler | null>(null);
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
    for (const timeoutId of completionTimeoutsRef.current) {
      globalThis.clearTimeout(timeoutId);
    }
    completionTimeoutsRef.current.clear();
    void scheduler?.close().catch(() => undefined);
  }, []);

  const unlockAudio = useCallback(async () => {
    if (sortedVoices.length === 0) {
      pushUniqueError(setErrors, PLAYBACK_VOICE_EMPTY_MESSAGE);
      return false;
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
  }, [ensureScheduler, sortedVoices.length]);

  useEffect(() => {
    if (previousVoicesKeyRef.current === voicesKey) {
      return;
    }
    previousVoicesKeyRef.current = voicesKey;
    consumedUtteranceIdsRef.current.clear();
    activeUtteranceIdsRef.current.clear();
    setCurrentItem(null);
    setErrors([]);
  }, [voicesKey]);

  useEffect(() => {
    if (!enabled || sortedVoices.length > 0) {
      return;
    }
    pushUniqueError(setErrors, PLAYBACK_VOICE_EMPTY_MESSAGE);
  }, [enabled, sortedVoices.length]);

  useEffect(() => {
    if (!enabled || isPaused || currentEventId === null) {
      return;
    }

    const nextVoice = sortedVoices.find(
      (voice) =>
        voice.source_event_id <= currentEventId &&
        !consumedUtteranceIdsRef.current.has(voice.utterance_id) &&
        !activeUtteranceIdsRef.current.has(voice.utterance_id),
    );
    if (!nextVoice) {
      return;
    }

    const audio = ensureScheduler();
    if (!audio) {
      markVoiceFailed(nextVoice.utterance_id, activeUtteranceIdsRef, consumedUtteranceIdsRef);
      pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
      return;
    }

    activeUtteranceIdsRef.current.add(nextVoice.utterance_id);
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
          setCurrentItem((current) =>
            current?.utteranceId === nextVoice.utterance_id ? null : current,
          );
        }, delayMs);
        completionTimeoutsRef.current.add(timeoutId);
      } catch {
        markVoiceFailed(nextVoice.utterance_id, activeUtteranceIdsRef, consumedUtteranceIdsRef);
        setCurrentItem(null);
        pushError(setErrors, PLAYBACK_VOICE_ERROR_MESSAGE);
      }
    })();

    return () => {
      isActive = false;
    };
  }, [currentEventId, enabled, ensureScheduler, isPaused, sortedVoices]);

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
    closeScheduler();
  }, [closeScheduler, enabled]);

  useEffect(() => closeScheduler, [closeScheduler]);

  return {
    connectionState,
    currentItem,
    currentSpeakerName: isPaused ? null : currentItem?.speakerName ?? null,
    errors,
    unlockAudio,
  };
}

function isPlayablePlaybackVoice(voice: PlaybackVoiceUtterance) {
  return (
    (voice.speaker_kind === "player" || voice.speaker_kind === "judge") &&
    voice.audio_format.toLowerCase() === "pcm" &&
    voice.sample_rate > 0 &&
    voice.chunks.length > 0
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
    speakerKind: voice.speaker_kind,
    speakerName: voice.speaker_name,
    mimeType: voice.mime_type,
    audioFormat: voice.audio_format,
    sampleRate: voice.sample_rate,
    chunks: chunkMetadata.map((chunk) => chunk.data),
    chunkMetadata,
    isEnded: true,
    status: "playing",
  };
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
