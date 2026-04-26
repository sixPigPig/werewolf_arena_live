import type { DirectorCue } from "../liveDirector";

type LiveDirectorStageProps = {
  cue: DirectorCue | null;
  backlogCount: number;
  isCatchingUp: boolean;
};

export function LiveDirectorStage({
  cue,
  backlogCount,
  isCatchingUp,
}: LiveDirectorStageProps) {
  if (!cue) {
    return (
      <section className="min-h-80 rounded-md border border-slate-200 bg-white p-6">
        <p className="text-sm text-slate-600">等待导播事件...</p>
      </section>
    );
  }

  return (
    <section className="min-h-80 rounded-md border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-medium text-slate-500">当前播放</p>
            <h2 className="mt-1 break-words text-xl font-semibold text-slate-950">
              {cue.title}
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded border border-slate-200 px-2 py-1 text-slate-700">
              #{cue.eventId}
            </span>
            <span className="rounded border border-slate-200 px-2 py-1 text-slate-700">
              {cue.type}
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-4 px-5 py-5">
        <div className="flex flex-wrap gap-2 text-sm text-slate-600">
          <span>{cue.round ? `第 ${cue.round} 轮` : "等待回合"}</span>
          <span>{cue.phase ? `阶段：${cue.phase}` : "阶段未开始"}</span>
          {cue.actor ? <span>玩家：{cue.actor}</span> : null}
        </div>

        {cue.body ? (
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-100 p-4 text-sm leading-6 text-slate-800">
            {cue.body}
          </pre>
        ) : (
          <p className="rounded-md bg-slate-50 p-4 text-sm text-slate-600">
            这条事件没有额外内容。
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <span className="rounded border border-slate-200 px-2 py-1">
            队列剩余：{backlogCount}
          </span>
          {isCatchingUp ? (
            <span className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-amber-800">
              自动追进度中
            </span>
          ) : null}
        </div>
      </div>
    </section>
  );
}
