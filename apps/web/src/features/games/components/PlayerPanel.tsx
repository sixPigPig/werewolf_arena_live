import type { GameReplay, RawPlayer } from "../types";

type PlayerPanelProps = {
  game: GameReplay;
};

const ROLE_STYLES: Record<string, string> = {
  werewolf: "border-red-200 bg-red-50 text-red-800",
  狼人: "border-red-200 bg-red-50 text-red-800",
  villager: "border-slate-200 bg-slate-50 text-slate-700",
  村民: "border-slate-200 bg-slate-50 text-slate-700",
  seer: "border-violet-200 bg-violet-50 text-violet-800",
  预言家: "border-violet-200 bg-violet-50 text-violet-800",
  doctor: "border-emerald-200 bg-emerald-50 text-emerald-800",
  守卫: "border-emerald-200 bg-emerald-50 text-emerald-800",
  医生: "border-emerald-200 bg-emerald-50 text-emerald-800",
  女巫: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-800",
  猎人: "border-orange-200 bg-orange-50 text-orange-800",
  白痴: "border-cyan-200 bg-cyan-50 text-cyan-800",
};

export function PlayerPanel({ game }: PlayerPanelProps) {
  return (
    <aside className="rounded border border-slate-200 bg-white">
      <div className="space-y-3 border-b border-slate-200 px-4 py-4">
        <p className="break-all font-mono text-xs text-slate-500">
          {game.sessionId}
        </p>
        <div>
          <p className="text-xs font-medium text-slate-500">场次胜者</p>
          <p className="text-lg font-semibold text-slate-950">
            {game.winner || "未决出"}
          </p>
        </div>
        <p className="text-sm text-slate-600">{game.rounds.length} 轮</p>
        {game.errorMessage ? (
          <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {game.errorMessage}
          </p>
        ) : null}
      </div>

      <div className="divide-y divide-slate-100">
        {game.players.map((player) => (
          <PlayerRow key={player.name} player={player} />
        ))}
      </div>
    </aside>
  );
}

function PlayerRow({ player }: { player: RawPlayer }) {
  const roleClass =
    ROLE_STYLES[player.role] ?? "border-amber-200 bg-amber-50 text-amber-800";

  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-medium text-slate-950">
          {player.name}
        </p>
        <span
          className={`shrink-0 rounded border px-2 py-0.5 text-xs font-medium ${roleClass}`}
        >
          {player.role}
        </span>
      </div>
      <p className="mt-1 break-all font-mono text-xs text-slate-500">
        {player.model}
      </p>
    </div>
  );
}
