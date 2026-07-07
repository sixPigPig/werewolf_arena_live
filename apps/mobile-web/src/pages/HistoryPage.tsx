import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import {
  listGames,
  resumeGameRun,
  type GameSessionSummary,
} from "@werewolf-arena/game-client";

export function HistoryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const gamesQuery = useQuery({
    queryKey: ["games"],
    queryFn: listGames,
  });
  const resumeMutation = useMutation({
    mutationFn: (sessionId: string) => resumeGameRun(sessionId),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["games"] });
      navigate(`/games/${run.run_id}/live`);
    },
  });

  const sessions = gamesQuery.data?.sessions ?? [];

  return (
    <main className="mobile-page mobile-archive-page mobile-history-page">
      <header className="mobile-archive-hero">
        <span>对局档案库</span>
        <h1>对局历史</h1>
        <p>回看已完成的战局，或从保存点继续一局未完的夜色。</p>
        <button
          className="mobile-button"
          disabled={gamesQuery.isFetching}
          onClick={() => void gamesQuery.refetch()}
          type="button"
        >
          {gamesQuery.isFetching ? "刷新中" : "刷新"}
        </button>
      </header>

      {gamesQuery.isPending ? <p>正在读取对局列表...</p> : null}
      {gamesQuery.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法读取对局列表
        </p>
      ) : null}
      {resumeMutation.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法继续对局
        </p>
      ) : null}
      {!gamesQuery.isPending && !gamesQuery.isError && sessions.length === 0 ? (
        <p>暂无历史对局</p>
      ) : null}

      <section aria-label="对局历史列表" className="mobile-session-list">
        {sessions.map((session) => (
          <HistorySessionCard
            isResuming={
              resumeMutation.isPending &&
              resumeMutation.variables === session.session_id
            }
            key={session.session_id}
            onResume={() => resumeMutation.mutate(session.session_id)}
            session={session}
          />
        ))}
      </section>
    </main>
  );
}

type HistorySessionCardProps = {
  isResuming: boolean;
  onResume: () => void;
  session: GameSessionSummary;
};

function HistorySessionCard({
  isResuming,
  onResume,
  session,
}: HistorySessionCardProps) {
  const canResume = session.resumable === true;

  return (
    <article
      aria-label={`${session.session_id} 对局档案`}
      className="mobile-archive-card mobile-history-card mobile-session-card"
    >
      <div className="mobile-session-card-heading">
        <h2>{session.session_id}</h2>
        <span>{formatStatus(session.status)}</span>
      </div>
      <dl className="mobile-session-meta">
        <div>
          <dt>规则</dt>
          <dd>{session.rule_set?.name ?? "未知规则"}</dd>
        </div>
        <div>
          <dt>胜者</dt>
          <dd>{session.winner ?? "未决出"}</dd>
        </div>
        <div>
          <dt>轮数</dt>
          <dd>{session.round_count}</dd>
        </div>
        <div>
          <dt>创建时间</dt>
          <dd>{formatDate(session.created_at)}</dd>
        </div>
      </dl>
      <div className="mobile-session-actions">
        {canResume ? (
          <button
            aria-label={`继续对局 ${session.session_id}`}
            className="mobile-button mobile-button-primary"
            disabled={isResuming}
            onClick={onResume}
            type="button"
          >
            {isResuming ? "继续中" : "继续对局"}
          </button>
        ) : null}
        <Link
          aria-label={`直播回放 ${session.session_id}`}
          className="mobile-button mobile-session-link"
          to={`/games/${session.session_id}/live-replay`}
        >
          直播回放
        </Link>
        <Link
          aria-label={`查看复盘 ${session.session_id}`}
          className="mobile-button mobile-session-link"
          to={`/games/${session.session_id}/replay`}
        >
          查看复盘
        </Link>
      </div>
    </article>
  );
}

function formatStatus(status: GameSessionSummary["status"]) {
  return status === "complete" ? "已完成" : "可继续";
}

function formatDate(value: string | null) {
  if (!value) {
    return "未知";
  }

  const date = new Date(value);

  return Number.isNaN(date.getTime()) ? value : date.toISOString().slice(0, 10);
}
