import { Button, Card, SegmentedControl } from "@radix-ui/themes";

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
    <Card asChild size="1">
      <section>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-36">
          <h2 className="text-sm font-semibold text-slate-950">观赛节奏</h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
            {isCatchingUp ? <span>自动追进度</span> : null}
            <span>队列 {backlogCount} 条</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            color="gray"
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
            <SegmentedControl.Item value="1">
              1x
            </SegmentedControl.Item>
            <SegmentedControl.Item value="1.5">
              1.5x
            </SegmentedControl.Item>
          </SegmentedControl.Root>
        </div>
      </div>
      </section>
    </Card>
  );
}
