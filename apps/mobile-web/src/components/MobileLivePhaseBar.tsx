import type { LivePhaseSegment } from "@werewolf-arena/game-client";

type MobileLivePhaseBarProps = {
  segments: LivePhaseSegment[];
  onSelectPhase: (segment: LivePhaseSegment) => void;
};

export function MobileLivePhaseBar({
  onSelectPhase,
  segments,
}: MobileLivePhaseBarProps) {
  if (segments.length === 0) {
    return null;
  }

  return (
    <nav
      aria-label="对局阶段"
      className="mobile-live-phase-bar"
      data-testid="mobile-live-phase-bar"
    >
      <div className="mobile-live-phase-track" role="list">
        {segments.map((segment) => (
          <div className="mobile-live-phase-item" key={segment.id} role="listitem">
            <button
              aria-current={segment.isCurrent ? "step" : undefined}
              aria-label={`从${segment.label}开始播放`}
              className={[
                "mobile-live-phase-button",
                segment.isVisited ? "mobile-live-phase-button-visited" : "",
                segment.isCurrent ? "mobile-live-phase-button-current" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => onSelectPhase(segment)}
              type="button"
            >
              {segment.label}
            </button>
          </div>
        ))}
      </div>
    </nav>
  );
}
