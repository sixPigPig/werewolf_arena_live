import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { listAdminAuditEvents } from "@/features/audit-events/api";
import { adminAuditKeys } from "@/features/audit-events/query-keys";
import type { AdminAuditParams } from "@/features/audit-events/types";

export default function AuditEventsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = paramsFromSearch(searchParams);
  const invalidRange = Boolean(params.created_from && params.created_to && params.created_from > params.created_to);
  const query = useQuery({
    enabled: !invalidRange,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => listAdminAuditEvents(params, signal),
    queryKey: adminAuditKeys.list(params),
  });
  function update(values: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries({ page: "1", ...values })) {
      if (value) next.set(key, value); else next.delete(key);
    }
    setSearchParams(next);
  }
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    update({ q: value(data, "q"), action: value(data, "action"), resource_type: value(data, "resource_type") });
  }
  return <div className="admin-page system-page">
    <header className="page-heading system-heading"><div><span className="page-kicker">SECURITY LEDGER</span><h1>审计日志</h1><p>查询后台身份、内容和运营操作的不可变审计记录。</p></div><button className="admin-secondary-button" onClick={() => void query.refetch()} type="button">手动刷新</button></header>
    <section aria-label="审计日志筛选" className="game-filter-panel"><form onSubmit={apply} role="search">
      <label className="game-filter-wide"><span>搜索审计</span><input defaultValue={params.q ?? ""} name="q" placeholder="操作者、资源或请求编号" type="search" /></label>
      <label><span>操作类型</span><input defaultValue={params.action ?? ""} name="action" placeholder="admin.user.update" /></label>
      <label><span>结果</span><select aria-label="审计结果" onChange={(event) => update({ result: event.target.value || undefined })} value={params.result ?? ""}><option value="">全部结果</option><option value="success">成功</option><option value="failure">失败</option></select></label>
      <label><span>资源类型</span><input defaultValue={params.resource_type ?? ""} name="resource_type" placeholder="user" /></label>
      <label><span>开始日期</span><input aria-label="审计开始日期" onChange={(event) => update({ created_from: event.target.value || undefined })} type="date" value={params.created_from ?? ""} /></label>
      <label><span>结束日期</span><input aria-label="审计结束日期" onChange={(event) => update({ created_to: event.target.value || undefined })} type="date" value={params.created_to ?? ""} /></label>
      <label><span>排序</span><select aria-label="审计排序" onChange={(event) => update({ direction: event.target.value })} value={params.direction}><option value="desc">最近发生</option><option value="asc">最早发生</option></select></label>
      <div className="game-filter-actions"><button className="admin-secondary-button" onClick={() => setSearchParams({})} type="button">清除筛选</button><button className="admin-primary-button" type="submit">应用筛选</button></div>
    </form></section>
    {invalidRange ? <p aria-live="polite" className="game-inline-warning" role="alert">开始日期不能晚于结束日期，请调整后重新筛选。</p> : null}
    <section aria-label="审计事件列表" className="game-list-panel">
      <div className="game-list-heading"><div><span>AUDIT EVENTS</span><h2>安全操作记录</h2></div><p>共 {query.data?.pagination.total ?? 0} 条记录</p></div>
      {query.isPending ? <div aria-live="polite" className="game-list-loading" role="status"><span /><span /><p>正在读取审计日志...</p></div> : null}
      {query.isError ? <div aria-live="assertive" className="game-list-error" role="alert"><h3>无法读取审计日志</h3><p>{isAdminApiError(query.error) ? query.error.message : "审计服务暂时不可用。"}</p><button onClick={() => void query.refetch()} type="button">重新加载</button></div> : null}
      {query.data?.items.length === 0 ? <div className="game-empty-state"><span>审</span><h3>没有符合条件的审计记录</h3><p>调整筛选条件后重试。</p></div> : null}
      {query.data?.items.length ? <ul className="audit-event-list">{query.data.items.map((event) => <li className="audit-event-row" key={event.id}>
        <div><strong>{event.action}</strong><small>{event.actor ? `${event.actor.display_name} · ${event.actor.email}` : "系统或未知操作者"}</small></div>
        <span className={`system-badge ${event.result === "success" ? "is-active" : "is-disabled"}`}>{event.result === "success" ? "成功" : "失败"}</span>
        <div><strong>{event.resource_type}{event.resource_id ? ` · ${event.resource_id}` : ""}</strong><small>{event.reason ?? "未记录原因"}</small></div>
        <div><strong>{formatDate(event.created_at)}</strong><small>{event.request_id ? `请求 ${event.request_id}` : "无请求编号"}</small></div>
      </li>)}</ul> : null}
      {query.data ? <nav aria-label="审计日志分页" className="game-pagination"><button disabled={query.data.pagination.page <= 1} onClick={() => update({ page: String(query.data!.pagination.page - 1) })} type="button">上一页</button><span>第 {query.data.pagination.page} / {Math.max(1, query.data.pagination.pages)} 页</span><button disabled={query.data.pagination.pages === 0 || query.data.pagination.page >= query.data.pagination.pages} onClick={() => update({ page: String(query.data!.pagination.page + 1) })} type="button">下一页</button></nav> : null}
    </section>
  </div>;
}

function paramsFromSearch(search: URLSearchParams): AdminAuditParams {
  const direction = search.get("direction");
  return { page: Math.max(1, Number(search.get("page")) || 1), page_size: 20, q: read(search, "q"), action: read(search, "action"), result: read(search, "result"), resource_type: read(search, "resource_type"), created_from: read(search, "created_from"), created_to: read(search, "created_to"), direction: direction === "asc" ? "asc" : "desc" };
}
function read(search: URLSearchParams, key: string) { return search.get(key)?.trim() || undefined; }
function value(data: FormData, key: string) { return String(data.get(key) ?? "").trim() || undefined; }
function formatDate(input: string) { return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(input)); }
