import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { Link, useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { useAdminSession } from "@/features/auth/session-context";
import { hasAdminPermission } from "@/features/auth/permissions";
import {
  deleteAdminGame,
  listAdminGames,
} from "@/features/game-records/api";
import {
  gameListParamsFromSearch,
  setGameSearchValues,
} from "@/features/game-records/list-state";
import {
  displayValue,
  formatDateTime,
  GAME_STATUS_LABELS,
  RUN_STATUS_LABELS,
} from "@/features/game-records/presentation";
import { adminGameKeys } from "@/features/game-records/query-keys";
import type { AdminGameListItem } from "@/features/game-records/types";

export default function GameRecordsPage() {
  const { session } = useAdminSession();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [deleteState, setDeleteState] = useState<{
    game: AdminGameListItem;
    opener: HTMLButtonElement;
  } | null>(null);
  const params = gameListParamsFromSearch(searchParams);
  const canDelete = hasAdminPermission(
    session?.permissions ?? [],
    "games.delete",
  );
  const invalidDateRange = Boolean(
    params.created_from &&
      params.created_to &&
      params.created_from > params.created_to,
  );
  const gamesQuery = useQuery({
    enabled: !invalidDateRange,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => listAdminGames(params, signal),
    queryKey: adminGameKeys.list(params),
  });
  const data = invalidDateRange ? undefined : gamesQuery.data;
  const deleteMutation = useMutation({
    mutationFn: (sessionId: string) =>
      deleteAdminGame(sessionId, session?.csrf_token ?? ""),
    onSuccess: async () => {
      setDeleteState(null);
      await queryClient.invalidateQueries({ queryKey: adminGameKeys.lists() });
    },
  });

  function updateSearch(values: Record<string, string | undefined>) {
    setSearchParams(setGameSearchValues(searchParams, { page: "1", ...values }));
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    updateSearch({
      q: formValue(values, "q"),
      winner: formValue(values, "winner"),
      rule_set_id: formValue(values, "rule_set_id"),
      created_from: formValue(values, "created_from"),
      created_to: formValue(values, "created_to"),
    });
  }

  function clearFilters() {
    setSearchParams(
      setGameSearchValues(searchParams, {
        page: undefined,
        q: undefined,
        status: undefined,
        run_status: undefined,
        winner: undefined,
        rule_set_id: undefined,
        created_from: undefined,
        created_to: undefined,
      }),
    );
  }

  function openDeleteDialog(
    game: AdminGameListItem,
    opener: HTMLButtonElement,
  ) {
    deleteMutation.reset();
    setDeleteState({ game, opener });
  }

  function closeDeleteDialog() {
    if (deleteMutation.isPending) {
      return;
    }
    deleteMutation.reset();
    setDeleteState(null);
  }

  const hasFilters = Boolean(
    params.q ||
      params.status ||
      params.run_status ||
      params.winner ||
      params.rule_set_id ||
      params.created_from ||
      params.created_to,
  );

  return (
    <div className="admin-page game-records-page">
      <header className="page-heading game-records-heading">
        <div>
          <span className="page-kicker">运营管理</span>
          <h1>对局记录</h1>
          <p>从持久化记录查看对局结果、运行状态与可公开诊断摘要。</p>
        </div>
        <span className="page-readiness-badge">
          {canDelete ? "可受控删除" : "只读模块"}
        </span>
      </header>

      <section aria-label="对局筛选" className="game-filter-panel">
        <form onSubmit={handleSearch} role="search">
          <label className="game-filter-wide">
            <span>搜索对局</span>
            <input
              defaultValue={params.q ?? ""}
              key={`q-${params.q ?? ""}`}
              name="q"
              placeholder="对局 ID、运行 ID、模型或胜方"
              type="search"
            />
          </label>
          <label>
            <span>对局状态</span>
            <select
              onChange={(event) => updateSearch({ status: event.target.value })}
              value={params.status ?? ""}
            >
              <option value="">全部状态</option>
              <option value="complete">已完成</option>
              <option value="partial">部分记录</option>
            </select>
          </label>
          <label>
            <span>最新运行状态</span>
            <select
              onChange={(event) =>
                updateSearch({ run_status: event.target.value })
              }
              value={params.run_status ?? ""}
            >
              <option value="">全部最新运行状态</option>
              <option value="queued">排队中</option>
              <option value="running">运行中</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
              <option value="canceled">已取消</option>
            </select>
          </label>
          <label>
            <span>胜方</span>
            <input
              defaultValue={params.winner ?? ""}
              key={`winner-${params.winner ?? ""}`}
              name="winner"
              placeholder="精确名称"
            />
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
              <option value="created_at:desc">最近创建</option>
              <option value="created_at:asc">最早创建</option>
              <option value="updated_at:desc">最近更新</option>
              <option value="updated_at:asc">最早更新</option>
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

      <section aria-labelledby="game-list-title" className="game-list-panel">
        <div className="game-list-heading">
          <div>
            <span>对局归档</span>
            <h2 id="game-list-title">持久化对局</h2>
          </div>
          <p aria-live="polite">
            {data
              ? `共 ${data.pagination.total} 场对局`
              : invalidDateRange
                ? "等待有效日期范围"
                : "正在统计..."}
          </p>
        </div>

        {!invalidDateRange && gamesQuery.isPending ? <GameListLoading /> : null}
        {!invalidDateRange && gamesQuery.isError ? (
          <GameListError error={gamesQuery.error} onRetry={gamesQuery.refetch} />
        ) : null}
        {data && data.items.length === 0 ? (
          <div className="game-empty-state">
            <span aria-hidden="true">局</span>
            <h3>{hasFilters ? "没有符合条件的对局" : "还没有对局记录"}</h3>
            <p>
              {hasFilters
                ? "调整或清除筛选条件后重试。"
                : "完成或中断的对局将在持久化后出现在这里。"}
            </p>
          </div>
        ) : null}
        {data && data.items.length > 0 ? (
          <ul aria-label="对局记录列表" className="game-admin-list">
            {data.items.map((game) => (
              <GameListItem
                canDelete={canDelete}
                game={game}
                key={game.session_id}
                onDelete={openDeleteDialog}
              />
            ))}
          </ul>
        ) : null}

        {data && data.pagination.total > 0 ? (
          <GamePagination
            page={data.pagination.page}
            pages={data.pagination.pages}
            setPage={(page) =>
              setSearchParams(
                setGameSearchValues(searchParams, { page: String(page) }),
              )
            }
          />
        ) : null}
      </section>

      {deleteState ? (
        <GameDeleteDialog
          error={
            deleteMutation.isError
              ? presentGameDeleteError(deleteMutation.error)
              : null
          }
          game={deleteState.game}
          onClose={closeDeleteDialog}
          onConfirm={() =>
            deleteMutation.mutate(deleteState.game.session_id)
          }
          opener={deleteState.opener}
          pending={deleteMutation.isPending}
        />
      ) : null}
    </div>
  );
}

function GameListItem({
  canDelete,
  game,
  onDelete,
}: {
  canDelete: boolean;
  game: AdminGameListItem;
  onDelete: (game: AdminGameListItem, opener: HTMLButtonElement) => void;
}) {
  return (
    <li className="game-admin-row">
      <div className="game-admin-identity">
        <strong>{game.session_id}</strong>
        <small>
          {game.rule_set
            ? `${game.rule_set.name} · ${game.rule_set.player_count ?? "人数未知"}${game.rule_set.player_count === null ? "" : " 人"}`
            : "规则快照不可用"}
        </small>
      </div>
      <div className="game-admin-status-cell">
        <span className={`game-status-badge is-${game.status}`}>
          {GAME_STATUS_LABELS[game.status]}
        </span>
        {game.resumable ? <small>可恢复</small> : null}
      </div>
      <div className="game-admin-result-cell">
        <strong>{displayValue(game.winner)}</strong>
        <small>{game.round_count} 轮</small>
      </div>
      <div className="game-admin-run-cell">
        {game.latest_run ? (
          <>
            <span className={`run-status-badge is-${game.latest_run.status}`}>
              {RUN_STATUS_LABELS[game.latest_run.status]}
            </span>
            <small title={game.latest_run.run_id}>
              {game.latest_run.run_id} · {game.latest_run.event_count} 事件
              {game.latest_run.has_error ? " · 有错误" : ""}
            </small>
          </>
        ) : (
          <small>无关联运行</small>
        )}
      </div>
      <div className="game-admin-time-cell">
        <strong>{formatDateTime(game.created_at)}</strong>
        <small>更新于 {formatDateTime(game.updated_at)}</small>
      </div>
      <div className="game-admin-action-cell">
        {canDelete ? (
          <button
            aria-label={`删除对局 ${game.session_id}`}
            className="admin-danger-button"
            onClick={(event: MouseEvent<HTMLButtonElement>) =>
              onDelete(game, event.currentTarget)
            }
            type="button"
          >
            删除
          </button>
        ) : null}
        <Link
          aria-label={`查看对局 ${game.session_id}`}
          className="admin-secondary-link"
          to={`/operations/games/${encodeURIComponent(game.session_id)}`}
        >
          查看诊断
        </Link>
      </div>
    </li>
  );
}

function GameDeleteDialog({
  error,
  game,
  onClose,
  onConfirm,
  opener,
  pending,
}: {
  error: string | null;
  game: AdminGameListItem;
  onClose: () => void;
  onConfirm: () => void;
  opener: HTMLButtonElement;
  pending: boolean;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    return () => opener.focus();
  }, [opener]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !pending) {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled])",
      ) ?? [],
    );
    if (focusable.length === 0) {
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1) ?? first;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="player-dialog-backdrop">
      <div
        aria-describedby="game-delete-description"
        aria-labelledby="game-delete-title"
        aria-modal="true"
        className="player-transition-dialog game-delete-dialog"
        onKeyDown={handleKeyDown}
        ref={dialogRef}
        role="alertdialog"
      >
        <span className="page-kicker">危险操作</span>
        <h2 id="game-delete-title">删除对局</h2>
        <p id="game-delete-description">
          将永久删除此对局及其回放、运行事件、语音和质量评估数据，无法撤销。
        </p>
        <code>{game.session_id}</code>
        <p className="game-delete-warning">
          正在排队或运行的对局需先停止，才能删除。
        </p>
        {error ? (
          <p aria-live="assertive" role="alert">
            {error}
          </p>
        ) : null}
        <div className="player-dialog-actions">
          <button
            className="admin-secondary-button"
            disabled={pending}
            onClick={onClose}
            ref={cancelRef}
            type="button"
          >
            取消
          </button>
          <button
            className="admin-danger-button"
            disabled={pending}
            onClick={onConfirm}
            type="button"
          >
            {pending ? "正在删除..." : "确认删除"}
          </button>
        </div>
      </div>
    </div>
  );
}

function presentGameDeleteError(error: unknown) {
  if (isAdminApiError(error, 409)) {
    return "对局仍在排队或运行，请先停止运行后再删除。";
  }
  if (isAdminApiError(error, 404)) {
    return "该对局已不存在，请取消后刷新列表。";
  }
  if (isAdminApiError(error)) {
    const requestId = error.requestId ? ` 请求编号：${error.requestId}` : "";
    return `暂时无法删除对局，请稍后重试。${requestId}`;
  }
  return "暂时无法删除对局，请检查网络后重试。";
}

function GamePagination({
  page,
  pages,
  setPage,
}: {
  page: number;
  pages: number;
  setPage: (page: number) => void;
}) {
  return (
    <nav aria-label="对局列表分页" className="game-pagination">
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

function GameListLoading() {
  return (
    <div aria-live="polite" className="game-list-loading" role="status">
      <span />
      <span />
      <span />
      <p>正在读取对局记录...</p>
    </div>
  );
}

function GameListError({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => unknown;
}) {
  return (
    <div aria-live="assertive" className="game-list-error" role="alert">
      <h3>无法读取对局记录</h3>
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
