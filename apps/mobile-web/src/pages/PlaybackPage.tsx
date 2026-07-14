import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import {
  getGamePlayback,
  type GamePlayback,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";

type PlaybackRound = {
  latestState: Record<string, unknown>;
  number: number;
};

export function PlaybackPage() {
  const { gameId } = useParams();
  const playbackQuery = useQuery({
    queryKey: ["game-playback", gameId],
    queryFn: () => getGamePlayback(gameId ?? "", "spectator_god_view"),
    enabled: Boolean(gameId),
  });
  const playback = playbackQuery.data;
  const winner = findWinner(playback);
  const rounds = playback ? playbackRounds(playback.events) : [];

  return (
    <main className="mobile-page mobile-archive-page mobile-playback-page">
      <header className="mobile-archive-hero">
        <span>对局卷宗</span>
        <h1>移动复盘</h1>
        <p>复核整局走势、关键轮次和观战视角下的结构化行动。</p>
        {gameId ? (
          <Link
            className="mobile-button mobile-session-link"
            to={`/games/${gameId}/live-replay`}
          >
            导入直播页播放
          </Link>
        ) : null}
      </header>

      {playbackQuery.isPending ? <p>正在读取复盘...</p> : null}
      {playbackQuery.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法读取复盘
        </p>
      ) : null}

      {playback ? (
        <>
          <section
            aria-label="复盘概要"
            className="mobile-archive-card mobile-playback-summary"
          >
            <div className="mobile-archive-card-heading">
              <span>战报摘要</span>
              <strong>{winner ? `${winner} 胜利` : "未决出"}</strong>
            </div>
            <dl className="mobile-session-meta">
              <div>
                <dt>会话</dt>
                <dd>{playback.session_id ?? gameId}</dd>
              </div>
              <div>
                <dt>状态</dt>
                <dd>{playback.status}</dd>
              </div>
              <div>
                <dt>胜者阵营</dt>
                <dd>{winner ?? "未决出"}</dd>
              </div>
              <div>
                <dt>玩家</dt>
                <dd>{playerCountFromPlayback(playback)}</dd>
              </div>
              <div>
                <dt>轮数</dt>
                <dd>{rounds.length}</dd>
              </div>
            </dl>
          </section>

          <section aria-label="轮次摘要" className="mobile-replay-rounds">
            <h2>轮次记录</h2>
            {rounds.length > 0 ? (
              rounds.map((round) => (
                <details className="mobile-replay-details" key={round.number}>
                  <summary>第 {round.number} 轮</summary>
                  <RoundSummary round={round} />
                </details>
              ))
            ) : (
              <p>暂无轮次摘要</p>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}

type RoundSummaryProps = {
  round: PlaybackRound;
};

function RoundSummary({ round }: RoundSummaryProps) {
  const privateSummaries = summaryEntries(round.latestState.summaries);
  const publicSummary = stringValue(round.latestState.public_summary);

  return (
    <div className="mobile-replay-round-body">
      {publicSummary ? <p>{publicSummary}</p> : null}
      <dl className="mobile-session-meta">
        <div>
          <dt>夜晚出局</dt>
          <dd>{stringValue(round.latestState.eliminated) ?? "无"}</dd>
        </div>
        <div>
          <dt>白天放逐</dt>
          <dd>{stringValue(round.latestState.exiled) ?? "无"}</dd>
        </div>
        <div>
          <dt>查验</dt>
          <dd>{stringValue(round.latestState.investigated) ?? "无"}</dd>
        </div>
      </dl>
      {privateSummaries.length > 0 ? (
        <ul className="mobile-replay-summary-list" aria-label="玩家摘要">
          {privateSummaries.map(([player, summary]) => (
            <li key={player}>
              <strong>{player}</strong>
              <span>{summary}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function playbackRounds(events: LiveGameEvent[]) {
  const roundsByNumber = new Map<number, PlaybackRound>();

  for (const event of events) {
    if (
      event.type !== "round_started" &&
      event.type !== "state_updated"
    ) {
      continue;
    }
    if (typeof event.round !== "number") {
      continue;
    }

    const round = roundsByNumber.get(event.round) ?? {
      latestState: {},
      number: event.round,
    };

    if (event.type === "state_updated") {
      round.latestState = { ...round.latestState, ...event.payload };
    }

    roundsByNumber.set(event.round, round);
  }

  return [...roundsByNumber.values()].sort((left, right) => left.number - right.number);
}

function findWinner(playback: GamePlayback | undefined) {
  const completedEvent = playback?.events?.find(
    (event) => event.type === "game_completed",
  );

  return stringValue(completedEvent?.payload.winner);
}

function playerCountFromPlayback(playback: GamePlayback) {
  const startEvent = playback.events?.find((event) => event.type === "game_started");
  const players = startEvent?.payload.players;

  return Array.isArray(players) ? players.length : 0;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value ? value : null;
}

function summaryEntries(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return [];
  }

  return Object.entries(value).map(([player, summary]) => [
    player,
    String(summary),
  ]);
}
