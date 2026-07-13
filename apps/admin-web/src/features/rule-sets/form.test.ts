import { describe, expect, it } from "vitest";
import { cleanRuleSetInput, defaultRuleSetInput, formErrorsFromApi, inputFromRuleSet, playerCount, roleSummary, validateRuleSetInput } from "./form";
import { fixtureDetail, fixtureRevision, fixtureRuleSet, ruleSetOptions, standardConfig } from "./test-fixtures";

describe("rule-set form model", () => {
  it("derives defaults from server options", () => {
    const input = defaultRuleSetInput(ruleSetOptions);
    expect(input).toMatchObject({ id: "", display_order: 0, config: { win_condition: "wolves_gte_others", sheriff_vote_weight: 1, speech_policy: "sequential", sheriff_badge_bomb_policy: "none" } });
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
    expect(formErrorsFromApi({ problem: { detail: "校验失败", errors: [{ path: "config.role_counts.werewolf", message: "狼人至少一个" }, { path: "unknown", message: "未知" }] } })).toEqual({ role_counts: "狼人至少一个", form: "校验失败；未知" });
  });

  it("makes cleaned values stable for dirty comparisons", () => {
    const base = { ...defaultRuleSetInput(ruleSetOptions), id: "new_rule", config: { ...standardConfig, rule_tags: ["标准", "九人"] } };
    const displayOnly = { ...base, id: " new_rule ", config: { ...base.config, name: ` ${base.config.name} `, rule_tags: ["标准, 九人"] } };
    expect(cleanRuleSetInput(displayOnly, ruleSetOptions)).toEqual(cleanRuleSetInput(base, ruleSetOptions));
  });
});
