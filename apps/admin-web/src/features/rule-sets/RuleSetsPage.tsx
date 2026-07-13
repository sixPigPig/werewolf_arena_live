import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { isAdminApiError } from "@/api/problem-details";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import { ruleSetListParamsFromSearch, setRuleSetSearchValues } from "./list-state";
import { ruleSetKeys } from "./query-keys";
import { useRuleSetRepository } from "./repository";
import type { AdminRuleSet, RuleSetStatus } from "./types";

const STATUS_LABELS: Record<RuleSetStatus, string> = { draft: "草稿", published: "已发布", archived: "已归档" };

export default function RuleSetsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = ruleSetListParamsFromSearch(searchParams);
  const repository = useRuleSetRepository(); const queryClient = useQueryClient(); const navigate = useNavigate();
  const { session } = useAdminSession(); const canWrite = hasAdminPermission(session?.permissions ?? [], "rules.write");
  const [duplicateSource, setDuplicateSource] = useState<AdminRuleSet | null>(null);
  const optionsQuery = useQuery({ queryKey: ruleSetKeys.options, queryFn: ({ signal }) => repository.getOptions(signal), staleTime: 300_000 });
  const rulesQuery = useQuery({ queryKey: ruleSetKeys.list(params), queryFn: ({ signal }) => repository.list(params, signal), placeholderData: keepPreviousData });
  const data = rulesQuery.data;
  function updateSearch(values: Record<string, string | undefined>) { setSearchParams(setRuleSetSearchValues(searchParams, values)); }
  function search(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const value = new FormData(event.currentTarget).get("q"); updateSearch({ q: typeof value === "string" ? value : undefined }); }
  function clear() { setSearchParams(setRuleSetSearchValues(searchParams, { page: undefined, q: undefined, status: undefined, player_count: undefined })); }
  const hasFilters = Boolean(params.q || params.status || params.player_count);
  return <div className="admin-page player-profiles-page">
    <header className="page-heading player-profiles-heading"><div><span className="page-kicker">CONTENT</span><h1>游戏规则</h1><p>管理狼人杀规则配置、版本与发布状态。</p></div>{canWrite ? <Link className="admin-primary-link" to="/content/rules/new">新建规则草稿</Link> : <span className="page-readiness-badge">只读权限</span>}</header>
    <section aria-label="规则筛选" className="player-filter-panel">
      <form className="player-search-form" onSubmit={search} role="search"><label><span>搜索规则</span><input defaultValue={params.q ?? ""} key={params.q ?? "empty"} name="q" placeholder="名称、ID 或简介" type="search" /></label><button className="admin-secondary-button" type="submit">搜索</button></form>
      <div className="player-filter-grid">
        <label><span>生命周期</span><select onChange={(event) => updateSearch({ status: event.target.value })} value={params.status ?? ""}><option value="">全部状态</option>{(optionsQuery.data?.statuses ?? [{ value: "draft", label: "草稿" }, { value: "published", label: "已发布" }, { value: "archived", label: "已归档" }]).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        <label><span>玩家人数</span><select onChange={(event) => updateSearch({ player_count: event.target.value })} value={params.player_count ?? ""}><option value="">全部人数</option>{Array.from({ length: 7 }, (_, index) => index + 6).map((count) => <option key={count} value={count}>{count} 人</option>)}</select></label>
        <label><span>排序</span><select onChange={(event) => { const [sort, direction] = event.target.value.split(":"); updateSearch({ sort, direction }); }} value={`${params.sort}:${params.direction}`}><option value="display_order:asc">展示顺序</option><option value="updated_at:desc">最近更新</option><option value="created_at:desc">最近创建</option><option value="name:asc">名称 A–Z</option></select></label>
        <label><span>每页</span><select onChange={(event) => updateSearch({ page_size: event.target.value })} value={params.page_size}><option value="10">10 条</option><option value="20">20 条</option><option value="50">50 条</option></select></label>
        {hasFilters ? <button className="admin-text-button player-clear-filter" onClick={clear} type="button">清除筛选</button> : null}
      </div>
    </section>
    {optionsQuery.isError ? <p className="player-inline-warning" role="status">筛选选项暂时不可用，规则列表仍可浏览。</p> : null}
    <section aria-labelledby="rule-list-title" className="player-list-panel"><div className="player-list-heading"><div><span>RULE LIBRARY</span><h2 id="rule-list-title">规则内容库</h2></div><p aria-live="polite">{data ? `共 ${data.pagination.total} 套规则` : "正在统计..."}</p></div>
      {rulesQuery.isPending ? <Loading /> : null}
      {rulesQuery.isError ? <ErrorState error={rulesQuery.error} retry={rulesQuery.refetch} /> : null}
      {data?.items.length === 0 ? <div className="player-empty-state"><span aria-hidden="true">规</span><h3>{hasFilters ? "没有符合条件的游戏规则" : "还没有游戏规则"}</h3><p>{hasFilters ? "调整或清除筛选条件后重试。" : "创建第一套规则草稿后开始配置。"}</p></div> : null}
      {data && data.items.length > 0 ? <ul aria-label="游戏规则列表" className="player-admin-list">{data.items.map((rule) => <RuleRow canWrite={canWrite} key={rule.id} onDuplicate={() => setDuplicateSource(rule)} rule={rule} />)}</ul> : null}
      {data && data.pagination.total > 0 ? <nav aria-label="规则列表分页" className="player-pagination"><button disabled={data.pagination.page <= 1} onClick={() => updateSearch({ page: String(data.pagination.page - 1) })}>上一页</button><span aria-current="page">第 {data.pagination.page} / {Math.max(1, data.pagination.pages)} 页</span><button disabled={data.pagination.pages === 0 || data.pagination.page >= data.pagination.pages} onClick={() => updateSearch({ page: String(data.pagination.page + 1) })}>下一页</button></nav> : null}
    </section>
    {duplicateSource ? <DuplicateDialog close={() => setDuplicateSource(null)} onSuccess={async (id) => { await queryClient.invalidateQueries({ queryKey: ruleSetKeys.lists }); setDuplicateSource(null); navigate(`/content/rules/${encodeURIComponent(id)}`); }} repository={repository} source={duplicateSource} /> : null}
  </div>;
}

function RuleRow({ canWrite, onDuplicate, rule }: { canWrite: boolean; onDuplicate: () => void; rule: AdminRuleSet }) {
  const revision = rule.draft_revision ?? rule.published_revision; const name = revision?.config?.name ?? rule.id;
  return <li className="player-admin-row"><div className="player-admin-identity"><span><strong>{name}</strong><small>{rule.id}</small></span></div><div className="player-admin-status-cell"><span className={`player-status-badge is-${rule.status}`}>{STATUS_LABELS[rule.status]}</span>{rule.is_default ? <span className="player-featured-badge">默认规则</span> : null}</div><div className="player-admin-model-cell"><strong>{revision?.player_count ?? 0} 人</strong><small>{revision?.role_summary ?? "暂无角色摘要"}</small></div><div className="player-admin-updated-cell"><strong>版本 {revision?.revision_no ?? 0}</strong><small>锁版本 {rule.lock_version}</small></div><div className="player-admin-action-cell">{canWrite ? <button aria-label={`复制 ${name}`} className="admin-text-button" onClick={onDuplicate} type="button">复制</button> : null}<Link aria-label={`查看 ${name}`} className="admin-secondary-link" to={`/content/rules/${encodeURIComponent(rule.id)}`}>查看</Link></div></li>;
}

function DuplicateDialog({ close, onSuccess, repository, source }: { close: () => void; onSuccess: (id: string) => Promise<void>; repository: ReturnType<typeof useRuleSetRepository>; source: AdminRuleSet }) {
  const [errors, setErrors] = useState<{ id?: string; name?: string }>({});
  const mutation = useMutation({ mutationFn: ({ id, name }: { id: string; name: string }) => repository.duplicate(source.id, { expected_source_lock_version: source.lock_version, new_rule_set_id: id, new_name: name }), onSuccess: (_, values) => onSuccess(values.id) });
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); const id = String(form.get("id") ?? "").trim(); const name = String(form.get("name") ?? "").trim(); const next = { id: /^[a-z][a-z0-9_]{2,79}$/.test(id) ? undefined : "请输入有效的新规则 ID", name: name ? undefined : "请输入新规则名称" }; setErrors(next); if (!next.id && !next.name) mutation.mutate({ id, name }); }
  return <div aria-labelledby="duplicate-rule-title" aria-modal="true" className="admin-dialog-backdrop" role="dialog"><form className="admin-dialog" onSubmit={submit}><h2 id="duplicate-rule-title">复制游戏规则</h2><p>从 {source.id} 创建独立草稿。</p><label><span>新规则 ID</span><input aria-label="新规则 ID" aria-describedby={errors.id ? "duplicate-id-error" : undefined} name="id" />{errors.id ? <small id="duplicate-id-error">{errors.id}</small> : null}</label><label><span>新规则名称</span><input aria-label="新规则名称" aria-describedby={errors.name ? "duplicate-name-error" : undefined} name="name" />{errors.name ? <small id="duplicate-name-error">{errors.name}</small> : null}</label>{mutation.isError ? <p role="alert">{mutation.error.message}</p> : null}<div><button onClick={close} type="button">取消</button><button disabled={mutation.isPending} type="submit">确认复制</button></div></form></div>;
}

function Loading() { return <div aria-live="polite" className="player-list-loading" role="status"><span /><span /><span /><p>正在读取游戏规则...</p></div>; }
function ErrorState({ error, retry }: { error: Error; retry: () => unknown }) { return <div aria-live="assertive" className="player-list-error" role="alert"><h3>无法读取游戏规则</h3><p>{error.message}</p>{isAdminApiError(error) && error.requestId ? <small>请求编号：{error.requestId}</small> : null}<button onClick={() => void retry()} type="button">重新加载</button></div>; }
export function RuleSetNewPage() { return <div className="admin-page"><header className="page-heading"><div><span className="page-kicker">CONTENT / RULES</span><h1>新建游戏规则</h1><p>规则编辑器将在后续任务中接入。</p></div></header></div>; }
export function RuleSetDetailPage() { const { ruleSetId } = useParams(); return <div className="admin-page"><header className="page-heading"><div><span className="page-kicker">CONTENT / RULES</span><h1>游戏规则详情</h1><p>{ruleSetId}</p></div></header></div>; }
