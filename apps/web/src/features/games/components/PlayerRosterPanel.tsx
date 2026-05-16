import type { KeyboardEvent, ReactNode } from "react";

import { withGlassPanel } from "../../../components/ui/glass";
import {
  appearanceClassName,
  personalityLabel,
} from "../playerProfileOptions";

export type PlayerRosterState =
  | "alive"
  | "dead"
  | "speaking"
  | "thinking"
  | "acted";

export type PlayerRosterItem = {
  seatNumber: number;
  name: string;
  role: string;
  model?: string;
  personalityId?: string;
  appearanceId?: string;
  tags?: string[];
  state: PlayerRosterState;
  statusLabel: string;
  isSheriff?: boolean;
  isFocused?: boolean;
};

type PlayerRosterPanelProps = {
  players: PlayerRosterItem[];
  meta?: ReactNode;
  onSelectPlayer?: (name: string) => void;
};

export function PlayerRosterPanel({
  players,
  meta,
  onSelectPlayer,
}: PlayerRosterPanelProps) {
  return (
    <aside
      className={withGlassPanel(
        "player-roster-panel overflow-hidden rounded-lg text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.28)]",
      )}
      data-testid="player-roster-panel"
    >
      <div className="player-roster-header border-b border-amber-500/15 px-4 py-3">
        <h2 className="player-roster-title text-base font-semibold text-amber-50">
          玩家列表（{players.length}人局）
        </h2>
        {meta ? <div className="mt-2">{meta}</div> : null}
      </div>

      <div
        className="player-roster-list space-y-2 p-3"
        data-testid="player-roster-list"
        role="list"
      >
        {players.length === 0 ? (
          <p className="rounded-md border border-slate-700/60 px-3 py-4 text-sm text-slate-400">
            等待玩家加入
          </p>
        ) : (
          players.map((player) => (
            <RosterRow
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

function RosterRow({
  player,
  onSelectPlayer,
}: {
  player: PlayerRosterItem;
  onSelectPlayer?: (name: string) => void;
}) {
  const role = roleTone(player.role);
  const state = stateTone(player.state, player.role);
  const isInteractive = Boolean(onSelectPlayer);
  const handleSelect = () => onSelectPlayer?.(player.name);
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!isInteractive) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleSelect();
    }
  };

  return (
    <div
      className={`player-roster-row flex items-center gap-3 rounded-lg border px-3 py-2.5 transition ${state.row} ${
        player.isFocused
          ? "ring-2 ring-amber-100 ring-offset-2 ring-offset-slate-950"
          : ""
      } ${isInteractive ? "cursor-pointer hover:-translate-y-0.5" : ""}`}
      data-roster-state={player.state}
      data-testid={`player-roster-row-${player.name}`}
      onClick={handleSelect}
      onKeyDown={handleKeyDown}
      role="listitem"
      tabIndex={isInteractive ? 0 : undefined}
    >
      <span className="player-roster-seat flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-amber-300/35 bg-black/55 text-sm font-semibold text-amber-100 shadow-md">
        {player.seatNumber}
      </span>
      <span
        className={`player-roster-avatar flex h-12 w-12 shrink-0 items-center justify-center rounded-full border-2 bg-gradient-to-br ${avatarGradient(
          player.name,
        )} ${appearanceClassName(
          player.appearanceId,
        )} text-sm font-semibold text-slate-100 shadow-lg ${role.ring} ${
          player.state === "dead" ? "grayscale" : ""
        }`}
      >
        {avatarText(player.name)}
      </span>
      <span className="player-roster-main min-w-0 flex-1">
        <span className="player-roster-name block truncate text-sm font-semibold text-slate-100">
          {player.name}
        </span>
        <span
          className={`player-roster-role mt-1 inline-flex max-w-full items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${role.badge}`}
        >
          <span className="truncate">{role.display}</span>
        </span>
        {player.model ? (
          <span className="player-roster-model mt-1 block truncate font-mono text-[11px] text-slate-500">
            {player.model} · {personalityLabel(player.personalityId)}
          </span>
        ) : null}
      </span>
      <span className="player-roster-status-group flex shrink-0 flex-col items-end gap-1">
        <span className="player-roster-status-icons flex items-center gap-1">
          {player.isSheriff ? (
            <span className="player-roster-icon flex h-6 min-w-6 items-center justify-center rounded-md border border-amber-300/35 bg-amber-400/15 px-1.5 text-xs font-semibold text-amber-100">
              冠
            </span>
          ) : null}
          {player.state === "speaking" ? (
            <span className="player-roster-icon flex h-6 min-w-6 items-center justify-center rounded-md border border-teal-300/35 bg-teal-400/15 px-1.5 text-xs font-semibold text-teal-100">
              麦
            </span>
          ) : null}
        </span>
        <span
          className={`player-roster-status rounded-md px-2 py-0.5 text-xs font-semibold ${state.status}`}
        >
          {player.statusLabel}
        </span>
      </span>
    </div>
  );
}

function roleTone(role: string) {
  const display = roleDisplayName(role);

  if (display.includes("狼")) {
    return {
      display,
      ring: "border-red-400 shadow-red-500/35",
      badge: "bg-red-950/75 text-red-100 ring-red-400/35",
    };
  }
  if (display.includes("预言家")) {
    return {
      display,
      ring: "border-amber-200 shadow-amber-300/30",
      badge: "bg-amber-950/70 text-amber-100 ring-amber-300/35",
    };
  }
  if (display.includes("女巫")) {
    return {
      display,
      ring: "border-fuchsia-200 shadow-fuchsia-300/25",
      badge: "bg-fuchsia-950/70 text-fuchsia-100 ring-fuchsia-300/35",
    };
  }
  if (display.includes("守卫") || display.includes("医生")) {
    return {
      display,
      ring: "border-sky-200 shadow-sky-300/25",
      badge: "bg-sky-950/70 text-sky-100 ring-sky-300/35",
    };
  }
  if (display.includes("猎人")) {
    return {
      display,
      ring: "border-orange-200 shadow-orange-300/25",
      badge: "bg-orange-950/70 text-orange-100 ring-orange-300/35",
    };
  }
  return {
    display,
    ring: "border-stone-300 shadow-stone-300/20",
    badge: "bg-stone-950/70 text-stone-100 ring-stone-300/25",
  };
}

function stateTone(state: PlayerRosterState, role: string) {
  if (state === "dead") {
    return {
      row: "border-slate-600/45 bg-slate-900/75 opacity-70",
      status: "bg-slate-800 text-slate-300",
    };
  }
  if (state === "speaking") {
    return {
      row: "border-teal-300/55 bg-teal-950/40 shadow-[0_0_28px_rgba(45,212,191,0.22)]",
      status: "bg-teal-400/15 text-teal-100 ring-1 ring-teal-300/35",
    };
  }
  if (state === "thinking") {
    return {
      row: "border-amber-300/45 bg-amber-950/25",
      status: "bg-amber-400/15 text-amber-100 ring-1 ring-amber-300/30",
    };
  }
  if (state === "acted") {
    return {
      row: "border-sky-300/35 bg-sky-950/25",
      status: "bg-sky-400/15 text-sky-100 ring-1 ring-sky-300/25",
    };
  }
  if (roleDisplayName(role).includes("狼")) {
    return {
      row: "border-red-500/35 bg-red-950/25",
      status: "bg-emerald-400/15 text-emerald-200",
    };
  }
  return {
    row: "border-slate-700/55 bg-slate-900/75",
    status: "bg-emerald-400/15 text-emerald-200",
  };
}

function roleDisplayName(role: string) {
  const normalized = role.toLowerCase();
  const map: Record<string, string> = {
    werewolf: "狼人",
    villager: "村民",
    seer: "预言家",
    guard: "守卫",
    doctor: "医生",
    witch: "女巫",
    hunter: "猎人",
    idiot: "白痴",
  };

  return map[normalized] ?? role;
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
