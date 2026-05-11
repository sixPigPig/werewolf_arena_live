import { Badge } from "@radix-ui/themes";

import type { ConnectionState } from "../hooks/useGameRunEvents";
import type { GameRun } from "../types";

const statusLabels = {
  queued: "排队中",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
} as const;

const connectionLabels = {
  idle: "未连接",
  connecting: "连接中",
  open: "已连接",
  closed: "已关闭",
  error: "连接异常",
} satisfies Record<ConnectionState, string>;

const eventPacingLabels = {
  off: "快速执行",
  standard: "标准演示",
  slow: "慢速讲解",
} as const;

export function LiveStatusStrip({
  run,
  connectionState,
}: {
  run: GameRun;
  connectionState: ConnectionState | (string & {});
}) {
  const eventPacingLabel =
    eventPacingLabels[run.event_pacing as keyof typeof eventPacingLabels] ??
    eventPacingLabels.off;

  return (
    <div
      className="live-status-strip flex flex-wrap items-center gap-3 border-b border-amber-500/10 bg-slate-950/70 px-4 py-3 text-sm text-slate-300 backdrop-blur-xl"
      data-testid="live-status-strip"
    >
      <Badge color={run.status === "failed" ? "red" : "amber"} variant="surface">
        {statusLabels[run.status] ?? run.status}
      </Badge>
      <span className="font-mono text-xs text-amber-50/80">
        {run.session_id}
      </span>
      <span className="text-slate-400">
        连接：
        {connectionLabels[connectionState as ConnectionState] ??
          connectionState}
      </span>
      <span className="text-slate-400">节奏：{eventPacingLabel}</span>
      {run.error ? <span className="text-red-300">{run.error}</span> : null}
    </div>
  );
}
