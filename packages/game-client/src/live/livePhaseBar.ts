import type { LiveGameEvent } from "../types";

export type LivePhaseKind = "night" | "day";

export type LivePhaseSegment = {
  id: string;
  round: number;
  phase: LivePhaseKind;
  label: string;
  startEventId: number;
  isCurrent: boolean;
  isVisited: boolean;
};

export function buildLivePhaseSegments(
  events: LiveGameEvent[],
  currentEventId: number | null,
): LivePhaseSegment[] {
  const seen = new Set<string>();
  const starts = [...events]
    .sort((left, right) => left.id - right.id)
    .filter(isMainPhaseStart)
    .filter((event) => {
      const key = phaseKey(event.round, event.phase);
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });

  return starts.map((event, index) => {
    const nextEvent = starts[index + 1];
    const isVisited =
      currentEventId !== null && currentEventId >= event.id;
    const isCurrent =
      isVisited && (!nextEvent || currentEventId < nextEvent.id);
    const phase = event.phase as LivePhaseKind;
    const round = event.round as number;

    return {
      id: phaseKey(round, phase),
      round,
      phase,
      label: phaseSegmentLabel(round, phase),
      startEventId: event.id,
      isCurrent,
      isVisited,
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
