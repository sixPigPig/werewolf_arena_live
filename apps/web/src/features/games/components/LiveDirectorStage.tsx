import { Badge, Switch } from "../../../components/ui";
import { withGlassPanel } from "../../../components/ui/glass";
import type { CSSProperties } from "react";

import type { DirectorCue } from "../liveDirector";
import { actionLabel, phaseLabel } from "../liveLabels";
import type { GodViewState } from "../liveGodView";
import type { LivePlayer } from "../liveSpectator";
import { appearanceClassName } from "../playerProfileOptions";

type LiveDirectorStageProps = {
  cue: DirectorCue | null;
  backlogCount: number;
  isCatchingUp: boolean;
  players: LivePlayer[];
  activePlayerName: string | null;
  focusedPlayerName: string | null;
  godViewState?: GodViewState;
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
  godViewState,
  autoFollow,
  onSelectPlayer,
  onAutoFollowChange,
}: LiveDirectorStageProps) {
  const tone = stageTone(cue);
  const focusedPlayer =
    players.find((player) => player.name === focusedPlayerName) ?? null;
  const focusedGodPlayer =
    godViewState?.players.find((player) => player.name === focusedPlayerName) ??
    null;
  const title = cue?.title ?? "等待导播事件";
  const body = cue?.body ?? "对局运行已创建，正在等待下一条实时事件。";
  const isTerminalCue = cue?.importance === "terminal";

  return (
    <section
      className={withGlassPanel(
        "relative overflow-hidden rounded-lg text-slate-100 shadow-[0_32px_100px_rgba(0,0,0,0.42)]",
        tone.surface,
      )}
      data-testid="live-director-stage"
    >
      <div
        className="relative min-h-[36rem] px-4 py-3 sm:min-h-[38rem] sm:px-6 lg:min-h-[40rem]"
        data-testid="live-director-stage-shell"
      >
        <div className="relative z-40 mx-auto flex w-full max-w-5xl flex-col gap-2">
          <div className="glass-panel-subtle mx-auto flex w-fit items-center gap-3 rounded-full border border-amber-300/35 px-4 py-2 text-sm shadow-[0_0_28px_rgba(245,158,11,0.2)]">
            <span className="text-slate-400">观赛舞台</span>
            <span className="font-semibold text-amber-200">
              {cue?.round ? `第 ${cue.round} 轮` : "等待回合"}
            </span>
            <span className="text-amber-500/40">|</span>
            <span className="font-semibold text-teal-100">
              {cue?.phase ? phaseLabel(cue.phase) : "阶段未开始"}
            </span>
          </div>
          {godViewState ? (
            <div
              className="god-view-stage-strip grid grid-cols-2 gap-1 rounded-md border border-amber-300/20 bg-black/35 px-3 py-2 text-[11px] text-slate-300 shadow-[0_16px_45px_rgba(0,0,0,0.24)] sm:grid-cols-4 lg:grid-cols-7"
              data-testid="god-view-stage-strip"
            >
              <StageStat label="局名" value={godViewState.boardName} />
              <StageStat label="天夜" value={godViewState.dayNightLabel} />
              <StageStat label="阶段" value={godViewState.phaseLabel} />
              <StageStat label="当前席" value={godViewState.currentSeatLabel} />
              <StageStat label="倒计时" value={godViewState.countdownLabel} />
              <StageStat label="存活" value={godViewState.aliveLabel} />
              <StageStat label="胜负" value={godViewState.winMode} />
            </div>
          ) : null}
        </div>

        <div className="absolute left-1/2 top-[55%] h-[58%] w-[78%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-amber-600/45 bg-[radial-gradient(circle_at_50%_45%,rgba(92,62,34,0.98),rgba(40,28,19,0.98)_52%,rgba(10,8,7,0.99)_78%)] shadow-[inset_0_0_82px_rgba(0,0,0,0.76),inset_0_0_0_1px_rgba(251,191,36,0.08),0_34px_95px_rgba(0,0,0,0.58)] sm:w-[70%]" />
        <div className="absolute left-1/2 top-[55%] h-[44%] w-[58%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-amber-300/18 bg-[conic-gradient(from_210deg,rgba(251,191,36,0.04),transparent_18%,rgba(20,184,166,0.06)_32%,transparent_48%,rgba(251,191,36,0.05)_72%,transparent)] shadow-[inset_0_0_50px_rgba(251,191,36,0.13)]" />
        <div className="absolute left-1/2 top-[48%] -translate-x-1/2 -translate-y-1/2 select-none text-7xl font-black text-amber-100/10 sm:text-9xl">
          狼
        </div>

        <div className="glass-panel-subtle absolute left-1/2 top-[51%] z-30 w-[min(24rem,48vw)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-amber-300/25 p-3 text-center shadow-[0_24px_68px_rgba(0,0,0,0.38)] sm:top-[55%] sm:w-[min(30rem,64vw)] sm:p-4">
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
          {focusedGodPlayer ? (
            <div className="mt-2 flex flex-wrap justify-center gap-2 text-xs">
              <span className="rounded-md border border-amber-300/30 bg-amber-400/10 px-2 py-1 text-amber-100">
                {focusedGodPlayer.seatNumber}号 · {focusedGodPlayer.role}
              </span>
              <span className="rounded-md border border-sky-300/25 bg-sky-400/10 px-2 py-1 text-sky-100">
                {focusedGodPlayer.camp} · {focusedGodPlayer.identityGroup}
              </span>
              {focusedGodPlayer.isSheriff ? (
                <span className="rounded-md border border-amber-300/35 bg-amber-400/15 px-2 py-1 text-amber-100">
                  警长发言
                </span>
              ) : null}
            </div>
          ) : null}
          <div
            className="mt-3 max-h-36 overflow-auto whitespace-pre-wrap break-words rounded-md border border-amber-300/15 p-3 text-left text-sm leading-6 text-slate-200 shadow-[inset_0_0_24px_rgba(0,0,0,0.24)] sm:max-h-48 sm:text-base"
            tabIndex={0}
          >
            {body}
          </div>
        </div>

        <div
          aria-label="圆桌座位"
          className="pointer-events-none absolute inset-x-0 top-0 bottom-24 z-20 sm:bottom-20 lg:bottom-16"
          role="group"
        >
          <p className="sr-only">圆桌座位</p>
          {players.length === 0 ? (
            <p className="absolute left-1/2 top-[72%] -translate-x-1/2 text-sm text-slate-400">
              等待玩家加入
            </p>
          ) : (
            players.map((player, index) => {
              const isCurrentSpeaker =
                !isTerminalCue &&
                player.name === activePlayerName &&
                player.isAlive;
              const isLastActive =
                isTerminalCue &&
                player.name === activePlayerName &&
                player.isAlive;
              const isFocused = player.name === focusedPlayerName;
              const role = roleTone(player.role);
              const lastAction = player.lastAction
                ? actionLabel(player.lastAction)
                : "";
              const status = playerSeatStatus(
                player,
                isTerminalCue,
                isCurrentSpeaker,
                isLastActive,
              );
              const seatState = !player.isAlive
                ? "out"
                : isCurrentSpeaker
                  ? "speaking"
                  : isLastActive
                    ? "last-active"
                    : isFocused
                      ? "focused"
                      : "idle";

              return (
                <button
                  aria-label={`${index + 1}号 ${player.name} ${
                    player.role
                  } ${status} ${lastAction} ${player.lastDetail}`}
                  className={`pointer-events-auto absolute left-[var(--seat-x)] top-[var(--seat-y)] w-14 translate-x-[var(--seat-offset-x)] -translate-y-1/2 text-center transition duration-200 hover:translate-x-[var(--seat-offset-x)] hover:-translate-y-1/2 hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-200 sm:left-[var(--seat-sm-x)] sm:top-[var(--seat-sm-y)] sm:w-24 sm:-translate-x-1/2 sm:hover:-translate-x-1/2 lg:w-28 ${
                    isFocused ? "is-focused" : ""
                  } ${!player.isAlive ? "opacity-60 grayscale" : ""}`}
                  data-seat-state={seatState}
                  key={player.name}
                  onClick={() => onSelectPlayer(player.name)}
                  style={seatStyle(index, players.length)}
                  type="button"
                >
                  <span className="mx-auto mb-1 flex h-5 w-5 items-center justify-center rounded-full border border-amber-300/50 text-[10px] font-semibold text-amber-100 shadow-md sm:h-7 sm:w-7 sm:text-xs">
                    {index + 1}
                  </span>
                  <span
                    className={`relative mx-auto flex h-10 w-10 items-center justify-center rounded-full border-2 bg-gradient-to-br ${avatarGradient(
                      player.name,
                    )} ${appearanceClassName(
                      player.appearanceId,
                    )} text-sm font-bold text-slate-100 shadow-lg sm:h-12 sm:w-12 sm:text-base md:h-16 md:w-16 md:text-lg ${role.ring} ${
                      isCurrentSpeaker
                        ? "border-teal-100 shadow-[0_0_28px_rgba(45,212,191,0.88),0_0_48px_rgba(250,204,21,0.28)]"
                        : isLastActive
                          ? "border-amber-200 shadow-[0_0_22px_rgba(251,191,36,0.45)]"
                        : ""
                    } ${
                      isFocused
                        ? "ring-2 ring-amber-100 ring-offset-2 ring-offset-slate-950"
                        : ""
                    }`}
                  >
                    {isCurrentSpeaker ? (
                      <span
                        aria-hidden="true"
                        className="absolute -inset-2 rounded-full border border-teal-200/55 shadow-[0_0_24px_rgba(45,212,191,0.42)] animate-pulse"
                      />
                    ) : null}
                    <span className="relative z-10">{avatarText(player.name)}</span>
                  </span>
                  <span className="mt-1 block truncate text-xs font-semibold text-slate-50 drop-shadow sm:text-sm">
                    {player.name}
                  </span>
                  <span
                    className={`mx-auto mt-1 hidden max-w-full items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 md:inline-flex ${role.badge}`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        player.isAlive ? role.dot : "bg-slate-400"
                      }`}
                    />
                    <span className="truncate">{player.role}</span>
                  </span>
                  <span
                    className={`mx-auto mt-1 hidden w-fit rounded-md px-2 py-0.5 text-[11px] font-semibold md:block ${
                      isCurrentSpeaker
                        ? "bg-teal-400/15 text-teal-100 ring-1 ring-teal-200/40"
                        : isLastActive
                          ? "bg-amber-500/15 text-amber-100 ring-1 ring-amber-300/35"
                        : "text-slate-300"
                    }`}
                  >
                    {status}
                  </span>
                </button>
              );
            })
          )}
        </div>

        <div className="glass-panel-subtle absolute inset-x-4 bottom-4 z-40 flex flex-col gap-3 rounded-lg border border-amber-300/20 p-3 text-sm text-slate-200 shadow-[0_16px_45px_rgba(0,0,0,0.24)] sm:inset-x-6 sm:flex-row sm:items-center sm:justify-between">
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

function StageStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="block text-[10px] text-slate-500">{label}</span>
      <span className="block truncate font-semibold text-slate-100">
        {value}
      </span>
    </div>
  );
}

function playerSeatStatus(
  player: LivePlayer,
  isTerminalCue: boolean,
  isCurrentSpeaker: boolean,
  isLastActive: boolean,
): string {
  if (!player.isAlive) {
    return "出局";
  }
  if (isTerminalCue) {
    return terminalPlayerStatus(player.status, isLastActive);
  }
  if (isCurrentSpeaker) {
    return "发言中";
  }
  return STATUS_LABELS[player.status];
}

function terminalPlayerStatus(
  status: LivePlayer["status"],
  isLastActive: boolean,
): string {
  if (isLastActive) {
    return "最后行动";
  }
  if (
    status === "thinking" ||
    status === "requesting" ||
    status === "streaming"
  ) {
    return "已行动";
  }
  return STATUS_LABELS[status];
}

const AVATAR_GRADIENTS = [
  "from-[#26323b] to-[#05070a]",
  "from-[#3b3226] to-[#060504]",
  "from-[#173136] to-[#030607]",
  "from-[#33263a] to-[#050407]",
  "from-[#4a271f] to-[#070404]",
  "from-[#1f2937] to-[#030507]",
];

function roleTone(role: string) {
  if (role.includes("狼")) {
    return {
      ring: "border-red-400 shadow-red-500/45",
      badge: "bg-red-950/75 text-red-100 ring-red-400/35",
      dot: "bg-red-400",
    };
  }
  if (role.includes("预言家")) {
    return {
      ring: "border-amber-200 shadow-amber-300/40",
      badge: "bg-amber-950/70 text-amber-100 ring-amber-300/35",
      dot: "bg-amber-300",
    };
  }
  if (role.includes("女巫")) {
    return {
      ring: "border-teal-200 shadow-teal-300/35",
      badge: "bg-teal-950/70 text-teal-100 ring-teal-300/35",
      dot: "bg-teal-300",
    };
  }
  if (role.includes("守卫") || role.includes("医生")) {
    return {
      ring: "border-teal-200 shadow-teal-300/35",
      badge: "bg-teal-950/70 text-teal-100 ring-teal-300/35",
      dot: "bg-teal-300",
    };
  }
  if (role.includes("猎人")) {
    return {
      ring: "border-amber-200 shadow-amber-300/35",
      badge: "bg-amber-950/70 text-amber-100 ring-amber-300/35",
      dot: "bg-amber-300",
    };
  }
  return {
    ring: "border-stone-300 shadow-stone-300/25",
    badge: "bg-stone-950/70 text-stone-100 ring-stone-300/25",
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
  const baseY = 50 + 40 * Math.sin(radians);
  const smX = 50 + 41 * xVector;
  const smY = 50 + 32 * Math.sin(radians);
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
