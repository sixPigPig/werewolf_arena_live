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
  sheriff: null,
  sheriff_candidates: [],
  sheriff_votes: {},
  speech_order: [],
  speech_order_choice: null,
  vote_weights: {},
  sheriff_badge_target: null,
  sheriff_badge_lost: false,
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

  it("hides bidding for ordered speech rounds and shows speech order", () => {
    render(
      <DayPhase
        round={{
          ...baseRound,
          hunter_shot: null,
          idiot_revealed: null,
          day_deaths: [],
          speech_order: ["Alice", "Bob"],
          debate: [
            { speaker: "Alice", message: "我先发言。" },
            { speaker: "Bob", message: "我跟着发言。" },
          ],
        }}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.queryByText("竞价")).not.toBeInTheDocument();
    expect(screen.getByText("发言顺序")).toBeInTheDocument();
    expect(screen.getByText("Alice -> Bob")).toBeInTheDocument();
  });

  it("shows sheriff vote weight in vote table", () => {
    render(
      <DayPhase
        round={{
          ...baseRound,
          hunter_shot: null,
          idiot_revealed: null,
          day_deaths: [],
          votes: [{ voter: "Alice", target: "Bob", weight: 1.5 }],
          voteTally: [{ target: "Bob", count: 1.5 }],
          voteCount: 1.5,
          voteMajorityThreshold: 1.5,
        }}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Bob：1.5票")).toBeInTheDocument();
    expect(screen.getByText("Alice（1.5票）")).toBeInTheDocument();
  });
});
