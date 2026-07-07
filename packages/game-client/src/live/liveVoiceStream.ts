import { useEffect, useMemo, useReducer, useRef, useState } from "react";

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
    }
  | {
      type: "audio_chunk";
      utterance_id: string;
      mime_type: string;
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

export type LiveVoiceQueueItem = {
  utteranceId: string;
  sourceEventId: number;
  speakerKind: "player" | "judge";
  speakerName: string;
  mimeType: string;
  chunks: string[];
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
          chunks: [],
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
        item.status !== "playing" &&
        item.status !== "played"
          ? { ...item, chunks: [...item.chunks, message.data] }
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
        ? { ...item, status: "ready" }
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
          ? { ...item, chunks: [], status: "played" }
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
      typeof value.mime_type === "string"
    );
  }

  if (value.type === "audio_chunk") {
    return (
      typeof value.utterance_id === "string" &&
      typeof value.mime_type === "string" &&
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
  const consumedUtteranceIdsRef = useRef<Set<string>>(new Set());
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
  const playbackKey =
    currentItem &&
    (currentItem.status === "ready" || currentItem.status === "playing")
      ? currentItem.utteranceId
      : null;

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
  }, [playbackKey, enabled]);

  useEffect(() => {
    if (!enabled || !playbackKey || !audioRef.current) {
      return;
    }

    let isActive = true;
    const audio = audioRef.current;
    const reportPlaybackError = () => {
      if (!isActive) {
        return;
      }
      consumedUtteranceIdsRef.current.add(playbackKey);
      dispatch({
        type: "queue_error",
        message: "Unable to play live voice audio.",
      });
      dispatch({
        type: "utterance_played",
        utteranceId: playbackKey,
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
  }, [playbackKey, enabled, isPaused]);

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
  };
}
