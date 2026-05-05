import { Badge, Card } from "@radix-ui/themes";

import type { DirectorCue } from "../liveDirector";
import { phaseLabel } from "../liveLabels";

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
      <Card asChild size="3">
        <section className="min-h-80">
          <p className="text-xs font-semibold text-slate-500">观赛舞台</p>
          <p className="mt-3 text-sm text-slate-600">等待导播事件...</p>
        </section>
      </Card>
    );
  }

  const tone = stageTone(cue);

  return (
    <Card asChild size="1">
      <section className={`min-h-80 overflow-hidden ${tone.surface}`}>
      <div className={`border-b px-5 py-4 ${tone.header}`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-slate-500">观赛舞台</p>
            <h2 className="mt-1 break-words text-2xl font-semibold text-slate-950">
              {cue.title}
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge color="gray" variant="surface">
              #{cue.eventId}
            </Badge>
            <Badge color="gray" variant="surface">
              {importanceLabel(cue.importance)}
            </Badge>
          </div>
        </div>
      </div>

      <div className="space-y-4 px-5 py-5">
        <div className="flex flex-wrap gap-2 text-sm text-slate-600">
          <span>{cue.round ? `第 ${cue.round} 轮` : "等待回合"}</span>
          <span>
            {cue.phase ? `阶段：${phaseLabel(cue.phase)}` : "阶段未开始"}
          </span>
          {cue.actor ? <span>玩家：{cue.actor}</span> : null}
        </div>

        {cue.body ? (
          <div className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-white/80 p-4 text-base leading-7 text-slate-800 shadow-sm">
            {cue.body}
          </div>
        ) : (
          <p className="rounded-md border border-slate-200 bg-white/80 p-4 text-sm text-slate-600">
            这条事件没有额外内容。
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <Badge color="gray" variant="surface">
            队列剩余：{backlogCount}
          </Badge>
          {isCatchingUp ? (
            <Badge color="amber" variant="surface">
              自动追进度中
            </Badge>
          ) : null}
        </div>
      </div>
      </section>
    </Card>
  );
}

function importanceLabel(importance: DirectorCue["importance"]) {
  if (importance === "terminal") {
    return "结算";
  }
  if (importance === "key") {
    return "关键";
  }
  if (importance === "action") {
    return "行动";
  }
  return "流程";
}

function stageTone(cue: DirectorCue) {
  if (cue.importance === "terminal") {
    return {
      surface: "bg-emerald-50/60",
      header: "border-emerald-200 bg-emerald-50/80",
    };
  }
  if (cue.phase === "night") {
    return {
      surface: "bg-indigo-50/70",
      header: "border-indigo-200 bg-indigo-50/90",
    };
  }
  if (cue.phase === "vote") {
    return {
      surface: "bg-amber-50/70",
      header: "border-amber-200 bg-amber-50/90",
    };
  }
  if (cue.importance === "key") {
    return {
      surface: "bg-sky-50/60",
      header: "border-sky-200 bg-sky-50/80",
    };
  }
  return {
    surface: "bg-white",
    header: "border-slate-200 bg-white",
  };
}
