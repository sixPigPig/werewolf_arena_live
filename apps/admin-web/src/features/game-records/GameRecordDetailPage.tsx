import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { useAdminSession } from "@/features/auth/session-context";
import {
  getAdminGame,
  getAdminGameDebug,
  getAdminGameModelRequest,
  getAdminGameQualityIssues,
  listAdminGameModelRequests,
  retryAdminGameQualityEvaluation,
} from "@/features/game-records/api";
import {
  actionLabel,
  displayValue,
  eventTypeLabel,
  formatDateTime,
  GAME_STATUS_LABELS,
  personalityLabel,
  phaseLabel,
  qualityActualLabel,
  qualityChannelLabel,
  qualityCodeLabel,
  qualityGateLabel,
  qualityIssueLabel,
  qualityPolicyLabel,
  qualitySeverityLabel,
  qualitySourceStatusLabel,
  RUN_STATUS_LABELS,
} from "@/features/game-records/presentation";
import { adminGameKeys } from "@/features/game-records/query-keys";
import type {
  AdminGameDeath,
  AdminGameEvent,
  AdminGameModelRequestDetail,
  AdminGameModelRequestSummary,
  AdminGameQualityEvaluation,
  AdminGameQualityIssues,
  AdminGameRound,
  AdminGameRun,
} from "@/features/game-records/types";
import type {
  AdminGameP2Quality,
  AdminPublicOutcome,
} from "@/features/p2-quality/types";

export default function GameRecordDetailPage() {
  const { sessionId } = useParams();
  const queryClient = useQueryClient();
  const [debugRequestedFor, setDebugRequestedFor] = useState<string | null>(
    null,
  );
  const debugRequested = Boolean(
    sessionId && debugRequestedFor === sessionId,
  );
  const [qualityIssuesRequestedFor, setQualityIssuesRequestedFor] = useState<
    string | null
  >(null);
  const [selectedModelRequestId, setSelectedModelRequestId] = useState<
    string | null
  >(null);
  const closeModelRequestDrawer = useCallback(
    () => setSelectedModelRequestId(null),
    [],
  );
  const qualityIssuesRequested = Boolean(
    sessionId && qualityIssuesRequestedFor === sessionId,
  );
  const { session } = useAdminSession();
  const canReadDebug = Boolean(
    session?.permissions.includes("*") ||
      session?.permissions.includes("games.debug.read"),
  );
  const canReadRuns = Boolean(
    session?.permissions.includes("*") ||
      session?.permissions.includes("runs.read"),
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
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const qualityIssuesQuery = useQuery({
    enabled: Boolean(
      sessionId &&
        canReadDebug &&
        gameQuery.isSuccess &&
        qualityIssuesRequested,
    ),
    queryFn: ({ signal }) => getAdminGameQualityIssues(sessionId!, signal),
    queryKey: adminGameKeys.qualityIssues(sessionId ?? "missing"),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const modelRequestsQuery = useQuery({
    enabled: Boolean(sessionId && canReadDebug && gameQuery.isSuccess),
    queryFn: ({ signal }) => listAdminGameModelRequests(sessionId!, signal),
    queryKey: adminGameKeys.modelRequests(sessionId ?? "missing"),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const modelRequestDetailQuery = useQuery({
    enabled: Boolean(sessionId && canReadDebug && selectedModelRequestId),
    queryFn: ({ signal }) =>
      getAdminGameModelRequest(sessionId!, selectedModelRequestId!, signal),
    queryKey: adminGameKeys.modelRequest(
      sessionId ?? "missing",
      selectedModelRequestId ?? "missing",
    ),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const qualityRetry = useMutation({
    mutationFn: () =>
      retryAdminGameQualityEvaluation(
        sessionId!,
        session?.csrf_token ?? "",
      ),
    onSuccess: async () => {
      setQualityIssuesRequestedFor(null);
      await queryClient.invalidateQueries({
        queryKey: adminGameKeys.detail(sessionId ?? "missing"),
      });
    },
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
          <span className="page-kicker">对局诊断</span>
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

      <GameP2QualityPanel quality={game.p2_quality} />

      <GameP3QualityPanel
        canReadDebug={canReadDebug}
        issues={qualityIssuesQuery.data ?? null}
        issuesError={qualityIssuesQuery.isError}
        issuesPending={
          qualityIssuesQuery.isPending && qualityIssuesQuery.fetchStatus !== "idle"
        }
        issuesRequested={qualityIssuesRequested}
        onRequestIssues={() => setQualityIssuesRequestedFor(sessionId ?? null)}
        onRetryEvaluation={() => qualityRetry.mutate()}
        onRetryIssues={() => void qualityIssuesQuery.refetch()}
        quality={game.quality_evaluation}
        retryError={qualityRetry.isError}
        retryPending={qualityRetry.isPending}
      />

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
            eyebrow="运行记录"
            id="game-runs-title"
            meta={`${game.runs.length} 次`}
            title="运行记录"
          />
          {game.runs.length > 0 ? (
            <ul aria-label="运行记录" className="game-run-list">
              {game.runs.map((run) => (
                <RunItem canReadRuns={canReadRuns} key={run.run_id} run={run} />
              ))}
            </ul>
          ) : (
            <PanelEmpty text="没有关联的运行记录。" />
          )}
        </section>

        <section aria-labelledby="game-players-title" className="game-detail-panel">
          <PanelHeading
            eyebrow="阵容快照"
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
                    <small>
                      {personalityLabel(player.personality_id)}
                      {player.tags.length > 0 ? ` · ${player.tags.join("、")}` : ""}
                    </small>
                    <small title={player.profile_id ?? undefined}>
                      {player.profile_id ? `档案：${player.profile_id}` : "无玩家资料快照"}
                    </small>
                  </span>
                  <span className="game-player-role">
                    <strong>{player.role ?? "未公开"}</strong>
                    <small>{player.model ?? "模型未记录"}</small>
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
          eyebrow="轮次摘要"
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
        <ModelRequestIndex
          canReadDebug={canReadDebug}
          error={modelRequestsQuery.isError ? modelRequestsQuery.error : null}
          items={modelRequestsQuery.data?.items ?? []}
          onOpen={setSelectedModelRequestId}
          onRetry={() => void modelRequestsQuery.refetch()}
          pending={modelRequestsQuery.isPending}
        />
      </section>

      <PublicOutcomePanel quality={game.p2_quality} />

      <section aria-labelledby="game-events-title" className="game-detail-panel">
        <PanelHeading
          eyebrow="最近事件"
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
      {selectedModelRequestId ? (
        <ModelRequestDrawer
          error={
            modelRequestDetailQuery.isError
              ? modelRequestDetailQuery.error
              : null
          }
          onClose={closeModelRequestDrawer}
          pending={modelRequestDetailQuery.isPending}
          request={modelRequestDetailQuery.data ?? null}
          requestId={selectedModelRequestId}
        />
      ) : null}
    </div>
  );
}

function GameP2QualityPanel({ quality }: { quality: AdminGameP2Quality }) {
  return (
    <section aria-labelledby="game-p2-title" className="game-detail-panel">
      <PanelHeading
        eyebrow="P2 质量"
        id="game-p2-title"
        meta={p2StatusLabel(quality.data_status)}
        title="P2 对局质量"
      />
      {quality.data_status === "legacy" ||
      quality.data_status === "unavailable" ? (
        <PanelEmpty
          text={
            quality.data_status === "legacy"
              ? "旧对局没有完整 P2 数据，质量门槛显示为不可用而不是通过。"
              : "该对局没有可用的 P2 质量数据。"
          }
        />
      ) : (
        <>
          <div className="game-detail-metrics game-quality-metrics">
            <article>
              <span>阵容模式 / 修复</span>
              <strong>{qualityPolicyLabel(quality.lineup_quality.policy_mode)}</strong>
              <small>
                {quality.lineup_quality.was_repaired ? "已自动修复" : "未自动修复"}
                {" · "}风格桶 {quality.lineup_quality.style_bucket_count ?? "—"}/
                {quality.lineup_quality.required_style_bucket_count ?? "—"}
              </small>
            </article>
            <article>
              <span>发言检查 / 重写</span>
              <strong>
                {quality.speech_quality.checked_count} / {quality.speech_quality.retry_count}
              </strong>
              <small>
                耗尽 {quality.speech_quality.exhausted_count} · 低新颖度窗口{" "}
                {quality.speech_quality.low_novelty_window_count}
              </small>
            </article>
            <article>
              <span>离散动作 P95</span>
              <strong>
                {quality.performance.discrete_action_p95_ms === null
                  ? "样本不足"
                  : `${quality.performance.discrete_action_p95_ms} ms`}
              </strong>
              <small>
                样本 {quality.performance.discrete_action_sample_count} · 最大值{" "}
                {quality.performance.discrete_action_max_ms ?? "—"} ms
              </small>
            </article>
            <article>
              <span>规范化 / 无效</span>
              <strong>
                {quality.choice_normalization.seat_alias_count} /{" "}
                {quality.choice_normalization.invalid_count}
              </strong>
              <small>不展示原始选择，只展示安全聚合</small>
            </article>
          </div>
          {quality.lineup_quality.violations.length > 0 ? (
            <ul aria-label="阵容质量违规" className="game-quality-list">
              {quality.lineup_quality.violations.map((violation, index) => (
                <li key={`${violation.code}-${index}`}>
                  <strong title={violation.code}>{qualityCodeLabel(violation.code)}</strong>
                  <span>
                    {qualitySeverityLabel(violation.severity)} · {violation.count}/{violation.limit} · 座位{" "}
                    {violation.seat_numbers.join("、") || "—"}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          <ul aria-label="P2 质量门槛" className="game-quality-list">
            {quality.quality_gates.map((gate) => (
              <li key={gate.gate}>
                <strong>
                  {qualityGateLabel(gate.gate)} · {gateStatusLabel(gate.status)}
                </strong>
                <span>
                  <span title={gate.code}>{qualityCodeLabel(gate.code)}</span>
                  {" · "}阈值 {gate.threshold ?? "—"} · 实际 {qualityActualLabel(gate.actual)}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function GameP3QualityPanel({
  canReadDebug,
  issues,
  issuesError,
  issuesPending,
  issuesRequested,
  onRequestIssues,
  onRetryEvaluation,
  onRetryIssues,
  quality,
  retryError,
  retryPending,
}: {
  canReadDebug: boolean;
  issues: AdminGameQualityIssues | null;
  issuesError: boolean;
  issuesPending: boolean;
  issuesRequested: boolean;
  onRequestIssues: () => void;
  onRetryEvaluation: () => void;
  onRetryIssues: () => void;
  quality: AdminGameQualityEvaluation;
  retryError: boolean;
  retryPending: boolean;
}) {
  const canRetry =
    canReadDebug &&
    (quality.evaluation_status === "failed" ||
      quality.evaluation_status === "not_scheduled" ||
      quality.data_status === "partial" ||
      quality.data_status === "legacy");
  return (
    <section aria-labelledby="game-p3-title" className="game-detail-panel">
      <div className="game-quality-heading">
        <div>
          <span className="page-kicker">P3 质量评估</span>
          <h2 id="game-p3-title">P3 质量评估</h2>
          <p>
            {p3EvaluationStatusLabel(quality.evaluation_status)} · 数据
            {p3DataStatusLabel(quality.data_status)} · 版本 {quality.evaluator_version}
          </p>
        </div>
        <span className={`game-status-badge is-${quality.verdict}`}>
          {p3VerdictLabel(quality.verdict)}
        </span>
      </div>

      <dl className="game-quality-coverage" aria-label="P3 来源覆盖">
        <div><dt>状态 / 日志</dt><dd>{qualitySourceStatusLabel(quality.source_coverage.state)} / {qualitySourceStatusLabel(quality.source_coverage.logs)}</dd></div>
        <div><dt>事件</dt><dd>{qualitySourceStatusLabel(quality.source_coverage.events)}</dd></div>
        <div><dt>语音 / 字幕</dt><dd>{qualitySourceStatusLabel(quality.source_coverage.voice)} / {qualitySourceStatusLabel(quality.source_coverage.subtitles)}</dd></div>
        <div><dt>待处理 / 失败语音</dt><dd>{quality.source_coverage.pending_voice_count} / {quality.source_coverage.failed_voice_count}</dd></div>
      </dl>

      {quality.evaluation_status === "completed" ? (
        <div className="game-detail-metrics game-quality-metrics">
          <article>
            <span>事实</span>
            <strong>{ratioLabel(quality.facts.critical_recorded_count, quality.facts.critical_opportunity_count)}</strong>
            <small>
              提示词 {ratioLabel(quality.facts.prompt_included_critical_count, quality.facts.prompt_expected_critical_count)} · 矛盾 {quality.facts.deterministic_contradiction_count}
            </small>
          </article>
          <article>
            <span>结构</span>
            <strong>最长连续自爆 {quality.structure.max_consecutive_self_explosions}</strong>
            <small>
              正常辩论 {quality.structure.normal_day_debate_round_count} 轮 · 警长请求 {ratioLabel(quality.structure.sheriff_model_request_count, quality.structure.public_model_request_count)}
            </small>
          </article>
          <article>
            <span>语音</span>
            <strong>{ratioLabel(quality.voice.effective_voice_event_count, quality.voice.narratable_event_count)}</strong>
            <small>
              尾段差 {quality.voice.voice_source_event_lag ?? "—"} · 中断/补播 {quality.voice.interruption_count}/{quality.voice.replay_count}
            </small>
          </article>
          <article>
            <span>性能</span>
            <strong>
              {quality.performance.action_duration_p95_ms === null
                ? `样本不足 (${quality.performance.action_count}/20)`
                : `P95 ${quality.performance.action_duration_p95_ms} ms`}
            </strong>
            <small>
              整局 {durationLabel(quality.performance.game_duration_ms)} · 超时 {quality.performance.timeout_count} · 重试 {quality.performance.retry_count}
            </small>
          </article>
          <article>
            <span>内容</span>
            <strong>重复 {quality.content.repeated_speech_count}/{quality.content.speech_check_count}</strong>
            <small>
              重写 {quality.content.speech_rewrite_count} · 耗尽 {quality.content.speech_retry_exhausted_count} · 阵容告警 {quality.content.lineup_warning_count}
            </small>
          </article>
          <article>
            <span>安全问题</span>
            <strong>P0 {quality.issue_counts.P0} · P1 {quality.issue_counts.P1} · P2 {quality.issue_counts.P2}</strong>
            <small>问题正文和私密证据不会进入 Admin 响应</small>
          </article>
        </div>
      ) : (
        <PanelEmpty text={p3UnavailableMessage(quality)} />
      )}

      {canReadDebug ? (
        <div className="game-debug-actions">
          <button
            className="admin-secondary-button"
            disabled={issuesPending}
            onClick={onRequestIssues}
            type="button"
          >
            {issuesPending ? "读取中" : "加载安全问题坐标"}
          </button>
          {canRetry ? (
            <button
              className="admin-secondary-button"
              disabled={retryPending}
              onClick={onRetryEvaluation}
              type="button"
            >
              {retryPending ? "正在提交重试" : "重试质量评估"}
            </button>
          ) : null}
        </div>
      ) : null}
      {retryError ? <p role="alert">质量评估重试失败，请刷新状态后再试。</p> : null}

      {issuesRequested ? (
        <div aria-live="polite" className="game-debug-result">
          <h3>安全问题坐标</h3>
          <p>仅展示问题码、级别、渠道和坐标；读取行为会进入审计日志。</p>
          {issuesPending ? <PanelEmpty text="正在读取安全问题坐标..." /> : null}
          {issuesError ? (
            <div>
              <p role="alert">安全问题坐标暂时不可读取。</p>
              <button className="admin-secondary-button" onClick={onRetryIssues} type="button">重新读取</button>
            </div>
          ) : null}
          {issues && !issuesPending && !issuesError ? (
            issues.items.length > 0 ? (
              <ul aria-label="P3 安全问题坐标" className="game-quality-list">
                {issues.items.map((issue) => (
                  <li key={issue.issue_id}>
                    <strong title={issue.code}>
                      {qualitySeverityLabel(issue.severity)} · {qualityIssueLabel(issue.code)}
                    </strong>
                    <span>
                      {qualityChannelLabel(issue.channel)} · 轮次 {issue.round_number ?? "—"} · 事件 {issue.event_id ?? "—"} · 语音记录 {issue.utterance_id ?? "—"} · {issue.issue_id}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <PanelEmpty text="当前评估没有安全问题坐标。" />
            )
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function p3EvaluationStatusLabel(status: AdminGameQualityEvaluation["evaluation_status"]) {
  return {
    not_scheduled: "未调度",
    pending: "排队中",
    processing: "评估中",
    completed: "已完成",
    failed: "执行失败",
    superseded: "已被新版本替代",
  }[status];
}

function p3DataStatusLabel(status: AdminGameQualityEvaluation["data_status"]) {
  return {
    collecting: "收集中",
    available: "完整",
    partial: "部分可用",
    legacy: "旧数据",
    unavailable: "不可用",
  }[status];
}

function p3VerdictLabel(verdict: AdminGameQualityEvaluation["verdict"]) {
  return { pass: "通过", warn: "警告", fail: "失败", unavailable: "无结论" }[verdict];
}

function p3UnavailableMessage(quality: AdminGameQualityEvaluation) {
  if (quality.evaluation_status === "pending") return "质量评估正在等待 Worker 处理。";
  if (quality.evaluation_status === "processing") return "质量评估正在执行。";
  if (quality.evaluation_status === "failed") return "质量评估执行失败，不会伪装为通过。";
  if (quality.data_status === "legacy") return "旧对局尚未生成 P3 质量评估。";
  return "当前没有可用的 P3 质量评估。";
}

function ratioLabel(numerator: number, denominator: number) {
  if (denominator === 0) return "无样本";
  return `${((numerator / denominator) * 100).toFixed(1)}% (${numerator}/${denominator})`;
}

function durationLabel(value: number | null) {
  return value === null ? "—" : `${Math.round(value / 1000)} 秒`;
}

function PublicOutcomePanel({ quality }: { quality: AdminGameP2Quality }) {
  return (
    <section aria-labelledby="game-outcomes-title" className="game-detail-panel">
      <PanelHeading
        eyebrow="公开结算"
        id="game-outcomes-title"
        meta={`${quality.public_outcomes.length} 条`}
        title="公开结算链"
      />
      {quality.public_outcomes.length > 0 ? (
        <ol aria-label="公开结算链" className="game-public-outcome-list">
          {quality.public_outcomes.map((outcome) => (
            <li key={outcome.event_id}>
              <strong>
                第 {outcome.round_number} 轮 · #{outcome.sequence} ·{" "}
                {publicOutcomeLabel(outcome)}
              </strong>
              <span>
                {outcome.caused_by_event_id
                  ? `因果来源 ${outcome.caused_by_event_id}`
                  : "独立公开结算"}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <PanelEmpty
          text={
            quality.data_status === "collecting"
              ? "对局尚未终局，暂不展示公开结算链。"
              : "旧对局没有结构化公开结算链。"
          }
        />
      )}
      {quality.public_outcome_summary_mismatch_count > 0 ? (
        <p className="game-events-boundary">
          检测到 {quality.public_outcome_summary_mismatch_count} 轮摘要与结算链不一致。
        </p>
      ) : null}
    </section>
  );
}

function publicOutcomeLabel(outcome: AdminPublicOutcome) {
  const actor = outcome.actor_player_id ?? "系统";
  const target = outcome.target_player_id ?? "无目标";
  const labels: Record<AdminPublicOutcome["kind"], string> = {
    night_death: `${target}夜间出局`,
    hunter_shot: `${actor}发动猎人技能带走${target}`,
    self_explosion: `${actor}自爆`,
    exile: `${target}被放逐`,
    idiot_reveal: `${actor}翻牌免死`,
    badge_transferred: `警徽由${actor}移交给${target}`,
    badge_lost: `${actor}警徽流失`,
  };
  return labels[outcome.kind];
}

function p2StatusLabel(status: AdminGameP2Quality["data_status"]) {
  return {
    available: "数据可用",
    collecting: "采集中",
    legacy: "旧数据",
    unavailable: "不可用",
  }[status];
}

function gateStatusLabel(status: AdminGameP2Quality["quality_gates"][number]["status"]) {
  return {
    pass: "通过",
    warn: "警告",
    fail: "失败",
    unavailable: "不可用",
  }[status];
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

function RunItem({
  canReadRuns,
  run,
}: {
  canReadRuns: boolean;
  run: AdminGameRun;
}) {
  return (
    <li>
      <div>
        {canReadRuns ? (
          <Link
            className="game-run-link"
            to={`/operations/runs/${encodeURIComponent(run.run_id)}`}
          >
            <code>{run.run_id}</code>
          </Link>
        ) : (
          <code>{run.run_id}</code>
        )}
        <span className={`run-status-badge is-${run.status}`}>
          {RUN_STATUS_LABELS[run.status]}
        </span>
        {run.has_error ? <span className="game-error-flag">有错误</span> : null}
      </div>
      <dl>
        <div>
          <dt>模型</dt>
          <dd>
            {formatRunModels(run)}
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

function formatRunModels(run: AdminGameRun) {
  if (run.villager_model && run.villager_model === run.werewolf_model) {
    return run.villager_model;
  }
  return `好人：${run.villager_model ?? "未记录"} · 狼人：${run.werewolf_model ?? "未记录"}`;
}

function RoundItem({ round }: { round: AdminGameRound }) {
  const voteEntries = Object.entries(round.votes);
  const speechGroups = [
    { label: "警长竞选发言", items: round.sheriff_speeches },
    { label: "警长平票发言", items: round.sheriff_pk_speeches },
    { label: "放逐平票发言", items: round.exile_pk_speeches },
    { label: "驱逐遗言", items: round.exile_last_words ? [round.exile_last_words] : [] },
    { label: "白天发言", items: round.debate },
  ].filter((group) => group.items.length > 0);
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
          <RoundFact label="白痴翻牌" value={displayValue(round.idiot_revealed)} />
          <RoundFact
            label="狼人自爆"
            value={
              round.werewolf_self_exploded && round.day_ended_by_self_explosion
                ? `${round.werewolf_self_exploded}（白天提前结束）`
                : displayValue(round.werewolf_self_exploded)
            }
          />
          <RoundFact label="本轮存活" value={formatNames(round.players)} />
          {round.sheriff_candidates.length > 0 ? (
            <RoundFact label="上警名单" value={formatNames(round.sheriff_candidates)} />
          ) : null}
          {round.sheriff_withdrawn.length > 0 ? (
            <RoundFact label="退水名单" value={formatNames(round.sheriff_withdrawn)} />
          ) : null}
          {round.sheriff_final_candidates.length > 0 ? (
            <RoundFact label="最终候选" value={formatNames(round.sheriff_final_candidates)} />
          ) : null}
          {Object.keys(round.sheriff_votes).length > 0 ? (
            <RoundFact label="警长票型" value={formatVotes(round.sheriff_votes)} />
          ) : null}
          {round.sheriff_pk_candidates.length > 0 ? (
            <RoundFact label="平票候选" value={formatNames(round.sheriff_pk_candidates)} />
          ) : null}
          {Object.keys(round.sheriff_runoff_votes).length > 0 ? (
            <RoundFact label="加赛票型" value={formatVotes(round.sheriff_runoff_votes)} />
          ) : null}
          {round.exile_pk_candidates.length > 0 ? (
            <RoundFact label="放逐 PK 候选" value={formatNames(round.exile_pk_candidates)} />
          ) : null}
          {Object.keys(round.exile_runoff_votes).length > 0 ? (
            <RoundFact label="放逐二轮票型" value={formatVotes(round.exile_runoff_votes)} />
          ) : null}
          {round.exile_resolution_reason ? (
            <RoundFact
              label="放逐结论"
              value={formatExileResolution(round.exile_resolution_reason)}
            />
          ) : null}
          {round.sheriff_speech_order.length > 0 ? (
            <RoundFact
              label="竞选发言顺序"
              value={`${formatNames(round.sheriff_speech_order)}${round.sheriff_speech_direction ? `（${round.sheriff_speech_direction}）` : ""}`}
            />
          ) : null}
          {round.speech_order.length > 0 ? (
            <RoundFact
              label="白天发言顺序"
              value={`${formatNames(round.speech_order)}${round.speech_order_choice ? `（${round.speech_order_choice}）` : ""}`}
            />
          ) : null}
          {round.sheriff_badge_lost ? (
            <RoundFact
              label="警徽状态"
              value={round.sheriff_badge_lost_reason ? `已流失（${badgeLostReasonLabel(round.sheriff_badge_lost_reason)}）` : "已流失"}
            />
          ) : round.sheriff_badge_target ? (
            <RoundFact label="警徽移交" value={round.sheriff_badge_target} />
          ) : null}
          <RoundFact
            label="最新票型"
            value={
              voteEntries.length > 0
                ? formatVotes(round.votes)
                : "—"
            }
          />
        </div>
        {speechGroups.length > 0 ? (
          <div className="game-round-speeches">
            {speechGroups.map((group) => (
              <section key={group.label}>
                <h3>{group.label} · {group.items.length} 条</h3>
                <ol>
                  {group.items.map((speech, index) => (
                    <li key={`${speech.speaker}-${index}`}>
                      <strong>{speech.speaker}</strong>
                      <p>{speech.message}</p>
                    </li>
                  ))}
                </ol>
              </section>
            ))}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function ModelRequestIndex({
  canReadDebug,
  error,
  items,
  onOpen,
  onRetry,
  pending,
}: {
  canReadDebug: boolean;
  error: Error | null;
  items: AdminGameModelRequestSummary[];
  onOpen: (requestId: string) => void;
  onRetry: () => void;
  pending: boolean;
}) {
  if (!canReadDebug) {
    return (
      <section className="game-model-request-index is-restricted">
        <h3>模型请求记录</h3>
        <p>输入输出包含私密推理，需要 games.debug.read 权限。</p>
      </section>
    );
  }
  if (pending) {
    return (
      <section
        aria-live="polite"
        className="game-model-request-index"
        role="status"
      >
        <h3>模型请求记录</h3>
        <p>正在读取请求索引...</p>
      </section>
    );
  }
  if (error) {
    return (
      <section className="game-model-request-index is-error" role="alert">
        <h3>模型请求记录加载失败</h3>
        <p>{error.message}</p>
        <button onClick={onRetry} type="button">重新加载</button>
      </section>
    );
  }
  if (items.length === 0) {
    return (
      <section className="game-model-request-index">
        <h3>模型请求记录</h3>
        <p>该对局没有持久化的模型请求。</p>
      </section>
    );
  }
  return (
    <section className="game-model-request-index">
      <div className="game-model-request-index-heading">
        <div>
          <h3>模型请求记录</h3>
          <p>展开轮次并点击任一请求，可在右侧查看输入、输出和模型信息。</p>
        </div>
        <strong>{items.length} 次</strong>
      </div>
      <div className="game-model-request-groups">
        {groupModelRequests(items).map((group) => (
          <details key={group.key}>
            <summary>
              <span>{group.label}</span>
              <strong>{group.items.length} 次请求</strong>
            </summary>
            <div className="game-model-request-buttons">
              {group.items.map((item) => (
                <button
                  aria-label={`查看模型请求 ${item.request_id}`}
                  className={`game-model-request-button is-${item.status}`}
                  key={item.request_id}
                  onClick={() => onOpen(item.request_id)}
                  type="button"
                >
                  <span>
                    <strong>
                      {item.actor ?? "系统"} · {actionLabel(item.action)}
                    </strong>
                    <small>
                      {item.model ?? "模型未记录"}
                      {item.phase ? ` · ${phaseLabel(item.phase)}` : ""}
                    </small>
                    <code>{item.request_id}</code>
                  </span>
                  <em>{modelRequestStatusLabel(item.status)}</em>
                </button>
              ))}
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}

function ModelRequestDrawer({
  error,
  onClose,
  pending,
  request,
  requestId,
}: {
  error: Error | null;
  onClose: () => void;
  pending: boolean;
  request: AdminGameModelRequestDetail | null;
  requestId: string;
}) {
  const drawerRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("keydown", handleEscape);
      document.body.style.overflow = previousOverflow;
      opener?.focus();
    };
  }, [onClose]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      drawerRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  };

  return (
    <div
      className="game-model-request-drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        aria-labelledby="game-model-request-drawer-title"
        aria-modal="true"
        className="game-model-request-drawer"
        onKeyDown={handleKeyDown}
        ref={drawerRef}
        role="dialog"
      >
        <header>
          <div>
            <span>模型请求</span>
            <h2 id="game-model-request-drawer-title">
              {request ? `${request.actor ?? "系统"} · ${actionLabel(request.action)}` : "请求详情"}
            </h2>
            <code>{requestId}</code>
          </div>
          <button
            aria-label="关闭模型请求详情"
            onClick={onClose}
            ref={closeButtonRef}
            type="button"
          >
            ×
          </button>
        </header>
        {pending ? (
          <div aria-live="polite" className="game-model-request-drawer-state" role="status">
            正在读取输入输出...
          </div>
        ) : error ? (
          <div className="game-model-request-drawer-state is-error" role="alert">
            <strong>请求详情读取失败</strong>
            <p>{error.message}</p>
          </div>
        ) : request ? (
          <div className="game-model-request-drawer-content">
            <dl className="game-model-request-metadata">
              <div><dt>模型</dt><dd>{request.model ?? "未记录"}</dd></div>
              <div><dt>状态</dt><dd>{modelRequestStatusLabel(request.status)}</dd></div>
              <div><dt>轮次 / 阶段</dt><dd>{request.round_number === null ? "未归类" : `第 ${request.round_number} 轮`}{request.phase ? ` · ${phaseLabel(request.phase)}` : ""}</dd></div>
              <div><dt>请求尝试</dt><dd>{request.attempt_count} 次{request.invalid_attempt_count > 0 ? ` · 无效 ${request.invalid_attempt_count} 次` : ""}</dd></div>
              <div><dt>运行 / 事件</dt><dd>{request.run_id ?? "未记录"}{request.event_id === null ? "" : ` · #${request.event_id}`}</dd></div>
              <div><dt>发起时间</dt><dd>{request.created_at ? formatDateTime(request.created_at) : "未记录"}</dd></div>
            </dl>
            {request.error ? (
              <section className="game-model-request-block is-error">
                <h3>请求错误</h3>
                <pre>{request.error}</pre>
              </section>
            ) : null}
            <ModelRequestBlock
              empty="该次请求没有持久化输入。"
              title="输入 Prompt"
              value={request.prompt}
            />
            <ModelRequestBlock
              empty="该次请求没有持久化原始输出。"
              title="原始输出"
              value={request.raw_response}
            />
            <ModelRequestBlock
              empty="该次请求没有可显示的解析输出。"
              title="解析输出"
              value={request.parsed_output}
            />
            {request.raw_choice ? (
              <ModelRequestBlock
                empty=""
                title="原始选择"
                value={request.raw_choice}
              />
            ) : null}
          </div>
        ) : null}
      </aside>
    </div>
  );
}

function ModelRequestBlock({
  empty,
  title,
  value,
}: {
  empty: string;
  title: string;
  value: string | null;
}) {
  return (
    <section className="game-model-request-block">
      <h3>{title}</h3>
      {value ? <pre>{value}</pre> : <p>{empty}</p>}
    </section>
  );
}

function groupModelRequests(items: AdminGameModelRequestSummary[]) {
  const groups = new Map<string, AdminGameModelRequestSummary[]>();
  for (const item of items) {
    const key = item.round_number === null ? "unassigned" : String(item.round_number);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()].map(([key, requests]) => ({
    key,
    label: key === "unassigned" ? "未归类轮次" : `第 ${key} 轮`,
    items: requests,
  }));
}

function modelRequestStatusLabel(status: AdminGameModelRequestSummary["status"]) {
  return {
    pending: "等待返回",
    completed: "已完成",
    failed: "失败",
    response_missing: "响应未记录",
  }[status];
}

function formatNames(values: string[]) {
  return values.length > 0 ? values.join("、") : "—";
}

function formatVotes(votes: Record<string, string>) {
  const entries = Object.entries(votes);
  return entries.length > 0
    ? entries.map(([voter, target]) => `${voter}→${target}`).join("、")
    : "—";
}

function formatExileResolution(reason: string) {
  return {
    first_vote_winner: "首轮唯一最高票放逐",
    first_vote_tied: "首轮平票，进入 PK",
    runoff_vote_winner: "二轮唯一最高票放逐",
    runoff_tied: "二轮再次平票，无人被放逐",
    no_valid_votes: "没有有效票，无人被放逐",
    no_runoff_voters: "没有二轮投票者，无人被放逐",
  }[reason] ?? reason;
}

function badgeLostReasonLabel(value: string) {
  return {
    no_target: "未选择移交目标",
    destroyed: "警徽被撕毁",
    owner_selected_destroy: "警长选择撕毁警徽",
  }[value] ?? "其他原因";
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
        <strong title={event.type}>{eventTypeLabel(event.type)}</strong>
        <small>
          {event.round ? `第 ${event.round} 轮` : "全局"}
          {event.phase ? ` · ${phaseLabel(event.phase)}` : ""}
          {event.actor ? ` · ${event.actor}` : ""}
          {event.action ? ` · ${actionLabel(event.action)}` : ""}
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
      <span className="page-kicker">对局诊断</span>
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
