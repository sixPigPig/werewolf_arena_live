import { describe, expect, it } from "vitest";
import {
  parseAdminRuleSet,
  parseAdminRuleSetDetail,
  parseAdminRuleSetList,
  parseRuleSetOptions,
  parseRuleSetValidation,
} from "./parsers";

const config = {
  name: "标准局", description: "", complexity: "中等", estimated_duration: "45 分钟",
  rule_tags: ["标准"], role_counts: { werewolf: 3, villager: 3, seer: 1, guard: 1, witch: 1, hunter: 0, idiot: 0 },
  win_condition: "wolves_gte_others", sheriff_enabled: true, sheriff_vote_weight: 1.5,
  speech_policy: "sequential", werewolf_self_explosion_enabled: true, sheriff_badge_bomb_policy: "none",
};
const revision = {
  id: "revision-1", rule_set_id: "standard_rule", revision_no: 1, state: "draft", schema_version: 1,
  content_hash: null, lock_version: 1, config, player_count: 9, role_summary: "3狼6好人",
  created_at: "2026-07-13T00:00:00Z", updated_at: "2026-07-13T00:00:00Z", published_at: null, published_by: null,
};
const ruleSet = {
  id: "standard_rule", status: "draft", is_default: false, display_order: 0, lock_version: 1,
  draft_revision: revision, published_revision: null, revisions: [revision],
  created_at: "2026-07-13T00:00:00Z", updated_at: "2026-07-13T00:00:00Z",
};
const options = {
  roles: [
    { id: "werewolf", label: "狼人", min_count: 1, max_count: 5 },
    { id: "villager", label: "村民", min_count: 0, max_count: 11 },
    { id: "seer", label: "预言家", min_count: 0, max_count: 1 },
    { id: "guard", label: "守卫", min_count: 0, max_count: 1 },
    { id: "witch", label: "女巫", min_count: 0, max_count: 1 },
    { id: "hunter", label: "猎人", min_count: 0, max_count: 1 },
    { id: "idiot", label: "白痴", min_count: 0, max_count: 1 },
  ],
  win_conditions: [{ value: "wolves_gte_others", label: "屠边" }], sheriff_vote_weights: [1, 1.5],
  speech_policies: [{ value: "sequential", label: "顺序" }],
  sheriff_badge_bomb_policies: [{ value: "none", label: "无" }], statuses: [{ value: "draft", label: "草稿" }],
  sorts: [
    { value: "display_order", label: "顺序升序" },
    { value: "-display_order", label: "顺序降序" },
    { value: "updated_at", label: "更新时间升序" },
    { value: "-updated_at", label: "更新时间降序" },
    { value: "name", label: "名称升序" },
    { value: "-name", label: "名称降序" },
    { value: "created_at", label: "创建时间升序" },
    { value: "-created_at", label: "创建时间降序" },
  ],
  constraints: { player_count_min: 6, player_count_max: 12, tags_max_items: 8, tag_max_length: 20, id_pattern: "x", reason_min_length: 3, reason_max_length: 500 },
};

describe("rule-set response contracts", () => {
  it("accepts exact rule set, detail, list, options, and validation payloads", () => {
    expect(parseAdminRuleSet(ruleSet)).toEqual(ruleSet);
    expect(parseAdminRuleSetDetail({ ...ruleSet, revisions: [{ ...revision, usage: { game_count: 1, live_count: 2 } }], usage: { game_count: 3, live_count: 4 }, warnings: [] })).toMatchObject({ usage: { game_count: 3, live_count: 4 } });
    expect(parseAdminRuleSetList({ items: [ruleSet], pagination: { page: 1, page_size: 20, total: 1, pages: 1 } })).toMatchObject({ items: [ruleSet] });
    expect(parseRuleSetOptions(options)).toEqual(options);
    expect(parseRuleSetValidation({ valid: true, errors: [], warnings: [], compiled_snapshot: { internal: true }, content_hash: "a".repeat(64), rule_text_preview: "preview" })).toEqual({ valid: true, errors: [], warnings: [], content_hash: "a".repeat(64), rule_text_preview: "preview" });
  });

  it.each<{ payload: unknown; label: string }>([
    { payload: { ...ruleSet, status: "deleted" }, label: "status" },
    { payload: { ...ruleSet, draft_revision: { ...revision, state: "active" } }, label: "state" },
    { payload: { ...ruleSet, lock_version: 0 }, label: "lock_version" },
    { payload: { items: [], pagination: { page: 0, page_size: 20, total: 0, pages: 0 } }, label: "pagination" },
    { payload: { ...ruleSet, draft_revision: { ...revision, config: { ...config, role_counts: { ...config.role_counts, werewolf: -1 } } } }, label: "role_counts" },
  ])("rejects malformed payload $label", ({ payload }) => {
    const parse = typeof payload === "object" && payload !== null && "items" in payload
      ? parseAdminRuleSetList
      : parseAdminRuleSet;
    expect(() => parse(payload)).toThrowError(expect.objectContaining({ code: "admin_invalid_rule_set_response", status: 502 }));
  });

  it.each(["compiled_snapshot", "rule_set_snapshot", "players", "sql", "raw_error"])("rejects forbidden key %s outside validation", (key) => {
    expect(() => parseAdminRuleSet({ ...ruleSet, [key]: {} })).toThrow();
    expect(() => parseAdminRuleSet({ ...ruleSet, draft_revision: { ...revision, config: { ...config, [key]: {} } } })).toThrow();
  });

  it("allows compiled_snapshot only at validation root", () => {
    expect(() => parseRuleSetValidation({ valid: false, errors: [], warnings: [], compiled_snapshot: null, content_hash: null, rule_text_preview: null })).not.toThrow();
    expect(() => parseRuleSetValidation({ valid: true, errors: [{ code: "x", path: "x", message: "x", compiled_snapshot: {} }], warnings: [], compiled_snapshot: null, content_hash: null, rule_text_preview: null })).toThrow();
  });

  it("treats the validation-root compiled snapshot as opaque and omits it", () => {
    const result = parseRuleSetValidation({
      valid: false,
      errors: [],
      warnings: [],
      compiled_snapshot: { sql: "opaque", nested: { players: [], raw_error: "opaque", compiled_snapshot: {} } },
      content_hash: null,
      rule_text_preview: null,
    });

    expect(result).toEqual({ valid: false, errors: [], warnings: [], content_hash: null, rule_text_preview: null });
    expect(result).not.toHaveProperty("compiled_snapshot");
  });

  it.each([
    ["role", { ...options, roles: [{ ...options.roles[0], id: "unknown" }] }],
    ["win condition", { ...options, win_conditions: [{ value: "unknown", label: "未知" }] }],
    ["speech policy", { ...options, speech_policies: [{ value: "unknown", label: "未知" }] }],
    ["badge policy", { ...options, sheriff_badge_bomb_policies: [{ value: "unknown", label: "未知" }] }],
    ["status", { ...options, statuses: [{ value: "deleted", label: "已删除" }] }],
    ["sort", { ...options, sorts: [{ value: "-unknown", label: "未知" }] }],
  ])("rejects an unknown option %s", (_name, payload) => {
    expect(() => parseRuleSetOptions(payload)).toThrowError(
      expect.objectContaining({ code: "admin_invalid_rule_set_response", status: 502 }),
    );
  });

  it.each([
    "roles",
    "win_conditions",
    "sheriff_vote_weights",
    "speech_policies",
    "sheriff_badge_bomb_policies",
    "statuses",
    "sorts",
  ] as const)("rejects an empty required options array: %s", (key) => {
    expect(() => parseRuleSetOptions({ ...options, [key]: [] })).toThrowError(
      expect.objectContaining({ code: "admin_invalid_rule_set_response", status: 502 }),
    );
  });

  it.each([
    ["missing role", { ...options, roles: options.roles.slice(0, 6) }],
    ["duplicate role", { ...options, roles: [...options.roles.slice(0, 6), options.roles[0]] }],
    ["role range", { ...options, roles: options.roles.map((role) => role.id === "werewolf" ? { ...role, min_count: 6, max_count: 5 } : role) }],
    ["duplicate choice", { ...options, statuses: [options.statuses[0], options.statuses[0]] }],
    ["duplicate sort", { ...options, sorts: [options.sorts[0], options.sorts[0]] }],
    ["duplicate weight", { ...options, sheriff_vote_weights: [1, 1] }],
    ["non-positive weight", { ...options, sheriff_vote_weights: [0] }],
    ["player range", { ...options, constraints: { ...options.constraints, player_count_min: 13, player_count_max: 12 } }],
    ["non-positive player minimum", { ...options, constraints: { ...options.constraints, player_count_min: 0 } }],
    ["negative tag count", { ...options, constraints: { ...options.constraints, tags_max_items: -1 } }],
    ["zero tag count", { ...options, constraints: { ...options.constraints, tags_max_items: 0 } }],
    ["reason range", { ...options, constraints: { ...options.constraints, reason_min_length: 501, reason_max_length: 500 } }],
    ["invalid id regex", { ...options, constraints: { ...options.constraints, id_pattern: "[" } }],
  ])("rejects malformed options contract: %s", (_label, payload) => {
    expect(() => parseRuleSetOptions(payload)).toThrowError(
      expect.objectContaining({ code: "admin_invalid_rule_set_response", status: 502 }),
    );
  });

  it("requires bounded successful validation output", () => {
    for (const payload of [
      { valid: true, errors: [], warnings: [], compiled_snapshot: null, content_hash: null, rule_text_preview: "preview" },
      { valid: true, errors: [], warnings: [], compiled_snapshot: null, content_hash: "A".repeat(64), rule_text_preview: "preview" },
      { valid: true, errors: [], warnings: [], compiled_snapshot: null, content_hash: "a".repeat(63), rule_text_preview: "preview" },
      { valid: true, errors: [], warnings: [], compiled_snapshot: null, content_hash: "a".repeat(64), rule_text_preview: "" },
    ]) expect(() => parseRuleSetValidation(payload)).toThrow();

    expect(() => parseRuleSetValidation({ valid: false, errors: [], warnings: [], compiled_snapshot: null, content_hash: null, rule_text_preview: null })).not.toThrow();
  });
});
