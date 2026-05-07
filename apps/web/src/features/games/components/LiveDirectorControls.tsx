import { Button, SegmentedControl } from "@radix-ui/themes";

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
    <section
      className="rounded-lg border border-amber-500/20 bg-slate-950/65 p-4 text-slate-100 shadow-[0_18px_50px_rgba(0,0,0,0.24)] backdrop-blur-xl"
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
