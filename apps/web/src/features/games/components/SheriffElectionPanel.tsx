import type { DeathEvent, DebugItem, GameRound, SpeechEntry } from "../types";

import { isSelfBadgeTransfer } from "../sheriffBadgeDisplay";

type SheriffElectionPanelProps = {
  items?: DebugItem[];
  round: GameRound;
};

export function SheriffElectionPanel({
  items = [],
  round,
}: SheriffElectionPanelProps) {
  if (!hasSheriffDisplayData(round)) {
    return null;
  }

  const offSheriffPlayers =
    round.sheriff_voters.length > 0
      ? round.sheriff_voters
      : round.sheriff_candidates.length > 0
        ? round.players.filter((player) => !round.sheriff_candidates.includes(player))
        : [];

  return (
    <section className="mt-4 rounded border border-slate-200 bg-white px-4 py-4">
      <h4 className="text-xs font-semibold text-slate-500">
        警长竞选
      </h4>

      <div className="mt-3 space-y-4 text-sm text-slate-700">
        <div className="grid gap-3 sm:grid-cols-2">
          <PlayerChips label="上警" values={round.sheriff_candidates} />
          <PlayerChips label="警下" values={offSheriffPlayers} />
          <PlayerChips label="退水" values={round.sheriff_withdrawn} />
          <PlayerChips label="最终候选" values={round.sheriff_final_candidates} />
        </div>

        <SheriffSpeechOrder round={round} />
        <SpeechList title="警上发言" speeches={round.sheriff_speeches} />
        <SheriffVoteStatus round={round} />
        <PlayerChips label="PK 候选" values={round.sheriff_pk_candidates} />
        <SpeechList title="PK 发言" speeches={round.sheriff_pk_speeches} />
        <VoteList title="二轮投票" votes={round.sheriff_runoff_votes} />
        <ElectionOutcome round={round} />
        <BadgeStatus items={items} round={round} />
        <SpeechDirection round={round} />
      </div>
    </section>
  );
}

function hasSheriffDisplayData(round: GameRound) {
  const sheriffSpeechOrder = round.sheriff_speech_order ?? [];
  const sheriffSpeechDirection = round.sheriff_speech_direction ?? null;

  return (
    round.sheriff !== null ||
    round.sheriff_candidates.length > 0 ||
    sheriffSpeechOrder.length > 0 ||
    sheriffSpeechDirection !== null ||
    round.sheriff_speeches.length > 0 ||
    round.sheriff_withdrawn.length > 0 ||
    round.sheriff_final_candidates.length > 0 ||
    round.sheriff_voters.length > 0 ||
    Object.keys(round.sheriff_votes).length > 0 ||
    round.sheriff_pk_candidates.length > 0 ||
    round.sheriff_pk_speeches.length > 0 ||
    Object.keys(round.sheriff_runoff_votes).length > 0 ||
    round.sheriff_elected !== null ||
    round.speech_order_choice !== null ||
    round.sheriff_badge_target !== null ||
    round.sheriff_badge_lost
  );
}

function SheriffSpeechOrder({ round }: { round: GameRound }) {
  const sheriffSpeechOrder = round.sheriff_speech_order ?? [];
  const sheriffSpeechDirection = round.sheriff_speech_direction ?? null;

  if (sheriffSpeechOrder.length === 0 && !sheriffSpeechDirection) {
    return null;
  }

  return (
    <div className="grid gap-2 border-t border-slate-200 pt-3 sm:grid-cols-2">
      {sheriffSpeechDirection ? (
        <p className="rounded bg-slate-50 px-3 py-2">
          警上发言方向：{sheriffSpeechDirection}
        </p>
      ) : null}
      {sheriffSpeechOrder.length > 0 ? (
        <p className="rounded bg-slate-50 px-3 py-2">
          警上发言顺序：{sheriffSpeechOrder.join(" -> ")}
        </p>
      ) : null}
    </div>
  );
}

function PlayerChips({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <ul aria-label={`${label}名单`} className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <li key={`${label}-${value}`}>
            <span className="inline-flex min-h-6 items-center rounded bg-slate-50 px-2 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-200">
              {value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SpeechList({
  title,
  speeches,
}: {
  title: string;
  speeches: SpeechEntry[];
}) {
  if (speeches.length === 0) {
    return null;
  }

  return (
    <section className="border-t border-slate-200 pt-3">
      <p className="text-xs font-medium text-slate-500">{title}</p>
      <ul aria-label={title} className="mt-2 divide-y divide-slate-200">
        {speeches.map((speech, index) => (
          <li
            className="grid gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[7rem_minmax(0,1fr)]"
            key={`${speech.speaker}-${index}`}
          >
            <span className="font-medium text-slate-950">{speech.speaker}</span>
            <p className="break-words leading-7 text-slate-700">
              {speech.message}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function VoteList({
  title,
  votes,
}: {
  title: string;
  votes: Record<string, string>;
}) {
  const entries = Object.entries(votes);

  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="border-t border-slate-200 pt-3">
      <p className="text-xs font-medium text-slate-500">{title}</p>
      <ul className="mt-1 flex flex-wrap gap-2">
        {entries.map(([voter, target]) => (
          <li
            className="rounded border border-slate-200 bg-slate-50 px-2 py-1 text-slate-800"
            key={`${voter}-${target}`}
          >
            {voter} -&gt; {target}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SheriffVoteStatus({ round }: { round: GameRound }) {
  if (Object.keys(round.sheriff_votes).length > 0) {
    return <VoteList title="警下投票" votes={round.sheriff_votes} />;
  }

  const soleFinalCandidate = round.sheriff_final_candidates[0];

  if (
    round.sheriff_final_candidates.length === 1 &&
    round.sheriff_elected === soleFinalCandidate
  ) {
    return (
      <p className="border-t border-slate-200 pt-3">
        {`警下投票：无需投票，最终候选仅 ${soleFinalCandidate}，自动当选`}
      </p>
    );
  }

  return null;
}

function ElectionOutcome({ round }: { round: GameRound }) {
  if (round.sheriff_elected) {
    return (
      <p className="font-medium text-slate-950">
        {round.sheriff_elected} 当选警长
      </p>
    );
  }

  if (hasElectionAttempt(round)) {
    return <p className="font-medium text-slate-950">未产生警长</p>;
  }

  return null;
}

function hasElectionAttempt(round: GameRound) {
  return (
    round.sheriff_candidates.length > 0 ||
    round.sheriff_speeches.length > 0 ||
    round.sheriff_final_candidates.length > 0 ||
    Object.keys(round.sheriff_votes).length > 0 ||
    round.sheriff_pk_candidates.length > 0 ||
    Object.keys(round.sheriff_runoff_votes).length > 0
  );
}

function BadgeStatus({
  items,
  round,
}: {
  items: DebugItem[];
  round: GameRound;
}) {
  const badgeTarget = visibleBadgeTarget(round, items);

  if (!round.sheriff && !badgeTarget && !round.sheriff_badge_lost) {
    return null;
  }

  if (
    hasBadgeChange(badgeTarget, round) &&
    !shouldShowBadgeChangeInElectionPanel(round)
  ) {
    return null;
  }

  const badgeTriggerText = badgeTriggerForElectedSheriff(round);
  const lostBadgeText =
    round.sheriff_badge_lost_reason === "双爆吞警徽"
      ? "警徽状态：双爆吞警徽，警徽流失"
      : round.sheriff_elected
        ? `${badgeTriggerText}警徽处理：撕毁警徽`
        : "警徽状态：警徽流失";

  return (
    <div className="space-y-2 border-t border-slate-200 pt-3">
      {round.sheriff ? <p>当前警长：{round.sheriff}</p> : null}
      {badgeTarget ? (
        <p>
          {badgeTriggerText}警徽处理：移交给 {badgeTarget}
        </p>
      ) : null}
      {round.sheriff_badge_lost ? <p>{lostBadgeText}</p> : null}
    </div>
  );
}

function visibleBadgeTarget(round: GameRound, items: DebugItem[]) {
  if (!round.sheriff_badge_target) {
    return null;
  }

  if (items.some(isNoopDayBadgeItem)) {
    return null;
  }

  return round.sheriff_badge_target;
}

function isNoopDayBadgeItem(item: DebugItem) {
  return (
    item.phase === "day" &&
    item.action === "sheriff_badge" &&
    isSelfBadgeTransfer(item.actor, item.choice)
  );
}

function hasBadgeChange(badgeTarget: string | null, round: GameRound) {
  return badgeTarget !== null || round.sheriff_badge_lost;
}

function shouldShowBadgeChangeInElectionPanel(round: GameRound) {
  if (!round.sheriff_elected) {
    return true;
  }

  if (round.day_deaths.some((death) => death.player === round.sheriff_elected)) {
    return false;
  }

  if (round.exiled === round.sheriff_elected) {
    return false;
  }

  return (
    round.night_deaths.some((death) => death.player === round.sheriff_elected) ||
    round.eliminated === round.sheriff_elected
  );
}

function badgeTriggerForElectedSheriff(round: GameRound) {
  if (!round.sheriff_elected) {
    return "";
  }

  const death = [...round.night_deaths, ...round.day_deaths].find(
    (event) => event.player === round.sheriff_elected,
  );

  if (!death) {
    return "警长出局后";
  }

  return deathTriggerText(death);
}

function deathTriggerText(death: DeathEvent) {
  if (death.cause === "vote_exile" || death.cause === "legacy_vote_exile") {
    return `${death.player} 被放逐后`;
  }

  if (
    death.cause === "werewolf_attack" ||
    death.cause === "legacy_night_elimination"
  ) {
    return `${death.player} 夜晚出局后`;
  }

  if (death.cause === "witch_poison") {
    return `${death.player} 被毒死后`;
  }

  if (death.cause === "hunter_shot") {
    return `${death.player} 被猎人带走后`;
  }

  return `${death.player} 出局后`;
}

function SpeechDirection({ round }: { round: GameRound }) {
  if (round.speech_order.length === 0 && !round.speech_order_choice) {
    return null;
  }

  return (
    <div className="space-y-2 border-t border-slate-200 pt-3">
      <p>
        {round.speech_order_choice
          ? `发言方向：${round.speech_order_choice}`
          : "无警长，按座次顺序发言"}
      </p>
      {round.speech_order.length > 0 ? (
        <p>发言顺序：{round.speech_order.join(" -> ")}</p>
      ) : null}
    </div>
  );
}
