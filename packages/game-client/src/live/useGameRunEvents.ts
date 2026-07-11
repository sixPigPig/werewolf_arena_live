import { useEffect, useMemo, useState } from "react";

import type { LiveGameEvent } from "../types";

type ConnectionState =
  | "idle"
  | "connecting"
  | "open"
  | "error"
  | "closed";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const EMPTY_EVENTS: LiveGameEvent[] = [];

const EVENT_TYPES = [
  "run_created",
  "run_started",
  "game_started",
  "round_started",
  "phase_started",
  "action_requested",
  "model_request_started",
  "model_thinking_tick",
  "model_response_delta",
  "model_request_failed",
  "model_response_received",
  "action_parsed",
  "state_updated",
  "game_completed",
  "game_failed",
  "run_stop_requested",
  "game_canceled",
];

type EventStreamState = {
  runId: string | undefined;
  events: LiveGameEvent[];
  connectionState: ConnectionState;
};

export function useGameRunEvents(runId: string | undefined) {
  const [streamState, setStreamState] = useState<EventStreamState>(() => ({
    runId,
    events: [],
    connectionState: runId ? "connecting" : "idle",
  }));

  if (streamState.runId !== runId) {
    setStreamState({
      runId,
      events: [],
      connectionState: runId ? "connecting" : "idle",
    });
  }

  const events = streamState.runId === runId ? streamState.events : EMPTY_EVENTS;
  const connectionState =
    streamState.runId === runId
      ? streamState.connectionState
      : runId
        ? "connecting"
        : "idle";

  useEffect(() => {
    if (!runId) {
      return;
    }

    let isActive = true;
    const EventSourceConstructor = globalThis.EventSource;
    if (typeof EventSourceConstructor !== "function") {
      setStreamState((current) =>
        current.runId === runId
          ? { ...current, connectionState: "error" }
          : current,
      );
      return;
    }

    const source = new EventSourceConstructor(
      `${API_BASE_URL}/api/v1/games/runs/${runId}/events`,
    );

    const closeSource = () => {
      source.onopen = null;
      source.onerror = null;
      source.onmessage = null;
      source.close();
    };

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
          ? { ...current, connectionState: "error" }
          : current,
      );
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
      const isTerminalEvent =
        event.type === "game_completed" ||
        event.type === "game_failed" ||
        event.type === "game_canceled";
      setStreamState((current) => {
        if (current.runId !== runId) {
          return current;
        }

        const nextEvents = current.events.some((item) => item.id === event.id)
          ? current.events
          : [...current.events, event].sort((a, b) => a.id - b.id);

        return {
          ...current,
          events: nextEvents,
          connectionState: isTerminalEvent ? "closed" : current.connectionState,
        };
      });
      if (isTerminalEvent) {
        isActive = false;
        closeSource();
      }
    };

    for (const eventType of EVENT_TYPES) {
      source.addEventListener(eventType, handleEvent);
    }

    return () => {
      isActive = false;
      closeSource();
      setStreamState((current) =>
        current.runId === runId
          ? { ...current, connectionState: "closed" }
          : current,
      );
    };
  }, [runId]);

  const latestEvent = useMemo(() => events.at(-1) ?? null, [events]);

  return { events, latestEvent, connectionState };
}
