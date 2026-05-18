import { Badge } from "../../../components/ui";
import { glassSubtlePanelClass } from "../../../components/ui/glass";

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

export function LiveStatusStrip({
  run,
  connectionState,
  variant = "panel",
}: {
  run: GameRun;
  connectionState: ConnectionState | (string & {});
  variant?: "panel" | "nav";
}) {
  const isNav = variant === "nav";
  const connectionLabel =
    connectionLabels[connectionState as ConnectionState] ?? connectionState;

  return (
    <div
      className={
        isNav
          ? "live-status-strip flex min-w-0 shrink-0 flex-nowrap items-center gap-x-3 text-xs font-medium text-slate-300"
          : `${glassSubtlePanelClass} live-status-strip flex flex-wrap items-center gap-3 border-b border-amber-500/10 px-4 py-3 text-sm text-slate-300`
      }
      data-testid="live-status-strip"
    >
      {isNav ? (
        <>
          <span className="text-teal-300">
            <span aria-hidden="true" className="mr-2 text-lg leading-none">
              ↗
            </span>
            {connectionLabel}
          </span>
          <span className="text-amber-300">
            <span aria-hidden="true" className="mr-2 leading-none">
              ▶
            </span>
            {statusLabels[run.status] ?? run.status}
          </span>
          <span aria-hidden="true" className="h-6 w-px bg-slate-500/45" />
          <span className="max-w-[15rem] truncate font-mono text-xs tracking-wide text-slate-300">
            {run.session_id}
          </span>
        </>
      ) : (
        <>
          <Badge color={run.status === "failed" ? "red" : "amber"} variant="surface">
            {statusLabels[run.status] ?? run.status}
          </Badge>
          <span className="max-w-[12rem] truncate font-mono text-xs text-amber-50/80">
            {run.session_id}
          </span>
          <span className="text-slate-400">连接：{connectionLabel}</span>
        </>
      )}
      {run.error ? <span className="text-red-300">{run.error}</span> : null}
    </div>
  );
}
