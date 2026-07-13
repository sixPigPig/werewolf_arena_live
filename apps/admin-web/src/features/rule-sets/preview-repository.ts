import { AdminApiError } from "@/api/problem-details";
import { cleanRuleSetInput, playerCount, roleSummary, validateRuleSetInput } from "./form";
import { fixtureDetail, fixtureRevision, fixtureRuleSet, ruleSetOptions, standardConfig } from "./test-fixtures";
import type { AdminRuleSet, AdminRuleSetDetail, ArchiveRuleSetRequest, CreateRuleSetRequest, DuplicateRuleSetRequest, PublishRuleSetRequest, RuleSetListParams, RuleSetRevision, RuleSetTransitionRequest, RuleSetValidation, SetDefaultRuleSetRequest, UpdateRuleSetDraftRequest, ValidateRuleSetRequest } from "./types";

const INITIAL = [fixtureRuleSet("classic_9", "published", true, 1), fixtureRuleSet("classic_12", "published", false, 2), fixtureRuleSet("preview_draft", "draft", false, 3), fixtureRuleSet("archived_rule", "archived", false, 4)].map(fixtureDetail);
INITIAL[0].usage = { game_count: 42, live_count: 2 }; INITIAL[1].usage = { game_count: 18, live_count: 1 };
let rules = structuredClone(INITIAL);

export async function getPreviewRuleSetOptions() { return structuredClone(ruleSetOptions); }
export async function listPreviewRuleSets(params: RuleSetListParams) {
  const q = params.q?.trim().toLocaleLowerCase("zh-Hans-CN") ?? "";
  const filtered = rules.filter((rule) => { const config = activeConfig(rule); return (!q || [rule.id, config?.name, config?.description, ...(config?.rule_tags ?? [])].join(" ").toLocaleLowerCase("zh-Hans-CN").includes(q)) && (!params.status || rule.status === params.status) && (params.player_count === undefined || (rule.draft_revision ?? rule.published_revision)?.player_count === params.player_count); });
  const sorted = filtered.toSorted((a, b) => compare(a, b, params.sort, params.direction)); const start = (params.page - 1) * params.page_size;
  return { items: structuredClone(sorted.slice(start, start + params.page_size)) as AdminRuleSet[], pagination: { page: params.page, page_size: params.page_size, total: sorted.length, pages: sorted.length ? Math.ceil(sorted.length / params.page_size) : 0 } };
}
export async function getPreviewRuleSet(id: string) { return structuredClone(find(id)); }

export async function createPreviewRuleSet(request: CreateRuleSetRequest) {
  if (rules.some((rule) => rule.id === request.id)) throw problem(409, "admin_rule_set_id_conflict", "规则 ID 已存在");
  const errors = validateRuleSetInput(request, ruleSetOptions); if (Object.keys(errors).length) throw validationProblem(errors);
  const now = nowIso(); const config = cleanRuleSetInput(request, ruleSetOptions).config; const revision = makeRevision(request.id, 1, "draft", config, now);
  const rule: AdminRuleSetDetail = { id: request.id, status: "draft", is_default: false, display_order: request.display_order, lock_version: 1, draft_revision: revision, published_revision: null, revisions: [history(revision)], usage: { game_count: 0, live_count: 0 }, warnings: [], created_at: now, updated_at: now };
  rules.unshift(rule); return structuredClone(rule) as AdminRuleSet;
}

export async function duplicatePreviewRuleSet(id: string, request: DuplicateRuleSetRequest) {
  const source = find(id); assertRuleLock(source, request.expected_source_lock_version); const config = activeConfig(source); if (!config) throw problem(409, "admin_rule_set_invalid_state", "源规则没有可复制配置");
  return createPreviewRuleSet({ id: request.new_rule_set_id, display_order: source.display_order, config: { ...structuredClone(config), name: request.new_name.trim() } });
}

export async function updatePreviewRuleSetDraft(id: string, request: UpdateRuleSetDraftRequest) {
  const rule = find(id); assertRuleLock(rule, request.expected_rule_set_lock_version); if (rule.status === "archived") throw problem(409, "admin_rule_set_invalid_state", "归档规则不能编辑");
  if ((rule.draft_revision?.lock_version ?? null) !== request.expected_revision_lock_version) throw lockProblem("规则草稿已更新");
  const input = cleanRuleSetInput({ id, display_order: request.display_order, config: request.config }, ruleSetOptions); const now = nowIso();
  if (rule.draft_revision) { rule.draft_revision = { ...rule.draft_revision, config: input.config, player_count: playerCount(input), role_summary: roleSummary(input, ruleSetOptions), lock_version: rule.draft_revision.lock_version + 1, updated_at: now }; replaceHistory(rule, rule.draft_revision); }
  else { const revision = makeRevision(id, Math.max(0, ...rule.revisions.map((item) => item.revision_no)) + 1, "draft", input.config, now); rule.draft_revision = revision; rule.revisions.unshift(history(revision)); }
  rule.display_order = input.display_order; touch(rule); return structuredClone(rule) as AdminRuleSet;
}

export async function validatePreviewRuleSet(id: string, request: ValidateRuleSetRequest): Promise<RuleSetValidation> {
  const rule = find(id); const draft = rule.draft_revision; if (!draft?.config) throw problem(409, "admin_rule_set_invalid_state", "没有可校验草稿"); if (draft.lock_version !== request.expected_revision_lock_version) throw lockProblem("规则草稿已更新");
  const errors = validateRuleSetInput({ id, display_order: rule.display_order, config: draft.config }, ruleSetOptions); const warnings = Object.entries(errors).map(([path, message]) => ({ code: "invalid_rule_config", path: path === "role_counts" ? "config.role_counts.werewolf" : `config.${path}`, message }));
  return { valid: warnings.length === 0, errors: warnings, warnings: [], content_hash: warnings.length ? null : hashFor(draft), rule_text_preview: warnings.length ? null : `${draft.config.name}（${draft.player_count} 人）` };
}

export async function publishPreviewRuleSet(id: string, request: PublishRuleSetRequest) {
  const rule = find(id); assertRuleLock(rule, request.expected_rule_set_lock_version); assertReason(request.reason); const draft = rule.draft_revision; if (!draft || draft.lock_version !== request.expected_revision_lock_version) throw lockProblem("规则草稿已更新");
  const validation = await validatePreviewRuleSet(id, { expected_revision_lock_version: draft.lock_version }); if (!validation.valid) throw validationProblem(Object.fromEntries(validation.errors.map((item) => [item.path, item.message])));
  const now = nowIso(); if (rule.published_revision) { rule.published_revision.state = "superseded"; replaceHistory(rule, rule.published_revision); }
  const published: RuleSetRevision = { ...structuredClone(draft), state: "published", content_hash: validation.content_hash, published_at: now, published_by: "preview-super-admin", updated_at: now };
  rule.published_revision = published; rule.draft_revision = null; rule.status = "published"; replaceHistory(rule, published); touch(rule); return structuredClone(rule) as AdminRuleSet;
}

export async function setDefaultPreviewRuleSet(id: string, request: SetDefaultRuleSetRequest) {
  const target = find(id); assertRuleLock(target, request.expected_rule_set_lock_version); assertReason(request.reason); if (target.status !== "published") throw problem(409, "admin_rule_set_invalid_state", "只有已发布规则可设为默认"); const previous = rules.find((rule) => rule.is_default);
  if (previous?.id === id) { if (request.previous_default_expected_lock_version !== null && request.previous_default_expected_lock_version !== target.lock_version) throw lockProblem("当前默认规则已更新"); return structuredClone(target) as AdminRuleSet; }
  if (previous) { if (previous.lock_version !== request.previous_default_expected_lock_version) throw lockProblem("当前默认规则已更新"); previous.is_default = false; touch(previous); }
  else if (request.previous_default_expected_lock_version !== null) throw lockProblem("当前没有默认规则");
  target.is_default = true; touch(target); return structuredClone(target) as AdminRuleSet;
}

export async function archivePreviewRuleSet(id: string, request: ArchiveRuleSetRequest) {
  const rule = find(id); assertRuleLock(rule, request.expected_rule_set_lock_version); assertReason(request.reason); if (rule.status === "archived") throw problem(409, "rule_set_unavailable", "规则已经归档");
  const hasReplacementId = request.replacement_default_rule_set_id !== null; const hasReplacementVersion = request.replacement_expected_lock_version !== null;
  if (hasReplacementId !== hasReplacementVersion) throw problem(422, "admin_rule_set_validation_failed", "替代规则 ID 和版本必须同时提供");
  if (rule.is_default) { if (!request.replacement_default_rule_set_id || request.replacement_expected_lock_version === null || request.replacement_default_rule_set_id === id) throw problem(409, "default_rule_required", "默认规则归档时必须指定其他已发布规则"); const replacement = find(request.replacement_default_rule_set_id); assertRuleLock(replacement, request.replacement_expected_lock_version); if (replacement.status !== "published") throw problem(409, "rule_set_unavailable", "替代规则必须已发布"); rule.is_default = false; replacement.is_default = true; touch(replacement); }
  else if (hasReplacementId) throw problem(409, "rule_set_unavailable", "非默认规则归档时不能指定替代规则");
  rule.status = "archived"; touch(rule); return structuredClone(rule) as AdminRuleSet;
}

export async function restorePreviewRuleSet(id: string, request: RuleSetTransitionRequest) { const rule = find(id); assertRuleLock(rule, request.expected_rule_set_lock_version); assertReason(request.reason); if (rule.status !== "archived") throw problem(409, "rule_set_unavailable", "只有归档规则可恢复"); if (rule.published_revision) rule.status = "published"; else if (rule.draft_revision) rule.status = "draft"; else throw problem(409, "rule_revision_changed", "规则没有可恢复版本"); touch(rule); return structuredClone(rule) as AdminRuleSet; }
export function resetPreviewRuleSets(options?: { withoutDefault?: boolean }) { rules = structuredClone(INITIAL); if (options?.withoutDefault) rules.forEach((rule) => { rule.is_default = false; }); }

function activeConfig(rule: AdminRuleSetDetail) { return rule.draft_revision?.config ?? rule.published_revision?.config; }
function find(id: string) { const rule = rules.find((item) => item.id === id); if (!rule) throw problem(404, "admin_rule_set_not_found", "没有找到该规则"); return rule; }
function touch(rule: AdminRuleSetDetail) { rule.lock_version += 1; rule.updated_at = nowIso(); }
function replaceHistory(rule: AdminRuleSetDetail, revision: RuleSetRevision) { const item = history(revision, rule.revisions.find((entry) => entry.id === revision.id)?.usage); rule.revisions = [item, ...rule.revisions.filter((entry) => entry.id !== revision.id)]; }
function history(revision: RuleSetRevision, usage = { game_count: 0, live_count: 0 }) { return { ...structuredClone(revision), usage }; }
function makeRevision(id: string, no: number, state: RuleSetRevision["state"], config: typeof standardConfig, now: string) { const base = fixtureRevision(id, no, state, config); const input = { id, display_order: 0, config }; return { ...base, id: `${id}-r${no}`, lock_version: 1, player_count: playerCount(input), role_summary: roleSummary(input, ruleSetOptions), created_at: now, updated_at: now }; }
function hashFor(revision: RuleSetRevision) { return revision.revision_no.toString(16).padStart(64, "0"); }
function assertRuleLock(rule: AdminRuleSetDetail, expected: number) { if (rule.lock_version !== expected) throw lockProblem("规则已被其他操作者更新"); }
function assertReason(reason: string) { const length = reason.trim().length; if (length < ruleSetOptions.constraints.reason_min_length || length > ruleSetOptions.constraints.reason_max_length) throw problem(422, "admin_rule_set_validation_failed", `操作原因需为 ${ruleSetOptions.constraints.reason_min_length} 到 ${ruleSetOptions.constraints.reason_max_length} 个字符`); }
function compare(a: AdminRuleSetDetail, b: AdminRuleSetDetail, field: RuleSetListParams["sort"], direction: RuleSetListParams["direction"]) { const av = field === "name" ? activeConfig(a)?.name ?? "" : a[field]; const bv = field === "name" ? activeConfig(b)?.name ?? "" : b[field]; const result = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv), "zh-Hans-CN"); return direction === "asc" ? result : -result; }
function validationProblem(errors: Record<string, string>) { return new AdminApiError({ problem: { type: "about:blank", title: "规则校验失败", status: 422, detail: "规则配置未通过校验", code: "admin_rule_set_validation_failed", request_id: null, errors: Object.entries(errors).map(([field, message]) => ({ field, message })) } }); }
function lockProblem(detail: string) { return problem(409, "rule_set_version_conflict", detail); }
function problem(status: number, code: string, detail: string) { return new AdminApiError({ problem: { type: "about:blank", title: "规则操作失败", status, detail, code, request_id: null } }); }
function nowIso() { return new Date().toISOString(); }
