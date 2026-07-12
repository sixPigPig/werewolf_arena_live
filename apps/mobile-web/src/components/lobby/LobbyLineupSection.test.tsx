import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LobbyLineupSection } from "./LobbyLineupSection";

const emptyStatus = {
  assignedCount: 0,
  emptySeatCount: 8,
  profileShortageCount: 0,
  summaryText: "已选 0/8 · 可自动补齐",
  ctaLabel: "还差 8 位",
  canLaunch: false,
};

describe("LobbyLineupSection", () => {
  it("renders visible two-digit seat numbers and opens the requested seat", async () => {
    const user = userEvent.setup();
    const onSelectSeat = vi.fn();
    render(
      <LobbyLineupSection
        activeSeat={1}
        canFillSeats
        favoritesAvailable
        isBusy={false}
        launchStatus={emptyStatus}
        onClear={vi.fn()}
        onFill={vi.fn()}
        onSelectSeat={onSelectSeat}
        playerCount={8}
        profilesBySeat={new Map()}
      />,
    );

    expect(screen.getByText("01")).toBeVisible();
    expect(screen.getByText("08")).toBeVisible();
    const seat = screen.getByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    });
    await user.click(seat);
    expect(onSelectSeat).toHaveBeenCalledWith(1, seat);
  });

  it("keeps fill and destructive clear outside the fixed launch bar", async () => {
    const user = userEvent.setup();
    const onFill = vi.fn();
    const onClear = vi.fn();
    render(
      <LobbyLineupSection
        activeSeat={1}
        canFillSeats
        favoritesAvailable
        isBusy={false}
        launchStatus={emptyStatus}
        onClear={onClear}
        onFill={onFill}
        onSelectSeat={vi.fn()}
        playerCount={8}
        profilesBySeat={new Map()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "智能补齐" }));
    const fillMenu = screen.getByRole("menu", { name: "智能补齐方式" });
    await user.click(
      within(fillMenu).getByRole("menuitem", { name: "收藏补齐" }),
    );
    expect(onFill).toHaveBeenCalledWith({ favoritesOnly: true });

    await user.click(screen.getByRole("button", { name: "阵容更多操作" }));
    await user.click(screen.getByRole("menuitem", { name: "清空阵容" }));
    expect(onClear).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("menuitem", { name: "确认清空阵容" }),
    );
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
