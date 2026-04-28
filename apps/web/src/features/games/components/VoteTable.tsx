import type { VoteEntry, VoteTallyEntry } from "../types";

type VoteTableProps = {
  votes: VoteEntry[];
  tally: VoteTallyEntry[];
};

export function VoteTable({ votes, tally }: VoteTableProps) {
  if (votes.length === 0) {
    return <p className="text-sm text-slate-500">无投票记录</p>;
  }

  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-medium uppercase text-slate-500">票型统计</p>
        <ul className="mt-2 flex flex-wrap gap-2 text-sm">
          {tally.map((entry) => (
            <li
              className="rounded border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-800"
              key={entry.target}
            >
              {entry.target}：{entry.count}票
            </li>
          ))}
        </ul>
      </div>

      <table className="w-full table-fixed text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
            <th className="py-2 font-medium">投票者</th>
            <th className="py-2 font-medium">投票对象</th>
          </tr>
        </thead>
        <tbody>
          {votes.map((vote, index) => (
            <tr
              className="border-b border-slate-100 last:border-0"
              key={`${vote.voter}-${index}`}
            >
              <td className="break-words py-2 pr-2 text-slate-700">
                {vote.voter}
              </td>
              <td className="break-words py-2 text-slate-950">{vote.target}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
