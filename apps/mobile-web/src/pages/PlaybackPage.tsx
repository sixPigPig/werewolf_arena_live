import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import {
  getGamePlayback,
  type GamePlayback,
  type RawGameState,
  type RawRoundState,
} from "@werewolf-arena/game-client";

type MobilePlayback = GamePlayback & {
  logs?: unknown[];
  state?: RawGameState;
};

export function PlaybackPage() {
  const { gameId } = useParams();
  const playbackQuery = useQuery({
    queryKey: ["game-playback", gameId],
    queryFn: () => getGamePlayback(gameId ?? ""),
    enabled: Boolean(gameId),
  });
  const playback = playbackQuery.data as MobilePlayback | undefined;
  const state = playback?.state;
  const winner = state?.winner ?? findWinner(playback);
  const rounds = state?.rounds ?? [];

  return (
    <main className="mobile-page">
      <header className="mobile-page-section">
        <h1>移动复盘</h1>
      </header>

      {playbackQuery.isPending ? <p>正在读取复盘...</p> : null}
      {playbackQuery.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法读取复盘
        </p>
      ) : null}

      {playback ? (
        <>
          <section aria-label="复盘概要" className="mobile-session-card">
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
                <dt>胜者</dt>
                <dd>{winner ?? "未决出"}</dd>
              </div>
              <div>
                <dt>玩家</dt>
                <dd>{state?.players.length ?? playerCountFromPlayback(playback)}</dd>
              </div>
              <div>
                <dt>轮数</dt>
                <dd>{rounds.length}</dd>
              </div>
            </dl>
          </section>

          <section aria-label="轮次摘要" className="mobile-replay-rounds">
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
  round: RawRoundState;
};

function RoundSummary({ round }: RoundSummaryProps) {
  const privateSummaries = Object.entries(round.summaries ?? {});

  return (
    <div className="mobile-replay-round-body">
      {round.public_summary ? <p>{round.public_summary}</p> : null}
      <dl className="mobile-session-meta">
        <div>
          <dt>夜晚出局</dt>
          <dd>{round.eliminated ?? "无"}</dd>
        </div>
        <div>
          <dt>白天放逐</dt>
          <dd>{round.exiled ?? "无"}</dd>
        </div>
        <div>
          <dt>查验</dt>
          <dd>{round.investigated ?? "无"}</dd>
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

function findWinner(playback: MobilePlayback | undefined) {
  const completedEvent = playback?.events?.find(
    (event) => event.type === "game_completed",
  );
  const winner = completedEvent?.payload.winner;

  return typeof winner === "string" ? winner : null;
}

function playerCountFromPlayback(playback: MobilePlayback) {
  const startEvent = playback.events?.find((event) => event.type === "game_started");
  const players = startEvent?.payload.players;

  return Array.isArray(players) ? players.length : 0;
}
