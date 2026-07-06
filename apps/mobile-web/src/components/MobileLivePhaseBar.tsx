import { useState } from "react";
import { ChevronDown } from "lucide-react";

import type { LivePhaseSegment } from "@werewolf-arena/game-client";

type MobileLivePhaseBarProps = {
  segments: LivePhaseSegment[];
  onSelectPhase: (segment: LivePhaseSegment) => void;
};

type MobileLiveDaySegment = {
  id: string;
  isCurrent: boolean;
  isVisited: boolean;
  label: string;
  startSegment: LivePhaseSegment;
};

export function MobileLivePhaseBar({
  onSelectPhase,
  segments,
}: MobileLivePhaseBarProps) {
  const [isOpen, setIsOpen] = useState(false);

  const daySegments = buildMobileLiveDaySegments(segments);

  if (daySegments.length === 0) {
    return null;
  }

  const selectedDay =
    daySegments.find((segment) => segment.isCurrent) ??
    [...daySegments].reverse().find((segment) => segment.isVisited) ??
    daySegments[0];

  return (
    <nav
      aria-label="对局阶段"
      className={[
        "mobile-live-phase-bar",
        isOpen ? "mobile-live-phase-bar-open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-testid="mobile-live-phase-bar"
    >
      <button
        aria-current={selectedDay.isCurrent ? "step" : undefined}
        aria-expanded={isOpen}
        aria-haspopup="true"
        aria-label={`选择阶段，当前${selectedDay.label}`}
        className="mobile-live-phase-trigger"
        onClick={() => setIsOpen((current) => !current)}
        type="button"
      >
        <span>{selectedDay.label}</span>
        <ChevronDown aria-hidden="true" size={14} strokeWidth={2.8} />
      </button>

      {isOpen ? (
        <div
          aria-label="阶段列表"
          className="mobile-live-phase-popover"
          data-testid="mobile-live-phase-popover"
          role="list"
        >
          {daySegments.map((daySegment) => (
            <div key={daySegment.id} role="listitem">
              <button
                aria-current={daySegment.isCurrent ? "step" : undefined}
                aria-label={`跳转到${daySegment.label}`}
                className={[
                  "mobile-live-phase-button",
                  daySegment.isVisited ? "mobile-live-phase-button-visited" : "",
                  daySegment.isCurrent ? "mobile-live-phase-button-current" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => {
                  onSelectPhase(daySegment.startSegment);
                  setIsOpen(false);
                }}
                type="button"
              >
                {daySegment.label}
              </button>
            </div>
          ))}
        </div>
      ) : null}
    </nav>
  );
}

function buildMobileLiveDaySegments(
  segments: LivePhaseSegment[],
): MobileLiveDaySegment[] {
  const segmentsByRound = new Map<number, LivePhaseSegment[]>();

  for (const segment of segments) {
    const roundSegments = segmentsByRound.get(segment.round) ?? [];
    roundSegments.push(segment);
    segmentsByRound.set(segment.round, roundSegments);
  }

  return [...segmentsByRound.entries()]
    .map(([round, roundSegments]) => {
      const sortedSegments = [...roundSegments].sort(
        (left, right) => left.startEventId - right.startEventId,
      );
      const startSegment = sortedSegments[0];

      return {
        id: `round-${round}`,
        isCurrent: sortedSegments.some((segment) => segment.isCurrent),
        isVisited: sortedSegments.some((segment) => segment.isVisited),
        label: `第${round}天`,
        startSegment,
      };
    })
    .sort(
      (left, right) =>
        left.startSegment.startEventId - right.startSegment.startEventId,
    );
}
