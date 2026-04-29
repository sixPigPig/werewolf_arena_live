import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GameRound } from "../types";
import { NightPhase } from "./NightPhase";

const baseRound: GameRound = {
  number: 1,
  players: ["Alice", "Bob"],
  attacked: "Alice",
  eliminated: null,
  protected: null,
  investigated: "Bob",
  exiled: null,
  saved_by_witch: "Alice",
  poisoned: "Bob",
  hunter_shot: null,
  idiot_revealed: null,
  sheriff: null,
  sheriff_candidates: [],
  sheriff_speech_order: [],
  sheriff_speech_direction: null,
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
  night_deaths: [{ player: "Bob", cause: "witch_poison", source: "Witch" }],
  day_deaths: [],
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

describe("NightPhase", () => {
  it("renders witch save, poison, and night death fields", () => {
    render(
      <NightPhase
        round={baseRound}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("解药")).toBeInTheDocument();
    expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    expect(screen.getByText("毒药")).toBeInTheDocument();
    expect(screen.getAllByText("Bob").length).toBeGreaterThan(0);
    expect(screen.getByText("夜晚死亡")).toBeInTheDocument();
    expect(screen.getByText("Bob 出局")).toBeInTheDocument();
  });
});
