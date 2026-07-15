import { useEffect, useMemo, useState } from "react";

import { ensurePublicSession } from "../api/publicSession";
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
  "run_recovered",
  "game_started",
  "game_resumed",
  "round_started",
  "phase_started",
  "judge_cue",
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
  audience: GameRunEventAudience;
  events: LiveGameEvent[];
  connectionState: ConnectionState;
};

export type GameRunEventAudience = "player_public" | "spectator_god_view";

export function useGameRunEvents(
  runId: string | undefined,
  audience: GameRunEventAudience = "player_public",
) {
  const [streamState, setStreamState] = useState<EventStreamState>(() => ({
    runId,
    audience,
    events: [],
    connectionState: runId ? "connecting" : "idle",
  }));

  if (streamState.runId !== runId || streamState.audience !== audience) {
    setStreamState({
      runId,
      audience,
      events: [],
      connectionState: runId ? "connecting" : "idle",
    });
  }

  const stateMatches =
    streamState.runId === runId && streamState.audience === audience;
  const events = stateMatches ? streamState.events : EMPTY_EVENTS;
  const connectionState =
    stateMatches
      ? streamState.connectionState
      : runId
        ? "connecting"
        : "idle";

  useEffect(() => {
    if (!runId) {
      return;
    }

    let isActive = true;
    let source: EventSource | null = null;

    const markConnectionError = () => {
      setStreamState((current) =>
        current.runId === runId && current.audience === audience
          ? { ...current, connectionState: "error" }
          : current,
      );
    };

    const closeSource = () => {
      if (!source) {
        return;
      }
      source.onopen = null;
      source.onerror = null;
      source.onmessage = null;
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
          current.runId === runId && current.audience === audience
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
        if (current.runId !== runId || current.audience !== audience) {
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

    const connect = async () => {
      if (audience === "spectator_god_view") {
        try {
          await ensurePublicSession();
        } catch {
          if (isActive) {
            markConnectionError();
          }
          return;
        }
      }

      if (!isActive) {
        return;
      }

      const EventSourceConstructor = globalThis.EventSource;
      if (typeof EventSourceConstructor !== "function") {
        markConnectionError();
        return;
      }

      const streamPath =
        audience === "spectator_god_view"
          ? "god-view/timeline-events"
          : "timeline-events";
      source = new EventSourceConstructor(
        `${API_BASE_URL}/api/v1/games/runs/${runId}/${streamPath}`,
        { withCredentials: true },
      );

      source.onopen = () => {
        if (!isActive) {
          return;
        }
        setStreamState((current) =>
          current.runId === runId && current.audience === audience
            ? { ...current, connectionState: "open" }
            : current,
        );
      };
      source.onerror = () => {
        if (isActive) {
          markConnectionError();
        }
      };

      for (const eventType of EVENT_TYPES) {
        source.addEventListener(eventType, handleEvent);
      }
    };

    void connect();

    return () => {
      isActive = false;
      closeSource();
      setStreamState((current) =>
        current.runId === runId && current.audience === audience
          ? { ...current, connectionState: "closed" }
          : current,
      );
    };
  }, [audience, runId]);

  const latestEvent = useMemo(() => events.at(-1) ?? null, [events]);

  return { events, latestEvent, connectionState };
}
