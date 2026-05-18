type LiveNavSessionBadgeProps = {
  sessionId: string;
};

export function LiveNavSessionBadge({ sessionId }: LiveNavSessionBadgeProps) {
  return (
    <div
      className="live-nav-session flex min-w-0 shrink-0 items-center gap-x-2 text-xs font-semibold text-slate-300"
      data-testid="live-nav-session"
    >
      <span className="shrink-0 text-slate-500">对局</span>
      <span
        className="max-w-[14rem] truncate font-mono tracking-wide text-slate-100"
        title={sessionId}
      >
        {sessionId}
      </span>
    </div>
  );
}
