import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlayerRosterPanel, type PlayerRosterItem } from "./PlayerRosterPanel";

function rosterPlayer(
  overrides: Partial<PlayerRosterItem> = {},
): PlayerRosterItem {
  return {
    seatNumber: 1,
    name: "阿夜",
    role: "村民",
    avatarImageUrl: "",
    state: "alive",
    statusLabel: "存活",
    ...overrides,
  };
}

describe("PlayerRosterPanel", () => {
  it("resolves database avatar asset URLs in roster rows", () => {
    render(
      <PlayerRosterPanel
        players={[
          rosterPlayer({
            avatarImageUrl: "/player-avatars/gothic-female-1.png",
          }),
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: "阿夜 人物形象" })).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
  });
});
