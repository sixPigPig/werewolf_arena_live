import { useQuery, useQueryClient } from "@tanstack/react-query";
import { cloneElement, type FormEvent, isValidElement, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { useBeforeUnload, useBlocker, useNavigate, useParams } from "react-router-dom";
import { isAdminApiError } from "@/api/problem-details";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import { cleanRuleSetInput, defaultRuleSetInput, formErrorsFromApi, inputFromRuleSet, playerCount, roleSummary, validateRuleSetInput, type RuleSetFormErrors, type RuleSetFormInput } from "./form";
import { ruleSetKeys } from "./query-keys";
import { useRuleSetRepository } from "./repository";
import RuleSetTransitionDialog from "./RuleSetTransitionDialog";
import { presentRuleSetError, type RuleSetErrorContext } from "./error-presentation";
import type { AdminRuleSetDetail, RuleContract, RuleContractClause, RuleSetOptions, RuleSetStatus, RuleSetValidation, RuleSetWarning } from "./types";

type ValidationView = RuleSetValidation & { revision_lock_version: number };
type Transition = "publish" | "default" | "archive" | "restore";
const STATUS: Record<RuleSetStatus, string> = { draft: "草稿", published: "已发布", archived: "已归档" };

export default function RuleSetEditorPage() {
  const { ruleSetId } = useParams(); const isNew = !ruleSetId; const repository = useRuleSetRepository();
  const options = useQuery({ queryKey: ruleSetKeys.options, queryFn: ({ signal }) => repository.getOptions(signal), staleTime: 300_000 });
  const detail = useQuery({ queryKey: ruleSetKeys.detail(ruleSetId ?? "new"), queryFn: ({ signal }) => repository.get(ruleSetId!, signal), enabled: !isNew });
  if (options.isPending || (!isNew && detail.isPending)) return <Loading />;
  if (options.isError) return <ErrorState error={options.error} retry={() => options.refetch()} />;
  if (!isNew && detail.isError) return isAdminApiError(detail.error, 404) ? <Message title="没有找到该游戏规则" detail="规则可能已被删除或 ID 不正确。" /> : <ErrorState error={detail.error} retry={() => detail.refetch()} />;
  return <Editor key={ruleSetId ?? "new"} options={options.data} initialDetail={detail.data} isNew={isNew} />;
}

function Editor({ options, initialDetail, isNew }: { options: RuleSetOptions; initialDetail?: AdminRuleSetDetail; isNew: boolean }) {
  const repository = useRuleSetRepository(); const queryClient = useQueryClient(); const navigate = useNavigate(); const { session } = useAdminSession();
  const permissions = session?.permissions ?? []; const canWrite = hasAdminPermission(permissions, "rules.write"); const canPublish = hasAdminPermission(permissions, "rules.publish"); const canSetDefault = hasAdminPermission(permissions, "rules.set_default"); const canArchive = hasAdminPermission(permissions, "rules.archive");
  const [detail, setDetail] = useState(initialDetail); const initial = initialDetail ? inputFromRuleSet(initialDetail, options) : defaultRuleSetInput(options);
  const [draft, setDraft] = useState<RuleSetFormInput>(initial); const [errors, setErrors] = useState<RuleSetFormErrors>({});
  const [requestError, setRequestError] = useState<Error | null>(null); const [requestErrorContext, setRequestErrorContext] = useState<RuleSetErrorContext>("save"); const [conflict, setConflict] = useState(false); const [validation, setValidation] = useState<ValidationView | null>(null);
  const [pending, setPending] = useState<"save" | "validate" | "reload" | null>(null); const [baseline, setBaseline] = useState(JSON.stringify(cleanRuleSetInput(initial, options))); const allowNavigation = useRef(false);
  const [transition, setTransition] = useState<Transition | null>(null); const [transitionOpener, setTransitionOpener] = useState<HTMLButtonElement | null>(null); const [transitionPending, setTransitionPending] = useState(false); const [transitionError, setTransitionError] = useState<string | null>(null); const [announcement, setAnnouncement] = useState<{ id: number; message: string } | null>(null); const announcementSequence = useRef(0);
  const cleaned = cleanRuleSetInput(draft, options); const isDirty = JSON.stringify(cleaned) !== baseline;
  const canQueryPublished = options.statuses.some(({ value }) => value === "published");
  const editable = canWrite && detail?.status !== "archived"; const blocker = useBlocker(({ currentLocation, nextLocation }) => !allowNavigation.current && isDirty && `${currentLocation.pathname}${currentLocation.search}${currentLocation.hash}` !== `${nextLocation.pathname}${nextLocation.search}${nextLocation.hash}`);
  useBeforeUnload(useCallback((event) => { if (isDirty) event.preventDefault(); }, [isDirty]), { capture: true });
  const publishedRules = useQuery({ queryKey: [...ruleSetKeys.lists, "transition", detail?.id], queryFn: ({ signal }) => listAllPublishedRules(repository, options, signal), enabled: Boolean(canQueryPublished && detail && (transition === "default" || (transition === "archive" && detail.is_default))) });

  function announce(message: string) { announcementSequence.current += 1; setAnnouncement({ id: announcementSequence.current, message }); }
  function markChanged() { setValidation(null); }
  function changeConfig<K extends keyof RuleSetFormInput["config"]>(key: K, value: RuleSetFormInput["config"][K]) { setDraft((current) => ({ ...current, config: { ...current.config, [key]: value } })); setErrors((current) => ({ ...current, [key]: undefined, form: undefined })); markChanged(); }
  async function save(event: FormEvent) {
    event.preventDefault(); const nextErrors = validateRuleSetInput(draft, options); setErrors(nextErrors); if (Object.keys(nextErrors).length) return;
    setPending("save"); setRequestErrorContext("save"); setRequestError(null); setConflict(false);
    try {
      const saved = isNew ? await repository.create(cleaned) : await repository.updateDraft(detail!.id, { expected_rule_set_lock_version: detail!.lock_version, expected_revision_lock_version: detail!.draft_revision?.lock_version ?? null, display_order: cleaned.display_order, config: cleaned.config });
      const fresh = await repository.get(saved.id); setDetail(fresh); const next = inputFromRuleSet(fresh, options); setDraft(next); setBaseline(JSON.stringify(cleanRuleSetInput(next, options)));
      await Promise.all([queryClient.invalidateQueries({ queryKey: ruleSetKeys.lists }), queryClient.invalidateQueries({ queryKey: ruleSetKeys.detail(saved.id) })]);
      if (isNew) { allowNavigation.current = true; navigate(`/content/rules/${encodeURIComponent(saved.id)}`); }
      else announce("草稿已保存");
    } catch (error) { setErrors(formErrorsFromApi(error)); if (isAdminApiError(error) && (error.status === 409 || error.status === 412)) setConflict(true); setRequestError(error as Error); }
    finally { setPending(null); }
  }
  async function validateSaved() {
    const revision = detail?.draft_revision; if (!revision) return; setPending("validate"); setRequestErrorContext("validate"); setRequestError(null);
    try { const result = await repository.validate(detail.id, { expected_revision_lock_version: revision.lock_version }); setValidation({ ...result, revision_lock_version: revision.lock_version }); setErrors(formErrorsFromApi({ warnings: result.errors })); announce(result.valid ? "规则校验通过" : "规则校验未通过"); }
    catch (error) { setErrors(formErrorsFromApi(error)); setRequestError(error as Error); }
    finally { setPending(null); }
  }
  async function reload() { if (!detail || pending) return; setPending("reload"); setRequestErrorContext("reload"); setRequestError(null); try { const fresh = await repository.get(detail.id); setDetail(fresh); const next = inputFromRuleSet(fresh, options); setDraft(next); setBaseline(JSON.stringify(cleanRuleSetInput(next, options))); setConflict(false); setValidation(null); } catch (error) { setRequestError(error as Error); } finally { setPending(null); } }

  function openTransition(next: Transition, opener: HTMLButtonElement) { if (transitionPending || isDirty) return; setTransitionError(null); setTransitionOpener(opener); setTransition(next); }
  function closeTransition() { if (transitionPending) return; setTransition(null); setTransitionOpener(null); }
  async function confirmTransition(reason: string, replacementId: string | null) {
    if (!detail || !transition || transitionPending) return; setTransitionPending(true); setTransitionError(null); setAnnouncement(null);
    try {
      if (transition === "publish") {
        const revision = detail.draft_revision; if (!revision || !validation?.valid || validation.revision_lock_version !== revision.lock_version || isDirty) return;
        await repository.publish(detail.id, { expected_rule_set_lock_version: detail.lock_version, expected_revision_lock_version: revision.lock_version, reason });
      } else if (transition === "default") {
        if (publishedRules.isFetching || publishedRules.isError || !publishedRules.data) return;
        const previousDefault = publishedRules.data?.items.find((rule) => rule.is_default);
        await repository.setDefault(detail.id, { expected_rule_set_lock_version: detail.lock_version, previous_default_expected_lock_version: previousDefault?.lock_version ?? null, reason });
      } else if (transition === "archive") {
        if (detail.is_default && (publishedRules.isFetching || publishedRules.isError || !publishedRules.data)) return;
        const replacement = detail.is_default ? publishedRules.data?.items.find((rule) => rule.id === replacementId) : undefined;
        if (detail.is_default && !replacement) return;
        await repository.archive(detail.id, { expected_rule_set_lock_version: detail.lock_version, replacement_default_rule_set_id: replacement?.id ?? null, replacement_expected_lock_version: replacement?.lock_version ?? null, reason });
      } else {
        await repository.restore(detail.id, { expected_rule_set_lock_version: detail.lock_version, reason });
      }
      const completed = transition; const fresh = await repository.get(detail.id); setDetail(fresh); const next = inputFromRuleSet(fresh, options); setDraft(next); setBaseline(JSON.stringify(cleanRuleSetInput(next, options))); setValidation(null); setConflict(false); setTransition(null); setTransitionOpener(null);
      await Promise.all([queryClient.invalidateQueries({ queryKey: ruleSetKeys.lists }), queryClient.invalidateQueries({ queryKey: ruleSetKeys.detail(detail.id) })]);
      announce({ publish: "规则已发布", default: "已设为默认规则", archive: "规则已归档", restore: "规则已恢复" }[completed]);
    } catch (error) { setTransitionError(transitionMessage(error)); }
    finally { setTransitionPending(false); }
  }

  const transitionCandidates = (publishedRules.data?.items ?? []).filter((rule) => rule.id !== detail?.id);
  const transitionDialog = transition ? transitionPresentation(transition) : null;
  const displayedContract = validation?.rule_contract ?? detail?.rule_contract;

  return <div className="admin-page rule-set-editor-page"><header className="page-heading rule-set-heading"><div><span className="page-kicker">CONTENT / RULES</span><h1>{isNew ? "新建游戏规则" : "游戏规则详情"}</h1>{detail ? <p><span>{STATUS[detail.status]}</span>{detail.is_default ? " · 默认规则" : ""} · 规则锁版本 {detail.lock_version} · 草稿版本 {detail.draft_revision?.revision_no ?? "无"}</p> : <p>创建结构化规则草稿</p>}</div>{!editable ? <span className="page-readiness-badge">只读权限</span> : null}</header>
    <div className="rule-set-editor-layout"><div className="rule-set-editor-main">
    {announcement ? <p aria-live="polite" className="rule-set-notice" key={announcement.id} role="status">{announcement.message}</p> : null}
    <form className="rule-set-form" onSubmit={save}><fieldset disabled={!editable || pending !== null}><legend>结构化规则配置</legend>
      <Field label="规则 ID" error={errors.id}><input aria-label="规则 ID" onChange={(e) => { setDraft({ ...draft, id: e.target.value }); markChanged(); }} readOnly={!isNew} value={draft.id} /></Field>
      <Field label="显示顺序" error={errors.display_order}><input aria-label="显示顺序" min="0" onChange={(e) => { setDraft({ ...draft, display_order: e.target.valueAsNumber }); markChanged(); }} type="number" value={draft.display_order} /></Field>
      <Text label="规则名称" value={draft.config.name} onChange={(v) => changeConfig("name", v)} error={errors.name} />
      <Field label="规则说明" error={errors.description}><textarea aria-label="规则说明" onChange={(e) => changeConfig("description", e.target.value)} value={draft.config.description} /></Field>
      <Text label="复杂度" value={draft.config.complexity} onChange={(v) => changeConfig("complexity", v)} error={errors.complexity} />
      <Text label="预计时长" value={draft.config.estimated_duration} onChange={(v) => changeConfig("estimated_duration", v)} error={errors.estimated_duration} />
      <Text label="规则标签" value={draft.config.rule_tags.join("，")} onChange={(v) => changeConfig("rule_tags", v.split(/[,，]/))} error={errors.rule_tags} />
      <fieldset className="rule-set-role-grid" aria-describedby={errors.role_counts ? "rule-error-role-counts" : undefined} aria-invalid={Boolean(errors.role_counts)}><legend>角色数量</legend>{options.roles.map((role) => <Field key={role.id} label={`${role.label}数量`}><input aria-describedby={errors.role_counts ? "rule-error-role-counts" : undefined} aria-invalid={Boolean(errors.role_counts)} aria-label={`${role.label}数量`} data-testid="role-count" max={role.max_count} min={role.min_count} onChange={(e) => changeConfig("role_counts", { ...draft.config.role_counts, [role.id]: e.target.valueAsNumber })} type="number" value={draft.config.role_counts[role.id]} /></Field>)}{errors.role_counts ? <p id="rule-error-role-counts" role="alert">{errors.role_counts}</p> : null}<p>总人数：{playerCount(draft)} 人</p><p>{roleSummary(draft, options) || "暂无角色"}</p></fieldset>
      <Choice label="胜利条件" value={draft.config.win_condition} choices={options.win_conditions} onChange={(v) => changeConfig("win_condition", v as typeof draft.config.win_condition)} error={errors.win_condition} />
      <Check label="启用警长" checked={draft.config.sheriff_enabled} onChange={(v) => changeConfig("sheriff_enabled", v)} />
      <Field label="警长票权" error={errors.sheriff_vote_weight}><select aria-label="警长票权" disabled={!draft.config.sheriff_enabled} onChange={(e) => changeConfig("sheriff_vote_weight", Number(e.target.value))} value={draft.config.sheriff_enabled ? draft.config.sheriff_vote_weight : options.sheriff_vote_weights[0]}>{options.sheriff_vote_weights.map((v) => <option key={v} value={v}>{v}</option>)}</select></Field>
      <Choice label="发言规则" value={draft.config.speech_policy} choices={options.speech_policies} onChange={(v) => changeConfig("speech_policy", v as typeof draft.config.speech_policy)} error={errors.speech_policy} />
      <Check label="允许狼人自爆" checked={draft.config.werewolf_self_explosion_enabled} onChange={(v) => changeConfig("werewolf_self_explosion_enabled", v)} />
      <Field label="警徽规则" error={errors.sheriff_badge_bomb_policy}><select aria-label="警徽规则" disabled={!draft.config.sheriff_enabled} onChange={(e) => changeConfig("sheriff_badge_bomb_policy", e.target.value as typeof draft.config.sheriff_badge_bomb_policy)} value={draft.config.sheriff_enabled ? draft.config.sheriff_badge_bomb_policy : options.sheriff_badge_bomb_policies[0]?.value}>{options.sheriff_badge_bomb_policies.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}</select></Field>
    </fieldset>{errors.form ? <p className="rule-set-error" role="alert">{errors.form}</p> : null}{requestError ? <p className="rule-set-error" role="alert">{presentRuleSetError(requestError, requestErrorContext)}</p> : null}{editable ? <div className="rule-set-form-actions"><button disabled={pending !== null} type="submit">保存草稿</button><button disabled={isNew || isDirty || !detail?.draft_revision || pending !== null} onClick={() => void validateSaved()} type="button">校验规则</button>{canPublish ? <button disabled={!validation?.valid || validation.revision_lock_version !== detail?.draft_revision?.lock_version || isDirty || pending !== null} onClick={(event) => openTransition("publish", event.currentTarget)} type="button">发布规则</button> : null}</div> : null}</form>
    {conflict ? <section className="rule-set-conflict" role="alert"><h2>规则版本冲突</h2><p>本地草稿已保留，请重新加载服务器版本后再合并。</p><button disabled={pending !== null} onClick={() => void reload()} type="button">{pending === "reload" ? "正在重新加载..." : "重新加载服务器版本"}</button></section> : null}
    {displayedContract ? <RuleContractPanel contract={displayedContract} /> : null}
    </div><aside aria-label="规则摘要" className="rule-set-summary"><section><h2>配置摘要</h2><p>配置人数：{playerCount(draft)} 人</p><p>阵容：{roleSummary(draft, options) || "暂无角色"}</p>{detail ? <><p>生命周期：{STATUS[detail.status]}{detail.is_default ? " · 默认规则" : ""}</p><p>当前草稿修订：{revisionSummary(detail.draft_revision)}</p><p>当前发布修订：{revisionSummary(detail.published_revision)}</p><p>累计使用：{detail.usage.game_count} 场游戏 / {detail.usage.live_count} 场直播</p>{detail.warnings.map((warning) => <p key={`${warning.code}-${warning.path}`} role="alert">{warning.message}</p>)}</> : <p>尚未保存的新规则</p>}</section>
    <div className="rule-set-lifecycle-actions">{detail && canSetDefault && detail.status === "published" && !detail.is_default ? <button disabled={transitionPending || isDirty || !canQueryPublished} onClick={(event) => openTransition("default", event.currentTarget)} type="button">设为默认</button> : null}
    {detail && canArchive && detail.status !== "archived" ? <button disabled={transitionPending || isDirty || (detail.is_default && !canQueryPublished)} onClick={(event) => openTransition("archive", event.currentTarget)} type="button">归档规则</button> : null}
    {detail && canArchive && detail.status === "archived" ? <button disabled={transitionPending || isDirty} onClick={(event) => openTransition("restore", event.currentTarget)} type="button">恢复规则</button> : null}</div>{detail && isDirty && (canSetDefault || canArchive) ? <p role="status">请先保存草稿或放弃修改，再执行生命周期操作。</p> : null}
    {detail && !canQueryPublished && ((canSetDefault && detail.status === "published" && !detail.is_default) || (canArchive && detail.is_default)) ? <p role="status">规则选项未提供已发布规则查询，暂不能执行相关生命周期操作。</p> : null}
    {validation ? <section aria-label="校验结果" className="rule-set-validation"><h2>{validation.valid ? "校验通过" : "校验失败"}</h2>{validation.errors.length ? <ul aria-label="校验错误">{validation.errors.map((warning) => <li key={`${warning.code}-${warning.path}`}><Warning warning={warning} /></li>)}</ul> : null}{validation.warnings.length ? <ul aria-label="校验警告">{validation.warnings.map((warning) => <li key={`${warning.code}-${warning.path}`}><Warning warning={warning} /></li>)}</ul> : null}{validation.content_hash ? <p>内容哈希：{validation.content_hash.slice(0, 12)}</p> : null}{validation.rule_text_preview ? <pre>{validation.rule_text_preview}</pre> : null}</section> : null}</aside></div>
    {transitionDialog ? <RuleSetTransitionDialog candidates={transition === "archive" && detail?.is_default ? transitionCandidates : undefined} candidatesError={publishedRules.isError} candidatesPending={publishedRules.isFetching} confirmLabel={transitionDialog.confirmLabel} description={transitionDialog.description} error={transitionError} onCancel={closeTransition} onConfirm={(reason, replacementId) => void confirmTransition(reason, replacementId)} opener={transitionOpener} pending={transitionPending} pendingLabel={transitionDialog.pendingLabel} reasonMaxLength={options.constraints.reason_max_length} reasonMinLength={options.constraints.reason_min_length} requiresReplacement={transition === "archive" && detail?.is_default} title={transitionDialog.title} /> : null}
    {blocker.state === "blocked" ? <UnsavedChangesDialog onDiscard={() => blocker.proceed()} onKeepEditing={() => blocker.reset()} /> : null}
    {detail ? <section className="rule-set-history"><h2>版本历史</h2><div aria-label="版本历史横向滚动区" className="rule-set-history-scroll" tabIndex={0}><ul aria-label="版本历史">{detail.revisions.slice(0, 50).map((revision) => <li key={revision.id}>版本 {revision.revision_no} · {revision.state} · 发布时间：{revision.published_at ? formatDate(revision.published_at) : "未发布"} · 发布人：{revision.published_by ?? "无"} · 哈希前缀：{revision.content_hash?.slice(0, 12) ?? "无"} · {revision.usage.game_count} 场游戏 / {revision.usage.live_count} 场直播</li>)}</ul></div></section> : null}
  </div>;
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) { const id = `rule-error-${label.replaceAll(" ", "-")}`; const control = isValidElement<Record<string, unknown>>(children) ? cloneElement(children, { "aria-invalid": error ? true : children.props["aria-invalid"] ?? false, "aria-describedby": error ? id : children.props["aria-describedby"] }) : children; return <label className="rule-set-field"><span>{label}</span>{control}{error ? <small id={id} role="alert">{error}</small> : null}</label>; }
function Text({ label, value, onChange, error }: { label: string; value: string; onChange: (v: string) => void; error?: string }) { return <Field label={label} error={error}><input aria-label={label} onChange={(e) => onChange(e.target.value)} value={value} /></Field>; }
function Choice({ label, value, choices, onChange, error }: { label: string; value: string; choices: { value: string; label: string }[]; onChange: (v: string) => void; error?: string }) { return <Field label={label} error={error}><select aria-label={label} onChange={(e) => onChange(e.target.value)} value={value}>{choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}</select></Field>; }
function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) { return <label className="rule-set-check"><input aria-label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} type="checkbox" />{label}</label>; }
function UnsavedChangesDialog({ onDiscard, onKeepEditing }: { onDiscard: () => void; onKeepEditing: () => void }) {
  const dialog = useRef<HTMLElement>(null); const keepEditing = useRef<HTMLButtonElement>(null); const origin = useRef<HTMLElement | null>(null);
  useEffect(() => { origin.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; keepEditing.current?.focus(); return () => origin.current?.focus(); }, []);
  function close() { onKeepEditing(); }
  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") { event.preventDefault(); close(); return; }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialog.current?.querySelectorAll<HTMLElement>("button:not([disabled])") ?? []); const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  return <div className="rule-set-dialog-backdrop"><section aria-describedby="unsaved-rule-description" aria-labelledby="unsaved-rule-title" aria-modal="true" className="rule-set-dialog" onKeyDown={handleKeyDown} ref={dialog} role="dialog"><h2 id="unsaved-rule-title">未保存规则</h2><p id="unsaved-rule-description">继续离开将放弃本次尚未保存的修改。</p><div className="rule-set-dialog-actions"><button onClick={close} ref={keepEditing} type="button">继续编辑</button><button onClick={onDiscard} type="button">放弃修改并离开</button></div></section></div>;
}
function Warning({ warning }: { warning: RuleSetWarning }) { return <p>{warning.path ? `${warning.path}：` : ""}{warning.message}</p>; }
function RuleContractPanel({ contract }: { contract: RuleContract }) {
  return <section aria-labelledby="rule-contract-title" className="rule-contract-panel">
    <header><div><h2 id="rule-contract-title">规则契约与引擎覆盖</h2><p>只读代码契约，不支持在此编辑模型 Prompt。</p></div><span className={`rule-contract-readiness ${contract.publish_ready ? "is-covered" : "is-broken"}`}>{contract.publish_ready ? "可发布" : "阻止发布"}</span></header>
    <dl className="rule-contract-meta"><div><dt>Schema</dt><dd>{contract.schema_version}</dd></div><div><dt>契约修订</dt><dd>{contract.revision_id}</dd></div><div><dt>Canonical hash</dt><dd><code>{contract.canonical_hash.slice(0, 12)}</code></dd></div><div><dt>总体覆盖</dt><dd>{contract.coverage_status === "covered" ? "完整" : "断链"}</dd></div></dl>
    {contract.missing_p0_clause_ids.length ? <div className="rule-contract-blockers" role="alert"><strong>缺失 P0 条款</strong><ul>{contract.missing_p0_clause_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul></div> : null}
    {contract.broken_engine_constraint_ids.length ? <div className="rule-contract-blockers" role="alert"><strong>断链的引擎约束</strong><ul>{contract.broken_engine_constraint_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul></div> : null}
    <div className="rule-contract-table-scroll" tabIndex={0}><table aria-label="规则条款与引擎约束覆盖"><thead><tr><th>级别 / 条款</th><th>角色 / 阶段 / 动作</th><th>Audience</th><th>Engine constraints</th><th>模型规则文本</th><th>覆盖</th></tr></thead><tbody>{contract.clauses.map((clause) => <RuleContractRow clause={clause} key={clause.clause_id} />)}</tbody></table></div>
  </section>;
}
function RuleContractRow({ clause }: { clause: RuleContractClause }) {
  const scope = [{ label: "角色", values: clause.roles }, { label: "阶段", values: clause.phases }, { label: "动作", values: clause.actions }].filter(({ values }) => values.length).map(({ label, values }) => `${label}：${values.join("、")}`).join("；") || "全部适用";
  const audience = { player_public: "玩家公开", role_private: "角色私有", internal_only: "仅内部" }[clause.audience];
  return <tr><td><strong>{clause.priority}</strong><code>{clause.clause_id}</code></td><td>{scope}</td><td>{audience}</td><td><ul>{clause.engine_constraint_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul></td><td>{clause.model_rule_text ?? <em>不进入模型规则</em>}</td><td><span className={clause.coverage_status === "covered" ? "is-covered" : "is-broken"}>{clause.coverage_status === "covered" ? "已覆盖" : "断链"}</span>{clause.uncovered_engine_constraint_ids.map((id) => <code key={id}>{id}</code>)}</td></tr>;
}
function Loading() { return <div aria-live="polite" role="status">正在读取游戏规则...</div>; }
function Message({ title, detail }: { title: string; detail: string }) { return <div className="admin-page" role="alert"><h1>{title}</h1><p>{detail}</p></div>; }
function ErrorState({ error, retry }: { error: Error; retry: () => unknown }) { return <div className="admin-page" role="alert"><h1>无法读取游戏规则</h1><p>{presentRuleSetError(error, "load")}</p><button onClick={() => void retry()} type="button">重新加载</button></div>; }

function transitionPresentation(transition: Transition) { return {
  publish: { title: "发布规则", description: "发布已保存且通过服务器校验的当前草稿。", confirmLabel: "确认发布", pendingLabel: "正在发布..." },
  default: { title: "设为默认规则", description: "将这套已发布规则设为当前默认规则。", confirmLabel: "确认设为默认", pendingLabel: "正在设置..." },
  archive: { title: "归档规则", description: "归档后规则将停止用于新的游戏。", confirmLabel: "确认归档", pendingLabel: "正在归档..." },
  restore: { title: "恢复规则", description: "恢复后的状态和可编辑性以服务器返回为准。", confirmLabel: "确认恢复", pendingLabel: "正在恢复..." },
}[transition]; }

function transitionMessage(error: unknown) {
  if (isAdminApiError(error, 409) || isAdminApiError(error, 412)) return "规则状态已发生变化。本地内容未被修改，请关闭对话框并刷新后重试。";
  if (isAdminApiError(error, 422)) return "操作原因或规则状态不符合要求，请修改后重试。";
  if (isAdminApiError(error, 503)) return "暂时无法完成操作，请稍后重试。";
  return "无法完成操作，请检查后重试。";
}

function revisionSummary(revision: AdminRuleSetDetail["draft_revision"]) { return revision ? `${revision.revision_no} · 哈希前缀：${revision.content_hash?.slice(0, 12) ?? "无"}` : "无"; }
function formatDate(value: string) { return value.replace("T", " ").replace(/Z$/, ""); }

async function listAllPublishedRules(repository: ReturnType<typeof useRuleSetRepository>, options: RuleSetOptions, signal: AbortSignal) {
  const signedSort = options.sorts[0].value; const params = { page_size: 100, status: "published" as const, sort: signedSort.replace(/^-/, "") as "display_order" | "updated_at" | "name" | "created_at", direction: signedSort.startsWith("-") ? "desc" as const : "asc" as const };
  const first = await repository.list({ ...params, page: 1 }, signal); const items = [...first.items]; let pages = first.pagination.pages;
  for (let page = 2; page <= pages; page += 1) { const next = await repository.list({ ...params, page }, signal); items.push(...next.items); pages = Math.max(pages, next.pagination.pages); }
  items.sort((left, right) => left.display_order - right.display_order || (left.id < right.id ? -1 : left.id > right.id ? 1 : 0));
  return { ...first, items };
}
