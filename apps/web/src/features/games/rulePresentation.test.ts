import { describe, expect, it } from "vitest";

import type { RuleSetSummary } from "./types";
import {
  formatReplayHint,
  formatRoleSummary,
  formatSheriffRule,
  formatSpeechPolicy,
  formatWinCondition,
  getRuleEmblem,
} from "./rulePresentation";

const sheriffRule: RuleSetSummary = {
  id: "sheriff_12",
  version: "2026.04",
  name: "标准 12 人警长局",
  player_count: 12,
  roles: [],
  role_summary: "4 狼人 / 8 好人",
  sheriff_enabled: true,
  sheriff_vote_weight: 1.5,
  speech_policy: "sheriff_directed",
  win_condition: "slaughter_side",
};

describe("rulePresentation", () => {
  it("formats the sheriff rule presentation copy", () => {
    expect(formatRoleSummary(sheriffRule)).toBe("4 狼人 / 8 好人");
    expect(getRuleEmblem(sheriffRule)).toBe("警");
    expect(formatSpeechPolicy(sheriffRule)).toContain("警长决定");
    expect(formatSheriffRule(sheriffRule)).toBe("有警长，警徽 1.5 票");
    expect(formatWinCondition(sheriffRule)).toContain("好人放逐所有狼人");
    expect(formatReplayHint(sheriffRule)).toContain("上警");
  });
});
