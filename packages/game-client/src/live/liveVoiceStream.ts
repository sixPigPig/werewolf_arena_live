import { useEffect, useMemo, useReducer, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const STALE_EVENT_DISTANCE = 8;

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
  status: "receiving" | "ready" | "error";
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
    };

export function resolveVoiceStreamUrl(runId: string, baseUrl = API_BASE_URL) {
  const fallbackOrigin =
    typeof window === "undefined" ? "http://localhost" : window.location.origin;
  const base = baseUrl || fallbackOrigin;
  const url = new URL(
    `/api/v1/games/runs/${encodeURIComponent(runId)}/voice-stream`,
    base,
  );

  if (url.protocol === "https:") {
    url.protocol = "wss:";
  } else if (url.protocol === "http:") {
    url.protocol = "ws:";
  }

  return url.toString();
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
        item.utteranceId === message.utterance_id
          ? { ...item, chunks: [...item.chunks, message.data] }
          : item,
      ),
    };
  }

  return {
    ...queue,
    items: queue.items.map((item) =>
      item.utteranceId === message.utterance_id
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

function voiceQueueReducer(
  queue: LiveVoiceQueue,
  action: VoiceQueueAction,
): LiveVoiceQueue {
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
  const currentItem =
    visibleQueue.items.find((item) => item.status === "ready") ??
    visibleQueue.items.find((item) => item.status === "receiving") ??
    null;

  useEffect(() => {
    if (!enabled || !streamUrl) {
      setConnectionState("idle");
      return;
    }

    const WebSocketConstructor = globalThis.WebSocket;
    if (typeof WebSocketConstructor !== "function") {
      setConnectionState("unavailable");
      dispatch({
        type: "queue_error",
        message: "Live voice streaming is unavailable in this browser.",
      });
      return;
    }

    let isActive = true;
    let hasError = false;

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

    setConnectionState("connecting");

    let socket: WebSocket;
    try {
      socket = new WebSocketConstructor(streamUrl);
    } catch {
      reportError("Unable to open live voice stream.");
      return;
    }

    socket.onopen = () => {
      if (isActive) {
        setConnectionState("open");
      }
    };
    socket.onerror = () => {
      reportError("Live voice stream connection failed.");
    };
    socket.onclose = () => {
      if (isActive && !hasError) {
        setConnectionState("closed");
      }
    };
    socket.onmessage = (event) => {
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
        socket.close();
        return;
      }

      dispatch(parsed);
    };

    return () => {
      isActive = false;
      socket.close();
    };
  }, [enabled, streamUrl]);

  return {
    connectionState,
    currentSpeakerName: isPaused ? null : currentItem?.speakerName ?? null,
    currentItem,
    errors: visibleQueue.errors,
  };
}
