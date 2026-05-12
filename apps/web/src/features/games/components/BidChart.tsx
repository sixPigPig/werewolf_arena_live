import { Progress } from "../../../components/ui";

import type { BidEntry } from "../types";

type BidChartProps = {
  bids: BidEntry[];
};

export function BidChart({ bids }: BidChartProps) {
  if (bids.length === 0) {
    return <p className="text-sm text-slate-500">无竞价记录</p>;
  }

  const maxScore = Math.max(...bids.map((bid) => bid.score), 1);

  return (
    <div className="space-y-2">
      {bids.map((bid, index) => (
        <div
          className="grid grid-cols-[5rem_1fr_3rem] items-center gap-2"
          key={`${bid.actor}-${index}`}
        >
          <span className="truncate text-sm text-slate-700">{bid.actor}</span>
          <Progress
            color="cyan"
            max={100}
            value={Math.max(8, (bid.score / maxScore) * 100)}
          />
          <span className="text-right font-mono text-xs text-slate-600">
            {bid.score}
          </span>
        </div>
      ))}
    </div>
  );
}
