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
    <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-4 py-3 text-sm">
      <span className="font-medium text-slate-950">
        {statusLabels[run.status] ?? run.status}
      </span>
      <span className="text-slate-600">{run.session_id}</span>
      <span className="text-slate-500">
        连接：
        {connectionLabels[connectionState as ConnectionState] ??
          connectionState}
      </span>
      <span className="text-slate-500">节奏：{eventPacingLabel}</span>
      {run.error ? <span className="text-red-700">{run.error}</span> : null}
    </div>
  );
}
