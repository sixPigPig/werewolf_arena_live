import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";

import {
  createPcmAudioScheduler,
  type PcmAudioScheduler,
} from "./livePcmPlayer";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const STALE_EVENT_DISTANCE = 8;
const VOICE_STREAM_UNAVAILABLE_ERROR =
  "Live voice streaming is unavailable in this browser.";

export type LiveVoiceConnectionState =
  | "idle"
  | "connecting"
  | "open"
  | "error"
  | "closed"
  | "unavailable";

export type LiveVoiceMessage =
  | {
      type: "voice_start";
      utterance_id: string;
      source_event_id: number;
      speaker_kind: "player" | "judge";
      speaker_name: string;
      mime_type: string;
      audio_format: string;
      sample_rate: number;
    }
  | {
      type: "audio_chunk";
      utterance_id: string;
      mime_type: string;
      chunk_index: number;
      audio_format: string;
      sample_rate: number;
      data: string;
    }
  | {
      type: "voice_end";
      utterance_id: string;
      duration_ms: number;
    }
  | {
      type: "voice_error";
      utterance_id?: string;
      source_event_id?: number;
      message: string;
    }
  | {
      type: "voice_unavailable";
    };

export type LiveVoiceChunk = {
  audioFormat: string;
  chunkIndex: number;
  data: string;
  sampleRate: number;
};

export type LiveVoiceQueueItem = {
  utteranceId: string;
  sourceEventId: number;
  speakerKind: "player" | "judge";
  speakerName: string;
  mimeType: string;
  audioFormat: string;
  sampleRate: number;
  chunks: string[];
  chunkMetadata: LiveVoiceChunk[];
  isEnded: boolean;
  status: "receiving" | "ready" | "playing" | "played" | "error";
};

export type LiveVoiceQueue = {
  items: LiveVoiceQueueItem[];
  errors: string[];
};

type VoiceQueueAction =
  | LiveVoiceMessage
  | {
      type: "queue_error";
      message: string;
    }
  | {
      type: "reset";
    }
  | {
      type: "utterance_played";
      utteranceId: string;
    }
  | {
      type: "utterance_started";
      utteranceId: string;
    };

export function resolveVoiceStreamUrl(runId: string, baseUrl = API_BASE_URL) {
  const fallbackOrigin =
    typeof window === "undefined" ? "http://localhost" : window.location.origin;
  const base = resolveUrlBase(baseUrl, fallbackOrigin);
  const voiceStreamPath = `/api/v1/games/runs/${encodeURIComponent(runId)}/voice-stream`;
  base.pathname = joinUrlPaths(base.pathname, voiceStreamPath);
  base.search = "";
  base.hash = "";

  if (base.protocol === "https:") {
    base.protocol = "wss:";
  } else if (base.protocol === "http:") {
    base.protocol = "ws:";
  }

  return base.toString();
}

function resolveUrlBase(baseUrl: string, fallbackOrigin: string) {
  const normalizedBaseUrl = baseUrl.trim();
  if (!normalizedBaseUrl) {
    return new URL(fallbackOrigin);
  }

  try {
    return new URL(normalizedBaseUrl);
  } catch {
    const relativeBase = normalizedBaseUrl.startsWith("/")
      ? normalizedBaseUrl
      : `/${normalizedBaseUrl}`;
    return new URL(relativeBase, `${fallbackOrigin}/`);
  }
}

function joinUrlPaths(prefix: string, path: string) {
  const trimmedPrefix = prefix.replace(/\/+$/, "");
  if (!trimmedPrefix) {
    return path;
  }
  return `${trimmedPrefix}${path}`;
}

export function createVoiceQueue(): LiveVoiceQueue {
  return { items: [], errors: [] };
}

export function enqueueVoiceMessage(
  queue: LiveVoiceQueue,
  message: LiveVoiceMessage,
): LiveVoiceQueue {
  if (message.type === "voice_unavailable") {
    return queue;
  }

  if (message.type === "voice_error") {
    return {
      ...queue,
      errors: [...queue.errors, message.message],
      items: message.utterance_id
        ? queue.items.map((item) =>
            item.utteranceId === message.utterance_id
              ? { ...item, status: "error" }
              : item,
          )
        : queue.items,
    };
  }

  if (message.type === "voice_start") {
    const existingItem = queue.items.find(
      (item) => item.utteranceId === message.utterance_id,
    );
    if (existingItem) {
      if (
        existingItem.status === "playing" ||
        existingItem.status === "played"
      ) {
        return queue;
      }

      return {
        ...queue,
        items: queue.items.map((item) =>
          item.utteranceId === message.utterance_id
            ? {
                ...item,
                sourceEventId: message.source_event_id,
                speakerKind: message.speaker_kind,
                speakerName: message.speaker_name,
                mimeType: message.mime_type,
                audioFormat: message.audio_format,
                sampleRate: message.sample_rate,
                isEnded: false,
                status: "receiving",
              }
            : item,
        ),
      };
    }

    return {
      ...queue,
      items: [
        ...queue.items,
        {
          utteranceId: message.utterance_id,
          sourceEventId: message.source_event_id,
          speakerKind: message.speaker_kind,
          speakerName: message.speaker_name,
          mimeType: message.mime_type,
          audioFormat: message.audio_format,
          sampleRate: message.sample_rate,
          chunks: [],
          chunkMetadata: [],
          isEnded: false,
          status: "receiving",
        },
      ],
    };
  }

  if (message.type === "audio_chunk") {
    return {
      ...queue,
      items: queue.items.map((item) =>
        item.utteranceId === message.utterance_id &&
        item.status !== "played" &&
        item.status !== "error"
          ? {
              ...item,
              chunks: [...item.chunks, message.data],
              chunkMetadata: [
                ...item.chunkMetadata,
                {
                  audioFormat: message.audio_format,
                  chunkIndex: message.chunk_index,
                  data: message.data,
                  sampleRate: message.sample_rate,
                },
              ],
            }
          : item,
      ),
    };
  }

  return {
    ...queue,
    items: queue.items.map((item) =>
      item.utteranceId === message.utterance_id &&
      item.status !== "playing" &&
      item.status !== "played"
        ? { ...item, isEnded: true, status: "ready" }
        : item.utteranceId === message.utterance_id &&
            item.status === "playing"
          ? { ...item, isEnded: true }
        : item,
    ),
  };
}

export function pruneStaleVoiceQueue(
  queue: LiveVoiceQueue,
  currentEventId: number | null,
): LiveVoiceQueue {
  if (currentEventId === null) {
    return queue;
  }

  return {
    ...queue,
    items: queue.items.filter(
      (item) =>
        item.speakerKind === "player" ||
        currentEventId - item.sourceEventId <= STALE_EVENT_DISTANCE,
    ),
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

function isPcmAudioFormat(audioFormat: string) {
  return audioFormat.toLowerCase() === "pcm";
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

function voiceQueueReducer(
  queue: LiveVoiceQueue,
  action: VoiceQueueAction,
): LiveVoiceQueue {
  if (action.type === "reset") {
    return createVoiceQueue();
  }

  if (action.type === "utterance_played") {
    return {
      ...queue,
      items: queue.items.map((item) =>
        item.utteranceId === action.utteranceId
          ? { ...item, chunks: [], chunkMetadata: [], status: "played" }
          : item,
      ),
    };
  }

  if (action.type === "utterance_started") {
    return {
      ...queue,
      items: queue.items.map((item) =>
        item.utteranceId === action.utteranceId &&
        item.status !== "played" &&
        item.status !== "error"
          ? { ...item, status: "playing" }
          : item,
      ),
    };
  }

  if (action.type === "queue_error") {
    return { ...queue, errors: [...queue.errors, action.message] };
  }

  return enqueueVoiceMessage(queue, action);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isSpeakerKind(value: unknown): value is "player" | "judge" {
  return value === "player" || value === "judge";
}

function isLiveVoiceMessage(value: unknown): value is LiveVoiceMessage {
  if (!isRecord(value) || typeof value.type !== "string") {
    return false;
  }

  if (value.type === "voice_unavailable") {
    return true;
  }

  if (value.type === "voice_start") {
    return (
      typeof value.utterance_id === "string" &&
      typeof value.source_event_id === "number" &&
      isSpeakerKind(value.speaker_kind) &&
      typeof value.speaker_name === "string" &&
      typeof value.mime_type === "string" &&
      typeof value.audio_format === "string" &&
      typeof value.sample_rate === "number"
    );
  }

  if (value.type === "audio_chunk") {
    return (
      typeof value.utterance_id === "string" &&
      typeof value.mime_type === "string" &&
      typeof value.chunk_index === "number" &&
      typeof value.audio_format === "string" &&
      typeof value.sample_rate === "number" &&
      typeof value.data === "string"
    );
  }

  if (value.type === "voice_end") {
    return (
      typeof value.utterance_id === "string" &&
      typeof value.duration_ms === "number"
    );
  }

  if (value.type === "voice_error") {
    return typeof value.message === "string";
  }

  return false;
}

export function useLiveVoiceStream(
  runId: string | undefined,
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
  const [connectionState, setConnectionState] =
    useState<LiveVoiceConnectionState>(
      enabled && runId ? "connecting" : "idle",
    );
  const [queue, dispatch] = useReducer(
    voiceQueueReducer,
    undefined,
    createVoiceQueue,
  );
  const streamUrl = useMemo(
    () => (runId ? resolveVoiceStreamUrl(runId) : null),
    [runId],
  );
  const visibleQueue = useMemo(
    () => pruneStaleVoiceQueue(queue, currentEventId),
    [currentEventId, queue],
  );
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const pcmSchedulerRef = useRef<PcmAudioScheduler | null>(null);
  const pcmCompletionTimeoutRef = useRef<number | null>(null);
  const pcmEndTimesRef = useRef<Map<string, number>>(new Map());
  const scheduledPcmChunkIndexesRef = useRef<Map<string, Set<number>>>(
    new Map(),
  );
  const consumedUtteranceIdsRef = useRef<Set<string>>(new Set());
  const clearPcmCompletionTimeout = useCallback(() => {
    if (pcmCompletionTimeoutRef.current === null) {
      return;
    }
    globalThis.clearTimeout(pcmCompletionTimeoutRef.current);
    pcmCompletionTimeoutRef.current = null;
  }, []);
  const closePcmScheduler = useCallback(() => {
    const scheduler = pcmSchedulerRef.current;
    audioContextRef.current = null;
    pcmSchedulerRef.current = null;
    pcmEndTimesRef.current.clear();
    scheduledPcmChunkIndexesRef.current.clear();
    clearPcmCompletionTimeout();
    void scheduler?.close().catch(() => {
      // AudioContext cleanup is best-effort.
    });
  }, [clearPcmCompletionTimeout]);
  const ensurePcmScheduler = useCallback(() => {
    if (audioContextRef.current && pcmSchedulerRef.current) {
      return {
        context: audioContextRef.current,
        scheduler: pcmSchedulerRef.current,
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
    pcmSchedulerRef.current = scheduler;

    return { context, scheduler };
  }, []);
  const unlockAudio = useCallback(async () => {
    const pcmAudio = ensurePcmScheduler();
    if (!pcmAudio) {
      dispatch({
        type: "queue_error",
        message: "当前浏览器不支持语音播放。",
      });
      return false;
    }

    try {
      if (pcmAudio.context.state !== "running") {
        await pcmAudio.context.resume();
      }
      await pcmAudio.scheduler.resume();
      return true;
    } catch {
      dispatch({
        type: "queue_error",
        message: "Unable to play live voice audio.",
      });
      return false;
    }
  }, [ensurePcmScheduler]);
  const isConsumableItem = (item: LiveVoiceQueueItem) =>
    !consumedUtteranceIdsRef.current.has(item.utteranceId);
  const hasReachedSourceEvent = (item: LiveVoiceQueueItem) =>
    currentEventId !== null && currentEventId >= item.sourceEventId;
  const isActivePlaybackItem = (item: LiveVoiceQueueItem) =>
    isConsumableItem(item) && hasReachedSourceEvent(item);
  const currentItem =
    visibleQueue.items.find(
      (item) => item.status === "playing" && isConsumableItem(item),
    ) ??
    visibleQueue.items.find(
      (item) => item.status === "ready" && isActivePlaybackItem(item),
    ) ??
    visibleQueue.items.find(
      (item) => item.status === "receiving" && isActivePlaybackItem(item),
    ) ??
    null;
  const blobPlaybackKey =
    currentItem &&
    !isPcmAudioFormat(currentItem.audioFormat) &&
    (currentItem.status === "ready" || currentItem.status === "playing")
      ? currentItem.utteranceId
      : null;
  const pcmPlaybackKey =
    currentItem && isPcmAudioFormat(currentItem.audioFormat)
      ? [
          currentItem.utteranceId,
          currentItem.status,
          currentItem.chunkMetadata.length,
          currentItem.isEnded ? "ended" : "receiving",
        ].join(":")
      : null;

  useEffect(() => {
    if (
      !enabled ||
      !currentItem ||
      !pcmPlaybackKey ||
      (!isActivePlaybackItem(currentItem) && currentItem.status !== "playing")
    ) {
      return;
    }

    let isActive = true;

    const consumeUtterance = () => {
      consumedUtteranceIdsRef.current.add(currentItem.utteranceId);
      scheduledPcmChunkIndexesRef.current.delete(currentItem.utteranceId);
      pcmEndTimesRef.current.delete(currentItem.utteranceId);
      dispatch({
        type: "utterance_played",
        utteranceId: currentItem.utteranceId,
      });
    };

    const reportPlaybackError = () => {
      if (!isActive) {
        return;
      }
      dispatch({
        type: "queue_error",
        message: "Unable to play live voice audio.",
      });
      consumeUtterance();
    };

    const scheduleCompletion = (context: AudioContext, endTime: number) => {
      clearPcmCompletionTimeout();
      const delayMs = Math.max(0, (endTime - context.currentTime) * 1000) + 20;
      pcmCompletionTimeoutRef.current = globalThis.setTimeout(() => {
        if (!isActive) {
          return;
        }
        consumeUtterance();
      }, delayMs);
    };

    const schedulePcmChunks = async () => {
      const pcmAudio = ensurePcmScheduler();
      if (!pcmAudio) {
        dispatch({
          type: "queue_error",
          message: "当前浏览器不支持语音播放。",
        });
        consumeUtterance();
        return;
      }

      try {
        const scheduledIndexes =
          scheduledPcmChunkIndexesRef.current.get(currentItem.utteranceId) ??
          new Set<number>();
        scheduledPcmChunkIndexesRef.current.set(
          currentItem.utteranceId,
          scheduledIndexes,
        );

        let didSchedule = false;
        let latestEndTime =
          pcmEndTimesRef.current.get(currentItem.utteranceId) ??
          pcmAudio.context.currentTime;
        const chunks = [...currentItem.chunkMetadata].sort(
          (left, right) => left.chunkIndex - right.chunkIndex,
        );
        const pendingChunks = chunks.filter(
          (chunk) => !scheduledIndexes.has(chunk.chunkIndex),
        );

        if (!isPaused && pendingChunks.length > 0) {
          if (pcmAudio.context.state !== "running") {
            await pcmAudio.context.resume();
          }
          await pcmAudio.scheduler.resume();
        }

        for (const chunk of pendingChunks) {
          scheduledIndexes.add(chunk.chunkIndex);
          const scheduledChunk = await pcmAudio.scheduler.schedule(
            chunk.data,
            chunk.sampleRate,
          );
          if (!isActive) {
            return;
          }
          didSchedule = true;
          latestEndTime = Math.max(latestEndTime, scheduledChunk.endTime);
        }

        if (didSchedule && currentItem.status !== "playing") {
          dispatch({
            type: "utterance_started",
            utteranceId: currentItem.utteranceId,
          });
        }

        pcmEndTimesRef.current.set(currentItem.utteranceId, latestEndTime);

        if (currentItem.isEnded && scheduledIndexes.size >= chunks.length) {
          scheduleCompletion(pcmAudio.context, latestEndTime);
        }
      } catch {
        reportPlaybackError();
      }
    };

    void schedulePcmChunks();

    return () => {
      isActive = false;
    };
  }, [
    clearPcmCompletionTimeout,
    currentItem,
    enabled,
    ensurePcmScheduler,
    isPaused,
    pcmPlaybackKey,
  ]);

  useEffect(() => {
    if (!enabled || !currentItem || currentItem.status !== "ready") {
      return;
    }

    let isActive = true;
    let isReleased = false;
    let isConsumed = false;
    let objectUrl: string | null = null;
    let audio: HTMLAudioElement | null = null;

    const consumeUtterance = () => {
      if (isConsumed) {
        return;
      }
      isConsumed = true;
      consumedUtteranceIdsRef.current.add(currentItem.utteranceId);
      dispatch({
        type: "utterance_played",
        utteranceId: currentItem.utteranceId,
      });
    };

    const releaseAudio = () => {
      if (isReleased) {
        return;
      }
      isReleased = true;
      try {
        audio?.pause();
      } catch {
        // Pause cleanup is best-effort.
      }
      if (objectUrl) {
        revokeAudioObjectUrl(objectUrl);
      }
      if (audioRef.current === audio) {
        audioRef.current = null;
      }
    };

    const markPlayed = () => {
      if (!isActive) {
        return;
      }
      releaseAudio();
      consumeUtterance();
    };

    const reportPlaybackError = () => {
      if (!isActive) {
        return;
      }
      releaseAudio();
      dispatch({
        type: "queue_error",
        message: "Unable to play live voice audio.",
      });
      consumeUtterance();
    };

    try {
      const blob = base64ToBlob(currentItem.chunks, currentItem.mimeType);
      objectUrl = createAudioObjectUrl(blob);
      audio = createAudioElement();
      audio.src = objectUrl;
      audioRef.current = audio;
      audio.addEventListener("ended", markPlayed);
      dispatch({
        type: "utterance_started",
        utteranceId: currentItem.utteranceId,
      });
    } catch {
      reportPlaybackError();
      return;
    }

    return () => {
      isActive = false;
      audio?.removeEventListener("ended", markPlayed);
      releaseAudio();
    };
  }, [blobPlaybackKey, enabled]);

  useEffect(() => {
    if (!enabled || !blobPlaybackKey || !audioRef.current) {
      return;
    }

    let isActive = true;
    const audio = audioRef.current;
    const reportPlaybackError = () => {
      if (!isActive) {
        return;
      }
      consumedUtteranceIdsRef.current.add(blobPlaybackKey);
      dispatch({
        type: "queue_error",
        message: "Unable to play live voice audio.",
      });
      dispatch({
        type: "utterance_played",
        utteranceId: blobPlaybackKey,
      });
    };

    if (isPaused) {
      try {
        audio.pause();
      } catch {
        // Pause is best-effort; the next resume still owns playback state.
      }
    } else {
      void Promise.resolve(audio.play()).catch(reportPlaybackError);
    }

    return () => {
      isActive = false;
    };
  }, [blobPlaybackKey, enabled, isPaused]);

  useEffect(() => {
    if (!enabled || !pcmSchedulerRef.current) {
      return;
    }

    let isActive = true;
    const reportPlaybackError = () => {
      if (!isActive) {
        return;
      }
      dispatch({
        type: "queue_error",
        message: "Unable to play live voice audio.",
      });
    };

    if (isPaused) {
      void pcmSchedulerRef.current.suspend().catch(reportPlaybackError);
    } else {
      void pcmSchedulerRef.current.resume().catch(reportPlaybackError);
    }

    return () => {
      isActive = false;
    };
  }, [enabled, isPaused, pcmPlaybackKey]);

  useEffect(() => {
    if (!enabled) {
      closePcmScheduler();
    }
  }, [closePcmScheduler, enabled]);

  useEffect(() => {
    return () => {
      closePcmScheduler();
    };
  }, [closePcmScheduler, streamUrl]);

  useEffect(() => {
    consumedUtteranceIdsRef.current.clear();
    dispatch({ type: "reset" });

    if (!enabled || !streamUrl) {
      setConnectionState("idle");
      return;
    }

    const WebSocketConstructor = globalThis.WebSocket;
    if (typeof WebSocketConstructor !== "function") {
      setConnectionState("unavailable");
      dispatch({
        type: "queue_error",
        message: VOICE_STREAM_UNAVAILABLE_ERROR,
      });
      return;
    }

    let isActive = true;
    let hasError = false;
    let socketHadError = false;
    let retryCount = 0;
    let socket: WebSocket | null = null;

    const reportError = (
      message: string,
      state: LiveVoiceConnectionState = "error",
    ) => {
      if (!isActive) {
        return;
      }
      hasError = true;
      setConnectionState(state);
      dispatch({ type: "queue_error", message });
    };

    const openSocket = () => {
      setConnectionState("connecting");

      let nextSocket: WebSocket;
      try {
        nextSocket = new WebSocketConstructor(streamUrl);
      } catch {
        reportError("Unable to open live voice stream.");
        return;
      }

      socket = nextSocket;
      socketHadError = false;
      nextSocket.onopen = () => {
        if (isActive) {
          setConnectionState("open");
        }
      };
      nextSocket.onerror = () => {
        socketHadError = true;
        if (retryCount >= 1) {
          reportError("Live voice stream connection failed.");
        }
      };
      nextSocket.onclose = () => {
        if (!isActive || hasError) {
          return;
        }
        if (retryCount < 1) {
          retryCount += 1;
          openSocket();
          return;
        }
        if (socketHadError) {
          reportError("Live voice stream connection failed.");
          return;
        }
        setConnectionState("closed");
      };
      nextSocket.onmessage = (event) => {
        if (!isActive) {
          return;
        }

        let parsed: unknown;
        try {
          parsed = JSON.parse(String(event.data));
        } catch {
          reportError("Malformed voice stream message.");
          return;
        }

        if (!isLiveVoiceMessage(parsed)) {
          reportError("Malformed voice stream message.");
          return;
        }

        if (parsed.type === "voice_unavailable") {
          isActive = false;
          setConnectionState("unavailable");
          dispatch({
            type: "queue_error",
            message: "Live voice streaming is unavailable.",
          });
          nextSocket.close();
          return;
        }

        dispatch(parsed);
      };
    };

    openSocket();

    return () => {
      isActive = false;
      socket?.close();
    };
  }, [enabled, streamUrl]);

  return {
    connectionState,
    currentSpeakerName: isPaused ? null : currentItem?.speakerName ?? null,
    currentItem,
    errors: visibleQueue.errors,
    unlockAudio,
  };
}
