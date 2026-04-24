import type { GameRun } from "../types";

export function LiveStatusStrip({
  run,
  connectionState,
}: {
  run: GameRun;
  connectionState: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-4 py-3 text-sm">
      <span className="font-medium text-slate-950">{run.status}</span>
      <span className="text-slate-600">{run.session_id}</span>
      <span className="text-slate-500">连接：{connectionState}</span>
      {run.error ? <span className="text-red-700">{run.error}</span> : null}
    </div>
  );
}
