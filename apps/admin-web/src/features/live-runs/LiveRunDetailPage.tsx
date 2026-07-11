import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { useAdminSession } from "@/features/auth/session-context";
import {
  controlAdminLiveRun,
  getAdminLiveRun,
  getAdminLiveRunDebug,
} from "@/features/live-runs/api";
import {
  formatLiveRunDateTime,
  LIVE_RUN_STATUS_LABELS,
  LIVE_RUN_WORKER_LABELS,
  liveRunDetailRefreshInterval,
} from "@/features/live-runs/presentation";
import { adminLiveRunKeys } from "@/features/live-runs/query-keys";
import type {
  AdminLiveRunEvent,
  AdminLiveRunControlAction,
  AdminLiveRunVoiceCounts,
} from "@/features/live-runs/types";

export default function LiveRunDetailPage() {
  const { runId } = useParams();
  const { session } = useAdminSession();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [debugRequestedFor, setDebugRequestedFor] = useState<string | null>(null);
  const [controlAction, setControlAction] =
    useState<AdminLiveRunControlAction | null>(null);
  const [controlNotice, setControlNotice] = useState<string | null>(null);
  const debugRequested = Boolean(runId && debugRequestedFor === runId);
  const canReadDebug = Boolean(
    session?.permissions.includes("*") ||
      session?.permissions.includes("runs.debug.read"),
  );
  const canReadGames = Boolean(
    session?.permissions.includes("*") ||
      session?.permissions.includes("games.read"),
  );
  const canControl = Boolean(
    session?.permissions.includes("*") ||
      session?.permissions.includes("runs.control"),
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
  const controlMutation = useMutation({
    mutationFn: ({
      action,
      reason,
    }: {
      action: AdminLiveRunControlAction;
      reason: string;
    }) =>
      controlAdminLiveRun(
        runId!,
        action,
        reason,
        session?.csrf_token ?? "",
      ),
    onSuccess: async (result) => {
      setControlAction(null);
      await queryClient.invalidateQueries({ queryKey: adminLiveRunKeys.all });
      if (result.action === "resume") {
        void navigate(`/operations/runs/${encodeURIComponent(result.run_id)}`);
        return;
      }
      setControlNotice(
        result.run_status === "canceled"
          ? "Worker 租约已过期，失联运行已安全终止。"
          : runQuery.data?.worker_state === "stale"
            ? "停止请求已持久化；若租约仍过期，当前 API Worker 会安全接管并终止运行。"
          : "停止请求已提交；运行会在下一个安全事件边界结束。",
      );
      await runQuery.refetch();
    },
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
        活跃运行每 5 秒刷新；Worker 状态来自数据库租约心跳，最近活动来自持久化事件。
      </p>

      {canControl ? (
        <RunControlPanel
          action={controlAction}
          error={controlMutation.isError ? controlMutation.error : null}
          notice={controlNotice}
          onCancel={() => {
            setControlAction(null);
            controlMutation.reset();
          }}
          onOpen={(action) => {
            setControlNotice(null);
            controlMutation.reset();
            setControlAction(action);
          }}
          onSubmit={(reason) => {
            if (controlAction) {
              controlMutation.mutate({ action: controlAction, reason });
            }
          }}
          pending={controlMutation.isPending}
          run={run}
        />
      ) : null}

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

function RunControlPanel({
  action,
  error,
  notice,
  onCancel,
  onOpen,
  onSubmit,
  pending,
  run,
}: {
  action: AdminLiveRunControlAction | null;
  error: Error | null;
  notice: string | null;
  onCancel: () => void;
  onOpen: (action: AdminLiveRunControlAction) => void;
  onSubmit: (reason: string) => void;
  pending: boolean;
  run: import("@/features/live-runs/types").AdminLiveRunDetail;
}) {
  const [reason, setReason] = useState("");
  const canStop =
    (run.status === "queued" || run.status === "running") &&
    run.stop_requested_at === null;
  const canResume =
    (run.status === "failed" ||
      run.status === "canceled" ||
      run.worker_state === "stale") &&
    run.game?.resumable === true;

  return (
    <section aria-label="运行控制" className="live-run-control-panel">
      <div>
        <span>RUNTIME CONTROL</span>
        <strong>安全运行控制</strong>
        <p>停止不会删除对局；失联运行可通过 fencing token 安全接管检查点。</p>
        <small>
          {LIVE_RUN_WORKER_LABELS[run.worker_state]}
          {run.worker_heartbeat_at
            ? ` · 心跳 ${formatLiveRunDateTime(run.worker_heartbeat_at)}`
            : ""}
          {run.recovery_attempts ? ` · 自动恢复 ${run.recovery_attempts} 次` : ""}
        </small>
        {run.recovery_not_before &&
        run.worker_state === "stale" &&
        !run.recovery_exhausted ? (
          <small>
            下次自动认领不早于 {formatLiveRunDateTime(run.recovery_not_before)}
          </small>
        ) : null}
        {run.recovery_exhausted ? (
          <small className="live-run-stale">自动恢复已耗尽，需要人工处理</small>
        ) : null}
      </div>
      <div className="live-run-control-actions">
        {run.stop_requested_at ? (
          <span className="live-run-stop-pending" role="status">
            停止请求已提交
          </span>
        ) : null}
        {canStop ? (
          <button
            className="admin-danger-button"
            onClick={() => {
              setReason("");
              onOpen("stop");
            }}
            type="button"
          >
            停止运行
          </button>
        ) : null}
        {canResume ? (
          <button
            className="admin-primary-button"
            onClick={() => {
              setReason("");
              onOpen("resume");
            }}
            type="button"
          >
            从检查点恢复
          </button>
        ) : null}
      </div>
      {notice ? <p className="live-run-control-notice">{notice}</p> : null}
      {action ? (
        <div className="live-run-control-confirmation" role="group">
          <label htmlFor="live-run-control-reason">操作原因</label>
          <textarea
            autoFocus
            id="live-run-control-reason"
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
            placeholder={
              action === "stop"
                ? "说明停止原因（至少 3 个字符）"
                : "说明恢复原因（至少 3 个字符）"
            }
            value={reason}
          />
          <p>
            {action === "stop"
              ? "确认后将发出协作取消信号，当前模型请求可能需要等待返回。"
              : run.worker_state === "stale"
                ? "确认后将夺取过期租约并复用当前运行；旧 Worker 的后续写入会被拒绝。"
                : "确认后将创建新的运行，原运行及审计记录保持不变。"}
          </p>
          {error ? <div role="alert">{error.message}</div> : null}
          <div>
            <button disabled={pending} onClick={onCancel} type="button">
              取消
            </button>
            <button
              className={
                action === "stop"
                  ? "admin-danger-button"
                  : "admin-primary-button"
              }
              disabled={pending || reason.trim().length < 3}
              onClick={() => onSubmit(reason.trim())}
              type="button"
            >
              {pending
                ? "提交中..."
                : action === "stop"
                  ? "确认停止"
                  : "确认恢复"}
            </button>
          </div>
        </div>
      ) : null}
    </section>
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
