import type { RuleSetSummary } from "../types";

export function formatRoleSummary(rule: RuleSetSummary) {
  if (rule.role_summary) {
    return rule.role_summary;
  }

  return rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");
}

export function getRuleEmblem(rule: RuleSetSummary) {
  if (rule.sheriff_enabled) {
    return "警";
  }

  if (rule.name.includes("新手")) {
    return "新";
  }

  if (rule.name.includes("社交")) {
    return "社";
  }

  return "典";
}

export function formatSpeechPolicy(rule: RuleSetSummary) {
  if (rule.speech_policy === "sheriff_directed") {
    return "警长决定警左或警右，所有玩家完成完整发言";
  }

  return "顺序发言";
}

export function formatSheriffRule(rule: RuleSetSummary) {
  if (!rule.sheriff_enabled) {
    return "无警长";
  }

  const voteWeight = rule.sheriff_vote_weight ?? 1.5;
  return `有警长，警徽 ${voteWeight} 票`;
}

export function formatWinCondition(rule: RuleSetSummary) {
  if (
    rule.win_condition === "slaughter_side" ||
    rule.rule_tags?.includes("屠边")
  ) {
    return "狼人淘汰所有神民或村民；好人放逐所有狼人";
  }

  return "狼人数量大于等于其他存活玩家；好人放逐所有狼人";
}

export function formatReplayHint(rule: RuleSetSummary) {
  const nightActions = rule.night_actions ?? [];
  const hasNightRoles = nightActions.length > 1;
  const hasSheriff = Boolean(rule.sheriff_enabled);

  if (hasSheriff) {
    return "显示上警、警徽流、投票轨迹与关键发言";
  }

  if (hasNightRoles) {
    return "显示夜间行动、投票轨迹与关键发言";
  }

  return "突出发言博弈、投票轨迹与关键轮次";
}
