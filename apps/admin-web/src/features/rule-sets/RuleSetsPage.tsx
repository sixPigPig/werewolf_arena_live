import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Button from "antd/es/button";
import Input, { type InputRef } from "antd/es/input";
import Select from "antd/es/select";
import { type FormEvent, type KeyboardEvent, type MouseEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import RuleSetEditorPage from "./RuleSetEditorPage";
import { isAdminApiError } from "@/api/problem-details";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import { ruleSetListParamsFromSearch, setRuleSetSearchValues } from "./list-state";
import { ruleSetKeys } from "./query-keys";
import { useRuleSetRepository } from "./repository";
import { presentRuleSetError } from "./error-presentation";
import type { AdminRuleSet, RuleSetOptions, RuleSetStatus } from "./types";

const STATUS_LABELS: Record<RuleSetStatus, string> = { draft: "草稿", published: "已发布", archived: "已归档" };

export default function RuleSetsPage() {
  const repository = useRuleSetRepository();
  const optionsQuery = useQuery({ queryKey: ruleSetKeys.options, queryFn: ({ signal }) => repository.getOptions(signal), staleTime: 300_000 });
  if (optionsQuery.isPending) return <div className="admin-page"><Loading /></div>;
  if (optionsQuery.isError) return <OptionsUnavailable retry={optionsQuery.refetch} />;
  return <RuleSetsContent options={optionsQuery.data} />;
}

function RuleSetsContent({ options }: { options: RuleSetOptions }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = ruleSetListParamsFromSearch(searchParams, options);
  const repository = useRuleSetRepository(); const queryClient = useQueryClient(); const navigate = useNavigate();
  const { session } = useAdminSession(); const canWrite = hasAdminPermission(session?.permissions ?? [], "rules.write");
  const [duplicateSource, setDuplicateSource] = useState<AdminRuleSet | null>(null);
  const [duplicateOpener, setDuplicateOpener] = useState<HTMLButtonElement | null>(null);
  const rulesQuery = useQuery({ queryKey: ruleSetKeys.list(params), queryFn: ({ signal }) => repository.list(params, signal), placeholderData: keepPreviousData });
  const data = rulesQuery.data;
  function updateSearch(values: Record<string, string | undefined>) { setSearchParams(setRuleSetSearchValues(searchParams, values, options)); }
  function search(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const value = new FormData(event.currentTarget).get("q"); updateSearch({ q: typeof value === "string" ? value : undefined }); }
  function clear() { setSearchParams(setRuleSetSearchValues(searchParams, { page: undefined, q: undefined, status: undefined, player_count: undefined }, options)); }
  const hasFilters = Boolean(params.q || params.status || params.player_count);
  return <div className="admin-page rule-set-page">
    <header className="page-heading rule-set-heading"><div><span className="page-kicker">CONTENT</span><h1>游戏规则</h1><p>管理狼人杀规则配置、版本与发布状态。</p></div>{canWrite ? <Link className="admin-primary-link" to="/content/rules/new">新建规则草稿</Link> : <span className="page-readiness-badge">只读权限</span>}</header>
    <section aria-label="规则筛选" className="rule-set-filter-panel">
      <form className="rule-set-search-form" onSubmit={search} role="search"><label><span>搜索规则</span><Input aria-label="搜索规则" defaultValue={params.q ?? ""} key={params.q ?? "empty"} name="q" placeholder="名称、ID 或简介" type="search" /></label><Button htmlType="submit">搜索</Button></form>
      <div className="rule-set-filter-grid">
        <label><span>生命周期</span><Select aria-label="生命周期" onChange={(value) => updateSearch({ status: value })} options={[{ label: "全部状态", value: "" }, ...options.statuses.map((item) => ({ label: item.label, value: item.value }))]} value={params.status ?? ""} /></label>
        <label><span>玩家人数</span><Select aria-label="玩家人数" onChange={(value) => updateSearch({ player_count: value })} options={[{ label: "全部人数", value: "" }, ...playerCounts(options.constraints.player_count_min, options.constraints.player_count_max).map((count) => ({ label: `${count} 人`, value: String(count) }))]} value={params.player_count === undefined ? "" : String(params.player_count)} /></label>
        <label><span>排序</span><Select aria-label="排序" onChange={(signed) => { updateSearch({ sort: signed.replace(/^-/, ""), direction: signed.startsWith("-") ? "desc" : "asc" }); }} options={options.sorts.map((item) => ({ label: item.label, value: item.value }))} value={`${params.direction === "desc" ? "-" : ""}${params.sort}`} /></label>
        <label><span>每页</span><Select aria-label="每页" onChange={(value) => updateSearch({ page_size: value })} options={[{ label: "10 条", value: "10" }, { label: "20 条", value: "20" }, { label: "50 条", value: "50" }]} value={String(params.page_size)} /></label>
        {hasFilters ? <Button className="rule-set-clear-filter" htmlType="button" onClick={clear} type="text">清除筛选</Button> : null}
      </div>
    </section>
    <section aria-labelledby="rule-list-title" className="rule-set-list-panel"><div className="rule-set-list-heading"><div><span>RULE LIBRARY</span><h2 id="rule-list-title">规则内容库</h2></div><p aria-live="polite">{data ? `共 ${data.pagination.total} 套规则` : "正在统计..."}</p></div>
      {rulesQuery.isPending ? <Loading /> : null}
      {rulesQuery.isError ? <ErrorState error={rulesQuery.error} retry={rulesQuery.refetch} /> : null}
      {data?.items.length === 0 ? <div className="rule-set-empty-state"><span aria-hidden="true">规</span><h3>{hasFilters ? "没有符合条件的游戏规则" : "还没有游戏规则"}</h3><p>{hasFilters ? "调整或清除筛选条件后重试。" : "创建第一套规则草稿后开始配置。"}</p></div> : null}
      {data && data.items.length > 0 ? <ul aria-label="游戏规则列表" className="rule-set-list">{data.items.map((rule) => <RuleRow canWrite={canWrite} key={rule.id} onDuplicate={(opener) => { setDuplicateOpener(opener); setDuplicateSource(rule); }} rule={rule} />)}</ul> : null}
      {data && data.pagination.total > 0 ? <nav aria-label="规则列表分页" className="rule-set-pagination"><button disabled={data.pagination.page <= 1} onClick={() => updateSearch({ page: String(data.pagination.page - 1) })}>上一页</button><span aria-current="page">第 {data.pagination.page} / {Math.max(1, data.pagination.pages)} 页</span><button disabled={data.pagination.pages === 0 || data.pagination.page >= data.pagination.pages} onClick={() => updateSearch({ page: String(data.pagination.page + 1) })}>下一页</button></nav> : null}
    </section>
    {duplicateSource ? <DuplicateDialog close={() => { duplicateOpener?.focus(); setDuplicateSource(null); setDuplicateOpener(null); }} idPattern={options.constraints.id_pattern} onSuccess={async (id) => { await queryClient.invalidateQueries({ queryKey: ruleSetKeys.lists }); setDuplicateSource(null); setDuplicateOpener(null); navigate(`/content/rules/${encodeURIComponent(id)}`); }} repository={repository} source={duplicateSource} /> : null}
  </div>;
}

function RuleRow({ canWrite, onDuplicate, rule }: { canWrite: boolean; onDuplicate: (opener: HTMLButtonElement) => void; rule: AdminRuleSet }) {
  const revision = rule.draft_revision ?? rule.published_revision; const name = revision?.config?.name ?? rule.id;
  return <li className="rule-set-row"><div className="rule-set-identity"><strong>{name}</strong><small>{rule.id}</small></div><div className="rule-set-status-cell"><span className={`rule-set-status is-${rule.status}`}>{STATUS_LABELS[rule.status]}</span>{rule.is_default ? <span className="rule-set-default-badge">默认规则</span> : null}</div><div className="rule-set-composition"><strong>{revision?.player_count ?? 0} 人</strong><small>{revision?.role_summary ?? "暂无角色摘要"}</small></div><div className="rule-set-version"><strong>草稿修订 {rule.draft_revision?.revision_no ?? "无"} · 发布修订 {rule.published_revision?.revision_no ?? "无"}</strong><small>展示顺序 {rule.display_order} · 更新时间 {formatDate(rule.updated_at)}</small></div><div className="rule-set-row-actions">{canWrite ? <button aria-label={`复制 ${name}`} className="admin-text-button" onClick={(event: MouseEvent<HTMLButtonElement>) => onDuplicate(event.currentTarget)} type="button">复制</button> : null}<Link aria-label={`查看 ${name}`} className="admin-secondary-link" to={`/content/rules/${encodeURIComponent(rule.id)}`}>查看</Link></div></li>;
}

function DuplicateDialog({ close, idPattern, onSuccess, repository, source }: { close: () => void; idPattern: string; onSuccess: (id: string) => Promise<void>; repository: ReturnType<typeof useRuleSetRepository>; source: AdminRuleSet }) {
  const [errors, setErrors] = useState<{ id?: string; name?: string }>({});
  const firstField = useRef<InputRef>(null); const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => { firstField.current?.focus(); }, []);
  const mutation = useMutation({ mutationFn: ({ id, name }: { id: string; name: string }) => repository.duplicate(source.id, { expected_source_lock_version: source.lock_version, new_rule_set_id: id, new_name: name }), onSuccess: (_, values) => onSuccess(values.id) });
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); const id = String(form.get("id") ?? "").trim(); const name = String(form.get("name") ?? "").trim(); const next = { id: new RegExp(idPattern).test(id) ? undefined : "请输入有效的新规则 ID", name: name ? undefined : "请输入新规则名称" }; setErrors(next); if (!next.id && !next.name) mutation.mutate({ id, name }); }
  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) { if (event.key === "Escape") { event.preventDefault(); close(); return; } if (event.key !== "Tab") return; const focusable = Array.from(dialog.current?.querySelectorAll<HTMLElement>('input, button:not([disabled])') ?? []); if (!focusable.length) return; const first = focusable[0]; const last = focusable[focusable.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } }
  return <div aria-describedby="duplicate-rule-description" aria-labelledby="duplicate-rule-title" aria-modal="true" className="rule-set-dialog-backdrop" onKeyDown={handleKeyDown} ref={dialog} role="dialog"><form className="rule-set-dialog" onSubmit={submit}><h2 id="duplicate-rule-title">复制游戏规则</h2><p id="duplicate-rule-description">从 {source.id} 创建独立草稿。</p><label><span>新规则 ID</span><Input aria-label="新规则 ID" aria-describedby={errors.id ? "duplicate-id-error" : undefined} aria-invalid={Boolean(errors.id)} name="id" ref={firstField} />{errors.id ? <small id="duplicate-id-error">{errors.id}</small> : null}</label><label><span>新规则名称</span><Input aria-label="新规则名称" aria-describedby={errors.name ? "duplicate-name-error" : undefined} aria-invalid={Boolean(errors.name)} name="name" />{errors.name ? <small id="duplicate-name-error">{errors.name}</small> : null}</label>{mutation.isError ? <p role="alert">{presentRuleSetError(mutation.error, "duplicate")}</p> : null}<div className="rule-set-dialog-actions"><button onClick={close} type="button">取消</button><button disabled={mutation.isPending} type="submit">确认复制</button></div></form></div>;
}

function playerCounts(minimum: number, maximum: number) { return Array.from({ length: maximum - minimum + 1 }, (_, index) => minimum + index); }
function formatDate(value: string) { return value.replace("T", " ").replace(/Z$/, ""); }

function Loading() { return <div aria-live="polite" className="rule-set-list-loading" role="status"><span /><span /><span /><p>正在读取游戏规则...</p></div>; }
function ErrorState({ error, retry }: { error: Error; retry: () => unknown }) { return <div aria-live="assertive" className="rule-set-list-error" role="alert"><h3>无法读取游戏规则</h3><p>{presentRuleSetError(error, "list")}</p>{isAdminApiError(error) && error.requestId ? <small>请求编号：{error.requestId}</small> : null}<button onClick={() => void retry()} type="button">重新加载</button></div>; }
function OptionsUnavailable({ retry }: { retry: () => unknown }) { return <div className="admin-page" role="alert"><h1>规则选项暂时不可用</h1><p>无法安全读取筛选与操作约束，暂不加载规则列表。</p><button onClick={() => void retry()} type="button">重新加载规则选项</button></div>; }
export function RuleSetNewPage() { return <RuleSetEditorPage />; }
export function RuleSetDetailPage() { return <RuleSetEditorPage />; }
