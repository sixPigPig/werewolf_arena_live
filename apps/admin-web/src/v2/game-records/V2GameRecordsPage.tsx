import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { listV2GameRecords } from "@/v2/game-records/api";
import { v2GameRecordKeys } from "@/v2/game-records/query-keys";

export default function V2GameRecordsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const query = useQuery({
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => listV2GameRecords(page, signal),
    queryKey: v2GameRecordKeys.list(page),
  });

  return (
    <div className="admin-page v2-game-records-page">
      <header className="page-heading game-records-heading">
        <div>
          <span className="page-kicker">LIVE V2 LEDGER</span>
          <h1>V2 对局记录</h1>
          <p>只读取全新的 V2 事实序列与展示序列，不投影旧对局记录。</p>
        </div>
        <span className="page-readiness-badge">独立记录模型</span>
      </header>

      <section aria-labelledby="v2-game-list-title" className="game-list-panel">
        <div className="game-list-heading">
          <div>
            <span>V2 GAMES</span>
            <h2 id="v2-game-list-title">新对局账本</h2>
          </div>
          <p>{query.data ? `共 ${query.data.pagination.total} 场` : "正在统计..."}</p>
        </div>
        {query.isPending ? (
          <div aria-live="polite" className="game-list-loading" role="status">
            <span />
            <span />
            <p>正在读取 V2 对局...</p>
          </div>
        ) : null}
        {query.isError ? (
          <div aria-live="assertive" className="game-list-error" role="alert">
            <h3>无法读取 V2 对局</h3>
            <p>
              {isAdminApiError(query.error)
                ? query.error.message
                : "V2 对局记录服务暂时不可用。"}
            </p>
            <button onClick={() => void query.refetch()} type="button">重新加载</button>
          </div>
        ) : null}
        {query.data?.items.length === 0 ? (
          <div className="game-empty-state">
            <span aria-hidden="true">V2</span>
            <h3>还没有 V2 对局</h3>
            <p>通过 V2 创建接口建立的对局会出现在这里。</p>
          </div>
        ) : null}
        {query.data?.items.length ? (
          <ul aria-label="V2 对局记录列表" className="v2-game-record-list">
            {query.data.items.map((game) => (
              <li key={game.game_id}>
                <div>
                  <strong>{game.title}</strong>
                  <small>{game.game_id}</small>
                </div>
                <div>
                  <span className="game-status-badge is-partial">{game.status}</span>
                  <small>{game.current_run_id}</small>
                </div>
                <div>
                  <strong>事实 #{game.last_record_seq}</strong>
                  <small>展示 #{game.last_presentation_seq}</small>
                </div>
                <time dateTime={game.created_at}>{formatDate(game.created_at)}</time>
                <Link to={`/v2/operations/games/${game.game_id}`}>查看记录</Link>
              </li>
            ))}
          </ul>
        ) : null}
        {query.data && query.data.pagination.total > 0 ? (
          <nav aria-label="V2 对局记录分页" className="game-pagination">
            <button
              disabled={page <= 1}
              onClick={() => setSearchParams({ page: String(page - 1) })}
              type="button"
            >
              上一页
            </button>
            <span>第 {page} / {Math.max(1, query.data.pagination.pages)} 页</span>
            <button
              disabled={page >= query.data.pagination.pages}
              onClick={() => setSearchParams({ page: String(page + 1) })}
              type="button"
            >
              下一页
            </button>
          </nav>
        ) : null}
      </section>
    </div>
  );
}

function formatDate(input: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(input));
}
