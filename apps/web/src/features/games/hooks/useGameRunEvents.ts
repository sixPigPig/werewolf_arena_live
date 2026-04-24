import { useEffect, useMemo, useState } from "react";

import type { LiveGameEvent } from "../types";

type ConnectionState = "idle" | "connecting" | "open" | "error" | "closed";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

const EVENT_TYPES = [
  "run_created",
  "run_started",
  "game_started",
  "round_started",
  "phase_started",
  "action_requested",
  "model_request_started",
  "model_response_received",
  "action_parsed",
  "state_updated",
  "game_completed",
  "game_failed",
];

export function useGameRunEvents(runId: string | undefined) {
  const [events, setEvents] = useState<LiveGameEvent[]>([]);
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("idle");

  useEffect(() => {
    if (!runId) {
      setEvents([]);
      setConnectionState("idle");
      return;
    }

    setConnectionState("connecting");
    let isActive = true;
    const source = new EventSource(
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
      setConnectionState("open");
    };
    source.onerror = () => {
      if (!isActive) {
        return;
      }
      setConnectionState("error");
    };

    const handleEvent = (message: MessageEvent) => {
      if (!isActive) {
        return;
      }
      const event = JSON.parse(message.data) as LiveGameEvent;
      setEvents((current) => {
        if (current.some((item) => item.id === event.id)) {
          return current;
        }
        return [...current, event].sort((a, b) => a.id - b.id);
      });
      if (event.type === "game_completed" || event.type === "game_failed") {
        isActive = false;
        setConnectionState("closed");
        closeSource();
      }
    };

    for (const eventType of EVENT_TYPES) {
      source.addEventListener(eventType, handleEvent);
    }

    return () => {
      isActive = false;
      closeSource();
      setConnectionState("closed");
    };
  }, [runId]);

  const latestEvent = useMemo(() => events.at(-1) ?? null, [events]);

  return { events, latestEvent, connectionState };
}
