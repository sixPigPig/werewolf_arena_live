import { Badge, Card, Switch } from "@radix-ui/themes";
import type { CSSProperties } from "react";

import type { DirectorCue } from "../liveDirector";
import { actionLabel, phaseLabel } from "../liveLabels";
import type { LivePlayer } from "../liveSpectator";

type LiveDirectorStageProps = {
  cue: DirectorCue | null;
  backlogCount: number;
  isCatchingUp: boolean;
  players?: LivePlayer[];
  activePlayerName?: string | null;
  focusedPlayerName?: string | null;
  autoFollow?: boolean;
  onSelectPlayer?: (name: string) => void;
  onAutoFollowChange?: (value: boolean) => void;
};

export function LiveDirectorStage({
  cue,
  backlogCount,
  isCatchingUp,
  players = [],
  activePlayerName = null,
  focusedPlayerName = null,
  autoFollow = true,
  onSelectPlayer = noopSelectPlayer,
  onAutoFollowChange = noopAutoFollowChange,
}: LiveDirectorStageProps) {
  const stagedPlayer =
    players.find(
      (player) => player.name === (focusedPlayerName ?? activePlayerName),
    ) ??
    players[0] ??
    null;
  const helperPreview = [
    actionLabel(stagedPlayer?.lastAction || cue?.action || null),
    autoFollow,
    Switch,
    avatarGradient(stagedPlayer?.name ?? ""),
    roleTone(stagedPlayer?.role ?? ""),
    seatStyle(stagedPlayer ? players.indexOf(stagedPlayer) : 0, players.length),
    onSelectPlayer,
    onAutoFollowChange,
    stagedPlayer
      ? STATUS_LABELS[stagedPlayer.status]
      : STATUS_LABELS.waiting,
    avatarText(stagedPlayer?.name ?? ""),
  ] as const;
  // Task 3 renders these helpers into the cinematic table; keep them checked.
  void helperPreview;

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

const STATUS_LABELS: Record<LivePlayer["status"], string> = {
  waiting: "等待中",
  thinking: "思考中",
  requesting: "请求模型",
  streaming: "发言中",
  responded: "已返回",
  acted: "已行动",
  out: "出局",
};

const AVATAR_GRADIENTS = [
  "from-slate-700 to-slate-950",
  "from-stone-600 to-slate-950",
  "from-zinc-700 to-stone-950",
  "from-neutral-600 to-slate-900",
  "from-amber-900 to-slate-950",
  "from-red-950 to-slate-950",
];

function roleTone(role: string) {
  if (role.includes("狼")) {
    return {
      ring: "border-red-400 shadow-red-500/45",
      badge: "bg-red-950/80 text-red-100 ring-red-500/40",
      dot: "bg-red-400",
    };
  }
  if (role.includes("预言家")) {
    return {
      ring: "border-amber-300 shadow-amber-300/45",
      badge: "bg-amber-900/80 text-amber-100 ring-amber-400/50",
      dot: "bg-amber-300",
    };
  }
  if (role.includes("女巫")) {
    return {
      ring: "border-violet-300 shadow-violet-300/45",
      badge: "bg-violet-950/80 text-violet-100 ring-violet-400/50",
      dot: "bg-violet-300",
    };
  }
  if (role.includes("守卫") || role.includes("医生")) {
    return {
      ring: "border-cyan-300 shadow-cyan-300/35",
      badge: "bg-cyan-950/80 text-cyan-100 ring-cyan-400/40",
      dot: "bg-cyan-300",
    };
  }
  if (role.includes("猎人")) {
    return {
      ring: "border-sky-300 shadow-sky-300/35",
      badge: "bg-sky-950/80 text-sky-100 ring-sky-400/40",
      dot: "bg-sky-300",
    };
  }
  return {
    ring: "border-stone-300 shadow-stone-300/25",
    badge: "bg-stone-900/80 text-stone-100 ring-stone-400/30",
    dot: "bg-stone-300",
  };
}

function avatarGradient(name: string) {
  const charTotal = Array.from(name).reduce(
    (total, char) => total + char.charCodeAt(0),
    0,
  );
  return AVATAR_GRADIENTS[charTotal % AVATAR_GRADIENTS.length];
}

function avatarText(name: string) {
  return Array.from(name).slice(0, 2).join("");
}

function seatStyle(index: number, total: number): CSSProperties {
  const angle = -90 + (360 / Math.max(total, 1)) * index;
  const radiusX = 43;
  const radiusY = 38;
  const x = 50 + radiusX * Math.cos((angle * Math.PI) / 180);
  const y = 50 + radiusY * Math.sin((angle * Math.PI) / 180);

  return {
    left: `${x}%`,
    top: `${y}%`,
    transform: "translate(-50%, -50%)",
  };
}

function noopSelectPlayer(_name: string) {
  return undefined;
}

function noopAutoFollowChange(_value: boolean) {
  return undefined;
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
