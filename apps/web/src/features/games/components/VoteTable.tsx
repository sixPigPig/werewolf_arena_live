import type { VoteEntry } from "../types";

type VoteTableProps = {
  votes: VoteEntry[];
};

export function VoteTable({ votes }: VoteTableProps) {
  if (votes.length === 0) {
    return <p className="text-sm text-slate-500">无投票记录</p>;
  }

  return (
    <table className="w-full table-fixed text-sm">
      <thead>
        <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
          <th className="py-2 font-medium">Voter</th>
          <th className="py-2 font-medium">Target</th>
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
  );
}
