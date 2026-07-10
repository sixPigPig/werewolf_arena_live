import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { useAdminSession } from "@/features/auth/session-context";
import {
  getAdminGame,
  getAdminGameDebug,
} from "@/features/game-records/api";
import {
  displayValue,
  formatDateTime,
  GAME_STATUS_LABELS,
  RUN_STATUS_LABELS,
} from "@/features/game-records/presentation";
import { adminGameKeys } from "@/features/game-records/query-keys";
import type {
  AdminGameDeath,
  AdminGameEvent,
  AdminGameRound,
  AdminGameRun,
} from "@/features/game-records/types";

export default function GameRecordDetailPage() {
  const { sessionId } = useParams();
  const [debugRequestedFor, setDebugRequestedFor] = useState<string | null>(
    null,
  );
  const debugRequested = Boolean(
    sessionId && debugRequestedFor === sessionId,
  );
  const { session } = useAdminSession();
  const canReadDebug = Boolean(
    session?.permissions.includes("*") ||
      session?.permissions.includes("games.debug.read"),
  );
  const gameQuery = useQuery({
    enabled: Boolean(sessionId),
    queryFn: ({ signal }) => getAdminGame(sessionId!, signal),
    queryKey: adminGameKeys.detail(sessionId ?? "missing"),
  });
  const debugQuery = useQuery({
    enabled: Boolean(
      sessionId && canReadDebug && gameQuery.isSuccess && debugRequested,
    ),
    queryFn: ({ signal }) => getAdminGameDebug(sessionId!, signal),
    queryKey: adminGameKeys.debug(sessionId ?? "missing"),
    retry: false,
  });

  if (gameQuery.isPending) {
    return (
      <div aria-live="polite" className="game-detail-loading" role="status">
        <span />
        正在读取对局诊断...
      </div>
    );
  }

  if (gameQuery.isError || !gameQuery.data) {
    return (
      <GameDetailError
        error={gameQuery.error ?? new Error("对局响应为空")}
        onRetry={gameQuery.refetch}
      />
    );
  }

  const game = gameQuery.data;
  const containsErrors = game.runs.some((run) => run.has_error);
  const revealsTerminalMetadata =
    game.status === "complete" && !game.resumable;

  return (
    <div className="admin-page game-detail-page">
      <Link className="game-back-link" to="/operations/games">
        ← 返回对局记录
      </Link>
      <header className="page-heading game-detail-heading">
        <div>
          <span className="page-kicker">GAME DIAGNOSTICS</span>
          <h1>{game.session_id}</h1>
          <p>
            {game.rule_set
              ? `${game.rule_set.name} · ${game.rule_set.player_count ?? "人数未知"}${game.rule_set.player_count === null ? "" : " 人"}${game.rule_set.id ? ` · ${game.rule_set.id}` : ""}`
              : "规则快照不可用"}
          </p>
        </div>
        <div className="game-detail-actions">
          <span className={`game-status-badge is-${game.status}`}>
            {GAME_STATUS_LABELS[game.status]}
          </span>
          <button
            className="admin-secondary-button"
            disabled={gameQuery.isFetching}
            onClick={() => void gameQuery.refetch()}
            type="button"
          >
            {gameQuery.isFetching ? "刷新中" : "刷新"}
          </button>
        </div>
      </header>

      <section aria-label="对局概览" className="game-detail-metrics">
        <article>
          <span>胜方</span>
          <strong>{displayValue(game.winner)}</strong>
          <small>{game.resumable ? "当前记录可恢复" : "当前记录不可恢复"}</small>
        </article>
        <article>
          <span>轮次</span>
          <strong>{game.round_count}</strong>
          <small>{game.rounds.length} 个公开轮次摘要</small>
        </article>
        <article>
          <span>运行 / 事件</span>
          <strong>
            {game.diagnostics.run_count} / {game.diagnostics.event_count}
          </strong>
          <small>失败语音 {game.diagnostics.failed_voice_count} 条</small>
        </article>
        <article>
          <span>创建时间</span>
          <strong className="is-date">{formatDateTime(game.created_at)}</strong>
          <small>更新于 {formatDateTime(game.updated_at)}</small>
        </article>
      </section>

      {containsErrors || canReadDebug ? (
        <DebugPanel
          canReadDebug={canReadDebug}
          debugError={debugQuery.isError ? debugQuery.error : null}
          debugPending={debugQuery.isPending && debugQuery.fetchStatus !== "idle"}
          debugRequested={debugRequested}
          gameError={debugQuery.data?.game_error ?? null}
          onRequest={() => setDebugRequestedFor(sessionId ?? null)}
          onRetry={debugQuery.refetch}
          runErrors={debugQuery.data?.run_errors ?? []}
        />
      ) : null}

      <div className="game-detail-grid">
        <section aria-labelledby="game-runs-title" className="game-detail-panel">
          <PanelHeading
            eyebrow="EXECUTIONS"
            id="game-runs-title"
            meta={`${game.runs.length} 次`}
            title="运行记录"
          />
          {game.runs.length > 0 ? (
            <ul aria-label="运行记录" className="game-run-list">
              {game.runs.map((run) => (
                <RunItem key={run.run_id} run={run} />
              ))}
            </ul>
          ) : (
            <PanelEmpty text="没有关联的运行记录。" />
          )}
        </section>

        <section aria-labelledby="game-players-title" className="game-detail-panel">
          <PanelHeading
            eyebrow="LINEUP SNAPSHOT"
            id="game-players-title"
            meta={`${game.players.length} 位`}
            title="玩家与角色结果"
          />
          {game.players.length > 0 ? (
            <ul aria-label="玩家与角色结果" className="game-player-list">
              {game.players.map((player) => (
                <li key={`${player.seat}-${player.name}`}>
                  <span className="game-player-avatar">
                    {player.avatar_image_url ? (
                      <img alt="" src={player.avatar_image_url} />
                    ) : (
                      <span aria-hidden="true">{player.seat}</span>
                    )}
                  </span>
                  <span className="game-player-identity">
                    <strong>
                      {player.seat} 号 · {player.name}
                    </strong>
                    <small title={player.profile_id ?? undefined}>
                      {player.profile_id ?? "无玩家资料快照"}
                    </small>
                  </span>
                  <span className="game-player-role">
                    <strong>{player.role ?? "未公开"}</strong>
                    <small>{player.model ?? "模型未公开"}</small>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <PanelEmpty text="没有可显示的玩家快照。" />
          )}
        </section>
      </div>

      <section aria-labelledby="game-rounds-title" className="game-detail-panel">
        <PanelHeading
          eyebrow="ROUND SUMMARY"
          id="game-rounds-title"
          meta={`${game.rounds.length} 轮`}
          title="公开轮次摘要"
        />
        {game.rounds.length > 0 ? (
          <ol className="game-round-list">
            {game.rounds.map((round) => (
              <RoundItem key={round.number} round={round} />
            ))}
          </ol>
        ) : (
          <PanelEmpty text="该对局还没有公开轮次摘要。" />
        )}
      </section>

      <section aria-labelledby="game-events-title" className="game-detail-panel">
        <PanelHeading
          eyebrow="RECENT EVENTS"
          id="game-events-title"
          meta={`最近 ${game.recent_events.length} / ${game.diagnostics.event_count} 条`}
          title="事件时间线"
        />
        <p className="game-events-boundary">
          {revealsTerminalMetadata
            ? "仅显示事件元数据，不包含 payload、提示词或模型原始响应。"
            : "对局未终局或仍可恢复，事件元数据暂不公开。"}
        </p>
        {game.recent_events.length > 0 ? (
          <ol aria-label="最近事件" className="game-event-list">
            {game.recent_events.map((event) => (
              <EventItem event={event} key={`${event.run_id}-${event.event_id}`} />
            ))}
          </ol>
        ) : (
          <PanelEmpty
            text={
              revealsTerminalMetadata
                ? "没有持久化事件元数据。"
                : "对局终局后才会公开事件元数据。"
            }
          />
        )}
      </section>
    </div>
  );
}

function DebugPanel({
  canReadDebug,
  debugError,
  debugPending,
  debugRequested,
  gameError,
  onRequest,
  onRetry,
  runErrors,
}: {
  canReadDebug: boolean;
  debugError: Error | null;
  debugPending: boolean;
  debugRequested: boolean;
  gameError: string | null;
  onRequest: () => void;
  onRetry: () => unknown;
  runErrors: Array<{ run_id: string; error: string }>;
}) {
  if (!canReadDebug) {
    return (
      <section aria-label="受限错误诊断" className="game-debug-panel is-restricted">
        <strong>该对局包含错误标记</strong>
        <p>错误原文需要 games.debug.read 权限；基础对局详情仍可正常查看。</p>
      </section>
    );
  }
  if (!debugRequested) {
    return (
      <section aria-label="受限错误诊断" className="game-debug-panel">
        <strong>受限错误诊断</strong>
        <p>
          按需读取经过脱敏的错误分类；最多展示最近 20 条，读取行为会进入审计日志。
        </p>
        <button onClick={onRequest} type="button">
          加载受限错误摘要
        </button>
      </section>
    );
  }
  if (debugPending) {
    return (
      <section aria-live="polite" className="game-debug-panel" role="status">
        <strong>正在读取受限错误摘要...</strong>
      </section>
    );
  }
  if (debugError) {
    return (
      <section aria-live="assertive" className="game-debug-panel is-error" role="alert">
        <strong>错误摘要暂时不可用</strong>
        <p>{debugError.message}</p>
        <button onClick={() => void onRetry()} type="button">重试错误摘要</button>
      </section>
    );
  }
  if (!gameError && runErrors.length === 0) {
    return (
      <section aria-label="错误诊断" className="game-debug-panel is-clean">
        <strong>未记录运行错误</strong>
        <p>受限错误摘要已检查。</p>
      </section>
    );
  }
  return (
    <section aria-labelledby="game-debug-title" className="game-debug-panel is-error">
      <strong id="game-debug-title">受限错误摘要</strong>
      <p>仅展示最近最多 20 条脱敏错误，更早记录不在本页显示。</p>
      {gameError ? <p>{gameError}</p> : null}
      {runErrors.length > 0 ? (
        <ul>
          {runErrors.map((item) => (
            <li key={item.run_id}>
              <code>{item.run_id}</code>
              <span>{item.error}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function RunItem({ run }: { run: AdminGameRun }) {
  return (
    <li>
      <div>
        <code>{run.run_id}</code>
        <span className={`run-status-badge is-${run.status}`}>
          {RUN_STATUS_LABELS[run.status]}
        </span>
        {run.has_error ? <span className="game-error-flag">有错误</span> : null}
      </div>
      <dl>
        <div>
          <dt>模型</dt>
          <dd>
            {run.villager_model && run.werewolf_model
              ? `${run.villager_model} / ${run.werewolf_model}`
              : "模型未公开"}
          </dd>
        </div>
        <div>
          <dt>事件</dt>
          <dd>{run.event_count}</dd>
        </div>
        <div>
          <dt>上限</dt>
          <dd>{run.max_rounds} 轮</dd>
        </div>
        <div>
          <dt>开始</dt>
          <dd>{formatDateTime(run.started_at ?? run.created_at)}</dd>
        </div>
        <div>
          <dt>结束</dt>
          <dd>{formatDateTime(run.completed_at)}</dd>
        </div>
      </dl>
    </li>
  );
}

function RoundItem({ round }: { round: AdminGameRound }) {
  const voteEntries = Object.entries(round.votes);
  return (
    <li>
      <div className="game-round-marker" aria-hidden="true">{round.number}</div>
      <div className="game-round-body">
        <header>
          <strong>第 {round.number} 轮</strong>
          <span className={round.success ? "is-success" : "is-failed"}>
            {round.success ? "完成" : "未完成"}
          </span>
        </header>
        <p>{round.public_summary || "本轮没有公开摘要。"}</p>
        <div className="game-round-facts">
          <RoundFact label="夜间死亡" value={formatDeaths(round.night_deaths)} />
          <RoundFact label="白天死亡" value={formatDeaths(round.day_deaths)} />
          <RoundFact label="放逐" value={displayValue(round.exiled)} />
          <RoundFact label="警长" value={displayValue(round.sheriff_elected ?? round.sheriff)} />
          <RoundFact label="猎人开枪" value={displayValue(round.hunter_shot)} />
          <RoundFact label="狼人自爆" value={displayValue(round.werewolf_self_exploded)} />
          <RoundFact
            label="最新票型"
            value={
              voteEntries.length > 0
                ? voteEntries.map(([voter, target]) => `${voter}→${target}`).join("、")
                : "—"
            }
          />
        </div>
      </div>
    </li>
  );
}

function RoundFact({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function EventItem({ event }: { event: AdminGameEvent }) {
  return (
    <li>
      <span className="game-event-index">#{event.event_id}</span>
      <span className="game-event-main">
        <strong>{event.type}</strong>
        <small>
          {event.round ? `第 ${event.round} 轮` : "全局"}
          {event.phase ? ` · ${event.phase}` : ""}
          {event.actor ? ` · ${event.actor}` : ""}
          {event.action ? ` · ${event.action}` : ""}
        </small>
      </span>
      <code title={event.run_id}>{event.run_id}</code>
      <time dateTime={event.created_at}>{formatDateTime(event.created_at)}</time>
    </li>
  );
}

function PanelHeading({
  eyebrow,
  id,
  meta,
  title,
}: {
  eyebrow: string;
  id: string;
  meta: string;
  title: string;
}) {
  return (
    <header className="game-panel-heading">
      <div>
        <span>{eyebrow}</span>
        <h2 id={id}>{title}</h2>
      </div>
      <small>{meta}</small>
    </header>
  );
}

function PanelEmpty({ text }: { text: string }) {
  return <p className="game-panel-empty">{text}</p>;
}

function GameDetailError({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => unknown;
}) {
  const notFound = isAdminApiError(error, 404);
  return (
    <section className="game-detail-load-error" role="alert">
      <span className="page-kicker">GAME DIAGNOSTICS</span>
      <h1>{notFound ? "对局不存在" : "无法读取对局详情"}</h1>
      <p>{error.message}</p>
      {isAdminApiError(error) && error.requestId ? (
        <small>请求编号：{error.requestId}</small>
      ) : null}
      <div>
        <Link to="/operations/games">返回对局记录</Link>
        {!notFound ? (
          <button onClick={() => void onRetry()} type="button">重新加载</button>
        ) : null}
      </div>
    </section>
  );
}

function formatDeaths(deaths: AdminGameDeath[]) {
  return deaths.length > 0
    ? deaths
        .map((death) => {
          const details = [death.cause, death.source].filter(Boolean);
          return details.length > 0
            ? `${death.player}（${details.join(" / ")}）`
            : death.player;
        })
        .join("、")
    : "—";
}
