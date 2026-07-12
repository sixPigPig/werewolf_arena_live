import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LobbyRuleSummary } from "./LobbyRuleSummary";

describe("LobbyRuleSummary", () => {
  it("disables retry while a failed rule query is refetching", () => {
    render(
      <LobbyRuleSummary
        changeButtonRef={createRef<HTMLButtonElement>()}
        disabled
        isError
        isLoading={false}
        onOpenPicker={vi.fn()}
        onRetry={vi.fn()}
        ruleSet={null}
      />,
    );

    expect(
      screen.getByRole("button", { name: "重新加载规则" }),
    ).toBeDisabled();
  });
});
