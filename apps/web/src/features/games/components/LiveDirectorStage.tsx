import { Badge, Switch } from "@radix-ui/themes";
import type { CSSProperties } from "react";

import type { DirectorCue } from "../liveDirector";
import { actionLabel, phaseLabel } from "../liveLabels";
import type { LivePlayer } from "../liveSpectator";

type LiveDirectorStageProps = {
  cue: DirectorCue | null;
  backlogCount: number;
  isCatchingUp: boolean;
  players: LivePlayer[];
  activePlayerName: string | null;
  focusedPlayerName: string | null;
  autoFollow: boolean;
  onSelectPlayer: (name: string) => void;
  onAutoFollowChange: (value: boolean) => void;
};

export function LiveDirectorStage({
  cue,
  backlogCount,
  isCatchingUp,
  players,
  activePlayerName,
  focusedPlayerName,
  autoFollow,
  onSelectPlayer,
  onAutoFollowChange,
}: LiveDirectorStageProps) {
  const tone = stageTone(cue);
  const focusedPlayer =
    players.find((player) => player.name === focusedPlayerName) ?? null;
  const title = cue?.title ?? "等待导播事件";
  const body = cue?.body ?? "对局运行已创建，正在等待下一条实时事件。";

  return (
    <section
      className={`relative overflow-hidden rounded-lg border border-amber-900/40 bg-slate-950 text-slate-100 shadow-2xl ${tone.surface}`}
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_8%,rgba(30,64,175,0.28),transparent_28%),radial-gradient(circle_at_50%_48%,rgba(146,64,14,0.42),transparent_42%),linear-gradient(180deg,#07111f_0%,#111827_48%,#030712_100%)]" />
      <div className="absolute inset-x-0 top-0 h-32 bg-[linear-gradient(180deg,rgba(15,23,42,0.15),rgba(15,23,42,0.82)),repeating-linear-gradient(90deg,rgba(148,163,184,0.12)_0_1px,transparent_1px_72px)]" />

      <div className="relative min-h-[42rem] px-4 py-4 sm:min-h-[44rem] sm:px-6 lg:min-h-[46rem]">
        <div className="mx-auto flex w-fit items-center gap-3 rounded-full border border-amber-500/50 bg-slate-950/85 px-4 py-2 text-sm shadow-[0_0_24px_rgba(245,158,11,0.24)]">
          <span className="text-slate-400">观赛舞台</span>
          <span className="font-semibold text-amber-200">
            {cue?.round ? `第 ${cue.round} 轮` : "等待回合"}
          </span>
          <span className="text-slate-500">|</span>
          <span className="font-semibold text-amber-100">
            {cue?.phase ? phaseLabel(cue.phase) : "阶段未开始"}
          </span>
        </div>

        <div className="absolute left-1/2 top-[52%] h-[58%] w-[78%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-amber-700/45 bg-[radial-gradient(circle_at_50%_45%,rgba(120,78,40,0.96),rgba(54,34,19,0.96)_48%,rgba(20,13,9,0.98)_76%)] shadow-[inset_0_0_70px_rgba(0,0,0,0.72),0_30px_90px_rgba(0,0,0,0.55)] sm:w-[70%]" />
        <div className="absolute left-1/2 top-[52%] h-[44%] w-[58%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-amber-400/20 shadow-[inset_0_0_45px_rgba(251,191,36,0.12)]" />
        <div className="absolute left-1/2 top-[45%] -translate-x-1/2 -translate-y-1/2 select-none text-7xl font-black text-amber-100/10 sm:text-9xl">
          狼
        </div>

        <div className="absolute left-1/2 top-[50%] z-30 w-[min(24rem,48vw)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-amber-500/30 bg-slate-950/70 p-3 text-center shadow-[0_20px_60px_rgba(0,0,0,0.42)] backdrop-blur-sm sm:top-[54%] sm:w-[min(30rem,64vw)] sm:p-4">
          <div className="mb-3 flex flex-wrap justify-center gap-2 text-xs">
            {cue ? (
              <>
                <Badge color="amber" variant="surface">
                  #{cue.eventId}
                </Badge>
                <Badge color="gray" variant="surface">
                  {importanceLabel(cue.importance)}
                </Badge>
              </>
            ) : null}
            <Badge color="gray" variant="surface">
              队列剩余：{backlogCount}
            </Badge>
            {isCatchingUp ? (
              <Badge color="amber" variant="surface">
                自动追进度中
              </Badge>
            ) : null}
          </div>
          <h2 className="text-xl font-semibold text-amber-50 sm:text-2xl">
            {title}
          </h2>
          <div
            className="mt-3 max-h-36 overflow-auto whitespace-pre-wrap break-words rounded-md border border-amber-500/20 bg-black/20 p-3 text-left text-sm leading-6 text-slate-200 sm:max-h-48 sm:text-base"
            tabIndex={0}
          >
            {body}
          </div>
        </div>

        <div
          aria-label="圆桌座位"
          className="pointer-events-none absolute inset-x-0 top-0 bottom-28 z-20 sm:bottom-24 lg:bottom-20"
          role="group"
        >
          <p className="sr-only">圆桌座位</p>
          {players.length === 0 ? (
            <p className="absolute left-1/2 top-[72%] -translate-x-1/2 text-sm text-slate-400">
              等待玩家加入
            </p>
          ) : (
            players.map((player, index) => {
              const isActive =
                player.name === activePlayerName && player.isAlive;
              const isFocused = player.name === focusedPlayerName;
              const role = roleTone(player.role);
              const lastAction = player.lastAction
                ? actionLabel(player.lastAction)
                : "";
              const status = player.isAlive
                ? isActive
                  ? "发言中"
                  : STATUS_LABELS[player.status]
                : "出局";

              return (
                <button
                  aria-label={`${index + 1}号 ${player.name} ${
                    player.role
                  } ${status} ${lastAction} ${player.lastDetail}`}
                  className={`pointer-events-auto absolute left-[var(--seat-x)] top-[var(--seat-y)] w-14 translate-x-[var(--seat-offset-x)] -translate-y-1/2 text-center transition duration-200 hover:translate-x-[var(--seat-offset-x)] hover:-translate-y-1/2 hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-200 sm:left-[var(--seat-sm-x)] sm:top-[var(--seat-sm-y)] sm:w-24 sm:-translate-x-1/2 sm:hover:-translate-x-1/2 lg:w-28 ${
                    isFocused ? "is-focused" : ""
                  } ${!player.isAlive ? "opacity-60 grayscale" : ""}`}
                  key={player.name}
                  onClick={() => onSelectPlayer(player.name)}
                  style={seatStyle(index, players.length)}
                  type="button"
                >
                  <span className="mx-auto mb-1 flex h-5 w-5 items-center justify-center rounded-full border border-amber-300/50 bg-slate-950 text-[10px] font-semibold text-amber-100 shadow-md sm:h-7 sm:w-7 sm:text-xs">
                    {index + 1}
                  </span>
                  <span
                    className={`mx-auto flex h-10 w-10 items-center justify-center rounded-full border-2 bg-gradient-to-br ${avatarGradient(
                      player.name,
                    )} text-sm font-bold text-slate-100 shadow-lg sm:h-16 sm:w-16 sm:text-lg ${role.ring} ${
                      isActive
                        ? "border-amber-200 shadow-[0_0_26px_rgba(250,204,21,0.85),0_0_42px_rgba(34,197,94,0.42)]"
                        : ""
                    } ${
                      isFocused
                        ? "ring-2 ring-amber-100 ring-offset-2 ring-offset-slate-950"
                        : ""
                    }`}
                  >
                    {avatarText(player.name)}
                  </span>
                  <span className="mt-1 block truncate text-xs font-semibold text-slate-50 drop-shadow sm:text-sm">
                    {player.name}
                  </span>
                  <span
                    className={`mx-auto mt-1 hidden max-w-full items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 sm:inline-flex ${role.badge}`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        player.isAlive ? role.dot : "bg-slate-400"
                      }`}
                    />
                    <span className="truncate">{player.role}</span>
                  </span>
                  <span
                    className={`mx-auto mt-1 hidden w-fit rounded-md px-2 py-0.5 text-[11px] font-semibold sm:block ${
                      isActive
                        ? "bg-green-500/20 text-green-200 ring-1 ring-green-300/40"
                        : "bg-black/35 text-slate-300"
                    }`}
                  >
                    {status}
                  </span>
                </button>
              );
            })
          )}
        </div>

        <div className="absolute inset-x-4 bottom-4 z-40 flex flex-col gap-3 rounded-lg border border-amber-500/25 bg-slate-950/78 p-3 text-sm text-slate-200 backdrop-blur sm:inset-x-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-amber-200">当前关注</p>
            <p className="mt-1 truncate">
              {focusedPlayer
                ? `${focusedPlayer.name} · ${focusedPlayer.role} · ${
                    focusedPlayer.lastAction
                      ? actionLabel(focusedPlayer.lastAction)
                      : "等待行动"
                  }`
                : "等待玩家行动"}
            </p>
          </div>
          <label className="flex shrink-0 items-center gap-2 text-xs text-slate-300">
            <Switch
              checked={autoFollow}
              color="amber"
              onCheckedChange={onAutoFollowChange}
            />
            自动跟随
          </label>
        </div>
      </div>
    </section>
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

type SeatStyle = CSSProperties &
  Record<
    | "--seat-x"
    | "--seat-y"
    | "--seat-offset-x"
    | "--seat-sm-x"
    | "--seat-sm-y",
    string
  >;

function seatStyle(index: number, total: number): SeatStyle {
  const angle = -90 + (360 / Math.max(total, 1)) * index;
  const radians = (angle * Math.PI) / 180;
  const xVector = Math.cos(radians);
  const baseX = 50 + 46 * xVector;
  const baseY = 50 + 45 * Math.sin(radians);
  const smX = 50 + 41 * xVector;
  const smY = 50 + 37 * Math.sin(radians);
  const seatOffsetX =
    xVector > 0.92 ? "-85%" : xVector < -0.92 ? "-15%" : "-50%";

  return {
    "--seat-x": `${baseX}%`,
    "--seat-y": `${baseY}%`,
    "--seat-offset-x": seatOffsetX,
    "--seat-sm-x": `${smX}%`,
    "--seat-sm-y": `${smY}%`,
  };
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

function stageTone(cue: DirectorCue | null) {
  if (!cue) {
    return { surface: "" };
  }
  if (cue.importance === "terminal") {
    return { surface: "ring-1 ring-emerald-400/30" };
  }
  if (cue.phase === "night") {
    return { surface: "ring-1 ring-indigo-300/25" };
  }
  if (cue.phase === "vote") {
    return { surface: "ring-1 ring-amber-300/30" };
  }
  if (cue.importance === "key") {
    return { surface: "ring-1 ring-cyan-300/25" };
  }
  return { surface: "" };
}
