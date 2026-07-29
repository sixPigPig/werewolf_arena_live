import { describe, expect, it } from "vitest";
import { cleanRuleSetInput, defaultRuleSetInput, formErrorsFromApi, inputFromRuleSet, playerCount, roleSummary, validateRuleSetInput } from "./form";
import { fixtureDetail, fixtureRevision, fixtureRuleSet, ruleSetOptions, standardConfig } from "./test-fixtures";
import type { RuleSetOptions } from "./types";

describe("rule-set form model", () => {
  it("derives defaults from server options", () => {
    const nonstandardOptions: RuleSetOptions = {
      ...ruleSetOptions,
      win_conditions: [{ value: "slaughter_side", label: "屠边" }],
      sheriff_vote_weights: [1.5, 2],
      speech_policies: [{ value: "sheriff_directed", label: "警长指定" }],
      sheriff_badge_bomb_policies: [{ value: "double", label: "双爆" }],
      werewolf_attack_resolutions: [{ value: "plurality_seeded_random", label: "随机破平" }],
    };
    const input = defaultRuleSetInput(nonstandardOptions);
    expect(input).toMatchObject({ id: "", display_order: 0, config: { win_condition: "slaughter_side", sheriff_vote_weight: 1.5, speech_policy: "sheriff_directed", sheriff_badge_bomb_policy: "double", werewolf_attack_policy: { resolution: "plurality_seeded_random", allow_no_attack: false, allow_wolf_target: false } } });
    expect(input.config.role_counts).toEqual({ werewolf: 1, villager: 0, seer: 0, guard: 0, witch: 0, hunter: 0, idiot: 0 });
  });

  it("prefers draft config over published and falls back to published", () => {
    const publishedOnly = fixtureRuleSet("published_rule", "published");
    expect(inputFromRuleSet(fixtureDetail(publishedOnly), ruleSetOptions).config.name).toBe("published_rule 规则");
    publishedOnly.draft_revision = fixtureRevision("published_rule", 2, "draft", { ...standardConfig, name: "更新草稿" });
    expect(inputFromRuleSet(fixtureDetail(publishedOnly), ruleSetOptions).config.name).toBe("更新草稿");
  });

  it("cleans scalars, comma-separated display tags, integer roles and sheriff-off fields", () => {
    const dirty = { ...defaultRuleSetInput(ruleSetOptions), id: "  new_rule  ", display_order: 2.8, config: { ...standardConfig, name: " 名称 ", description: " 描述 ", complexity: " 中 ", estimated_duration: " 30 分钟 ", rule_tags: [" 标签一, 标签二 ", "标签一"], role_counts: { ...standardConfig.role_counts, werewolf: 2.9, villager: -2 }, sheriff_enabled: false, sheriff_vote_weight: 2, sheriff_badge_bomb_policy: "double" as const } };
    expect(cleanRuleSetInput(dirty, ruleSetOptions)).toMatchObject({ id: "new_rule", display_order: 2, config: { name: "名称", rule_tags: ["标签一", "标签二"], role_counts: { werewolf: 2, villager: 0 }, sheriff_vote_weight: 1, sheriff_badge_bomb_policy: "none" } });
  });

  it("normalizes sheriff-off fields only to choices supplied by the server", () => {
    const options: RuleSetOptions = { ...ruleSetOptions, sheriff_vote_weights: [1.5, 2], sheriff_badge_bomb_policies: [{ value: "double", label: "双爆" }] };
    const input = { ...defaultRuleSetInput(options), config: { ...standardConfig, sheriff_enabled: false } };
    const clean = cleanRuleSetInput(input, options);
    expect(clean.config.sheriff_vote_weight).toBe(1.5);
    expect(clean.config.sheriff_badge_bomb_policy).toBe("double");
    expect(options.sheriff_vote_weights).toContain(clean.config.sheriff_vote_weight);
    expect(options.sheriff_badge_bomb_policies.map(({ value }) => value)).toContain(clean.config.sheriff_badge_bomb_policy);
  });

  it("calculates players and localized role summary", () => {
    const input = { ...defaultRuleSetInput(ruleSetOptions), config: standardConfig };
    expect(playerCount(input)).toBe(9);
    expect(roleSummary(input, ruleSetOptions)).toBe("3 狼人 / 3 村民 / 1 预言家 / 1 女巫 / 1 猎人");
  });

  it("validates identifiers, text, tags, order, roles, choices and player range", () => {
    const input = { ...defaultRuleSetInput(ruleSetOptions), id: "Bad", display_order: -1, config: { ...standardConfig, name: "x".repeat(121), description: "x".repeat(1001), complexity: "x".repeat(41), estimated_duration: "x".repeat(41), rule_tags: Array.from({ length: 9 }, (_, i) => i === 0 ? "x".repeat(21) : `t${i}`), role_counts: { ...standardConfig.role_counts, werewolf: -1.2, villager: 20 }, sheriff_vote_weight: 9 } };
    expect(validateRuleSetInput(input, ruleSetOptions)).toMatchObject({ id: expect.any(String), display_order: expect.any(String), name: expect.any(String), description: expect.any(String), complexity: expect.any(String), estimated_duration: expect.any(String), rule_tags: expect.any(String), role_counts: expect.any(String), sheriff_vote_weight: expect.any(String), form: expect.any(String) });
  });

  it("maps API warning paths to fields and summary", () => {
    expect(formErrorsFromApi({ problem: { errors: [{ path: "config.name", message: "SELECT raw_name" }] } })).toEqual({ name: "规则名称不符合要求", form: "规则名称不符合要求" });
    expect(formErrorsFromApi({ problem: { detail: "driver secret", errors: [{ path: "config.role_counts.werewolf", message: "raw player" }, { path: "unknown", message: "未知" }] } })).toEqual({ role_counts: "角色数量不符合要求", form: "角色数量不符合要求；规则内容不符合要求" });
    expect(formErrorsFromApi({ warnings: [{ path: "config.name", message: "名称必填" }] })).toEqual({ name: "名称必填", form: "名称必填" });
  });

  it("makes cleaned values stable for dirty comparisons", () => {
    const base = { ...defaultRuleSetInput(ruleSetOptions), id: "new_rule", config: { ...standardConfig, rule_tags: ["标准", "九人"] } };
    const displayOnly = { ...base, id: " new_rule ", config: { ...base.config, name: ` ${base.config.name} `, rule_tags: ["标准, 九人"] } };
    expect(cleanRuleSetInput(displayOnly, ruleSetOptions)).toEqual(cleanRuleSetInput(base, ruleSetOptions));
  });
});
