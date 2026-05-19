import { Badge, Switch } from "../../../components/ui";
import { withGlassPanel } from "../../../components/ui/glass";

import type { DirectorCue } from "../liveDirector";
import { actionLabel, phaseLabel } from "../liveLabels";
import type { LiveDebugTrace } from "../liveDebugTrace";
import type { GodViewPlayer, GodViewState } from "../liveGodView";
import type { LivePlayer } from "../liveSpectator";
import { appearanceClassName } from "../playerProfileOptions";

type LiveDirectorStageProps = {
  cue: DirectorCue | null;
  backlogCount: number;
  isCatchingUp: boolean;
  players: LivePlayer[];
  activePlayerName: string | null;
  focusedPlayerName: string | null;
  debugTrace?: LiveDebugTrace | null;
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
  debugTrace,
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
  const speakerGodPlayer = godViewState?.speakerFlow.current ?? focusedGodPlayer;
  const title = cue?.title ?? "等待导播事件";
  const body = cue?.body ?? "对局运行已创建，正在等待下一条实时事件。";
  const isTerminalCue = cue?.importance === "terminal";
  const stagePlayers = godViewState?.players.slice(0, 12) ?? [];
  const railSplitIndex = Math.ceil(stagePlayers.length / 2);
  const leftRailPlayers = stagePlayers.slice(0, railSplitIndex);
  const rightRailPlayers = stagePlayers.slice(railSplitIndex);
  const livePlayersByName = new Map(players.map((player) => [player.name, player]));
  const debugHighlightedPlayers = new Set(debugTrace?.relatedPlayers ?? []);

  return (
    <section
      className={withGlassPanel(
        "god-view-frame relative overflow-hidden rounded-lg text-slate-100 shadow-[0_32px_100px_rgba(0,0,0,0.42)]",
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
        </div>

        <div className="absolute left-1/2 top-[55%] h-[58%] w-[78%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-amber-600/45 bg-[radial-gradient(circle_at_50%_45%,rgba(92,62,34,0.98),rgba(40,28,19,0.98)_52%,rgba(10,8,7,0.99)_78%)] shadow-[inset_0_0_82px_rgba(0,0,0,0.76),inset_0_0_0_1px_rgba(251,191,36,0.08),0_34px_95px_rgba(0,0,0,0.58)] sm:w-[70%]" />
        <div className="absolute left-1/2 top-[55%] h-[44%] w-[58%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-amber-300/18 bg-[conic-gradient(from_210deg,rgba(251,191,36,0.04),transparent_18%,rgba(20,184,166,0.06)_32%,transparent_48%,rgba(251,191,36,0.05)_72%,transparent)] shadow-[inset_0_0_50px_rgba(251,191,36,0.13)]" />
        <div className="absolute left-1/2 top-[48%] -translate-x-1/2 -translate-y-1/2 select-none text-7xl font-black text-amber-100/10 sm:text-9xl">
          狼
        </div>

        <div className="god-view-player-rails pointer-events-none absolute inset-x-3 top-20 bottom-24 z-40 grid grid-cols-[minmax(7rem,12rem)_minmax(14rem,1fr)_minmax(7rem,12rem)] gap-3 sm:inset-x-5 sm:top-20 sm:bottom-24 lg:grid-cols-[minmax(9rem,14rem)_minmax(20rem,1fr)_minmax(9rem,14rem)]">
          <PlayerRail
            activePlayerName={activePlayerName}
            focusedPlayerName={focusedPlayerName}
            isTerminalCue={isTerminalCue}
            debugHighlightedPlayers={debugHighlightedPlayers}
            livePlayersByName={livePlayersByName}
            onSelectPlayer={onSelectPlayer}
            players={leftRailPlayers}
            side="left"
          />
          <div aria-hidden="true" />
          <PlayerRail
            activePlayerName={activePlayerName}
            focusedPlayerName={focusedPlayerName}
            isTerminalCue={isTerminalCue}
            debugHighlightedPlayers={debugHighlightedPlayers}
            livePlayersByName={livePlayersByName}
            onSelectPlayer={onSelectPlayer}
            players={rightRailPlayers}
            side="right"
          />
        </div>

        <div className="glass-panel-subtle absolute left-1/2 top-[51%] z-30 w-[min(24rem,48vw)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-amber-300/25 p-3 text-center shadow-[0_24px_68px_rgba(0,0,0,0.38)] sm:top-[55%] sm:w-[min(30rem,64vw)] sm:p-4">
          <div className="mb-3 flex flex-wrap justify-center gap-2 text-xs">
            {speakerGodPlayer ? (
              <div
                className="god-view-speaker-stage mb-2 grid w-full grid-cols-[5rem_minmax(0,1fr)] items-center gap-3 rounded-lg border border-amber-300/30 bg-black/45 p-3 text-left shadow-[0_0_36px_rgba(251,191,36,0.16)] sm:grid-cols-[6rem_minmax(0,1fr)]"
                data-testid="god-view-speaker-stage"
              >
                <div
                  className={`relative flex aspect-[3/4] items-center justify-center overflow-hidden rounded-md border-2 bg-gradient-to-br ${avatarGradient(
                    speakerGodPlayer.name,
                  )} ${appearanceClassName(
                    speakerGodPlayer.appearanceId,
                  )} ${speakerTone(speakerGodPlayer)}`}
                >
                  {speakerGodPlayer.avatarImageUrl ? (
                    <img
                      alt={`${speakerGodPlayer.name} 当前发言形象`}
                      className="h-full w-full object-cover"
                      src={speakerGodPlayer.avatarImageUrl}
                    />
                  ) : (
                    <span className="text-3xl font-black text-amber-50">
                      {avatarText(speakerGodPlayer.name)}
                    </span>
                  )}
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-amber-200">
                    {speakerGodPlayer.seatNumber} 号
                  </p>
                  <p className="truncate text-xl font-semibold text-amber-50">
                    {speakerGodPlayer.name}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    <span className="rounded border border-amber-300/30 bg-amber-400/10 px-2 py-1 text-amber-100">
                      {speakerGodPlayer.role}
                    </span>
                    <span className="rounded border border-sky-300/25 bg-sky-400/10 px-2 py-1 text-sky-100">
                      {speakerGodPlayer.camp}
                    </span>
                  </div>
                  <div className="mt-2 grid grid-cols-1 gap-1 text-xs text-slate-300 sm:grid-cols-2">
                    <span>
                      上一位：{godViewState?.speakerFlow.previous?.name ?? "-"}
                    </span>
                    <span>
                      下一位：{godViewState?.speakerFlow.next?.name ?? "-"}
                    </span>
                  </div>
                </div>
              </div>
            ) : null}
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
            {debugTrace ? (
              <Badge color="amber" variant="surface">
                {traceEventRange(debugTrace)}
              </Badge>
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

        {stagePlayers.length === 0 ? (
          <p className="absolute left-1/2 top-[72%] z-40 -translate-x-1/2 text-sm text-slate-400">
            等待玩家加入
          </p>
        ) : null}

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

function PlayerRail({
  activePlayerName,
  focusedPlayerName,
  isTerminalCue,
  debugHighlightedPlayers,
  livePlayersByName,
  onSelectPlayer,
  players,
  side,
}: {
  activePlayerName: string | null;
  focusedPlayerName: string | null;
  isTerminalCue: boolean;
  debugHighlightedPlayers: Set<string>;
  livePlayersByName: Map<string, LivePlayer>;
  onSelectPlayer: (name: string) => void;
  players: GodViewPlayer[];
  side: "left" | "right";
}) {
  return (
    <div
      className={`flex min-h-0 flex-col justify-center gap-2 ${
        side === "left" ? "items-start" : "items-end"
      }`}
      data-testid={`god-view-player-rail-${side}`}
    >
      {players.map((player) => (
        <StagePlayerCard
          activePlayerName={activePlayerName}
          focusedPlayerName={focusedPlayerName}
          isTerminalCue={isTerminalCue}
          debugHighlighted={debugHighlightedPlayers.has(player.name)}
          key={player.name}
          livePlayer={livePlayersByName.get(player.name) ?? null}
          onSelectPlayer={onSelectPlayer}
          player={player}
          side={side}
        />
      ))}
    </div>
  );
}

function StagePlayerCard({
  activePlayerName,
  focusedPlayerName,
  isTerminalCue,
  debugHighlighted,
  livePlayer,
  onSelectPlayer,
  player,
  side,
}: {
  activePlayerName: string | null;
  focusedPlayerName: string | null;
  isTerminalCue: boolean;
  debugHighlighted: boolean;
  livePlayer: LivePlayer | null;
  onSelectPlayer: (name: string) => void;
  player: GodViewPlayer;
  side: "left" | "right";
}) {
  const isLastActive =
    isTerminalCue && player.name === activePlayerName && player.isAlive;
  const isCurrentSpeaker = !isTerminalCue && player.isSpeaking;
  const isFocused = player.name === focusedPlayerName;
  const cardState = !player.isAlive
    ? "out"
    : isCurrentSpeaker
      ? "speaking"
      : isLastActive
        ? "last-active"
        : isFocused
          ? "focused"
          : "idle";
  const status = stageCardStatus(player, livePlayer, isTerminalCue, isLastActive);
  const role = roleTone(player.role);
  const liveAction = livePlayer?.lastAction ? actionLabel(livePlayer.lastAction) : "";
  const liveDetail = livePlayer?.lastDetail ?? "";

  return (
    <button
      aria-label={`${player.seatNumber}号 ${player.name} ${player.role} ${status} ${liveAction} ${liveDetail}`}
      className={`god-view-player-card pointer-events-auto grid w-full max-w-[13rem] grid-cols-[2.2rem_minmax(0,1fr)] items-center gap-2 rounded-md border bg-black/45 px-2 py-2 text-left shadow-[0_12px_32px_rgba(0,0,0,0.26)] transition duration-200 hover:-translate-y-0.5 hover:border-amber-200/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-200 ${
        side === "right" ? "text-right" : ""
      } ${stagePlayerTone(player, cardState)} ${
        isFocused ? "is-focused ring-1 ring-amber-100/70" : ""
      } ${
        debugHighlighted
          ? "ring-2 ring-amber-300/85 shadow-[0_0_30px_rgba(251,191,36,0.38),0_12px_32px_rgba(0,0,0,0.26)]"
          : ""
      } ${!player.isAlive ? "opacity-65 grayscale" : ""}`}
      data-card-state={cardState}
      data-debug-highlighted={debugHighlighted ? "true" : "false"}
      data-testid={`god-view-stage-player-card-${player.name}`}
      onClick={() => onSelectPlayer(player.name)}
      type="button"
    >
      <span className="flex h-8 w-8 items-center justify-center rounded-md border border-amber-300/45 bg-black/55 text-xs font-semibold text-amber-100">
        {player.seatNumber}
      </span>
      <span className="flex min-w-0 items-center gap-2">
        <span
          className={`relative flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border-2 bg-gradient-to-br ${avatarGradient(
            player.name,
          )} ${appearanceClassName(
            player.appearanceId,
          )} text-xs font-bold text-slate-100 shadow-lg ${role.ring}`}
        >
          {isCurrentSpeaker ? (
            <span
              aria-hidden="true"
              className="absolute -inset-1 rounded-full border border-teal-200/55 shadow-[0_0_20px_rgba(45,212,191,0.42)] animate-pulse"
            />
          ) : null}
          {player.avatarImageUrl ? (
            <img
              alt={`${player.name} 虚拟头像`}
              className="relative z-10 h-full w-full object-cover"
              src={player.avatarImageUrl}
            />
          ) : (
            <span className="relative z-10">{avatarText(player.name)}</span>
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1">
            <span className="truncate text-sm font-semibold text-slate-50">
              {player.name}
            </span>
            {player.isSheriff ? (
              <span className="shrink-0 rounded bg-amber-400/15 px-1 py-0.5 text-[10px] font-semibold text-amber-100 ring-1 ring-amber-300/35">
                警
              </span>
            ) : null}
          </span>
          <span className="mt-1 flex min-w-0 flex-wrap gap-1">
            <span className={`rounded px-1.5 py-0.5 text-[10px] ring-1 ${role.badge}`}>
              {player.role}
            </span>
            <span className="rounded bg-slate-950/70 px-1.5 py-0.5 text-[10px] text-slate-300 ring-1 ring-slate-600/45">
              {player.identityGroup}
            </span>
          </span>
          <span
            className={`mt-1 block truncate text-[11px] font-semibold ${
              cardState === "speaking"
                ? "text-teal-100"
                : cardState === "last-active"
                  ? "text-amber-100"
                  : cardState === "out"
                    ? "text-slate-400"
                    : "text-slate-300"
            }`}
          >
            {status}
          </span>
        </span>
      </span>
    </button>
  );
}

function stagePlayerTone(player: GodViewPlayer, cardState: string) {
  if (cardState === "speaking") {
    return "border-teal-200/55 bg-teal-950/35 shadow-[0_0_28px_rgba(45,212,191,0.18)]";
  }
  if (cardState === "last-active") {
    return "border-amber-200/55 bg-amber-950/30";
  }
  if (!player.isAlive) {
    return "border-slate-600/45 bg-slate-950/70";
  }
  if (player.camp === "狼人阵营") {
    return "border-red-400/35 bg-red-950/24";
  }
  if (player.identityGroup === "神职") {
    return "border-sky-300/30 bg-sky-950/20";
  }
  return "border-stone-300/25 bg-stone-950/20";
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

function stageCardStatus(
  player: GodViewPlayer,
  livePlayer: LivePlayer | null,
  isTerminalCue: boolean,
  isLastActive: boolean,
) {
  if (!player.isAlive) {
    return player.statusLabel || "出局";
  }
  if (!isTerminalCue) {
    return player.statusLabel;
  }
  if (isLastActive) {
    return "最后行动";
  }
  if (livePlayer) {
    return livePlayer.status === "streaming"
      ? "已行动"
      : STATUS_LABELS[livePlayer.status];
  }
  return player.statusLabel === "发言中" ? "已行动" : player.statusLabel;
}

function speakerTone(player: GodViewPlayer) {
  if (player.camp === "狼人阵营") {
    return "border-red-400 shadow-[0_0_30px_rgba(248,113,113,0.28)]";
  }
  if (player.identityGroup === "神职") {
    return "border-sky-200 shadow-[0_0_30px_rgba(125,211,252,0.22)]";
  }
  return "border-stone-300 shadow-[0_0_30px_rgba(214,211,209,0.16)]";
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

function traceEventRange(trace: LiveDebugTrace) {
  const first = trace.eventIds[0];
  const last = trace.eventIds.at(-1);
  return first === last ? `Trace #${first}` : `Trace #${first}-${last}`;
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
