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
  sheriff_speeches: [],
  sheriff_withdrawn: [],
  sheriff_final_candidates: [],
  sheriff_voters: [],
  sheriff_votes: {},
  sheriff_pk_candidates: [],
  sheriff_pk_speeches: [],
  sheriff_runoff_votes: {},
  sheriff_elected: null,
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

  it("hides bidding for ordered speech rounds and shows day speeches", () => {
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

    expect(screen.queryByText("历史竞价")).not.toBeInTheDocument();
    expect(screen.queryByText("发言顺序")).not.toBeInTheDocument();
    expect(screen.getByText("白天发言")).toBeInTheDocument();
  });

  it("renders the sheriff election panel inside the day phase", () => {
    render(
      <DayPhase
        round={{
          ...baseRound,
          hunter_shot: null,
          idiot_revealed: null,
          day_deaths: [],
          sheriff: "Alice",
          sheriff_candidates: ["Alice", "Bob"],
          sheriff_speeches: [{ speaker: "Alice", message: "我上警争警徽。" }],
          sheriff_final_candidates: ["Alice"],
          sheriff_voters: ["Cora", "Dan"],
          sheriff_votes: { Cora: "Alice" },
          sheriff_elected: "Alice",
          speech_order: ["Cora", "Dan", "Bob", "Alice"],
          speech_order_choice: "警左发言",
        }}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("警长竞选")).toBeInTheDocument();
    expect(screen.getByText("上警：Alice、Bob")).toBeInTheDocument();
    expect(screen.getByText("发言方向：警左发言")).toBeInTheDocument();
    expect(screen.getByText("白天发言")).toBeInTheDocument();
    expect(screen.getByText("放逐投票")).toBeInTheDocument();
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
