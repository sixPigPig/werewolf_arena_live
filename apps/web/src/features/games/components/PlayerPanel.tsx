import { Callout } from "@radix-ui/themes";

import type { GameReplay } from "../types";
import {
  PlayerRosterPanel,
  type PlayerRosterItem,
} from "./PlayerRosterPanel";

type PlayerPanelProps = {
  game: GameReplay;
};

export function PlayerPanel({ game }: PlayerPanelProps) {
  const deadPlayers = deadPlayerNames(game);
  const sheriffName = currentSheriffName(game);
  const rosterPlayers = game.players.map<PlayerRosterItem>((player, index) => {
    const isDead = deadPlayers.has(player.name);

    return {
      seatNumber: index + 1,
      name: player.name,
      role: player.role,
      model: player.model,
      state: isDead ? "dead" : "alive",
      statusLabel: isDead ? "死亡" : "存活",
      isSheriff: player.is_sheriff || player.name === sheriffName,
    };
  });

  return (
    <PlayerRosterPanel
      meta={
        <div className="space-y-2 text-xs text-slate-400">
          <p className="break-all font-mono text-[11px] text-slate-500">
          {game.sessionId}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-md bg-emerald-400/10 px-2 py-0.5 font-semibold text-emerald-200">
              <span>胜者：</span>
              <span>{game.winner || "未决出"}</span>
            </span>
            <span className="rounded-md bg-slate-800 px-2 py-0.5">
              {game.rounds.length} 轮
            </span>
          </div>
          {game.errorMessage ? (
            <Callout.Root color="red" size="1" variant="soft">
              <Callout.Text>{game.errorMessage}</Callout.Text>
            </Callout.Root>
          ) : null}
        </div>
      }
      players={rosterPlayers}
    />
  );
}

function deadPlayerNames(game: GameReplay) {
  const deadPlayers = new Set<string>();

  for (const round of game.rounds) {
    if (round.eliminated && round.eliminated !== round.protected) {
      deadPlayers.add(round.eliminated);
    }
    if (round.exiled) {
      deadPlayers.add(round.exiled);
    }
    if (round.poisoned) {
      deadPlayers.add(round.poisoned);
    }
    if (round.hunter_shot) {
      deadPlayers.add(round.hunter_shot);
    }
    if (round.werewolf_self_exploded) {
      deadPlayers.add(round.werewolf_self_exploded);
    }
    for (const death of [...round.night_deaths, ...round.day_deaths]) {
      deadPlayers.add(death.player);
    }
  }

  return deadPlayers;
}

function currentSheriffName(game: GameReplay) {
  if (game.sheriff && !game.sheriffBadgeLost) {
    return game.sheriff;
  }

  for (let index = game.rounds.length - 1; index >= 0; index -= 1) {
    const round = game.rounds[index];
    if (round.sheriff_badge_lost) {
      return null;
    }
    if (round.sheriff_badge_target) {
      return round.sheriff_badge_target;
    }
    if (round.sheriff_elected) {
      return round.sheriff_elected;
    }
    if (round.sheriff) {
      return round.sheriff;
    }
  }

  return null;
}
