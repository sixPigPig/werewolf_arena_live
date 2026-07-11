import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { useAdminSession } from "@/features/auth/session-context";
import {
  getAdminLiveRun,
  getAdminLiveRunDebug,
} from "@/features/live-runs/api";
import {
  formatLiveRunDateTime,
  LIVE_RUN_STATUS_LABELS,
  liveRunDetailRefreshInterval,
} from "@/features/live-runs/presentation";
import { adminLiveRunKeys } from "@/features/live-runs/query-keys";
import type {
  AdminLiveRunEvent,
  AdminLiveRunVoiceCounts,
} from "@/features/live-runs/types";

export default function LiveRunDetailPage() {
  const { runId } = useParams();
  const { session } = useAdminSession();
  const [debugRequestedFor, setDebugRequestedFor] = useState<string | null>(null);
  const debugRequested = Boolean(runId && debugRequestedFor === runId);
  const canReadDebug = Boolean(
    session?.permissions.includes("*") ||
      session?.permissions.includes("runs.debug.read"),
  );
  const canReadGames = Boolean(
    session?.permissions.includes("*") ||
      session?.permissions.includes("games.read"),
  );
  const runQuery = useQuery({
    enabled: Boolean(runId),
    queryFn: ({ signal }) => getAdminLiveRun(runId!, signal),
    queryKey: adminLiveRunKeys.detail(runId ?? "missing"),
    refetchInterval: (query) =>
      liveRunDetailRefreshInterval(query.state.data?.status),
  });
  const debugQuery = useQuery({
    enabled: Boolean(
      runId && canReadDebug && runQuery.isSuccess && debugRequested,
    ),
    queryFn: ({ signal }) => getAdminLiveRunDebug(runId!, signal),
    queryKey: adminLiveRunKeys.debug(runId ?? "missing"),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });

  if (runQuery.isPending) {
    return (
      <div aria-live="polite" className="game-detail-loading" role="status">
        <span />
        正在读取运行监控...
      </div>
    );
  }

  if (runQuery.isError || !runQuery.data) {
    return (
      <RunDetailError
        error={runQuery.error ?? new Error("运行响应为空")}
        onRetry={runQuery.refetch}
      />
    );
  }

  const run = runQuery.data;
  const revealsEventIdentity =
    run.status === "completed" && run.game?.terminal === true;

  return (
    <div className="admin-page live-run-detail-page">
      <Link className="game-back-link" to="/operations/runs">
        ← 返回运行监控
      </Link>
      <header className="page-heading game-detail-heading">
        <div>
          <span className="page-kicker">RUN OBSERVABILITY</span>
          <h1>{run.run_id}</h1>
          <p>Session · {run.session_id}</p>
        </div>
        <div className="game-detail-actions">
          <span className={`run-status-badge is-${run.status}`}>
            {LIVE_RUN_STATUS_LABELS[run.status]}
          </span>
          {run.is_stale ? (
            <span className="live-run-stale-badge">可能失联</span>
          ) : null}
          <button
            className="admin-secondary-button"
            disabled={runQuery.isFetching}
            onClick={() => void runQuery.refetch()}
            type="button"
          >
            {runQuery.isFetching ? "刷新中" : "刷新"}
          </button>
        </div>
      </header>

      <p className="live-run-freshness-note">
        活跃运行每 5 秒刷新；最近活动是数据库持久化时间，不是进程心跳或健康检查。
      </p>

      <section aria-label="运行概览" className="game-detail-metrics">
        <article>
          <span>运行状态 / 胜方</span>
          <strong>{LIVE_RUN_STATUS_LABELS[run.status]}</strong>
          <small>{run.winner ?? "尚无终局结果"}</small>
        </article>
        <article>
          <span>事件</span>
          <strong>{run.event_count}</strong>
          <small>最近活动 {formatLiveRunDateTime(run.last_activity_at)}</small>
        </article>
        <article>
          <span>语音</span>
          <strong>
            {run.voice_counts.complete} / {run.voice_counts.total}
          </strong>
          <small>失败 {run.voice_counts.failed} 条</small>
        </article>
        <article>
          <span>轮次上限</span>
          <strong>{run.max_rounds}</strong>
          <small>{run.rule_set?.name ?? "规则快照不可用"}</small>
        </article>
      </section>

      {run.has_error || run.voice_counts.failed > 0 || canReadDebug ? (
        <RunDebugPanel
          canReadDebug={canReadDebug}
          debugError={debugQuery.isError ? debugQuery.error : null}
          debugPending={debugQuery.isPending && debugQuery.fetchStatus !== "idle"}
          debugRequested={debugRequested}
          onRequest={() => setDebugRequestedFor(runId ?? null)}
          onRetry={debugQuery.refetch}
          runError={debugQuery.data?.run_error ?? null}
          truncated={debugQuery.data?.truncated ?? false}
          voiceErrorTotal={debugQuery.data?.voice_error_total ?? 0}
          voiceErrors={debugQuery.data?.voice_errors ?? []}
        />
      ) : null}

      <div className="game-detail-grid">
        <section aria-labelledby="live-run-models-title" className="game-detail-panel">
          <PanelHeading
            eyebrow="MODEL CONFIGURATION"
            id="live-run-models-title"
            meta="安全摘要"
            title="模型配置"
          />
          <dl className="live-run-definition-list">
            <div>
              <dt>好人阵营</dt>
              <dd>{run.villager_model ?? "终局后显示"}</dd>
            </div>
            <div>
              <dt>狼人阵营</dt>
              <dd>{run.werewolf_model ?? "终局后显示"}</dd>
            </div>
            <div>
              <dt>规则 ID</dt>
              <dd>{run.rule_set?.id ?? "—"}</dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{formatLiveRunDateTime(run.created_at)}</dd>
            </div>
            <div>
              <dt>开始时间</dt>
              <dd>{formatLiveRunDateTime(run.started_at)}</dd>
            </div>
            <div>
              <dt>结束时间</dt>
              <dd>{formatLiveRunDateTime(run.completed_at)}</dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="live-run-game-title" className="game-detail-panel">
          <PanelHeading
            eyebrow="ASSOCIATED GAME"
            id="live-run-game-title"
            meta={run.game ? "已关联" : "未持久化"}
            title="关联对局"
          />
          {run.game ? (
            <div className="live-run-game-card">
              <strong>{run.session_id}</strong>
              <p>
                {run.game.status === "complete" ? "已完成" : "部分记录"}
                {run.game.resumable ? " · 可恢复" : " · 不可恢复"}
              </p>
              {canReadGames ? (
                <Link
                  className="admin-secondary-link"
                  to={`/operations/games/${encodeURIComponent(run.session_id)}`}
                >
                  查看关联对局
                </Link>
              ) : (
                <small>需要 games.read 权限查看对局详情</small>
              )}
            </div>
          ) : (
            <p className="game-panel-empty">
              关联对局尚未持久化；运行详情仍可独立查看。
            </p>
          )}
        </section>
      </div>

      <section aria-labelledby="live-run-voice-title" className="game-detail-panel">
        <PanelHeading
          eyebrow="VOICE PIPELINE"
          id="live-run-voice-title"
          meta={`${run.voice_counts.total} 条`}
          title="语音计数"
        />
        <VoiceCounts counts={run.voice_counts} />
      </section>

      <section aria-labelledby="live-run-events-title" className="game-detail-panel">
        <PanelHeading
          eyebrow="RECENT EVENTS"
          id="live-run-events-title"
          meta={`最近 ${run.recent_events.length} / ${run.event_count} 条`}
          title="运行时序"
        />
        <p className="game-events-boundary">
          {revealsEventIdentity
            ? "仅显示事件元数据，不包含 payload、提示词或模型原始响应。"
            : "运行或对局尚未安全终局，活动已归类以保护未终局身份，actor/action 已隐藏。"}
        </p>
        {run.recent_events.length > 0 ? (
          <ol aria-label="最近运行事件" className="game-event-list">
            {run.recent_events.map((event) => (
              <RunEventItem event={event} key={event.event_id} />
            ))}
          </ol>
        ) : (
          <p className="game-panel-empty">没有持久化事件元数据。</p>
        )}
      </section>
    </div>
  );
}

function RunDebugPanel({
  canReadDebug,
  debugError,
  debugPending,
  debugRequested,
  onRequest,
  onRetry,
  runError,
  truncated,
  voiceErrorTotal,
  voiceErrors,
}: {
  canReadDebug: boolean;
  debugError: Error | null;
  debugPending: boolean;
  debugRequested: boolean;
  onRequest: () => void;
  onRetry: () => unknown;
  runError: string | null;
  truncated: boolean;
  voiceErrorTotal: number;
  voiceErrors: Array<{ utterance_id: string; error: string }>;
}) {
  if (!canReadDebug) {
    return (
      <section aria-label="受限运行错误" className="game-debug-panel is-restricted">
        <strong>该运行包含错误标记</strong>
        <p>错误摘要需要 runs.debug.read 权限；基础运行详情仍可正常查看。</p>
      </section>
    );
  }
  if (!debugRequested) {
    return (
      <section aria-label="受限运行错误" className="game-debug-panel">
        <strong>受限错误诊断</strong>
        <p>按需读取脱敏错误分类；读取行为会进入审计日志。</p>
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
        <button onClick={() => void onRetry()} type="button">
          重试错误摘要
        </button>
      </section>
    );
  }
  if (!runError && voiceErrorTotal === 0) {
    return (
      <section aria-label="运行错误诊断" className="game-debug-panel is-clean">
        <strong>未记录运行错误</strong>
        <p>受限错误摘要已检查。</p>
      </section>
    );
  }
  return (
    <section aria-label="运行错误诊断" className="game-debug-panel is-error">
      <strong>受限错误摘要</strong>
      <p>
        语音错误共 {voiceErrorTotal} 条
        {truncated
          ? "；部分错误未显示（仅提供最近最多 20 条可分类摘要）"
          : ""}
        。
      </p>
      {runError ? <p>{runError}</p> : null}
      {voiceErrors.length > 0 ? (
        <ul>
          {voiceErrors.map((item) => (
            <li key={item.utterance_id}>
              <code>{item.utterance_id}</code>
              <span>{item.error}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function VoiceCounts({ counts }: { counts: AdminLiveRunVoiceCounts }) {
  const entries = [
    ["待处理", counts.pending],
    ["合成中", counts.synthesizing],
    ["已完成", counts.complete],
    ["失败", counts.failed],
    ["已取消", counts.canceled],
    ["其他", counts.other],
  ];
  return (
    <dl className="live-run-voice-grid">
      {entries.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function RunEventItem({ event }: { event: AdminLiveRunEvent }) {
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
      <time dateTime={event.created_at}>{formatLiveRunDateTime(event.created_at)}</time>
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

function RunDetailError({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => unknown;
}) {
  const notFound = isAdminApiError(error, 404);
  return (
    <section className="game-detail-load-error" role="alert">
      <span className="page-kicker">RUN OBSERVABILITY</span>
      <h1>{notFound ? "运行不存在" : "无法读取运行详情"}</h1>
      <p>{error.message}</p>
      {isAdminApiError(error) && error.requestId ? (
        <small>请求编号：{error.requestId}</small>
      ) : null}
      <div>
        <Link to="/operations/runs">返回运行监控</Link>
        {!notFound ? (
          <button onClick={() => void onRetry()} type="button">
            重新加载
          </button>
        ) : null}
      </div>
    </section>
  );
}
