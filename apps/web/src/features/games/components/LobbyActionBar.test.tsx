import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LobbyActionBar } from "./LobbyActionBar";

function renderActionBar() {
  const props = {
    disabled: false,
    loading: false,
    maxRounds: "8",
    onClearAll: vi.fn(),
    onFillFavorites: vi.fn(),
    onMaxRoundsChange: vi.fn(),
    onRandomFill: vi.fn(),
    onSeedChange: vi.fn(),
    seed: "884512",
  };

  render(<LobbyActionBar {...props} />);

  return props;
}

describe("LobbyActionBar", () => {
  it("renders launch parameters and confirms clearing the lineup", async () => {
    const user = userEvent.setup();
    const props = renderActionBar();

    const actionBar = screen.getByTestId("lobby-action-bar");
    expect(actionBar).toBeInTheDocument();
    expect(within(actionBar).getByLabelText("随机种子")).toHaveValue("884512");
    expect(
      within(actionBar).getByRole("spinbutton", { name: "最大轮数" }),
    ).toHaveValue(8);

    const submitButton = within(actionBar).getByRole("button", {
      name: "发起对局",
    });
    expect(submitButton).toBeInTheDocument();
    expect(submitButton).toHaveAttribute("type", "submit");

    await user.click(within(actionBar).getByRole("button", { name: "清空阵容" }));

    const dialog = screen.getByRole("alertdialog", { name: "确认清空阵容" });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "取消" })).toHaveFocus();

    await user.click(within(dialog).getByRole("button", { name: "确认清空" }));

    expect(props.onClearAll).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("alertdialog", { name: "确认清空阵容" }),
    ).not.toBeInTheDocument();
  });

  it("closes the clear confirmation with Escape without clearing", async () => {
    const user = userEvent.setup();
    const props = renderActionBar();

    const clearTrigger = screen.getByRole("button", { name: "清空阵容" });
    await user.click(clearTrigger);

    expect(
      screen.getByRole("alertdialog", { name: "确认清空阵容" }),
    ).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(props.onClearAll).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("alertdialog", { name: "确认清空阵容" }),
    ).not.toBeInTheDocument();
    expect(clearTrigger).toHaveFocus();
  });
});
