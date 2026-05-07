import { Badge, Table } from "@radix-ui/themes";

import type { VoteEntry, VoteTallyEntry } from "../types";

import { formatVoteCount } from "./voteFormatting";

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
            <li key={entry.target}>
              <Badge color="gray" variant="surface">
                {entry.target}：{formatVoteCount(entry.count)}票
              </Badge>
            </li>
          ))}
        </ul>
      </div>

      <Table.Root size="1" variant="surface">
        <Table.Header>
          <Table.Row>
            <Table.ColumnHeaderCell>投票者</Table.ColumnHeaderCell>
            <Table.ColumnHeaderCell>投票对象</Table.ColumnHeaderCell>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {votes.map((vote, index) => (
            <Table.Row key={`${vote.voter}-${index}`}>
              <Table.Cell className="break-words">
                {vote.weight === 1
                  ? vote.voter
                  : `${vote.voter}（${formatVoteCount(vote.weight)}票）`}
              </Table.Cell>
              <Table.Cell className="break-words">{vote.target}</Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table.Root>
    </div>
  );
}
