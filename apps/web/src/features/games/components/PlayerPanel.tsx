import { Badge, Callout, Card } from "@radix-ui/themes";
import type { BadgeProps } from "@radix-ui/themes";

import type { GameReplay, RawPlayer } from "../types";

type PlayerPanelProps = {
  game: GameReplay;
};

const ROLE_COLORS: Record<string, BadgeProps["color"]> = {
  werewolf: "red",
  狼人: "red",
  villager: "gray",
  村民: "gray",
  seer: "violet",
  预言家: "violet",
  doctor: "green",
  守卫: "green",
  医生: "green",
  女巫: "pink",
  猎人: "orange",
  白痴: "cyan",
};

export function PlayerPanel({ game }: PlayerPanelProps) {
  return (
    <Card asChild size="1">
      <aside>
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
          <Callout.Root color="red" size="1" variant="soft">
            <Callout.Text>{game.errorMessage}</Callout.Text>
          </Callout.Root>
        ) : null}
      </div>

      <div className="divide-y divide-slate-100">
        {game.players.map((player) => (
          <PlayerRow key={player.name} player={player} />
        ))}
      </div>
      </aside>
    </Card>
  );
}

function PlayerRow({ player }: { player: RawPlayer }) {
  const roleColor = ROLE_COLORS[player.role] ?? "amber";

  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-medium text-slate-950">
          {player.name}
        </p>
        <Badge color={roleColor} variant="surface">
          {player.role}
        </Badge>
      </div>
      <p className="mt-1 break-all font-mono text-xs text-slate-500">
        {player.model}
      </p>
    </div>
  );
}
