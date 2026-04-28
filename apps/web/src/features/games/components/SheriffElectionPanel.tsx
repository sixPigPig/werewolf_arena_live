import type { GameRound, SpeechEntry } from "../types";

type SheriffElectionPanelProps = {
  round: GameRound;
};

export function SheriffElectionPanel({ round }: SheriffElectionPanelProps) {
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
    <section className="mt-4 rounded border border-slate-200 bg-slate-50 px-3 py-3">
      <h4 className="text-xs font-semibold uppercase text-slate-500">
        警长竞选
      </h4>

      <div className="mt-2 space-y-3 text-sm text-slate-700">
        <Line label="上警" values={round.sheriff_candidates} />
        <Line label="警下" values={offSheriffPlayers} />
        <SpeechList speeches={round.sheriff_speeches} />
        <Line label="退水" values={round.sheriff_withdrawn} />
        <Line label="最终候选" values={round.sheriff_final_candidates} />
        <VoteList title="警下投票" votes={round.sheriff_votes} />
        <Line label="PK 候选" values={round.sheriff_pk_candidates} />
        <SpeechList speeches={round.sheriff_pk_speeches} />
        <VoteList title="二轮投票" votes={round.sheriff_runoff_votes} />
        <ElectionOutcome round={round} />
        <BadgeStatus round={round} />
        <SpeechDirection round={round} />
      </div>
    </section>
  );
}

function hasSheriffDisplayData(round: GameRound) {
  return (
    round.sheriff !== null ||
    round.sheriff_candidates.length > 0 ||
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

function Line({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) {
    return null;
  }

  return <p>{label}：{values.join("、")}</p>;
}

function SpeechList({ speeches }: { speeches: SpeechEntry[] }) {
  if (speeches.length === 0) {
    return null;
  }

  return (
    <div className="space-y-1">
      {speeches.map((speech, index) => (
        <p className="break-words" key={`${speech.speaker}-${index}`}>
          {speech.speaker}：{speech.message}
        </p>
      ))}
    </div>
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
    <div>
      <p className="text-xs font-medium uppercase text-slate-500">{title}</p>
      <ul className="mt-1 flex flex-wrap gap-2">
        {entries.map(([voter, target]) => (
          <li
            className="rounded border border-slate-200 bg-white px-2 py-1 text-slate-800"
            key={`${voter}-${target}`}
          >
            {voter} -&gt; {target}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ElectionOutcome({ round }: { round: GameRound }) {
  if (round.sheriff_badge_lost) {
    return <p className="font-medium text-slate-950">警徽流失</p>;
  }

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

function BadgeStatus({ round }: { round: GameRound }) {
  if (!round.sheriff && !round.sheriff_badge_target && !round.sheriff_badge_lost) {
    return null;
  }

  return (
    <div className="space-y-1">
      {round.sheriff ? <p>当前警长：{round.sheriff}</p> : null}
      {round.sheriff_badge_target ? (
        <p>警徽移交：{round.sheriff_badge_target}</p>
      ) : null}
      {round.sheriff_badge_lost ? <p>警徽状态：警徽流失</p> : null}
    </div>
  );
}

function SpeechDirection({ round }: { round: GameRound }) {
  if (round.speech_order.length === 0 && !round.speech_order_choice) {
    return null;
  }

  return (
    <div className="space-y-1">
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
