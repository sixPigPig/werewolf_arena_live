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
import {
  SUBTITLE_CLOCK_POLL_INTERVAL_MS,
  currentSubtitleForItem,
  isPcmAudioFormat,
  subtitleElapsedMsForItem,
  type LiveVoiceSubtitleClock,
} from "./liveVoiceSubtitleClock";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const STALE_EVENT_DISTANCE = 8;
const PCM_COMPLETION_POLL_INTERVAL_MS = 25;
const BLOB_PLAYBACK_STALL_POLL_INTERVAL_MS = 1000;
const BLOB_PLAYBACK_STALL_TIMEOUT_MS = 30_000;
const VOICE_STREAM_UNAVAILABLE_ERROR =
  "当前浏览器不支持语音连接。";
const VOICE_STREAM_SERVER_UNAVAILABLE_ERROR = "语音服务暂不可用，请稍后重试。";

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
      last_source_event_id?: number;
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
      type: "subtitle_timing";
      utterance_id: string;
      cues: {
        end_ms: number;
        start_ms: number;
        text: string;
      }[];
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
      reason?: string;
      message?: string;
    };

export type LiveVoiceChunk = {
  audioFormat: string;
  chunkIndex: number;
  data: string;
  sampleRate: number;
};

export type LiveVoiceSubtitleCue = {
  endMs: number;
  startMs: number;
  text: string;
};

export type LiveVoiceSubtitle = {
  activeText: string;
  completedText: string;
  pageIndex: number;
  pendingText: string;
  speakerKind: "player" | "judge";
  speakerName: string;
  text: string;
  utteranceId: string;
};

export type VoicePlaybackCompletion = {
  id: string;
  sourceEventId: number;
  lastSourceEventId: number;
};

export type LiveVoiceQueueItem = {
  utteranceId: string;
  sourceEventId: number;
  lastSourceEventId: number;
  speakerKind: "player" | "judge";
  speakerName: string;
  mimeType: string;
  audioFormat: string;
  sampleRate: number;
  subtitleCues: LiveVoiceSubtitleCue[];
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
      type: "stream_terminated";
    }
  | {
      type: "utterance_played";
      utteranceId: string;
    }
  | {
      type: "utterance_started";
      utteranceId: string;
    };

export function resolveVoiceStreamUrl(
  runId: string,
  baseUrl = API_BASE_URL,
  currentEventId?: number | null,
) {
  const fallbackOrigin =
    typeof window === "undefined" ? "http://localhost" : window.location.origin;
  const base = resolveUrlBase(baseUrl, fallbackOrigin);
  const voiceStreamPath = `/api/v1/games/runs/${encodeURIComponent(runId)}/voice-stream`;
  base.pathname = joinUrlPaths(stripApiPathSuffix(base.pathname), voiceStreamPath);
  base.search = "";
  base.hash = "";
  if (currentEventId !== null && currentEventId !== undefined) {
    base.searchParams.set("current_event_id", String(currentEventId));
  }
  base.searchParams.set("playback_ack", "1");

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

function stripApiPathSuffix(pathname: string) {
  const trimmedPathname = pathname.replace(/\/+$/, "");
  if (trimmedPathname === "/api") {
    return "";
  }
  if (trimmedPathname.endsWith("/api")) {
    return trimmedPathname.slice(0, -"/api".length);
  }
  return pathname;
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
    const lastSourceEventId = liveVoiceMessageLastSourceEventId(message);
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
                lastSourceEventId: Math.max(
                  item.lastSourceEventId,
                  lastSourceEventId,
                ),
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
          lastSourceEventId,
          speakerKind: message.speaker_kind,
          speakerName: message.speaker_name,
          mimeType: message.mime_type,
          audioFormat: message.audio_format,
          sampleRate: message.sample_rate,
          chunks: [],
          chunkMetadata: [],
          subtitleCues: [],
          isEnded: false,
          status: "receiving",
        },
      ],
    };
  }

  if (message.type === "audio_chunk") {
    return {
      ...queue,
      items: queue.items.map((item) => {
        if (
          item.utteranceId !== message.utterance_id ||
          item.status === "played" ||
          item.status === "error"
        ) {
          return item;
        }

        if (
          item.audioFormat !== message.audio_format ||
          item.sampleRate !== message.sample_rate
        ) {
          return { ...item, status: "error" };
        }

        if (
          item.chunkMetadata.some(
            (chunk) => chunk.chunkIndex === message.chunk_index,
          )
        ) {
          return item;
        }

        return {
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
        };
      }),
    };
  }

  if (message.type === "subtitle_timing") {
    return {
      ...queue,
      items: queue.items.map((item) => {
        if (
          item.utteranceId !== message.utterance_id ||
          item.status === "played" ||
          item.status === "error"
        ) {
          return item;
        }

        return {
          ...item,
          subtitleCues: mergeSubtitleCues(
            item.subtitleCues,
            message.cues.map((cue) => ({
              endMs: cue.end_ms,
              startMs: cue.start_ms,
              text: cue.text,
            })),
          ),
        };
      }),
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

function liveVoiceMessageLastSourceEventId(
  message: Extract<LiveVoiceMessage, { type: "voice_start" }>,
) {
  return Math.max(
    message.source_event_id,
    message.last_source_event_id ?? message.source_event_id,
  );
}

function mergeSubtitleCues(
  current: LiveVoiceSubtitleCue[],
  next: LiveVoiceSubtitleCue[],
) {
  const cuesByKey = new Map<string, LiveVoiceSubtitleCue>();
  for (const cue of [...current, ...next]) {
    if (!cue.text || cue.endMs <= cue.startMs) {
      continue;
    }
    cuesByKey.set(`${cue.startMs}:${cue.endMs}:${cue.text}`, cue);
  }
  return [...cuesByKey.values()].sort(
    (left, right) => left.startMs - right.startMs || left.endMs - right.endMs,
  );
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
      (item) => !isStaleJudgeVoiceItem(item, currentEventId),
    ),
  };
}

function isStaleJudgeVoiceItem(
  item: LiveVoiceQueueItem,
  currentEventId: number,
) {
  return (
    item.speakerKind === "judge" &&
    currentEventId - item.lastSourceEventId > STALE_EVENT_DISTANCE
  );
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
          ? {
              ...item,
              chunks: [],
              chunkMetadata: [],
              status: "played",
              subtitleCues: [],
            }
          : item,
      ),
    };
  }

  if (action.type === "stream_terminated") {
    return {
      ...queue,
      items: queue.items.map((item) =>
        item.status === "receiving" ||
        (item.status === "playing" && !item.isEnded)
          ? { ...item, status: "error" }
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
    return (
      (value.reason === undefined || typeof value.reason === "string") &&
      (value.message === undefined || typeof value.message === "string")
    );
  }

  if (value.type === "voice_start") {
    return (
      typeof value.utterance_id === "string" &&
      typeof value.source_event_id === "number" &&
      (value.last_source_event_id === undefined ||
        typeof value.last_source_event_id === "number") &&
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

  if (value.type === "subtitle_timing") {
    return (
      typeof value.utterance_id === "string" &&
      Array.isArray(value.cues) &&
      value.cues.every(isLiveVoiceSubtitleCueMessage)
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

function isLiveVoiceSubtitleCueMessage(value: unknown) {
  return (
    isRecord(value) &&
    typeof value.text === "string" &&
    typeof value.start_ms === "number" &&
    typeof value.end_ms === "number" &&
    Number.isFinite(value.start_ms) &&
    Number.isFinite(value.end_ms) &&
    value.end_ms > value.start_ms
  );
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
  const hasCurrentEventId = currentEventId !== null;
  const [connectionState, setConnectionState] =
    useState<LiveVoiceConnectionState>(
      enabled && runId && hasCurrentEventId ? "connecting" : "idle",
    );
  const [queue, dispatch] = useReducer(
    voiceQueueReducer,
    undefined,
    createVoiceQueue,
  );
  const [subtitleClock, setSubtitleClock] =
    useState<LiveVoiceSubtitleClock>(null);
  const [lastCompletedPlayback, setLastCompletedPlayback] =
    useState<VoicePlaybackCompletion | null>(null);
  const streamUrl = useMemo(
    () => (runId ? resolveVoiceStreamUrl(runId) : null),
    [runId],
  );
  const latestCurrentEventIdRef = useRef(currentEventId);
  latestCurrentEventIdRef.current = currentEventId;
  const visibleQueue = useMemo(
    () => pruneStaleVoiceQueue(queue, currentEventId),
    [currentEventId, queue],
  );
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const pcmSchedulerRef = useRef<PcmAudioScheduler | null>(null);
  const pcmCompletionTimeoutRef = useRef<
    ReturnType<typeof globalThis.setTimeout> | null
  >(null);
  const socketRef = useRef<WebSocket | null>(null);
  const acknowledgedUtteranceIdsRef = useRef<Set<string>>(new Set());
  const pcmEndTimesRef = useRef<Map<string, number>>(new Map());
  const pcmSubtitleStartTimesRef = useRef<Map<string, number>>(new Map());
  const scheduledPcmChunkIndexesRef = useRef<Map<string, Set<number>>>(
    new Map(),
  );
  const isPausedRef = useRef(isPaused);
  const consumedUtteranceIdsRef = useRef<Set<string>>(new Set());
  const playbackCompletionSequenceRef = useRef(0);
  useEffect(() => {
    isPausedRef.current = isPaused;
  }, [isPaused]);
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
    pcmSubtitleStartTimesRef.current.clear();
    scheduledPcmChunkIndexesRef.current.clear();
    setSubtitleClock(null);
    clearPcmCompletionTimeout();
    void scheduler?.close().catch(() => {
      // AudioContext cleanup is best-effort.
    });
  }, [clearPcmCompletionTimeout]);
  const sendPlaybackAck = useCallback((utteranceId: string) => {
    if (acknowledgedUtteranceIdsRef.current.has(utteranceId)) {
      return;
    }
    acknowledgedUtteranceIdsRef.current.add(utteranceId);
    try {
      socketRef.current?.send(
        JSON.stringify({ type: "voice_played", utterance_id: utteranceId }),
      );
    } catch {
      // Playback progression should not depend on ack delivery.
    }
  }, []);
  useEffect(() => {
    if (!enabled || currentEventId === null) {
      return;
    }

    for (const item of queue.items) {
      if (
        (item.status === "played" || item.status === "error") ||
        !isStaleJudgeVoiceItem(item, currentEventId)
      ) {
        continue;
      }
      consumedUtteranceIdsRef.current.add(item.utteranceId);
      sendPlaybackAck(item.utteranceId);
      dispatch({
        type: "utterance_played",
        utteranceId: item.utteranceId,
      });
    }
  }, [currentEventId, enabled, queue.items, sendPlaybackAck]);
  const recordPlaybackCompletion = useCallback(
    (
      item: Pick<
        LiveVoiceQueueItem,
        "utteranceId" | "sourceEventId" | "lastSourceEventId"
      >,
    ) => {
      playbackCompletionSequenceRef.current += 1;
      setLastCompletedPlayback({
        id: `${item.utteranceId}:${playbackCompletionSequenceRef.current}`,
        sourceEventId: item.sourceEventId,
        lastSourceEventId: item.lastSourceEventId,
      });
    },
    [],
  );
  const consumePcmUtterance = useCallback(
    (
      utteranceId: string,
      completedItem?: Pick<
        LiveVoiceQueueItem,
        "utteranceId" | "sourceEventId" | "lastSourceEventId"
      >,
    ) => {
      consumedUtteranceIdsRef.current.add(utteranceId);
      sendPlaybackAck(utteranceId);
      scheduledPcmChunkIndexesRef.current.delete(utteranceId);
      pcmEndTimesRef.current.delete(utteranceId);
      pcmSubtitleStartTimesRef.current.delete(utteranceId);
      setSubtitleClock((current) =>
        current?.utteranceId === utteranceId ? null : current,
      );
      dispatch({
        type: "utterance_played",
        utteranceId,
      });
      if (completedItem) {
        recordPlaybackCompletion(completedItem);
      }
    },
    [recordPlaybackCompletion, sendPlaybackAck],
  );
  const armPcmCompletionPoll = useCallback(
    ({
      context,
      endTime,
      item,
    }: {
      context: AudioContext;
      endTime: number;
      item: Pick<
        LiveVoiceQueueItem,
        "utteranceId" | "sourceEventId" | "lastSourceEventId"
      >;
    }) => {
      clearPcmCompletionTimeout();

      if (isPausedRef.current || context.state !== "running") {
        return;
      }

      const pollForCompletion = () => {
        if (isPausedRef.current || context.state !== "running") {
          pcmCompletionTimeoutRef.current = null;
          return;
        }
        if (context.currentTime >= endTime) {
          pcmCompletionTimeoutRef.current = null;
          consumePcmUtterance(item.utteranceId, item);
          return;
        }

        pcmCompletionTimeoutRef.current = globalThis.setTimeout(
          pollForCompletion,
          PCM_COMPLETION_POLL_INTERVAL_MS,
        );
      };

      pcmCompletionTimeoutRef.current = globalThis.setTimeout(() => {
        pcmCompletionTimeoutRef.current = null;
        pollForCompletion();
      }, PCM_COMPLETION_POLL_INTERVAL_MS);
    },
    [clearPcmCompletionTimeout, consumePcmUtterance],
  );
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
  // A coalesced speech may span many delta events. Start at its first event;
  // lastSourceEventId remains the durable replay/deduplication range boundary.
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
        audio: audioRef.current,
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
    if (
      !enabled ||
      !currentItem ||
      !pcmPlaybackKey ||
      (!isActivePlaybackItem(currentItem) && currentItem.status !== "playing")
    ) {
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
      consumePcmUtterance(currentItem.utteranceId);
    };

    const schedulePcmChunks = async () => {
      const pcmAudio = ensurePcmScheduler();
      if (!pcmAudio) {
        dispatch({
          type: "queue_error",
          message: "当前浏览器不支持语音播放。",
        });
        consumePcmUtterance(currentItem.utteranceId);
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
            if (!isActive) {
              return;
            }
          }
          await pcmAudio.scheduler.resume();
          if (!isActive) {
            return;
          }
        }

        for (const chunk of pendingChunks) {
          if (!isActive) {
            return;
          }
          if (scheduledIndexes.has(chunk.chunkIndex)) {
            continue;
          }
          scheduledIndexes.add(chunk.chunkIndex);
          const scheduledChunk = await pcmAudio.scheduler.schedule(
            chunk.data,
            chunk.sampleRate,
          );
          if (!isActive) {
            return;
          }
          if (!pcmSubtitleStartTimesRef.current.has(currentItem.utteranceId)) {
            pcmSubtitleStartTimesRef.current.set(
              currentItem.utteranceId,
              scheduledChunk.startTime,
            );
            setSubtitleClock({
              elapsedMs: Math.max(
                0,
                Math.round(
                  (pcmAudio.context.currentTime - scheduledChunk.startTime) *
                    1000,
                ),
              ),
              utteranceId: currentItem.utteranceId,
            });
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
          armPcmCompletionPoll({
            context: pcmAudio.context,
            endTime: latestEndTime,
            item: currentItem,
          });
        }
      } catch {
        reportPlaybackError();
      }
    };

    void schedulePcmChunks();

    return () => {
      isActive = false;
      clearPcmCompletionTimeout();
    };
  }, [
    armPcmCompletionPoll,
    clearPcmCompletionTimeout,
    consumePcmUtterance,
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

    const consumeUtterance = (completed: boolean) => {
      if (isConsumed) {
        return;
      }
      isConsumed = true;
      consumedUtteranceIdsRef.current.add(currentItem.utteranceId);
      setSubtitleClock((current) =>
        current?.utteranceId === currentItem.utteranceId ? null : current,
      );
      sendPlaybackAck(currentItem.utteranceId);
      dispatch({
        type: "utterance_played",
        utteranceId: currentItem.utteranceId,
      });
      if (completed) {
        recordPlaybackCompletion(currentItem);
      }
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
      consumeUtterance(true);
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
      consumeUtterance(false);
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
  }, [blobPlaybackKey, enabled, recordPlaybackCompletion, sendPlaybackAck]);

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
      sendPlaybackAck(blobPlaybackKey);
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
  }, [blobPlaybackKey, enabled, isPaused, sendPlaybackAck]);

  useEffect(() => {
    if (
      !enabled ||
      isPaused ||
      !currentItem ||
      currentItem.status !== "playing" ||
      isPcmAudioFormat(currentItem.audioFormat) ||
      !audioRef.current
    ) {
      return;
    }

    const audio = audioRef.current;
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

      consumedUtteranceIdsRef.current.add(utteranceId);
      sendPlaybackAck(utteranceId);
      dispatch({
        type: "queue_error",
        message: "Unable to play live voice audio.",
      });
      dispatch({ type: "utterance_played", utteranceId });
    }, BLOB_PLAYBACK_STALL_POLL_INTERVAL_MS);

    return () => {
      globalThis.clearInterval(intervalId);
    };
  }, [currentItem, enabled, isPaused, sendPlaybackAck]);

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

    const scheduler = pcmSchedulerRef.current;

    if (isPaused) {
      clearPcmCompletionTimeout();
      void scheduler.suspend().catch(reportPlaybackError);
    } else {
      void (async () => {
        await scheduler.resume();
        if (!isActive || !currentItem || !isPcmAudioFormat(currentItem.audioFormat)) {
          return;
        }
        const scheduledIndexes = scheduledPcmChunkIndexesRef.current.get(
          currentItem.utteranceId,
        );
        const latestEndTime = pcmEndTimesRef.current.get(currentItem.utteranceId);
        const context = audioContextRef.current;
        if (
          currentItem.isEnded &&
          context &&
          latestEndTime !== undefined &&
          scheduledIndexes &&
          scheduledIndexes.size >= currentItem.chunkMetadata.length
        ) {
          armPcmCompletionPoll({
            context,
            endTime: latestEndTime,
            item: currentItem,
          });
        }
      })().catch(reportPlaybackError);
    }

    return () => {
      isActive = false;
    };
  }, [
    armPcmCompletionPoll,
    clearPcmCompletionTimeout,
    currentItem,
    enabled,
    isPaused,
    pcmPlaybackKey,
  ]);

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
    acknowledgedUtteranceIdsRef.current.clear();
    playbackCompletionSequenceRef.current = 0;
    pcmSubtitleStartTimesRef.current.clear();
    setLastCompletedPlayback(null);
    setSubtitleClock(null);
    dispatch({ type: "reset" });

    if (!enabled || !streamUrl || !runId || !hasCurrentEventId) {
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
    let retryCount = 0;
    let socket: WebSocket | null = null;

    const reportError = (
      message: string,
      state: LiveVoiceConnectionState = "error",
      terminateStream = false,
    ) => {
      if (!isActive) {
        return;
      }
      hasError = true;
      setConnectionState(state);
      if (terminateStream) {
        dispatch({ type: "stream_terminated" });
      }
      dispatch({ type: "queue_error", message });
    };

    const openSocket = () => {
      setConnectionState("connecting");

      let nextSocket: WebSocket;
      try {
        const connectionUrl = resolveVoiceStreamUrl(
          runId,
          API_BASE_URL,
          latestCurrentEventIdRef.current,
        );
        nextSocket = new WebSocketConstructor(connectionUrl);
      } catch {
        reportError("Unable to open live voice stream.");
        return;
      }

      socket = nextSocket;
      socketRef.current = nextSocket;
      let isAttemptSettled = false;
      const settleSocketAttempt = (failed: boolean) => {
        if (!isActive || hasError || isAttemptSettled) {
          return;
        }
        isAttemptSettled = true;
        if (failed) {
          try {
            nextSocket.close();
          } catch {
            // Closing a failed socket is best-effort.
          }
        }
        if (retryCount < 1) {
          retryCount += 1;
          openSocket();
          return;
        }
        if (failed) {
          reportError("Live voice stream connection failed.", "error", true);
          return;
        }
        dispatch({ type: "stream_terminated" });
        setConnectionState("closed");
      };

      nextSocket.onopen = () => {
        if (isActive) {
          setConnectionState("open");
        }
      };
      nextSocket.onerror = () => {
        settleSocketAttempt(true);
      };
      nextSocket.onclose = () => {
        settleSocketAttempt(false);
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
          dispatch({ type: "stream_terminated" });
          dispatch({
            type: "queue_error",
            message:
              parsed.message?.trim() ||
              unavailableMessageForReason(parsed.reason),
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
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
      socket?.close();
    };
  }, [enabled, hasCurrentEventId, runId, streamUrl]);

  return {
    connectionState,
    currentSpeakerName: isPaused ? null : currentItem?.speakerName ?? null,
    currentItem,
    currentSubtitle,
    errors: visibleQueue.errors,
    lastCompletedPlayback,
    unlockAudio,
  };
}

function unavailableMessageForReason(reason: string | undefined) {
  if (reason === "disabled") {
    return "语音服务未启用，请检查后端语音配置。";
  }
  if (reason === "misconfigured") {
    return "语音模型配置不完整，请检查 Ark API Key、资源 ID 和音色配置。";
  }
  if (reason === "terminal") {
    return "语音只支持进行中的实时对局；该对局已结束或异常中断。";
  }
  if (reason === "run_not_found") {
    return "对局不存在或已失效，请返回大厅重新开始。";
  }
  return VOICE_STREAM_SERVER_UNAVAILABLE_ERROR;
}
