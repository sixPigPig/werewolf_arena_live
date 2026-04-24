import type { DebugItem, GameRound } from "../types";

import { DayPhase } from "./DayPhase";
import { NightPhase } from "./NightPhase";

type RoundTimelineProps = {
  rounds: GameRound[];
  debugItems: DebugItem[];
  selectedItem: DebugItem | null;
  onSelect: (item: DebugItem) => void;
};

export function RoundTimeline({
  rounds,
  debugItems,
  selectedItem,
  onSelect,
}: RoundTimelineProps) {
  return (
    <section className="rounded border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-4">
        <h1 className="text-xl font-semibold text-slate-950">对局时间线</h1>
      </div>

      <div className="divide-y divide-slate-200">
        {rounds.map((round) => {
          const roundItems = debugItems.filter(
            (item) => item.roundNumber === round.number,
          );
          const nightItems = roundItems.filter((item) => item.phase === "night");
          const dayItems = roundItems.filter((item) => item.phase !== "night");

          return (
            <article className="space-y-4 px-4 py-5" key={round.number}>
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
                round={round}
                selectedItem={selectedItem}
              />
              <DayPhase
                items={dayItems}
                onSelect={onSelect}
                round={round}
                selectedItem={selectedItem}
              />
            </article>
          );
        })}
      </div>
    </section>
  );
}
