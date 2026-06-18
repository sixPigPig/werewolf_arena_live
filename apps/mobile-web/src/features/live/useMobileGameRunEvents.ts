import { useEffect, useMemo, useState } from "react";

import { createRunEventSource } from "../../api/liveApi";
import type { LiveGameEvent } from "../../api/types";

export type MobileConnectionState =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "error"
  | "closed";

const emptyEvents: LiveGameEvent[] = [];

const eventTypes = [
  "run_created",
  "run_started",
  "game_started",
  "round_started",
  "phase_started",
  "action_requested",
  "model_request_started",
  "model_thinking_tick",
  "model_response_delta",
  "model_retry_scheduled",
  "model_request_failed",
  "model_response_received",
  "action_parsed",
  "action_quality_warning",
  "state_updated",
  "game_completed",
  "game_failed",
];

type StreamState = {
  connectionState: MobileConnectionState;
  events: LiveGameEvent[];
  runId: string | undefined;
};

export function useMobileGameRunEvents(runId: string | undefined) {
  const [streamState, setStreamState] = useState<StreamState>(() => ({
    connectionState: runId ? "connecting" : "idle",
    events: [],
    runId,
  }));

  if (streamState.runId !== runId) {
    setStreamState({
      connectionState: runId ? "connecting" : "idle",
      events: [],
      runId,
    });
  }

  useEffect(() => {
    if (!runId) {
      return;
    }

    let isActive = true;
    let lastEventId: number | undefined;
    let reconnectTimer: number | undefined;
    let source: EventSource | null = null;

    const closeSource = () => {
      if (!source) {
        return;
      }

      source.onopen = null;
      source.onerror = null;
      source.close();
      source = null;
    };

    const handleEvent = (message: MessageEvent) => {
      if (!isActive) {
        return;
      }

      let event: LiveGameEvent;
      try {
        event = JSON.parse(message.data) as LiveGameEvent;
      } catch {
        setStreamState((current) =>
          current.runId === runId
            ? { ...current, connectionState: "error" }
            : current,
        );
        return;
      }

      lastEventId = event.id;
      const isTerminal =
        event.type === "game_completed" || event.type === "game_failed";

      setStreamState((current) => {
        if (current.runId !== runId) {
          return current;
        }

        const events = current.events.some((item) => item.id === event.id)
          ? current.events
          : [...current.events, event].sort((a, b) => a.id - b.id);

        return {
          ...current,
          connectionState: isTerminal ? "closed" : current.connectionState,
          events,
        };
      });

      if (isTerminal) {
        isActive = false;
        closeSource();
      }
    };

    const connect = () => {
      closeSource();
      source = createRunEventSource(runId, lastEventId);
      source.onopen = () => {
        if (!isActive) {
          return;
        }

        setStreamState((current) =>
          current.runId === runId
            ? { ...current, connectionState: "open" }
            : current,
        );
      };
      source.onerror = () => {
        if (!isActive) {
          return;
        }

        setStreamState((current) =>
          current.runId === runId
            ? { ...current, connectionState: "reconnecting" }
            : current,
        );
        closeSource();
        reconnectTimer = window.setTimeout(connect, 1200);
      };

      for (const eventType of eventTypes) {
        source.addEventListener(eventType, handleEvent);
      }
    };

    connect();

    return () => {
      isActive = false;
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      closeSource();
      setStreamState((current) =>
        current.runId === runId
          ? { ...current, connectionState: "closed" }
          : current,
      );
    };
  }, [runId]);

  const events = streamState.runId === runId ? streamState.events : emptyEvents;
  const latestEvent = useMemo(() => events.at(-1) ?? null, [events]);
  const connectionState =
    streamState.runId === runId
      ? streamState.connectionState
      : runId
        ? "connecting"
        : "idle";

  return { connectionState, events, latestEvent };
}
