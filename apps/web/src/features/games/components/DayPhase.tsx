import { Callout, Card } from "../../../components/ui";

import type { DebugItem, GameRound } from "../types";

import { isSelfBadgeTransfer } from "../sheriffBadgeDisplay";
import { ActionCardGroup } from "./ActionCard";
import { BidChart } from "./BidChart";
import { SheriffElectionPanel } from "./SheriffElectionPanel";
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
  const visibleItems = items.filter((item) => !isNoopDayBadgeItem(item));

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

      <SheriffElectionPanel items={items} round={round} />
      <SelfExplosionNotice round={round} />

      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          白天发言
        </h4>
        <div className="mt-2 grid gap-2">
          {round.debate.length === 0 ? (
            <p className="text-sm text-slate-500">无发言记录</p>
          ) : (
            round.debate.map((entry, index) => (
              <Card asChild key={`${entry.speaker}-${index}`} size="1" variant="surface">
                <p className="break-words text-sm text-slate-700">
                  {entry.speaker} -&gt; {entry.message}
                </p>
              </Card>
            ))
          )}
        </div>
      </section>

      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          放逐投票
        </h4>
        <div className="mt-2">
          <VoteTable tally={round.voteTally} votes={round.votes} />
        </div>
        <VoteResolution round={round} />
        <SpecialDayResolution items={items} round={round} />
      </section>

      <section className="mt-4">
        <h4 className="text-xs font-semibold uppercase text-slate-500">
          轮次总结
        </h4>
        <div className="mt-2">
          <SummaryStrip
            publicSummary={round.public_summary}
            summaries={round.summaries}
          />
        </div>
      </section>

      <ActionCardGroup
        ariaLabel="白天行动记录"
        className="mt-4"
        columns={{ initial: "1", sm: "2", xl: "3" }}
        items={visibleItems}
        onSelect={onSelect}
        selectedItem={selectedItem}
      />
    </section>
  );
}

function SelfExplosionNotice({ round }: { round: GameRound }) {
  if (!round.day_ended_by_self_explosion || !round.werewolf_self_exploded) {
    return null;
  }

  return (
    <Callout.Root className="mt-4" color="red" size="1" variant="soft">
      <Callout.Text className="font-medium">
        {round.werewolf_self_exploded} 自爆为狼人，白天提前结束
      </Callout.Text>
      {round.sheriff_badge_lost_reason === "首爆中断警长竞选" ? (
        <Callout.Text>首爆中断警长竞选，下一天继续竞选</Callout.Text>
      ) : null}
      {round.sheriff &&
      round.sheriff_badge_lost_reason !== "首爆中断警长竞选" &&
      round.sheriff_badge_lost_reason !== "双爆吞警徽" ? (
        <Callout.Text>警长已产生，自爆不吞警徽</Callout.Text>
      ) : null}
    </Callout.Root>
  );
}

function isNoopDayBadgeItem(item: DebugItem) {
  return (
    item.phase === "day" &&
    item.action === "sheriff_badge" &&
    isSelfBadgeTransfer(item.actor, item.choice)
  );
}

function SpecialDayResolution({
  items,
  round,
}: {
  items: DebugItem[];
  round: GameRound;
}) {
  const badgeResolution = hasDayResolution(round)
    ? sheriffBadgeResolution(round, items)
    : null;

  if (
    !round.idiot_revealed &&
    !round.hunter_shot &&
    round.day_deaths.length === 0 &&
    !badgeResolution
  ) {
    return null;
  }

  return (
    <Card className="mt-3 space-y-1 text-sm text-slate-700" size="1" variant="surface">
      {round.idiot_revealed ? (
        <p>{round.idiot_revealed} 翻牌免死，失去投票权</p>
      ) : null}
      {round.hunter_shot ? <p>猎人带走 {round.hunter_shot}</p> : null}
      {round.day_deaths.length > 0 ? (
        <p>
          白天死亡：{round.day_deaths.map((death) => death.player).join("、")}
        </p>
      ) : null}
      {badgeResolution ? <p>{badgeResolution}</p> : null}
    </Card>
  );
}

function hasDayResolution(round: GameRound) {
  return round.day_deaths.length > 0 || Boolean(round.exiled);
}

function sheriffBadgeResolution(round: GameRound, items: DebugItem[]) {
  const badgeItem = items.find(
    (item) =>
      item.phase === "day" &&
      item.action === "sheriff_badge" &&
      !isSelfBadgeTransfer(item.actor, item.choice),
  );
  if (badgeItem?.actor && badgeItem.choice) {
    return `警徽处理：${badgeItem.actor} 选择 ${formatBadgeChoice(
      badgeItem.choice,
    )}`;
  }

  if (items.some(isNoopDayBadgeItem)) {
    return null;
  }

  if (!round.sheriff_badge_target && !round.sheriff_badge_lost) {
    return null;
  }

  if (!hasKnownBadgeOwner(round)) {
    return null;
  }

  const actor = sheriffBadgeActorFromDayResolution(round);
  if (round.sheriff_badge_target) {
    return actor
      ? `警徽处理：${actor} 选择 移交给 ${round.sheriff_badge_target}`
      : `警徽处理：移交给 ${round.sheriff_badge_target}`;
  }

  return actor
    ? `警徽处理：${actor} 选择 撕毁警徽`
    : "警徽处理：撕毁警徽";
}

function hasKnownBadgeOwner(round: GameRound) {
  return Boolean(round.sheriff || round.sheriff_elected);
}

function formatBadgeChoice(choice: string) {
  if (choice === "撕毁警徽" || choice.startsWith("移交给")) {
    return choice;
  }

  return `移交给 ${choice}`;
}

function sheriffBadgeActorFromDayResolution(round: GameRound) {
  const knownSheriffs = [round.sheriff, round.sheriff_elected].filter(
    (name): name is string => Boolean(name),
  );
  const sheriffDeath = round.day_deaths.find((death) =>
    knownSheriffs.includes(death.player),
  );

  return sheriffDeath?.player ?? null;
}

function BidRounds({ round }: { round: GameRound }) {
  if (round.bidGroups.length === 0) {
    return <BidChart bids={round.bids} />;
  }

  return (
    <div className="space-y-4">
      {round.bidGroups.map((group) => (
        <Card asChild key={group.turn} size="1">
          <section>
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
        </Card>
      ))}
    </div>
  );
}

function VoteResolution({ round }: { round: GameRound }) {
  if (round.voteCount === 0 || round.voteMajorityThreshold === null) {
    return null;
  }

  return (
    <Card className="mt-3 text-sm text-slate-700" size="1" variant="surface">
      <p className="font-medium text-slate-950">
        {`多数门槛 ${formatVoteCount(round.voteMajorityThreshold)}/${formatVoteCount(
          round.voteCount,
        )}`}
      </p>
      <p className="mt-1">
        {round.exiled ? `${round.exiled} 被放逐` : "无人被放逐"}
      </p>
    </Card>
  );
}
