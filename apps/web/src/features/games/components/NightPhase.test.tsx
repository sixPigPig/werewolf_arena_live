import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DebugItem, GameRound } from "../types";
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
  werewolf_self_exploded: null,
  day_ended_by_self_explosion: false,
  sheriff_pre_election_bomb_count: 0,
  sheriff_election_pending: false,
  sheriff_badge_lost_reason: null,
  night_deaths: [{ player: "Bob", cause: "witch_poison", source: "Witch" }],
  day_deaths: [],
  werewolf_discussion: [],
  werewolf_vote_rounds: [],
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

  it("renders night action debug items as selectable radio cards", async () => {
    const item: DebugItem = {
      id: "round-1-night-eliminate",
      roundNumber: 1,
      phase: "night",
      title: "狼人击杀",
      actor: "Alice",
      action: "remove",
      choice: "Bob",
      prompt: "请选择今晚击杀对象。",
      rawResponse: '{"choice":"Bob"}',
      parsed: { choice: "Bob" },
    };
    const onSelect = vi.fn();

    render(
      <NightPhase
        round={baseRound}
        items={[item]}
        selectedItem={null}
        onSelect={onSelect}
      />,
    );

    const actionGroup = screen.getByRole("radiogroup", { name: "夜晚行动" });
    const actionCard = within(actionGroup).getByRole("radio", {
      name: "狼人击杀 Alice 选择 Bob",
    });

    expect(actionCard).toHaveAttribute("aria-checked", "false");
    await userEvent.click(actionCard);
    expect(onSelect).toHaveBeenCalledWith(item);
  });
});
