import type { LineupLaunchStatus } from "./lobbyModel";

type LobbyLaunchBarProps = { error: string | null; isLaunchDisabled: boolean; isPending: boolean; onLaunch: () => void; status: LineupLaunchStatus };

export function LobbyLaunchBar({ error, isLaunchDisabled, isPending, onLaunch, status }: LobbyLaunchBarProps) {
  return (
    <div className="mobile-lobby-launch-region">
      {error ? <p role="alert">{error}</p> : null}
      <div className="mobile-lobby-launch-bar">
        <span aria-live="polite">{status.summaryText}</span>
        <button className="mobile-button mobile-button-primary mobile-lobby-launch-button" disabled={isLaunchDisabled} onClick={onLaunch} type="button">
          {isPending ? "发起中…" : status.ctaLabel}
        </button>
      </div>
    </div>
  );
}
