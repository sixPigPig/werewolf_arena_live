import type { AdminRuleSetDetail, RuleRoleId, RuleSetConfig, RuleSetOptions } from "./types";

export type RuleSetFormInput = { id: string; display_order: number; config: RuleSetConfig };
export type RuleSetFormErrors = Partial<Record<"id" | "display_order" | "name" | "description" | "complexity" | "estimated_duration" | "rule_tags" | "role_counts" | "win_condition" | "sheriff_vote_weight" | "speech_policy" | "sheriff_badge_bomb_policy" | "form", string>>;

export function defaultRuleSetInput(options: RuleSetOptions): RuleSetFormInput {
  const roleCounts = Object.fromEntries(options.roles.map((role) => [role.id, role.min_count])) as Record<RuleRoleId, number>;
  return { id: "", display_order: 0, config: { name: "", description: "", complexity: "", estimated_duration: "", rule_tags: [], role_counts: roleCounts, win_condition: options.win_conditions[0].value, sheriff_enabled: true, sheriff_vote_weight: options.sheriff_vote_weights[0], speech_policy: options.speech_policies[0].value, werewolf_self_explosion_enabled: true, sheriff_badge_bomb_policy: options.sheriff_badge_bomb_policies[0].value } };
}

export function inputFromRuleSet(detail: AdminRuleSetDetail, options: RuleSetOptions): RuleSetFormInput {
  const config = detail.draft_revision?.config ?? detail.published_revision?.config;
  return config ? { id: detail.id, display_order: detail.display_order, config: structuredClone(config) } : defaultRuleSetInput(options);
}

export function cleanRuleSetInput(input: RuleSetFormInput, options: RuleSetOptions): RuleSetFormInput {
  const roleIds = new Set(options.roles.map((role) => role.id));
  const roles = Object.fromEntries(Object.entries(input.config.role_counts).filter(([id]) => roleIds.has(id as RuleRoleId)).map(([id, count]) => [id, Math.max(0, Math.trunc(finite(count)))])) as Record<RuleRoleId, number>;
  const tags = [...new Set(input.config.rule_tags.flatMap((tag) => tag.split(/[,，]/)).map((tag) => tag.trim()).filter(Boolean))];
  const sheriffEnabled = Boolean(input.config.sheriff_enabled);
  return { id: input.id.trim(), display_order: Math.max(0, Math.trunc(finite(input.display_order))), config: { ...input.config, name: input.config.name.trim(), description: input.config.description.trim(), complexity: input.config.complexity.trim(), estimated_duration: input.config.estimated_duration.trim(), rule_tags: tags, role_counts: roles, sheriff_enabled: sheriffEnabled, sheriff_vote_weight: sheriffEnabled ? finite(input.config.sheriff_vote_weight) : options.sheriff_vote_weights[0], sheriff_badge_bomb_policy: sheriffEnabled ? input.config.sheriff_badge_bomb_policy : options.sheriff_badge_bomb_policies[0].value } };
}

export function playerCount(input: RuleSetFormInput) { return Object.values(input.config.role_counts).reduce((sum, count) => sum + Math.max(0, Math.trunc(finite(count))), 0); }

export function roleSummary(input: RuleSetFormInput, options: RuleSetOptions) {
  return options.roles.map((role) => ({ label: role.label, count: Math.max(0, Math.trunc(finite(input.config.role_counts[role.id]))) })).filter(({ count }) => count > 0).map(({ label, count }) => `${count} ${label}`).join(" / ");
}

export function validateRuleSetInput(input: RuleSetFormInput, options: RuleSetOptions): RuleSetFormErrors {
  const clean = cleanRuleSetInput(input, options); const errors: RuleSetFormErrors = {};
  if (!new RegExp(options.constraints.id_pattern).test(clean.id)) errors.id = "规则 ID 格式不正确";
  if (!Number.isInteger(input.display_order) || input.display_order < 0) errors.display_order = "显示顺序必须是非负整数";
  lengthError(errors, "name", clean.config.name, 1, 120); lengthError(errors, "description", clean.config.description, 0, 1000); lengthError(errors, "complexity", clean.config.complexity, 1, 40); lengthError(errors, "estimated_duration", clean.config.estimated_duration, 1, 40);
  if (clean.config.rule_tags.length > options.constraints.tags_max_items || clean.config.rule_tags.some((tag) => tag.length > options.constraints.tag_max_length)) errors.rule_tags = `标签最多 ${options.constraints.tags_max_items} 个，每个不超过 ${options.constraints.tag_max_length} 字符`;
  if (options.roles.some((role) => { const raw = input.config.role_counts[role.id]; return !Number.isInteger(raw) || raw < role.min_count || raw > role.max_count; })) errors.role_counts = "角色数量必须是允许范围内的非负整数";
  if (!options.win_conditions.some(({ value }) => value === clean.config.win_condition)) errors.win_condition = "请选择有效的胜利条件";
  if (clean.config.sheriff_enabled && !options.sheriff_vote_weights.includes(clean.config.sheriff_vote_weight)) errors.sheriff_vote_weight = "请选择有效的警长票权";
  if (!options.speech_policies.some(({ value }) => value === clean.config.speech_policy)) errors.speech_policy = "请选择有效的发言规则";
  if (!options.sheriff_badge_bomb_policies.some(({ value }) => value === clean.config.sheriff_badge_bomb_policy)) errors.sheriff_badge_bomb_policy = "请选择有效的警徽规则";
  const count = playerCount(clean); if (count < options.constraints.player_count_min || count > options.constraints.player_count_max) errors.form = `总人数必须为 ${options.constraints.player_count_min}–${options.constraints.player_count_max} 人`;
  return errors;
}

export function formErrorsFromApi(value: unknown): RuleSetFormErrors {
  const source = isRecord(value) && isRecord(value.problem) ? value.problem : isRecord(value) ? value : {};
  const errors: RuleSetFormErrors = {}; const messages: string[] = [];
  const issues = Array.isArray(source.errors) ? source.errors : Array.isArray(source.warnings) ? source.warnings : [];
  for (const issue of issues) { if (!isRecord(issue) || typeof issue.message !== "string") continue; messages.push(issue.message); const field = fieldFromPath(typeof issue.path === "string" ? issue.path : typeof issue.field === "string" ? issue.field : ""); if (field) errors[field] ??= issue.message; }
  const detail = typeof source.detail === "string" ? source.detail : ""; const summary = [detail, ...messages].filter(Boolean); if (summary.length) errors.form = summary.join("；");
  return errors;
}

function fieldFromPath(path: string): Exclude<keyof RuleSetFormErrors, "form"> | null { const leaf = path.split(/[.[\]]/).filter(Boolean).at(-1) ?? ""; if (leaf in ({ id: 1, display_order: 1, name: 1, description: 1, complexity: 1, estimated_duration: 1, rule_tags: 1, role_counts: 1, win_condition: 1, sheriff_vote_weight: 1, speech_policy: 1, sheriff_badge_bomb_policy: 1 })) return leaf as Exclude<keyof RuleSetFormErrors, "form">; if (path.includes("role_counts")) return "role_counts"; return null; }
function lengthError(errors: RuleSetFormErrors, key: "name" | "description" | "complexity" | "estimated_duration", value: string, min: number, max: number) { if (value.length < min || value.length > max) errors[key] = `${min ? `必填且` : ""}最多 ${max} 个字符`; }
function finite(value: number) { return Number.isFinite(value) ? value : 0; }
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null; }
