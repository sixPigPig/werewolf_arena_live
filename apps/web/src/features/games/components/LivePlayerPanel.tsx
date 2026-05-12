import { Badge, Card, Switch } from "../../../components/ui";
import type { BadgeProps } from "../../../components/ui";

import type { LivePlayer } from "../liveSpectator";
import { actionLabel } from "../liveLabels";

type LivePlayerPanelProps = {
  players: LivePlayer[];
  activePlayerName: string | null;
  focusedPlayerName: string | null;
  autoFollow: boolean;
  onSelectPlayer: (name: string) => void;
  onAutoFollowChange: (value: boolean) => void;
};

const STATUS_LABELS: Record<LivePlayer["status"], string> = {
  waiting: "等待中",
  thinking: "思考中",
  requesting: "请求模型",
  streaming: "输出中",
  responded: "已返回",
  acted: "已行动",
  out: "出局",
};

const ROLE_COLORS: Record<string, BadgeProps["color"]> = {
  狼人: "red",
  werewolf: "red",
  预言家: "violet",
  seer: "violet",
  守卫: "green",
  医生: "green",
  doctor: "green",
  女巫: "pink",
  猎人: "orange",
  白痴: "cyan",
  村民: "gray",
  villager: "gray",
};

export function LivePlayerPanel({
  players,
  activePlayerName,
  focusedPlayerName,
  autoFollow,
  onSelectPlayer,
  onAutoFollowChange,
}: LivePlayerPanelProps) {
  const focusedPlayer =
    players.find((player) => player.name === focusedPlayerName) ?? null;

  return (
    <Card asChild size="1">
      <aside className="overflow-hidden">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">座位盘</h2>
            <p className="mt-1 text-xs text-slate-500">
              {players.length > 0 ? `${players.length} 名玩家` : "等待开局"}
            </p>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <Switch
              checked={autoFollow}
              color="gray"
              onCheckedChange={onAutoFollowChange}
            />
            自动跟随
          </label>
        </div>
      </div>
      {players.length === 0 ? (
        <p className="px-4 py-6 text-sm text-slate-600">等待玩家加入...</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 p-3">
            {players.map((player, index) => (
              <PlayerButton
                active={player.name === activePlayerName}
                focused={player.name === focusedPlayerName}
                key={player.name}
                onClick={() => onSelectPlayer(player.name)}
                player={player}
                seatNumber={index + 1}
              />
            ))}
          </div>
          <FocusedPlayerDetail player={focusedPlayer} />
        </>
      )}
      </aside>
    </Card>
  );
}

function PlayerButton({
  active,
  focused,
  onClick,
  player,
  seatNumber,
}: {
  active: boolean;
  focused: boolean;
  onClick: () => void;
  player: LivePlayer;
  seatNumber: number;
}) {
  const roleColor = ROLE_COLORS[player.role] ?? "amber";
  const activeClass = active
    ? "border-slate-100"
    : "border-slate-200";
  const focusedClass = focused ? "ring-2 ring-slate-950 ring-inset" : "";
  const mutedClass = player.isAlive ? "" : "opacity-60";
  const lastAction = player.lastAction ? actionLabel(player.lastAction) : "";

  return (
    <button
      aria-label={`${player.name} ${player.role} ${
        player.isAlive ? STATUS_LABELS[player.status] : "出局"
      } ${lastAction} ${player.lastDetail ?? ""}`}
      className={`min-h-28 w-full rounded-md border p-3 text-left transition ${activeClass} ${focusedClass} ${mutedClass}`}
      onClick={onClick}
      type="button"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] font-medium text-slate-500">
            #{seatNumber}
          </p>
          <p className="min-w-0 truncate text-sm font-semibold text-slate-950">
            {player.name}
          </p>
        </div>
        <Badge color={roleColor} variant="surface">
          {player.role}
        </Badge>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${statusDotClass(player)}`} />
        <span className="min-w-0 truncate text-xs font-medium text-slate-600">
          {player.isAlive ? STATUS_LABELS[player.status] : "出局"}
        </span>
      </div>
      {player.lastAction || player.lastDetail ? (
        <p className="mt-2 line-clamp-2 break-words text-xs leading-5 text-slate-600">
          {lastAction ? `${lastAction}：` : ""}
          {player.lastDetail || "处理中"}
        </p>
      ) : null}
    </button>
  );
}

function FocusedPlayerDetail({ player }: { player: LivePlayer | null }) {
  const lastAction = player?.lastAction ? actionLabel(player.lastAction) : "";

  return (
    <div className="border-t border-slate-200 p-4">
      <p className="text-xs font-semibold text-slate-500">当前关注</p>
      {!player ? (
        <p className="mt-2 text-sm text-slate-600">等待玩家行动...</p>
      ) : (
        <div className="mt-2 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-base font-semibold text-slate-950">
              {player.name}
            </p>
            <Badge color={ROLE_COLORS[player.role] ?? "amber"} variant="surface">
              {player.role}
            </Badge>
            <Badge color={player.isAlive ? "green" : "gray"} variant="surface">
              {player.isAlive ? STATUS_LABELS[player.status] : "出局"}
            </Badge>
          </div>
          <p className="text-xs text-slate-500">{player.model}</p>
          <p className="rounded-md border border-slate-500/30 p-3 text-sm leading-6 text-slate-300">
            {player.lastAction || player.lastDetail
              ? `${lastAction ? `${lastAction}：` : ""}${
                  player.lastDetail || "处理中"
                }`
              : "还没有可展示的行动。"}
          </p>
        </div>
      )}
    </div>
  );
}

function statusDotClass(player: LivePlayer) {
  if (!player.isAlive) {
    return "bg-slate-300";
  }
  if (player.status === "thinking" || player.status === "requesting") {
    return "bg-amber-500";
  }
  if (player.status === "streaming") {
    return "bg-sky-500";
  }
  if (player.status === "acted" || player.status === "responded") {
    return "bg-emerald-500";
  }
  return "bg-slate-400";
}
