import type { AdminRuleSet, AdminRuleSetDetail, RuleSetConfig, RuleSetOptions, RuleSetRevision } from "./types";

export const ruleSetOptions: RuleSetOptions = {
  roles: [
    { id: "werewolf", label: "狼人", min_count: 1, max_count: 5 }, { id: "villager", label: "村民", min_count: 0, max_count: 11 },
    { id: "seer", label: "预言家", min_count: 0, max_count: 1 }, { id: "guard", label: "守卫", min_count: 0, max_count: 1 },
    { id: "witch", label: "女巫", min_count: 0, max_count: 1 }, { id: "hunter", label: "猎人", min_count: 0, max_count: 1 },
    { id: "idiot", label: "白痴", min_count: 0, max_count: 1 },
  ],
  win_conditions: [{ value: "wolves_gte_others", label: "狼人数量不少于好人" }, { value: "slaughter_side", label: "屠边" }],
  sheriff_vote_weights: [1, 1.5, 2], speech_policies: [{ value: "sequential", label: "顺序发言" }, { value: "sheriff_directed", label: "警长指定" }],
  sheriff_badge_bomb_policies: [{ value: "none", label: "不撕警徽" }, { value: "double", label: "双爆吞警徽" }],
  statuses: [{ value: "draft", label: "草稿" }, { value: "published", label: "已发布" }, { value: "archived", label: "已归档" }],
  sorts: ["display_order", "-display_order", "updated_at", "-updated_at", "name", "-name", "created_at", "-created_at"].map((value) => ({ value: value as RuleSetOptions["sorts"][number]["value"], label: value })),
  constraints: { player_count_min: 6, player_count_max: 12, tags_max_items: 8, tag_max_length: 20, id_pattern: "^[a-z][a-z0-9_]{2,79}$", reason_min_length: 3, reason_max_length: 500 },
};

export const standardConfig: RuleSetConfig = {
  name: "标准九人局", description: "标准配置", complexity: "中等", estimated_duration: "45 分钟", rule_tags: ["标准", "九人"],
  role_counts: { werewolf: 3, villager: 3, seer: 1, guard: 0, witch: 1, hunter: 1, idiot: 0 },
  win_condition: "wolves_gte_others", sheriff_enabled: true, sheriff_vote_weight: 1.5, speech_policy: "sheriff_directed",
  werewolf_self_explosion_enabled: true, sheriff_badge_bomb_policy: "double",
};

export function fixtureRevision(ruleSetId: string, no: number, state: RuleSetRevision["state"], config: RuleSetConfig = standardConfig): RuleSetRevision {
  return { id: `${ruleSetId}-r${no}`, rule_set_id: ruleSetId, revision_no: no, state, schema_version: 1, content_hash: state === "draft" ? null : `${no}`.repeat(64), lock_version: no, config: structuredClone(config), player_count: Object.values(config.role_counts).reduce((a, b) => a + b, 0), role_summary: "3 狼人 / 6 好人", created_at: `2026-07-0${no}T00:00:00Z`, updated_at: `2026-07-0${no}T00:00:00Z`, published_at: state === "draft" ? null : `2026-07-0${no}T00:00:00Z`, published_by: state === "draft" ? null : "preview-super-admin" };
}

export function fixtureRuleSet(id: string, status: AdminRuleSet["status"], isDefault = false, order = 1): AdminRuleSet {
  const published = status === "draft" ? null : fixtureRevision(id, 1, "published", { ...standardConfig, name: `${id} 规则` });
  const draft = status === "draft" ? fixtureRevision(id, 1, "draft", { ...standardConfig, name: `${id} 草稿` }) : null;
  return { id, status, is_default: isDefault, display_order: order, lock_version: 1, draft_revision: draft, published_revision: published, revisions: [draft ?? published!], created_at: "2026-07-01T00:00:00Z", updated_at: `2026-07-0${order}T00:00:00Z` };
}

export function fixtureDetail(rule: AdminRuleSet): AdminRuleSetDetail {
  return { ...structuredClone(rule), revisions: rule.revisions.map((revision) => ({ ...revision, usage: { game_count: revision.revision_no, live_count: 0 } })), usage: { game_count: 2, live_count: 1 }, warnings: [] };
}
