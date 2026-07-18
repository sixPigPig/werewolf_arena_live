import type { LiveGameEvent } from "../types";
import { livePhaseLifecycleForEvent } from "./liveEventMeta";

export type LivePhaseKind = "night" | "day";

export type LivePhaseSegment = {
  id: string;
  round: number;
  phase: LivePhaseKind;
  label: string;
  startEventId: number;
  isCurrent: boolean;
  isVisited: boolean;
  phaseInstanceId?: string | null;
  completionEventId?: number | null;
  completionStatus?: string | null;
  completionReason?: string | null;
};

export function buildLivePhaseSegments(
  events: LiveGameEvent[],
  currentEventId: number | null,
): LivePhaseSegment[] {
  const seen = new Set<string>();
  const orderedEvents = [...events].sort((left, right) => left.id - right.id);
  const starts = [...events]
    .sort((left, right) => left.id - right.id)
    .filter(isMainPhaseStart)
    .filter((event) => {
      const key = phaseIdentity(event);
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });

  return starts.map((event, index) => {
    const nextEvent = starts[index + 1];
    const lifecycle = livePhaseLifecycleForEvent(event);
    const identity = phaseIdentity(event);
    const completionEvent = orderedEvents.find(
      (candidate) =>
        candidate.type === "phase_completed" &&
        candidate.id >= event.id &&
        phaseIdentity(candidate) === identity,
    );
    const completion = completionEvent
      ? livePhaseLifecycleForEvent(completionEvent)
      : null;
    const isVisited =
      currentEventId !== null && currentEventId >= event.id;
    const isCompleted =
      currentEventId !== null &&
      completionEvent !== undefined &&
      currentEventId >= completionEvent.id;
    const isCurrent =
      isVisited &&
      !isCompleted &&
      (!nextEvent || currentEventId < nextEvent.id);
    const phase = event.phase as LivePhaseKind;
    const round = event.round as number;

    return {
      id: lifecycle?.phaseInstanceId
        ? `phase-${lifecycle.phaseInstanceId}`
        : phaseKey(round, phase),
      round,
      phase,
      label: phaseSegmentLabel(round, phase),
      startEventId: event.id,
      isCurrent,
      isVisited,
      phaseInstanceId: lifecycle?.phaseInstanceId ?? null,
      completionEventId: completionEvent?.id ?? null,
      completionStatus: completion?.completionStatus ?? null,
      completionReason: completion?.completionReason ?? null,
    };
  });
}

function isMainPhaseStart(
  event: LiveGameEvent,
): event is LiveGameEvent & { round: number; phase: LivePhaseKind } {
  return (
    event.type === "phase_started" &&
    isValidRound(event.round) &&
    (event.phase === "night" || event.phase === "day")
  );
}

function isValidRound(round: number | null): round is number {
  return typeof round === "number" && Number.isInteger(round) && round > 0;
}

function phaseKey(round: number | null, phase: string | null) {
  return `round-${String(round)}-${String(phase)}`;
}

function phaseIdentity(event: LiveGameEvent): string {
  const phaseInstanceId = livePhaseLifecycleForEvent(event)?.phaseInstanceId;
  return phaseInstanceId
    ? `instance-${phaseInstanceId}`
    : phaseKey(event.round, event.phase);
}

function phaseSegmentLabel(round: number, phase: LivePhaseKind): string {
  const prefix = phase === "night" ? "夜" : "昼";
  return `${prefix}${roundLabel(round)}`;
}

function roundLabel(round: number): string {
  const labels: Record<number, string> = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
  };

  return labels[round] ?? String(round);
}
