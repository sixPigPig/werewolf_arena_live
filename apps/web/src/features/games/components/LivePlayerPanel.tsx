import type { LivePlayer } from "../liveSpectator";

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

const ROLE_STYLES: Record<string, string> = {
  狼人: "border-red-200 bg-red-50 text-red-800",
  werewolf: "border-red-200 bg-red-50 text-red-800",
  预言家: "border-violet-200 bg-violet-50 text-violet-800",
  seer: "border-violet-200 bg-violet-50 text-violet-800",
  守卫: "border-emerald-200 bg-emerald-50 text-emerald-800",
  医生: "border-emerald-200 bg-emerald-50 text-emerald-800",
  doctor: "border-emerald-200 bg-emerald-50 text-emerald-800",
  女巫: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-800",
  猎人: "border-orange-200 bg-orange-50 text-orange-800",
  白痴: "border-cyan-200 bg-cyan-50 text-cyan-800",
  村民: "border-slate-200 bg-slate-50 text-slate-700",
  villager: "border-slate-200 bg-slate-50 text-slate-700",
};

export function LivePlayerPanel({
  players,
  activePlayerName,
  focusedPlayerName,
  autoFollow,
  onSelectPlayer,
  onAutoFollowChange,
}: LivePlayerPanelProps) {
  return (
    <aside className="overflow-hidden rounded-md border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-950">玩家</h2>
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <input
              checked={autoFollow}
              className="h-4 w-4 accent-slate-950"
              onChange={(event) => onAutoFollowChange(event.target.checked)}
              type="checkbox"
            />
            自动跟随
          </label>
        </div>
      </div>
      {players.length === 0 ? (
        <p className="px-4 py-6 text-sm text-slate-600">等待玩家加入...</p>
      ) : (
        <div className="divide-y divide-slate-100">
          {players.map((player) => (
            <PlayerButton
              active={player.name === activePlayerName}
              focused={player.name === focusedPlayerName}
              key={player.name}
              onClick={() => onSelectPlayer(player.name)}
              player={player}
            />
          ))}
        </div>
      )}
    </aside>
  );
}

function PlayerButton({
  active,
  focused,
  onClick,
  player,
}: {
  active: boolean;
  focused: boolean;
  onClick: () => void;
  player: LivePlayer;
}) {
  const roleClass =
    ROLE_STYLES[player.role] ?? "border-amber-200 bg-amber-50 text-amber-800";
  const activeClass = active
    ? "border-l-4 border-l-slate-950 bg-slate-50"
    : "border-l-4 border-l-transparent bg-white";
  const focusedClass = focused ? "ring-2 ring-slate-950 ring-inset" : "";
  const mutedClass = player.isAlive ? "" : "opacity-60";

  return (
    <button
      className={`block w-full px-4 py-3 text-left transition hover:bg-slate-50 ${activeClass} ${focusedClass} ${mutedClass}`}
      onClick={onClick}
      type="button"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-medium text-slate-950">
          {player.name}
        </p>
        <span className={`shrink-0 rounded border px-2 py-0.5 text-xs ${roleClass}`}>
          {player.role}
        </span>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="truncate text-xs text-slate-500">{player.model}</span>
        <span className="shrink-0 text-xs font-medium text-slate-600">
          {player.isAlive ? STATUS_LABELS[player.status] : "出局"}
        </span>
      </div>
      {player.lastAction || player.lastDetail ? (
        <p className="mt-2 line-clamp-2 break-words text-xs text-slate-600">
          {player.lastAction ? `${player.lastAction}：` : ""}
          {player.lastDetail || "处理中"}
        </p>
      ) : null}
    </button>
  );
}
