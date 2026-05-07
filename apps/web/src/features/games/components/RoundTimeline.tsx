import { Card, Tabs } from "@radix-ui/themes";
import { useMemo, useState } from "react";

import type { DebugItem, GameRound, RawPlayer, RuleSetSummary } from "../types";

import { DayPhase } from "./DayPhase";
import { NightPhase } from "./NightPhase";

type RoundTimelineProps = {
  rounds: GameRound[];
  debugItems: DebugItem[];
  players: RawPlayer[];
  ruleSet?: RuleSetSummary | null;
  winner: string;
  selectedItem: DebugItem | null;
  onSelect: (item: DebugItem) => void;
};

export function RoundTimeline({
  rounds,
  debugItems,
  players,
  ruleSet = null,
  winner,
  selectedItem,
  onSelect,
}: RoundTimelineProps) {
  const roundTabs = useMemo(
    () =>
      rounds.map((round) => {
        const roundItems = debugItems.filter(
          (item) => item.roundNumber === round.number,
        );

        return {
          round,
          value: roundValue(round),
          items: roundItems,
          nightItems: roundItems.filter((item) => item.phase === "night"),
          dayItems: roundItems.filter((item) => item.phase !== "night"),
        };
      }),
    [debugItems, rounds],
  );
  const firstRoundValue = roundTabs[0]?.value ?? "";
  const [activeRoundValue, setActiveRoundValue] = useState<string | null>(null);
  const currentRoundValue =
    roundTabs.some((tab) => tab.value === activeRoundValue) && activeRoundValue
      ? activeRoundValue
      : firstRoundValue;

  function handleRoundChange(value: string) {
    setActiveRoundValue(value);

    const firstItemInRound = roundTabs.find((tab) => tab.value === value)
      ?.items[0];
    if (firstItemInRound) {
      onSelect(firstItemInRound);
    }
  }

  return (
    <Card asChild size="1">
      <section>
      <div className="border-b border-slate-200 px-4 py-4">
        <h1 className="text-xl font-semibold text-slate-950">对局时间线</h1>
      </div>

      <div>
        {roundTabs.length > 0 ? (
          <Tabs.Root
            onValueChange={handleRoundChange}
            value={currentRoundValue}
          >
            <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
              <Tabs.List
                aria-label="回放轮次"
                className="w-full overflow-x-auto"
                justify="start"
              >
                {roundTabs.map(({ round, value }) => (
                  <Tabs.Trigger key={value} value={value}>
                    第 {round.number} 轮
                  </Tabs.Trigger>
                ))}
              </Tabs.List>
            </div>

            {roundTabs.map(({ dayItems, nightItems, round, value }) => (
              <Tabs.Content className="px-4 py-5" key={value} value={value}>
                <article className="space-y-4">
                  <header className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <h2 className="text-lg font-semibold text-slate-950">
                      第 {round.number} 轮
                    </h2>
                    <p className="text-sm text-slate-600">
                      {round.success ? "已完成" : "未完成"}
                    </p>
                  </header>

                  <NightPhase
                    items={nightItems}
                    onSelect={onSelect}
                    players={players}
                    round={round}
                    ruleSet={ruleSet}
                    selectedItem={selectedItem}
                  />
                  <DayPhase
                    items={dayItems}
                    onSelect={onSelect}
                    round={round}
                    selectedItem={selectedItem}
                  />
                </article>
              </Tabs.Content>
            ))}
          </Tabs.Root>
        ) : null}
        <GameConclusion players={players} rounds={rounds} winner={winner} />
      </div>
      </section>
    </Card>
  );
}

function roundValue(round: GameRound) {
  return `round-${round.number}`;
}

function GameConclusion({
  players,
  rounds,
  winner,
}: {
  players: RawPlayer[];
  rounds: GameRound[];
  winner: string;
}) {
  if (!winner) {
    return null;
  }

  return (
    <section className="bg-emerald-50 px-4 py-5">
      <p className="text-sm font-semibold text-emerald-950">
        场次胜者：{winner}
      </p>
      <p className="mt-1 text-sm text-emerald-800">
        {conclusionDetail(players, rounds, winner)}
      </p>
    </section>
  );
}

function conclusionDetail(
  players: RawPlayer[],
  rounds: GameRound[],
  winner: string,
) {
  const removedPlayers = new Set<string>();
  rounds.forEach((round) => {
    if (round.eliminated) {
      removedPlayers.add(round.eliminated);
    }
    if (round.exiled) {
      removedPlayers.add(round.exiled);
    }
  });

  const lastExiled = [...rounds]
    .reverse()
    .find((round) => round.exiled)?.exiled;
  const werewolves = players.filter((player) => isWerewolfRole(player.role));
  const allWerewolvesRemoved =
    werewolves.length > 0 &&
    werewolves.every((player) => removedPlayers.has(player.name));

  if (isVillagerWinner(winner) && allWerewolvesRemoved) {
    if (lastExiled && isWerewolfRole(roleForPlayer(players, lastExiled))) {
      return `${lastExiled} 被放逐，狼人全部出局`;
    }
    return "狼人全部出局";
  }

  if (lastExiled) {
    return `${lastExiled} 被放逐，${winner}获胜`;
  }

  return "胜利条件达成，场次结束";
}

function roleForPlayer(players: RawPlayer[], name: string) {
  return players.find((player) => player.name === name)?.role ?? "";
}

function isWerewolfRole(role: string) {
  return role === "狼人" || role.toLowerCase().includes("werewolf");
}

function isVillagerWinner(winner: string) {
  return winner === "好人阵营" || winner.toLowerCase().includes("villager");
}
