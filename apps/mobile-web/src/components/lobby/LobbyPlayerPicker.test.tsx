import type { PublicPlayerProfileWithFavorite } from "@werewolf-arena/game-client";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { LobbyPlayerPicker } from "./LobbyPlayerPicker";

function buildProfile(
  id: string,
  overrides: Partial<PublicPlayerProfileWithFavorite> = {},
): PublicPlayerProfileWithFavorite {
  return {
    id,
    display_name: id,
    model_provider: "deepseek",
    model: "test-model",
    personality_id: "balanced",
    personality_text: "沉稳控场",
    appearance_id: "default",
    avatar_image_url: "",
    short_description: "先盘逻辑再站边",
    background_story: "",
    speaking_style: "",
    catchphrases: [],
    strategy_profile: "analysis",
    risk_tolerance: 3,
    bluffing_tendency: 3,
    trust_tendency: 3,
    leadership_tendency: 3,
    talkativeness: 3,
    example_messages: [],
    display_order: 1,
    featured: false,
    tags: ["逻辑"],
    is_favorite: false,
    ...overrides,
  };
}

function PickerHarness() {
  const [isOpen, setIsOpen] = useState(true);
  const [activeSeat, setActiveSeat] = useState(1);
  const [pendingProfileId, setPendingProfileId] = useState<string | null>(null);
  const backgroundRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const profiles = [
    buildProfile("alpha", {
      display_name: "暗巷观星",
      featured: true,
      is_favorite: true,
    }),
    buildProfile("beta", {
      display_name: "狼啸听风",
      strategy_profile: "aggressive",
    }),
  ];

  return (
    <main>
      <div ref={backgroundRef}>
        <button ref={triggerRef} type="button">
          1号座位
        </button>
      </div>
      {isOpen ? (
        <LobbyPlayerPicker
          activeSeat={activeSeat}
          assignedSeatByProfileId={new Map([["beta", 2]])}
          backgroundRef={backgroundRef}
          canConfirm={pendingProfileId !== null}
          confirmLabel="确认并下一位"
          favoriteUpdateError={null}
          favoritesAvailable
          isRefreshing={false}
          onClose={() => setIsOpen(false)}
          onConfirm={() => {
            setPendingProfileId(null);
            setActiveSeat(2);
          }}
          onPendingProfileIdChange={setPendingProfileId}
          onRefresh={vi.fn().mockResolvedValue(undefined)}
          onToggleFavorite={vi.fn()}
          pendingFavoriteProfileIds={new Set()}
          pendingProfileId={pendingProfileId}
          playerCount={2}
          profiles={profiles}
          profilesError={false}
          restoreFocusRef={triggerRef}
        />
      ) : null}
    </main>
  );
}

describe("LobbyPlayerPicker", () => {
  it("opens as an isolated full-screen searchable picker", async () => {
    const user = userEvent.setup();
    render(<PickerHarness />);

    expect(screen.getByRole("dialog", { name: "玩家卡牌库" })).toHaveAttribute(
      "aria-modal",
      "true",
    );
    const search = screen.getByRole("searchbox", { name: "搜索玩家" });
    await waitFor(() => expect(search).toHaveFocus());
    expect(
      screen.getByRole("button", {
        name: "筛选玩家，当前 全部玩家、全部策略",
      }),
    ).toBeVisible();
    expect(screen.getByText("推荐")).toBeVisible();

    await user.type(search, "观星");

    expect(
      screen.getByRole("button", { name: "为 1 号座位候选 暗巷观星" }),
    ).toBeVisible();
    expect(screen.queryByText("狼啸听风")).not.toBeInTheDocument();
  });

  it("shows assignment state and controls a pending candidate", async () => {
    const user = userEvent.setup();
    render(<PickerHarness />);

    expect(screen.getByText("已在 2 号座位")).toBeVisible();
    const candidate = screen.getByRole("button", {
      name: "为 1 号座位候选 暗巷观星",
    });
    await user.click(candidate);

    expect(
      screen.getByRole("button", { name: "确认并下一位" }),
    ).toBeEnabled();
    expect(candidate).toHaveAttribute("aria-pressed", "true");
  });

  it("resets search and keeps focus inside when the active seat advances", async () => {
    const user = userEvent.setup();
    render(<PickerHarness />);
    const search = screen.getByRole("searchbox", { name: "搜索玩家" });

    await user.type(search, "观星");
    await user.click(
      screen.getByRole("button", { name: "为 1 号座位候选 暗巷观星" }),
    );
    await user.click(screen.getByRole("button", { name: "确认并下一位" }));

    expect(screen.getByText(/当前选择：2号座位/)).toBeVisible();
    await waitFor(() => {
      expect(search).toHaveValue("");
      expect(search).toHaveFocus();
    });
  });

  it("closes on Escape without committing", async () => {
    const user = userEvent.setup();
    render(<PickerHarness />);

    await user.keyboard("{Escape}");

    expect(
      screen.queryByRole("dialog", { name: "玩家卡牌库" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1号座位" })).toHaveFocus();
  });
});
