import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { listGames, resumeGameRun } from "../api/gamesApi";
import { MobileButton } from "../components/MobileButton";
import { StatusBanner } from "../components/StatusBanner";

function formatWinner(winner: string | null) {
  return winner ?? "未记录胜方";
}

export function HistoryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [resumingSessionId, setResumingSessionId] = useState<string | null>(null);
  const gamesQuery = useQuery({
    queryFn: listGames,
    queryKey: ["mobile-games"],
  });
  const resumeMutation = useMutation({
    mutationFn: resumeGameRun,
    onMutate: (sessionId) => {
      setResumingSessionId(sessionId);
    },
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["mobile-games"] });
      navigate(`/live/${run.run_id}`);
    },
    onSettled: () => {
      setResumingSessionId(null);
    },
  });

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">历史</p>
        <h2>对局记录</h2>
      </header>

      {gamesQuery.isError ? (
        <StatusBanner title="历史不可用" tone="error">
          <p>无法读取历史对局，请确认后端正在运行。</p>
        </StatusBanner>
      ) : null}
      {resumeMutation.isError ? (
        <StatusBanner title="继续失败" tone="error">
          <p>无法继续这场对局，请稍后重试。</p>
        </StatusBanner>
      ) : null}

      <section className="mobile-card">
        {gamesQuery.isPending ? <p>正在读取历史...</p> : null}
        {gamesQuery.data?.sessions.map((session) => (
          <article className="mobile-list-row" key={session.session_id}>
            <div>
              <strong>{session.session_id}</strong>
              <p>
                {session.round_count} 轮 · {formatWinner(session.winner)}
              </p>
            </div>
            {session.resumable ? (
              <MobileButton
                disabled={resumingSessionId === session.session_id}
                onClick={() => {
                  resumeMutation.mutate(session.session_id);
                }}
              >
                {resumingSessionId === session.session_id ? "继续中..." : "继续"}
              </MobileButton>
            ) : (
              <Link className="mobile-link-button" to={`/playback/${session.session_id}`}>
                复盘
              </Link>
            )}
          </article>
        ))}
        {gamesQuery.data?.sessions.length === 0 ? <p>暂无历史对局。</p> : null}
      </section>
    </section>
  );
}
