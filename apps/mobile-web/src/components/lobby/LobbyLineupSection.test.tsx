import { render, screen, within } from "@testing-library/react";
import type { PublicPlayerProfileWithFavorite } from "@werewolf-arena/game-client";
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

function buildProfile(
  overrides: Partial<PublicPlayerProfileWithFavorite> = {},
): PublicPlayerProfileWithFavorite {
  return {
    id: "recommended-player",
    display_name: "推荐玩家",
    model_provider: "deepseek",
    model: "test-model",
    personality_id: "balanced",
    personality_text: "",
    appearance_id: "default",
    avatar_image_url: "",
    short_description: "",
    background_story: "",
    speaking_style: "",
    catchphrases: [],
    strategy_profile: "balanced",
    risk_tolerance: 3,
    bluffing_tendency: 3,
    trust_tendency: 3,
    leadership_tendency: 3,
    talkativeness: 3,
    example_messages: [],
    display_order: 1,
    featured: true,
    tags: [],
    is_favorite: false,
    ...overrides,
  };
}

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
        qualityError={null}
        qualityOverrideConfirmed={false}
        qualityReport={null}
        onClear={vi.fn()}
        onConfirmQualityOverride={vi.fn()}
        onFill={vi.fn()}
        onReshuffle={vi.fn()}
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

  it("marks admin-recommended players in selected seats", () => {
    render(
      <LobbyLineupSection
        activeSeat={1}
        canFillSeats
        favoritesAvailable
        isBusy={false}
        launchStatus={emptyStatus}
        qualityError={null}
        qualityOverrideConfirmed={false}
        qualityReport={null}
        onClear={vi.fn()}
        onConfirmQualityOverride={vi.fn()}
        onFill={vi.fn()}
        onReshuffle={vi.fn()}
        onSelectSeat={vi.fn()}
        playerCount={8}
        profilesBySeat={new Map([[1, buildProfile()]])}
      />,
    );

    const seat = screen.getByRole("button", {
      name: "选择 1 号座位，当前为 推荐玩家，管理端推荐",
    });
    expect(within(seat).getByText("推荐")).toBeVisible();
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
        qualityError={null}
        qualityOverrideConfirmed={false}
        qualityReport={null}
        onClear={onClear}
        onConfirmQualityOverride={vi.fn()}
        onFill={onFill}
        onReshuffle={vi.fn()}
        onSelectSeat={vi.fn()}
        playerCount={8}
        profilesBySeat={new Map()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "智能补齐" }));
    const fillMenu = screen.getByRole("group", { name: "智能补齐方式" });
    await user.click(
      within(fillMenu).getByRole("button", { name: "收藏补齐" }),
    );
    expect(onFill).toHaveBeenCalledWith({ favoritesOnly: true });

    await user.click(screen.getByRole("button", { name: "阵容更多操作" }));
    await user.click(screen.getByRole("button", { name: "清空阵容" }));
    expect(onClear).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "确认清空阵容" }),
    );
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("renders structured quality risk and only offers repair-mode override", async () => {
    const user = userEvent.setup();
    const onConfirmQualityOverride = vi.fn();
    const qualityReport = {
      schema_version: 1 as const,
      policy_mode: "repair" as const,
      player_count: 8,
      configured_count: 8,
      is_blocked: true,
      was_repaired: false,
      style_bucket_count: 2,
      required_style_bucket_count: 4,
      violations: [
        {
          code: "personality_overrepresented",
          severity: "error" as const,
          key: "balanced",
          count: 5,
          limit: 3,
          seat_numbers: [1, 2, 3, 4, 5],
        },
      ],
    };
    const { rerender } = render(
      <LobbyLineupSection
        activeSeat={1}
        canFillSeats={false}
        favoritesAvailable
        isBusy={false}
        launchStatus={emptyStatus}
        qualityError={null}
        qualityOverrideConfirmed={false}
        qualityReport={qualityReport}
        onClear={vi.fn()}
        onConfirmQualityOverride={onConfirmQualityOverride}
        onFill={vi.fn()}
        onReshuffle={vi.fn()}
        onSelectSeat={vi.fn()}
        playerCount={8}
        profilesBySeat={new Map()}
      />,
    );

    const quality = screen.getByRole("region", { name: "阵容质量" });
    expect(within(quality).getByText("阵容需要调整")).toBeVisible();
    expect(within(quality).getByText("同人格过多：5/3（1、2、3、4、5号）")).toBeVisible();
    await user.click(
      within(quality).getByRole("button", { name: "仍使用当前阵容" }),
    );
    expect(onConfirmQualityOverride).toHaveBeenCalledTimes(1);

    rerender(
      <LobbyLineupSection
        activeSeat={1}
        canFillSeats={false}
        favoritesAvailable
        isBusy={false}
        launchStatus={emptyStatus}
        qualityError={null}
        qualityOverrideConfirmed={false}
        qualityReport={{ ...qualityReport, policy_mode: "enforce" }}
        onClear={vi.fn()}
        onConfirmQualityOverride={vi.fn()}
        onFill={vi.fn()}
        onReshuffle={vi.fn()}
        onSelectSeat={vi.fn()}
        playerCount={8}
        profilesBySeat={new Map()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "仍使用当前阵容" }),
    ).not.toBeInTheDocument();
  });
});
