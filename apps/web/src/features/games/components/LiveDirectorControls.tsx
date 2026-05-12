import { Button, SegmentedControl } from "../../../components/ui";
import { withGlassPanel } from "../../../components/ui/glass";

import type { LiveDirectorSpeed } from "../hooks/useLiveDirector";

type LiveDirectorControlsProps = {
  backlogCount: number;
  isCatchingUp: boolean;
  isPaused: boolean;
  speed: LiveDirectorSpeed;
  variant?: "panel" | "nav";
  onTogglePaused: () => void;
  onCatchUpToLatest: () => void;
  onSpeedChange: (speed: LiveDirectorSpeed) => void;
};

export function LiveDirectorControls({
  backlogCount,
  isCatchingUp,
  isPaused,
  speed,
  variant = "panel",
  onTogglePaused,
  onCatchUpToLatest,
  onSpeedChange,
}: LiveDirectorControlsProps) {
  const isNav = variant === "nav";

  if (isNav) {
    return (
      <section
        className="live-command-controls flex shrink-0 items-center gap-2 text-slate-100"
        data-testid="director-controls"
      >
        <span className="sr-only">
          观赛节奏，队列 {backlogCount} 条
          {isCatchingUp ? "，自动追进度" : ""}
        </span>
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
        <label className="relative flex h-10 items-center rounded-md border border-slate-500/35 bg-white/5 text-xs font-semibold text-slate-100 shadow-[inset_0_0_12px_rgba(255,255,255,0.04)]">
          <span className="sr-only">播放速度</span>
          <select
            aria-label="播放速度"
            className="h-full appearance-none rounded-md bg-transparent py-0 pl-3 pr-8 text-slate-100 outline-none"
            onChange={(event) =>
              onSpeedChange(Number(event.target.value) as LiveDirectorSpeed)
            }
            value={String(speed)}
          >
            <option value="1">1x</option>
            <option value="1.5">1.5x</option>
          </select>
          <span
            aria-hidden="true"
            className="pointer-events-none absolute right-2.5 text-slate-400"
          >
            ⌄
          </span>
        </label>
      </section>
    );
  }

  return (
    <section
      className={withGlassPanel("rounded-lg p-4 text-slate-100")}
      data-testid="director-controls"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-36">
          <h2 className="text-sm font-semibold text-amber-50">观赛节奏</h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            {isCatchingUp ? (
              <span className="text-teal-200">自动追进度</span>
            ) : null}
            <span>队列 {backlogCount} 条</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            color="amber"
            onClick={onTogglePaused}
            type="button"
            variant="surface"
          >
            {isPaused ? "继续" : "暂停"}
          </Button>
          <Button
            color="gray"
            disabled={backlogCount === 0}
            onClick={onCatchUpToLatest}
            type="button"
            variant="surface"
          >
            追到最新
          </Button>
          <SegmentedControl.Root
            aria-label="播放速度"
            onValueChange={(value) =>
              onSpeedChange(Number(value) as LiveDirectorSpeed)
            }
            value={String(speed)}
          >
            <SegmentedControl.Item value="1">1x</SegmentedControl.Item>
            <SegmentedControl.Item value="1.5">1.5x</SegmentedControl.Item>
          </SegmentedControl.Root>
        </div>
      </div>
    </section>
  );
}
