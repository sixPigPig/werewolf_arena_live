import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { createGameRun, listGames } from "../api/gamesApi";
import type { GameSessionSummary } from "../api/types";
import { MobileButton } from "../components/MobileButton";
import { StatusBanner } from "../components/StatusBanner";

const quickStartRuleSetId = "classic_12_seer_witch_hunter_idiot";

function formatWinner(winner: string | null) {
  if (!winner) {
    return "未记录胜方";
  }

  if (winner === "werewolves" || winner === "werewolf") {
    return "狼人胜利";
  }

  if (winner === "villagers" || winner === "villager" || winner === "good") {
    return "好人胜利";
  }

  return winner;
}

function formatStatus(status: GameSessionSummary["status"]) {
  return status === "complete" ? "已结束" : "进行中";
}

function mutationErrorMessage(error: unknown) {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "请检查网络连接或稍后再试。";
}

function RecentGameCard() {
  const gamesQuery = useQuery({
    queryKey: ["games", "recent"],
    queryFn: listGames,
  });

  const recentGame = gamesQuery.data?.sessions[0];

  return (
    <section className="mobile-card" aria-labelledby="recent-games-title">
      <header>
        <p className="mobile-kicker">Status</p>
        <h2 id="recent-games-title">最近对局</h2>
      </header>

      {gamesQuery.isLoading ? (
        <p>正在读取最近对局...</p>
      ) : null}

      {gamesQuery.isError ? (
        <StatusBanner title="读取失败" tone="error">
          <p>最近对局暂时无法加载，请稍后再试。</p>
        </StatusBanner>
      ) : null}

      {!gamesQuery.isLoading && !gamesQuery.isError && !recentGame ? (
        <p>还没有对局记录，今晚可以从第一局开始。</p>
      ) : null}

      {recentGame ? (
        <div className="mobile-list-row">
          <div>
            <strong>{recentGame.session_id}</strong>
            <p>
              {formatStatus(recentGame.status)} · {formatWinner(recentGame.winner)}
            </p>
            <p>{recentGame.round_count} 轮</p>
          </div>
          <Link
            className="mobile-link-button"
            to={`/playback/${recentGame.session_id}`}
          >
            查看复盘
          </Link>
        </div>
      ) : null}
    </section>
  );
}

export function GameHomePage() {
  const navigate = useNavigate();
  const createRunMutation = useMutation({
    mutationFn: (request: Parameters<typeof createGameRun>[0]) =>
      createGameRun(request),
    onSuccess: (run) => {
      navigate(`/live/${run.run_id}`);
    },
  });

  return (
    <section className="mobile-page-section">
      <div className="mobile-hero-panel">
        <p className="mobile-kicker">大厅</p>
        <h2>今晚开一局</h2>
        <p>
          快速创建一场经典 12 人狼人杀，系统会准备默认阵容并进入实时直播。
        </p>

        <div className="mobile-home-actions">
          <MobileButton
            disabled={createRunMutation.isPending}
            onClick={() => {
              createRunMutation.mutate({
                max_rounds: 8,
                player_configs: [],
                rule_set_id: quickStartRuleSetId,
              });
            }}
            tone="primary"
          >
            {createRunMutation.isPending ? "开局中..." : "一键开局"}
          </MobileButton>
          <Link className="mobile-link-button" to="/custom-game">
            自定义开局
          </Link>
        </div>

        {createRunMutation.isError ? (
          <StatusBanner title="开局失败" tone="error">
            <p>{mutationErrorMessage(createRunMutation.error)}</p>
          </StatusBanner>
        ) : null}
      </div>

      <RecentGameCard />
    </section>
  );
}
