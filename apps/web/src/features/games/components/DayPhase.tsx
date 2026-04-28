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

      <section className="mt-3">
        <h4 className="text-xs font-semibold uppercase text-slate-500">竞价</h4>
        <div className="mt-2">
          <BidRounds round={round} />
        </div>
      </section>

      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          发言
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
          投票
        </h4>
        <div className="mt-2">
          <VoteTable tally={round.voteTally} votes={round.votes} />
        </div>
        <VoteResolution round={round} />
      </section>

      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          轮次总结
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

function BidRounds({ round }: { round: GameRound }) {
  if (round.bidGroups.length === 0) {
    return <BidChart bids={round.bids} />;
  }

  return (
    <div className="space-y-4">
      {round.bidGroups.map((group) => (
        <section
          className="rounded border border-slate-200 bg-white px-3 py-3"
          key={group.turn}
        >
          <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <h5 className="text-sm font-medium text-slate-950">
              第 {group.turn} 次发言竞价
            </h5>
            {group.speaker ? (
              <span className="text-xs text-slate-600">
                发言人：{group.speaker}
              </span>
            ) : null}
          </div>
          <BidChart bids={group.bids} />
        </section>
      ))}
    </div>
  );
}

function VoteResolution({ round }: { round: GameRound }) {
  if (round.voteCount === 0 || round.voteMajorityThreshold === null) {
    return null;
  }

  return (
    <div className="mt-3 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
      <p className="font-medium text-slate-950">
        多数门槛 {round.voteMajorityThreshold}/{round.voteCount}
      </p>
      <p className="mt-1">
        {round.exiled ? `${round.exiled} 被放逐` : "无人被放逐"}
      </p>
    </div>
  );
}
