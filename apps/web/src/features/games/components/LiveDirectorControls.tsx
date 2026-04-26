import type { LiveDirectorSpeed } from "../hooks/useLiveDirector";

type LiveDirectorControlsProps = {
  backlogCount: number;
  isCatchingUp: boolean;
  isPaused: boolean;
  speed: LiveDirectorSpeed;
  onTogglePaused: () => void;
  onCatchUpToLatest: () => void;
  onSpeedChange: (speed: LiveDirectorSpeed) => void;
};

export function LiveDirectorControls({
  backlogCount,
  isCatchingUp,
  isPaused,
  speed,
  onTogglePaused,
  onCatchUpToLatest,
  onSpeedChange,
}: LiveDirectorControlsProps) {
  return (
    <section className="rounded-md border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-36">
          <h2 className="text-sm font-semibold text-slate-950">观赛节奏</h2>
          <p className="mt-1 text-xs text-slate-600">
            {isCatchingUp ? "自动追进度" : `队列 ${backlogCount} 条`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            className="h-9 min-w-16 rounded-md border border-slate-300 px-3 text-sm font-medium text-slate-800 hover:bg-slate-50"
            onClick={onTogglePaused}
            type="button"
          >
            {isPaused ? "继续" : "暂停"}
          </button>
          <button
            className="h-9 min-w-24 rounded-md border border-slate-300 px-3 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={backlogCount === 0}
            onClick={onCatchUpToLatest}
            type="button"
          >
            追到最新
          </button>
          <div className="flex rounded-md border border-slate-300 p-0.5">
            <button
              className={speedButtonClass(speed === 1)}
              onClick={() => onSpeedChange(1)}
              type="button"
            >
              1x
            </button>
            <button
              className={speedButtonClass(speed === 1.5)}
              onClick={() => onSpeedChange(1.5)}
              type="button"
            >
              1.5x
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

function speedButtonClass(isActive: boolean) {
  return [
    "h-8 min-w-12 rounded px-2 text-sm font-medium",
    isActive
      ? "bg-slate-950 text-white"
      : "text-slate-700 hover:bg-slate-100",
  ].join(" ");
}
