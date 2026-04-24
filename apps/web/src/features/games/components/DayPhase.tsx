import type { DebugItem, GameRound } from "../types";

import { ActionCard } from "./ActionCard";
import { BidChart } from "./BidChart";
import { SummaryStrip } from "./SummaryStrip";
import { VoteTable } from "./VoteTable";

type DayPhaseProps = {
  round: GameRound;
  items: DebugItem[];
  selectedItem: DebugItem | null;
  onSelect: (item: DebugItem) => void;
};

export function DayPhase({
  round,
  items,
  selectedItem,
  onSelect,
}: DayPhaseProps) {
  return (
    <section className="border-t border-slate-200 pt-4">
      <h3 className="text-sm font-semibold text-slate-950">白天</h3>

      <div className="mt-3 grid gap-4 xl:grid-cols-2">
        <section>
          <h4 className="text-xs font-semibold uppercase text-slate-500">Bid</h4>
          <div className="mt-2">
            <BidChart bids={round.bids} />
          </div>
        </section>

        <section>
          <h4 className="text-xs font-semibold uppercase text-slate-500">
            Vote
          </h4>
          <div className="mt-2">
            <VoteTable votes={round.votes} />
          </div>
        </section>
      </div>

      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          Debate
        </h4>
        <div className="mt-2 space-y-2">
          {round.debate.length === 0 ? (
            <p className="text-sm text-slate-500">无发言记录</p>
          ) : (
            round.debate.map((entry, index) => (
              <p
                className="break-words rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700"
                key={`${entry.speaker}-${index}`}
              >
                {entry.speaker} -&gt; {entry.message}
              </p>
            ))
          )}
        </div>
      </section>

      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          Summary
        </h4>
        <div className="mt-2">
          <SummaryStrip summaries={round.summaries} />
        </div>
      </section>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <ActionCard
            item={item}
            key={item.id}
            onSelect={onSelect}
            selected={selectedItem?.id === item.id}
          />
        ))}
      </div>
    </section>
  );
}
