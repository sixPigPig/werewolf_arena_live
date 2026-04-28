import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GameRound } from "../types";
import { DayPhase } from "./DayPhase";

const baseRound: GameRound = {
  number: 1,
  players: ["Alice", "Bob"],
  attacked: null,
  eliminated: null,
  protected: null,
  investigated: null,
  exiled: null,
  saved_by_witch: null,
  poisoned: null,
  hunter_shot: "Alice",
  idiot_revealed: "Bob",
  night_deaths: [],
  day_deaths: [{ player: "Alice", cause: "hunter_shot", source: "Hunter" }],
  debate: [],
  bids: [],
  bidGroups: [],
  votes: [],
  voteTally: [],
  voteCount: 0,
  voteMajorityThreshold: null,
  summaries: {},
  success: true,
};

describe("DayPhase", () => {
  it("renders idiot reveal and hunter shot fields", () => {
    render(
      <DayPhase
        round={baseRound}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Bob 翻牌免死，失去投票权")).toBeInTheDocument();
    expect(screen.getByText("猎人带走 Alice")).toBeInTheDocument();
  });
});
