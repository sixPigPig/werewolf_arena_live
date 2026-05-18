import type { LiveDirectorSpeed } from "../hooks/useLiveDirector";

type LiveDirectorControlsProps = {
  backlogCount: number;
  isPaused: boolean;
  speed: LiveDirectorSpeed;
  onTogglePaused: () => void;
  onCatchUpToLatest: () => void;
  onSpeedChange: (speed: LiveDirectorSpeed) => void;
};

export function LiveDirectorControls({
  backlogCount,
  isPaused,
  speed,
  onTogglePaused,
  onCatchUpToLatest,
  onSpeedChange,
}: LiveDirectorControlsProps) {
  return (
    <section
      className="flex shrink-0 items-center gap-2 text-slate-100"
      data-testid="director-controls"
    >
      <button
        aria-label={isPaused ? "继续" : "暂停"}
        className="flex h-10 w-10 items-center justify-center rounded-md border border-slate-500/35 bg-white/5 text-base font-semibold text-slate-100 shadow-[inset_0_0_12px_rgba(255,255,255,0.04)] transition hover:border-amber-300/55 hover:bg-amber-300/10 focus:outline-none focus:ring-2 focus:ring-amber-300/70"
        onClick={onTogglePaused}
        type="button"
      >
        <span aria-hidden="true">{isPaused ? "▶" : "Ⅱ"}</span>
      </button>
      <button
        aria-label="追到最新"
        className="flex h-10 w-10 items-center justify-center rounded-md border border-slate-500/35 bg-white/5 text-sm text-slate-100 shadow-[inset_0_0_12px_rgba(255,255,255,0.04)] transition hover:border-amber-300/55 hover:bg-amber-300/10 disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus:ring-2 focus:ring-amber-300/70"
        disabled={backlogCount === 0}
        onClick={onCatchUpToLatest}
        type="button"
      >
        <span aria-hidden="true">↻</span>
      </button>
      <div className="relative flex h-10 items-center rounded-md border border-slate-500/35 bg-white/5 text-xs font-semibold text-slate-100 shadow-[inset_0_0_12px_rgba(255,255,255,0.04)]">
        <select
          aria-label="播放速度"
          className="h-full appearance-none rounded-md bg-transparent py-0 pl-3 pr-8 text-slate-100 outline-none"
          onChange={(event) =>
            onSpeedChange(Number(event.target.value) as LiveDirectorSpeed)
          }
          value={String(speed)}
        >
          <option value="1">1x</option>
          <option value="2">2x</option>
        </select>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute right-2.5 text-slate-400"
        >
          ⌄
        </span>
      </div>
    </section>
  );
}
