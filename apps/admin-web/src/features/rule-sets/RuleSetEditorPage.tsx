import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useCallback, useRef, useState } from "react";
import { useBeforeUnload, useBlocker, useNavigate, useParams } from "react-router-dom";
import { isAdminApiError } from "@/api/problem-details";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import { cleanRuleSetInput, defaultRuleSetInput, formErrorsFromApi, inputFromRuleSet, playerCount, roleSummary, validateRuleSetInput, type RuleSetFormErrors, type RuleSetFormInput } from "./form";
import { ruleSetKeys } from "./query-keys";
import { useRuleSetRepository } from "./repository";
import type { AdminRuleSetDetail, RuleSetOptions, RuleSetStatus, RuleSetValidation, RuleSetWarning } from "./types";

type ValidationView = RuleSetValidation & { revision_lock_version: number };
const STATUS: Record<RuleSetStatus, string> = { draft: "草稿", published: "已发布", archived: "已归档" };

export default function RuleSetEditorPage() {
  const { ruleSetId } = useParams(); const isNew = !ruleSetId; const repository = useRuleSetRepository();
  const options = useQuery({ queryKey: ruleSetKeys.options, queryFn: ({ signal }) => repository.getOptions(signal), staleTime: 300_000 });
  const detail = useQuery({ queryKey: ruleSetKeys.detail(ruleSetId ?? "new"), queryFn: ({ signal }) => repository.get(ruleSetId!, signal), enabled: !isNew });
  if (options.isPending || (!isNew && detail.isPending)) return <Loading />;
  if (options.isError) return <ErrorState error={options.error} retry={() => options.refetch()} />;
  if (!isNew && detail.isError) return isAdminApiError(detail.error, 404) ? <Message title="没有找到该游戏规则" detail="规则可能已被删除或 ID 不正确。" /> : <ErrorState error={detail.error} retry={() => detail.refetch()} />;
  return <Editor options={options.data} initialDetail={detail.data} isNew={isNew} />;
}

function Editor({ options, initialDetail, isNew }: { options: RuleSetOptions; initialDetail?: AdminRuleSetDetail; isNew: boolean }) {
  const repository = useRuleSetRepository(); const queryClient = useQueryClient(); const navigate = useNavigate(); const { session } = useAdminSession();
  const canWrite = hasAdminPermission(session?.permissions ?? [], "rules.write");
  const [detail, setDetail] = useState(initialDetail); const initial = initialDetail ? inputFromRuleSet(initialDetail, options) : defaultRuleSetInput(options);
  const [draft, setDraft] = useState<RuleSetFormInput>(initial); const [errors, setErrors] = useState<RuleSetFormErrors>({});
  const [requestError, setRequestError] = useState<Error | null>(null); const [conflict, setConflict] = useState(false); const [validation, setValidation] = useState<ValidationView | null>(null);
  const [pending, setPending] = useState<"save" | "validate" | null>(null); const [baseline, setBaseline] = useState(JSON.stringify(cleanRuleSetInput(initial, options))); const allowNavigation = useRef(false);
  const cleaned = cleanRuleSetInput(draft, options); const isDirty = JSON.stringify(cleaned) !== baseline;
  const editable = canWrite && detail?.status !== "archived"; const blocker = useBlocker(({ currentLocation, nextLocation }) => !allowNavigation.current && isDirty && currentLocation.pathname !== nextLocation.pathname);
  useBeforeUnload(useCallback((event) => { if (isDirty) event.preventDefault(); }, [isDirty]), { capture: true });

  function markChanged() { setValidation(null); }
  function changeConfig<K extends keyof RuleSetFormInput["config"]>(key: K, value: RuleSetFormInput["config"][K]) { setDraft((current) => ({ ...current, config: { ...current.config, [key]: value } })); setErrors((current) => ({ ...current, [key]: undefined, form: undefined })); markChanged(); }
  async function save(event: FormEvent) {
    event.preventDefault(); const nextErrors = validateRuleSetInput(draft, options); setErrors(nextErrors); if (Object.keys(nextErrors).length) return;
    setPending("save"); setRequestError(null); setConflict(false);
    try {
      const saved = isNew ? await repository.create(cleaned) : await repository.updateDraft(detail!.id, { expected_rule_set_lock_version: detail!.lock_version, expected_revision_lock_version: detail!.draft_revision?.lock_version ?? null, display_order: cleaned.display_order, config: cleaned.config });
      const fresh = await repository.get(saved.id); setDetail(fresh); const next = inputFromRuleSet(fresh, options); setDraft(next); setBaseline(JSON.stringify(cleanRuleSetInput(next, options)));
      await Promise.all([queryClient.invalidateQueries({ queryKey: ruleSetKeys.lists }), queryClient.invalidateQueries({ queryKey: ruleSetKeys.detail(saved.id) })]);
      if (isNew) { allowNavigation.current = true; navigate(`/content/rules/${encodeURIComponent(saved.id)}`); }
    } catch (error) { setErrors(formErrorsFromApi(error)); if (isAdminApiError(error) && (error.status === 409 || error.status === 412)) setConflict(true); setRequestError(error as Error); }
    finally { setPending(null); }
  }
  async function validateSaved() {
    const revision = detail?.draft_revision; if (!revision) return; setPending("validate"); setRequestError(null);
    try { const result = await repository.validate(detail.id, { expected_revision_lock_version: revision.lock_version }); setValidation({ ...result, revision_lock_version: revision.lock_version }); setErrors(formErrorsFromApi({ warnings: result.errors })); }
    catch (error) { setErrors(formErrorsFromApi(error)); setRequestError(error as Error); }
    finally { setPending(null); }
  }
  async function reload() { if (!detail) return; const fresh = await repository.get(detail.id); setDetail(fresh); const next = inputFromRuleSet(fresh, options); setDraft(next); setBaseline(JSON.stringify(cleanRuleSetInput(next, options))); setConflict(false); setRequestError(null); setValidation(null); }

  return <div className="admin-page"><header className="page-heading"><div><span className="page-kicker">CONTENT / RULES</span><h1>{isNew ? "新建游戏规则" : "游戏规则详情"}</h1>{detail ? <p><span>{STATUS[detail.status]}</span>{detail.is_default ? " · 默认规则" : ""} · 规则锁版本 {detail.lock_version} · 草稿版本 {detail.draft_revision?.revision_no ?? "无"}</p> : <p>创建结构化规则草稿</p>}</div>{!editable ? <span className="page-readiness-badge">只读权限</span> : null}</header>
    {detail ? <section aria-label="规则使用情况"><p>累计使用：{detail.usage.game_count} 场游戏 / {detail.usage.live_count} 场直播</p>{detail.warnings.map((warning) => <p key={`${warning.code}-${warning.path}`} role="alert">{warning.message}</p>)}</section> : null}
    <form onSubmit={save}><fieldset disabled={!editable || pending !== null}><legend>结构化规则配置</legend>
      <Field label="规则 ID" error={errors.id}><input aria-label="规则 ID" onChange={(e) => { setDraft({ ...draft, id: e.target.value }); markChanged(); }} readOnly={!isNew} value={draft.id} /></Field>
      <Field label="显示顺序" error={errors.display_order}><input aria-label="显示顺序" min="0" onChange={(e) => { setDraft({ ...draft, display_order: e.target.valueAsNumber }); markChanged(); }} type="number" value={draft.display_order} /></Field>
      <Text label="规则名称" value={draft.config.name} onChange={(v) => changeConfig("name", v)} error={errors.name} />
      <Field label="规则说明" error={errors.description}><textarea aria-label="规则说明" onChange={(e) => changeConfig("description", e.target.value)} value={draft.config.description} /></Field>
      <Text label="复杂度" value={draft.config.complexity} onChange={(v) => changeConfig("complexity", v)} error={errors.complexity} />
      <Text label="预计时长" value={draft.config.estimated_duration} onChange={(v) => changeConfig("estimated_duration", v)} error={errors.estimated_duration} />
      <Text label="规则标签" value={draft.config.rule_tags.join("，")} onChange={(v) => changeConfig("rule_tags", v.split(/[,，]/))} error={errors.rule_tags} />
      <fieldset><legend>角色数量</legend>{options.roles.map((role) => <Field key={role.id} label={`${role.label}数量`}><input aria-label={`${role.label}数量`} data-testid="role-count" max={role.max_count} min={role.min_count} onChange={(e) => changeConfig("role_counts", { ...draft.config.role_counts, [role.id]: e.target.valueAsNumber })} type="number" value={draft.config.role_counts[role.id]} /></Field>)}{errors.role_counts ? <p role="alert">{errors.role_counts}</p> : null}<p>总人数：{playerCount(draft)} 人</p><p>{roleSummary(draft, options) || "暂无角色"}</p></fieldset>
      <Choice label="胜利条件" value={draft.config.win_condition} choices={options.win_conditions} onChange={(v) => changeConfig("win_condition", v as typeof draft.config.win_condition)} />
      <Check label="启用警长" checked={draft.config.sheriff_enabled} onChange={(v) => changeConfig("sheriff_enabled", v)} />
      <Field label="警长票权" error={errors.sheriff_vote_weight}><select aria-label="警长票权" disabled={!draft.config.sheriff_enabled} onChange={(e) => changeConfig("sheriff_vote_weight", Number(e.target.value))} value={draft.config.sheriff_enabled ? draft.config.sheriff_vote_weight : 1}>{options.sheriff_vote_weights.map((v) => <option key={v} value={v}>{v}</option>)}</select></Field>
      <Choice label="发言规则" value={draft.config.speech_policy} choices={options.speech_policies} onChange={(v) => changeConfig("speech_policy", v as typeof draft.config.speech_policy)} />
      <Check label="允许狼人自爆" checked={draft.config.werewolf_self_explosion_enabled} onChange={(v) => changeConfig("werewolf_self_explosion_enabled", v)} />
      <Field label="警徽规则" error={errors.sheriff_badge_bomb_policy}><select aria-label="警徽规则" disabled={!draft.config.sheriff_enabled} onChange={(e) => changeConfig("sheriff_badge_bomb_policy", e.target.value as typeof draft.config.sheriff_badge_bomb_policy)} value={draft.config.sheriff_enabled ? draft.config.sheriff_badge_bomb_policy : "none"}>{options.sheriff_badge_bomb_policies.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}</select></Field>
    </fieldset>{errors.form ? <p role="alert">{errors.form}</p> : null}{requestError ? <p role="alert">{requestError.message}</p> : null}{editable ? <div><button disabled={pending !== null} type="submit">保存草稿</button><button disabled={isNew || isDirty || !detail?.draft_revision || pending !== null} onClick={() => void validateSaved()} type="button">校验规则</button><button disabled={!validation?.valid || isDirty} type="button">发布规则</button></div> : null}</form>
    {conflict ? <section role="alert"><h2>规则版本冲突</h2><p>本地草稿已保留，请重新加载服务器版本后再合并。</p><button onClick={() => void reload()} type="button">重新加载服务器版本</button></section> : null}
    {validation ? <section aria-label="校验结果"><h2>{validation.valid ? "校验通过" : "校验失败"}</h2>{validation.errors.length ? <ul aria-label="校验错误">{validation.errors.map((warning) => <li key={`${warning.code}-${warning.path}`}><Warning warning={warning} /></li>)}</ul> : null}{validation.warnings.length ? <ul aria-label="校验警告">{validation.warnings.map((warning) => <li key={`${warning.code}-${warning.path}`}><Warning warning={warning} /></li>)}</ul> : null}{validation.content_hash ? <p>内容哈希：{validation.content_hash.slice(0, 12)}</p> : null}{validation.rule_text_preview ? <pre>{validation.rule_text_preview}</pre> : null}</section> : null}
    {blocker.state === "blocked" ? <section aria-modal="true" role="dialog" aria-label="未保存规则"><h2>有未保存的规则修改</h2><button onClick={() => blocker.reset()} type="button">继续编辑</button><button onClick={() => blocker.proceed()} type="button">放弃修改并离开</button></section> : null}
    {detail ? <section><h2>版本历史</h2><ul aria-label="版本历史">{detail.revisions.slice(0, 50).map((revision) => <li key={revision.id}>版本 {revision.revision_no} · {revision.state} · {revision.usage.game_count} 场游戏 / {revision.usage.live_count} 场直播</li>)}</ul></section> : null}
  </div>;
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) { return <label><span>{label}</span>{children}{error ? <small role="alert">{error}</small> : null}</label>; }
function Text({ label, value, onChange, error }: { label: string; value: string; onChange: (v: string) => void; error?: string }) { return <Field label={label} error={error}><input aria-label={label} onChange={(e) => onChange(e.target.value)} value={value} /></Field>; }
function Choice({ label, value, choices, onChange }: { label: string; value: string; choices: { value: string; label: string }[]; onChange: (v: string) => void }) { return <Field label={label}><select aria-label={label} onChange={(e) => onChange(e.target.value)} value={value}>{choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}</select></Field>; }
function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) { return <label><input aria-label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} type="checkbox" />{label}</label>; }
function Warning({ warning }: { warning: RuleSetWarning }) { return <p>{warning.path ? `${warning.path}：` : ""}{warning.message}</p>; }
function Loading() { return <div aria-live="polite" role="status">正在读取游戏规则...</div>; }
function Message({ title, detail }: { title: string; detail: string }) { return <div className="admin-page" role="alert"><h1>{title}</h1><p>{detail}</p></div>; }
function ErrorState({ error, retry }: { error: Error; retry: () => unknown }) { return <div className="admin-page" role="alert"><h1>无法读取游戏规则</h1><p>{error.message}</p><button onClick={() => void retry()} type="button">重新加载</button></div>; }
