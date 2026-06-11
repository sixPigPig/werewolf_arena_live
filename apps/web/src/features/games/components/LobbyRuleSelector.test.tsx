import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RuleSetSummary } from "../types";
import { LobbyRuleSelector } from "./LobbyRuleSelector";

const rules: RuleSetSummary[] = [
  {
    id: "classic_8",
    version: "2026.04",
    name: "经典 8 人局",
    player_count: 8,
    roles: [],
    role_summary: "2 狼人 / 6 好人",
    complexity: "标准",
  },
  {
    id: "starter_6",
    version: "2026.04",
    name: "新手 6 人快局",
    player_count: 6,
    roles: [],
    role_summary: "2 狼人 / 4 好人",
  },
];

describe("LobbyRuleSelector", () => {
  it("shows loading status without rendering an empty rule group", () => {
    render(
      <LobbyRuleSelector
        error={false}
        loading
        onValueChange={vi.fn()}
        rules={[]}
        value=""
      />,
    );

    expect(screen.getByText("正在读取官方规则...")).toBeInTheDocument();
    expect(
      screen.queryByRole("radiogroup", { name: "官方规则" }),
    ).not.toBeInTheDocument();
  });

  it("renders the rule column and reports a newly selected rule", async () => {
    const onValueChange = vi.fn();

    render(
      <LobbyRuleSelector
        error={false}
        loading={false}
        onValueChange={onValueChange}
        rules={rules}
        value="classic_8"
      />,
    );

    expect(screen.getByTestId("lobby-rule-column")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("新手 6 人快局"));

    expect(onValueChange).toHaveBeenCalledWith("starter_6");
  });
});
