import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { listAdminLiveRuns } from "@/features/live-runs/api";
import {
  liveRunListParamsFromSearch,
  setLiveRunSearchValues,
} from "@/features/live-runs/list-state";
import {
  formatLiveRunDateTime,
  LIVE_RUN_STATUS_LABELS,
  LIVE_RUN_WORKER_LABELS,
  liveRunListRefreshInterval,
} from "@/features/live-runs/presentation";
import { adminLiveRunKeys } from "@/features/live-runs/query-keys";
import type { AdminLiveRunListItem } from "@/features/live-runs/types";

export default function LiveRunsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = liveRunListParamsFromSearch(searchParams);
  const invalidDateRange = Boolean(
    params.created_from &&
      params.created_to &&
      params.created_from > params.created_to,
  );
  const runsQuery = useQuery({
    enabled: !invalidDateRange,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => listAdminLiveRuns(params, signal),
    queryKey: adminLiveRunKeys.list(params),
    refetchInterval: (query) =>
      liveRunListRefreshInterval(query.state.data, params.page),
  });
  const data = invalidDateRange ? undefined : runsQuery.data;

  function updateSearch(values: Record<string, string | undefined>) {
    setSearchParams(
      setLiveRunSearchValues(searchParams, { page: "1", ...values }),
    );
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    updateSearch({
      q: formValue(values, "q"),
      rule_set_id: formValue(values, "rule_set_id"),
      created_from: formValue(values, "created_from"),
      created_to: formValue(values, "created_to"),
    });
  }

  function clearFilters() {
    setSearchParams(
      setLiveRunSearchValues(searchParams, {
        page: undefined,
        q: undefined,
        status: undefined,
        rule_set_id: undefined,
        created_from: undefined,
        created_to: undefined,
      }),
    );
  }

  const hasFilters = Boolean(
    params.q ||
      params.status ||
      params.rule_set_id ||
      params.created_from ||
      params.created_to,
  );

  return (
    <div className="admin-page live-runs-page">
      <header className="page-heading live-runs-heading">
        <div>
          <span className="page-kicker">LIVE OPERATIONS</span>
          <h1>运行监控</h1>
          <p>查看持久化运行状态、事件进度与安全诊断摘要。</p>
        </div>
        <div className="live-run-heading-actions">
          <span className="page-readiness-badge">监控与控制</span>
          <button
            className="admin-secondary-button"
            disabled={invalidDateRange || runsQuery.isFetching}
            onClick={() => void runsQuery.refetch()}
            type="button"
          >
            {runsQuery.isFetching ? "刷新中" : "手动刷新"}
          </button>
        </div>
      </header>

      <p className="live-run-freshness-note">
        第 1 页活跃运行每 5 秒刷新，无活跃运行时每 30 秒发现新记录；Worker 状态来自数据库租约，“最近活动”来自持久化事件。
      </p>

      <section aria-label="运行筛选" className="game-filter-panel">
        <form onSubmit={handleSearch} role="search">
          <label className="game-filter-wide">
            <span>搜索运行</span>
            <input
              defaultValue={params.q ?? ""}
              key={`q-${params.q ?? ""}`}
              name="q"
              placeholder="Run ID 或 Session ID"
              type="search"
            />
          </label>
          <label>
            <span>运行状态</span>
            <select
              onChange={(event) => updateSearch({ status: event.target.value })}
              value={params.status ?? ""}
            >
              <option value="">全部状态</option>
              <option value="queued">排队中</option>
              <option value="running">运行中</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
              <option value="canceled">已取消</option>
            </select>
          </label>
          <label>
            <span>规则 ID</span>
            <input
              defaultValue={params.rule_set_id ?? ""}
              key={`rule-${params.rule_set_id ?? ""}`}
              name="rule_set_id"
              placeholder="例如 classic_8"
            />
          </label>
          <label>
            <span>开始日期</span>
            <input
              defaultValue={params.created_from ?? ""}
              key={`from-${params.created_from ?? ""}`}
              name="created_from"
              type="date"
            />
          </label>
          <label>
            <span>结束日期</span>
            <input
              defaultValue={params.created_to ?? ""}
              key={`to-${params.created_to ?? ""}`}
              name="created_to"
              type="date"
            />
          </label>
          <label>
            <span>排序</span>
            <select
              onChange={(event) => {
                const [sort, direction] = event.target.value.split(":");
                updateSearch({ sort, direction });
              }}
              value={`${params.sort}:${params.direction}`}
            >
              <option value="updated_at:desc">最近更新</option>
              <option value="updated_at:asc">最早更新</option>
              <option value="created_at:desc">最近创建</option>
              <option value="created_at:asc">最早创建</option>
            </select>
          </label>
          <label>
            <span>每页</span>
            <select
              onChange={(event) =>
                updateSearch({ page_size: event.target.value })
              }
              value={String(params.page_size)}
            >
              <option value="10">10 条</option>
              <option value="20">20 条</option>
              <option value="50">50 条</option>
            </select>
          </label>
          <div className="game-filter-actions">
            {hasFilters ? (
              <button
                className="admin-text-button"
                onClick={clearFilters}
                type="button"
              >
                清除筛选
              </button>
            ) : null}
            <button className="admin-secondary-button" type="submit">
              应用筛选
            </button>
          </div>
        </form>
      </section>

      {invalidDateRange ? (
        <p className="game-inline-warning" role="alert">
          开始日期不能晚于结束日期，请调整后重新筛选。
        </p>
      ) : null}

      <section aria-labelledby="live-run-list-title" className="game-list-panel">
        <div className="game-list-heading">
          <div>
            <span>EXECUTION ARCHIVE</span>
            <h2 id="live-run-list-title">持久化运行</h2>
          </div>
          <p aria-live="polite">
            {data
              ? `共 ${data.pagination.total} 次运行`
              : invalidDateRange
                ? "等待有效日期范围"
                : "正在统计..."}
          </p>
        </div>

        {!invalidDateRange && runsQuery.isPending ? <RunListLoading /> : null}
        {!invalidDateRange && runsQuery.isError ? (
          <RunListError error={runsQuery.error} onRetry={runsQuery.refetch} />
        ) : null}
        {data && data.items.length === 0 ? (
          <div className="game-empty-state">
            <span aria-hidden="true">运</span>
            <h3>{hasFilters ? "没有符合条件的运行" : "还没有运行记录"}</h3>
            <p>
              {hasFilters
                ? "调整或清除筛选条件后重试。"
                : "创建运行后，持久化摘要会出现在这里。"}
            </p>
          </div>
        ) : null}
        {data && data.items.length > 0 ? (
          <ul aria-label="运行监控列表" className="live-run-admin-list">
            {data.items.map((run) => (
              <RunListItem key={run.run_id} run={run} />
            ))}
          </ul>
        ) : null}

        {data && data.pagination.total > 0 ? (
          <RunPagination
            page={data.pagination.page}
            pages={data.pagination.pages}
            setPage={(page) =>
              setSearchParams(
                setLiveRunSearchValues(searchParams, { page: String(page) }),
              )
            }
          />
        ) : null}
      </section>
    </div>
  );
}

function RunListItem({ run }: { run: AdminLiveRunListItem }) {
  return (
    <li className="live-run-admin-row">
      <div className="live-run-admin-identity">
        <strong>{run.run_id}</strong>
        <small title={run.session_id}>Session · {run.session_id}</small>
      </div>
      <div className="live-run-admin-status">
        <span className={`run-status-badge is-${run.status}`}>
          {LIVE_RUN_STATUS_LABELS[run.status]}
        </span>
        {run.is_stale ? <small className="live-run-stale">可能失联</small> : null}
        {run.recovery_exhausted ? (
          <small className="live-run-stale">自动恢复已耗尽</small>
        ) : null}
        {!run.is_stale ? <small>{LIVE_RUN_WORKER_LABELS[run.worker_state]}</small> : null}
      </div>
      <div className="live-run-admin-models">
        <strong title={run.villager_model ?? undefined}>
          {run.villager_model ?? "模型未公开"}
        </strong>
        <small title={run.werewolf_model ?? undefined}>
          {run.werewolf_model ?? "终局后显示模型"}
        </small>
      </div>
      <div className="live-run-admin-progress">
        <strong>{run.event_count} 事件</strong>
        <small>
          语音 {run.voice_counts.complete}/{run.voice_counts.total}
          {run.voice_counts.failed ? ` · 失败 ${run.voice_counts.failed}` : ""}
          {run.recovery_attempts ? ` · 自动恢复 ${run.recovery_attempts} 次` : ""}
        </small>
      </div>
      <div className="live-run-admin-activity">
        <strong>{formatLiveRunDateTime(run.last_activity_at)}</strong>
        <small>{run.rule_set?.name ?? run.rule_set?.id ?? "规则未知"}</small>
      </div>
      <div className="game-admin-action-cell">
        <Link
          aria-label={`查看运行 ${run.run_id}`}
          className="admin-secondary-link"
          to={`/operations/runs/${encodeURIComponent(run.run_id)}`}
        >
          查看监控
        </Link>
      </div>
    </li>
  );
}

function RunPagination({
  page,
  pages,
  setPage,
}: {
  page: number;
  pages: number;
  setPage: (page: number) => void;
}) {
  return (
    <nav aria-label="运行列表分页" className="game-pagination">
      <button disabled={page <= 1} onClick={() => setPage(page - 1)} type="button">
        上一页
      </button>
      <span aria-current="page">第 {page} / {Math.max(1, pages)} 页</span>
      <button
        disabled={pages === 0 || page >= pages}
        onClick={() => setPage(page + 1)}
        type="button"
      >
        下一页
      </button>
    </nav>
  );
}

function RunListLoading() {
  return (
    <div aria-live="polite" className="game-list-loading" role="status">
      <span />
      <span />
      <span />
      <p>正在读取运行记录...</p>
    </div>
  );
}

function RunListError({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => unknown;
}) {
  return (
    <div aria-live="assertive" className="game-list-error" role="alert">
      <h3>无法读取运行记录</h3>
      <p>{error.message}</p>
      {isAdminApiError(error) && error.requestId ? (
        <small>请求编号：{error.requestId}</small>
      ) : null}
      <button onClick={() => void onRetry()} type="button">
        重新加载
      </button>
    </div>
  );
}

function formValue(values: FormData, key: string) {
  const value = values.get(key);
  return typeof value === "string" ? value : undefined;
}
