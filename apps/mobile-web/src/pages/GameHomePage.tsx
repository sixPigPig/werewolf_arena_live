import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createGameRun, listGames, listRuleSets } from "../api/gamesApi";
import type { GameSessionSummary } from "../api/types";
import { MobileButton } from "../components/MobileButton";
import { StatusBanner } from "../components/StatusBanner";

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
  const [selectedRuleSetId, setSelectedRuleSetId] = useState("");
  const [confirmedRuleSetId, setConfirmedRuleSetId] = useState("");
  const ruleSetsQuery = useQuery({
    queryKey: ["rule-sets"],
    queryFn: listRuleSets,
  });
  const ruleSets = useMemo(
    () => ruleSetsQuery.data?.rule_sets ?? [],
    [ruleSetsQuery.data?.rule_sets],
  );
  const activeRule = useMemo(
    () =>
      ruleSets.find((ruleSet) => ruleSet.id === selectedRuleSetId) ??
      ruleSets[0],
    [ruleSets, selectedRuleSetId],
  );
  const confirmedRule = useMemo(
    () =>
      ruleSets.find((ruleSet) => ruleSet.id === confirmedRuleSetId) ?? null,
    [ruleSets, confirmedRuleSetId],
  );
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
        <h2>先确认今晚规则</h2>
        <p>选定规则后，可以直接快速开局，也可以带着规则进入自定义阵容。</p>

        {!confirmedRule ? (
          <>
            {ruleSetsQuery.isLoading ? <p>正在读取规则预设...</p> : null}
            {ruleSetsQuery.isError ? (
              <StatusBanner title="规则读取失败" tone="error">
                <p>规则预设暂时无法加载，请稍后再试。</p>
              </StatusBanner>
            ) : null}
            {!ruleSetsQuery.isLoading &&
            !ruleSetsQuery.isError &&
            ruleSets.length === 0 ? (
              <p>暂无可用规则预设。</p>
            ) : null}
            {ruleSets.map((ruleSet) => (
              <label className="mobile-choice-row" key={ruleSet.id}>
                <input
                  checked={activeRule?.id === ruleSet.id}
                  name="home-rule-set"
                  onChange={() => {
                    setSelectedRuleSetId(ruleSet.id);
                  }}
                  type="radio"
                />
                <span>
                  <strong>{ruleSet.name}</strong>
                  <span>
                    {ruleSet.player_count} 人
                    {ruleSet.role_summary ? ` · ${ruleSet.role_summary}` : ""}
                  </span>
                </span>
              </label>
            ))}
            <MobileButton
              disabled={!activeRule || createRunMutation.isPending}
              onClick={() => {
                if (activeRule) {
                  setConfirmedRuleSetId(activeRule.id);
                }
              }}
              tone="primary"
            >
              确认规则
            </MobileButton>
          </>
        ) : (
          <>
            <div className="mobile-list-row">
              <div>
                <strong>{confirmedRule.name}</strong>
                <p>
                  {confirmedRule.player_count} 人
                  {confirmedRule.role_summary
                    ? ` · ${confirmedRule.role_summary}`
                    : ""}
                </p>
              </div>
              <MobileButton
                disabled={createRunMutation.isPending}
                onClick={() => {
                  setConfirmedRuleSetId("");
                }}
              >
                更换规则
              </MobileButton>
            </div>
            <div className="mobile-home-actions">
              <MobileButton
                disabled={createRunMutation.isPending}
                onClick={() => {
                  createRunMutation.mutate({
                    max_rounds: 8,
                    player_configs: [],
                    rule_set_id: confirmedRule.id,
                  });
                }}
                tone="primary"
              >
                {createRunMutation.isPending ? "开局中..." : "快速开局"}
              </MobileButton>
              <Link
                className="mobile-link-button"
                to={`/custom-game?ruleSetId=${encodeURIComponent(
                  confirmedRule.id,
                )}`}
              >
                自定义开局
              </Link>
            </div>
          </>
        )}

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
