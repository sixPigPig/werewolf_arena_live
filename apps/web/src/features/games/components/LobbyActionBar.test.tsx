import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LobbyActionBar, type LobbyActionBarProps } from "./LobbyActionBar";

function renderActionBar(overrides: Partial<LobbyActionBarProps> = {}) {
  const props: LobbyActionBarProps = {
    disabled: false,
    loading: false,
    maxRounds: "8",
    onClearAll: vi.fn(),
    onFillFavorites: vi.fn(),
    onMaxRoundsChange: vi.fn(),
    onRandomFill: vi.fn(),
    onSeedChange: vi.fn(),
    seed: "884512",
    ...overrides,
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
    expect(dialog).toHaveAttribute(
      "aria-describedby",
      "lobby-clear-dialog-description",
    );
    expect(
      within(dialog).getByText("全部席位玩家与临时模型覆盖都会被移除。"),
    ).toHaveAttribute("id", "lobby-clear-dialog-description");
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

  it("keeps keyboard focus inside the clear confirmation actions", async () => {
    const user = userEvent.setup();
    renderActionBar();

    await user.click(screen.getByRole("button", { name: "清空阵容" }));

    const dialog = screen.getByRole("alertdialog", { name: "确认清空阵容" });
    const cancelButton = within(dialog).getByRole("button", { name: "取消" });
    const confirmButton = within(dialog).getByRole("button", {
      name: "确认清空",
    });

    expect(cancelButton).toHaveFocus();

    await user.tab();
    expect(confirmButton).toHaveFocus();

    await user.tab();
    expect(cancelButton).toHaveFocus();

    await user.tab({ shift: true });
    expect(confirmButton).toHaveFocus();

    await user.tab({ shift: true });
    expect(cancelButton).toHaveFocus();
  });

  it("calls fill action callbacks from the action buttons", async () => {
    const user = userEvent.setup();
    const props = renderActionBar();

    await user.click(screen.getByRole("button", { name: "随机填充空席" }));
    await user.click(screen.getByRole("button", { name: "只用收藏填充" }));

    expect(props.onRandomFill).toHaveBeenCalledTimes(1);
    expect(props.onFillFavorites).toHaveBeenCalledTimes(1);
  });

  it("reports changed seed and max rounds values", () => {
    const props = renderActionBar();

    fireEvent.change(screen.getByLabelText("随机种子"), {
      target: { value: "13579" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "最大轮数" }), {
      target: { value: "12" },
    });

    expect(props.onSeedChange).toHaveBeenCalledWith("13579");
    expect(props.onMaxRoundsChange).toHaveBeenCalledWith("12");
  });

  it("disables the launch button when disabled", () => {
    renderActionBar({ disabled: true });

    expect(screen.getByRole("button", { name: "发起对局" })).toBeDisabled();
  });
});
