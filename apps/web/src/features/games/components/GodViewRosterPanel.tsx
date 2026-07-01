import type { KeyboardEvent } from "react";

import { withGlassPanel } from "../../../components/ui/glass";
import type { GodViewPlayer } from "../liveGodView";
import { appearanceClassName } from "../playerProfileOptions";
import { resolveAvatarImageUrl } from "../types";
import { formatVoteCount } from "./voteFormatting";

type GodViewRosterPanelProps = {
  players: GodViewPlayer[];
  onSelectPlayer: (name: string) => void;
};

export function GodViewRosterPanel({
  players,
  onSelectPlayer,
}: GodViewRosterPanelProps) {
  return (
    <aside
      className={withGlassPanel(
        "god-view-roster-panel god-view-frame overflow-hidden rounded-lg text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.32)]",
      )}
      data-testid="god-view-roster-panel"
    >
      <div className="god-view-panel-header border-b border-amber-500/20 px-3 py-2.5">
        <h2 className="text-sm font-semibold text-amber-50">
          身份牌（上帝视角）
        </h2>
        <div className="mt-2 grid grid-cols-3 gap-1 text-[11px] text-slate-400">
          <span>席位</span>
          <span>身份/阵营</span>
          <span className="text-right">票型</span>
        </div>
      </div>

      <div
        className="god-view-roster-list space-y-1.5 p-2.5"
        role="list"
      >
        {players.length === 0 ? (
          <p className="rounded-md border border-slate-700/60 px-3 py-4 text-sm text-slate-400">
            等待玩家加入
          </p>
        ) : (
          players.map((player) => (
            <GodViewRosterRow
              key={player.name}
              onSelectPlayer={onSelectPlayer}
              player={player}
            />
          ))
        )}
      </div>
    </aside>
  );
}

function GodViewRosterRow({
  player,
  onSelectPlayer,
}: {
  player: GodViewPlayer;
  onSelectPlayer: (name: string) => void;
}) {
  const tone = playerTone(player);
  const avatarImageUrl = resolveAvatarImageUrl({
    avatar_image_url: player.avatarImageUrl,
  });
  const handleSelect = () => onSelectPlayer(player.name);
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleSelect();
    }
  };

  return (
    <div
      className={`god-view-player-row god-view-compact-row grid grid-cols-[2.4rem_minmax(0,1fr)_4.6rem] items-center gap-2 rounded-md border px-2 py-2 transition hover:-translate-y-0.5 ${tone.row}`}
      data-testid={`god-view-player-row-${player.name}`}
      onClick={handleSelect}
      onKeyDown={handleKeyDown}
      role="listitem"
      tabIndex={0}
    >
      <div className="min-w-0 text-center">
        <div className="mx-auto flex h-6 w-6 items-center justify-center rounded-md border border-amber-300/35 bg-black/55 text-xs font-semibold text-amber-100">
          {player.seatNumber}
        </div>
        <div className="mt-1 text-[10px] text-slate-500">
          {player.isSheriff ? "警长" : player.isSpeaking ? "发言" : "席位"}
        </div>
      </div>

      <div className="flex min-w-0 items-center gap-2">
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border-2 bg-gradient-to-br ${avatarGradient(
            player.name,
          )} ${appearanceClassName(player.appearanceId)} text-xs font-semibold text-slate-100 shadow-lg ${tone.avatar} ${
            player.isAlive ? "" : "grayscale opacity-65"
          }`}
        >
          {avatarImageUrl ? (
            <img
              alt={`${player.name} 虚拟头像`}
              className="h-full w-full object-cover"
              src={avatarImageUrl}
            />
          ) : (
            avatarText(player.name)
          )}
        </span>
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-1">
            <span className="truncate text-sm font-semibold text-slate-100">
              {player.name}
            </span>
            {player.isSheriff ? (
              <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-100 ring-1 ring-amber-300/35">
                冠
              </span>
            ) : null}
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            <span className={`rounded px-1.5 py-0.5 text-[11px] ring-1 ${tone.badge}`}>
              {player.role}
            </span>
            <span className="rounded bg-slate-900/65 px-1.5 py-0.5 text-[11px] text-slate-300 ring-1 ring-slate-600/50">
              {player.identityGroup}
            </span>
          </div>
          <div className="god-view-clue-tags mt-1 flex min-w-0 gap-1 overflow-hidden">
            {player.clueTags.slice(0, 3).map((tag) => (
              <span
                className="shrink-0 rounded bg-black/35 px-1.5 py-0.5 text-[10px] text-slate-400"
                key={tag}
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="min-w-0 text-right">
        <div className={`text-xs font-semibold ${tone.status}`}>
          {player.statusLabel}
        </div>
        <div className="mt-1 truncate text-[11px] text-slate-400">
          投 → {player.voteTarget ?? "-"}
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          票 {formatVoteCount(player.receivedVotes)}
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-black/45">
          <span
            className={`block h-full rounded-full ${tone.meter}`}
            style={{ width: `${player.suspicionScore}%` }}
          />
        </div>
        <div className="mt-0.5 text-[10px] text-slate-500">
          嫌疑 {player.suspicionScore}%
        </div>
      </div>
    </div>
  );
}

function playerTone(player: GodViewPlayer) {
  if (!player.isAlive) {
    return {
      row: "border-slate-600/45 bg-slate-950/70 opacity-75",
      avatar: "border-slate-400 shadow-slate-500/20",
      badge: "bg-slate-900/80 text-slate-200 ring-slate-500/35",
      status: "text-slate-300",
      meter: "bg-slate-500",
    };
  }
  if (player.camp === "狼人阵营") {
    return {
      row: "border-red-500/35 bg-red-950/22",
      avatar: "border-red-400 shadow-red-500/35",
      badge: "bg-red-950/75 text-red-100 ring-red-400/35",
      status: player.isSpeaking ? "text-teal-100" : "text-red-100",
      meter: "bg-red-400",
    };
  }
  if (player.identityGroup === "神职") {
    return {
      row: "border-sky-300/30 bg-sky-950/18",
      avatar: "border-sky-200 shadow-sky-300/25",
      badge: "bg-sky-950/70 text-sky-100 ring-sky-300/35",
      status: player.isSpeaking ? "text-teal-100" : "text-sky-100",
      meter: "bg-sky-300",
    };
  }
  return {
    row: "border-slate-700/55 bg-slate-950/62",
    avatar: "border-stone-300 shadow-stone-300/20",
    badge: "bg-stone-950/70 text-stone-100 ring-stone-300/25",
    status: player.isSpeaking ? "text-teal-100" : "text-emerald-200",
    meter: "bg-emerald-400",
  };
}

function avatarGradient(name: string) {
  const gradients = [
    "from-[#26323b] to-[#05070a]",
    "from-[#3b3226] to-[#060504]",
    "from-[#173136] to-[#030607]",
    "from-[#33263a] to-[#050407]",
    "from-[#4a271f] to-[#070404]",
    "from-[#1f2937] to-[#030507]",
  ];
  const charTotal = Array.from(name).reduce(
    (total, char) => total + char.charCodeAt(0),
    0,
  );
  return gradients[charTotal % gradients.length];
}

function avatarText(name: string) {
  return Array.from(name).slice(0, 2).join("");
}
