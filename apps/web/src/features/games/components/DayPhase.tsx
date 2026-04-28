import type { DebugItem, GameRound } from "../types";

import { ActionCard } from "./ActionCard";
import { BidChart } from "./BidChart";
import { SummaryStrip } from "./SummaryStrip";
import { VoteTable } from "./VoteTable";
import { formatVoteCount } from "./voteFormatting";

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

      {round.bidGroups.length > 0 || round.bids.length > 0 ? (
        <section className="mt-3">
          <h4 className="text-xs font-semibold uppercase text-slate-500">
            历史竞价
          </h4>
          <div className="mt-2">
            <BidRounds round={round} />
          </div>
        </section>
      ) : null}

      {round.speech_order.length > 0 ? (
        <section className="mt-4">
          <h4 className="text-xs font-semibold uppercase text-slate-500">
            发言顺序
          </h4>
          <p className="mt-2 text-sm text-slate-700">
            {round.speech_order.join(" -> ")}
          </p>
        </section>
      ) : null}

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
        <SpecialDayResolution round={round} />
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

function SpecialDayResolution({ round }: { round: GameRound }) {
  if (!round.idiot_revealed && !round.hunter_shot && round.day_deaths.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 space-y-1 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
      {round.idiot_revealed ? (
        <p>{round.idiot_revealed} 翻牌免死，失去投票权</p>
      ) : null}
      {round.hunter_shot ? <p>猎人带走 {round.hunter_shot}</p> : null}
      {round.day_deaths.length > 0 ? (
        <p>
          白天死亡：{round.day_deaths.map((death) => death.player).join("、")}
        </p>
      ) : null}
    </div>
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
        {`多数门槛 ${formatVoteCount(round.voteMajorityThreshold)}/${formatVoteCount(
          round.voteCount,
        )}`}
      </p>
      <p className="mt-1">
        {round.exiled ? `${round.exiled} 被放逐` : "无人被放逐"}
      </p>
    </div>
  );
}
