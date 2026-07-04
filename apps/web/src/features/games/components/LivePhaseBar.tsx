import type { LivePhaseSegment } from "../livePhaseBar";

type LivePhaseBarProps = {
  segments: LivePhaseSegment[];
  onSelectPhase: (segment: LivePhaseSegment) => void;
};

export function LivePhaseBar({
  onSelectPhase,
  segments,
}: LivePhaseBarProps) {
  if (segments.length === 0) {
    return null;
  }

  return (
    <nav
      aria-label="对局阶段"
      className="live-phase-bar"
      data-testid="live-phase-bar"
    >
      <div className="live-phase-bar-track" role="list">
        {segments.map((segment) => (
          <div className="live-phase-bar-item" key={segment.id} role="listitem">
            <button
              aria-current={segment.isCurrent ? "step" : undefined}
              aria-label={`从${segment.label}开始播放`}
              className={cx(
                "live-phase-segment",
                segment.isVisited && "live-phase-segment-visited",
                segment.isCurrent && "live-phase-segment-current",
              )}
              onClick={() => onSelectPhase(segment)}
              type="button"
            >
              <span className="live-phase-segment-label">{segment.label}</span>
            </button>
          </div>
        ))}
      </div>
    </nav>
  );
}

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}
