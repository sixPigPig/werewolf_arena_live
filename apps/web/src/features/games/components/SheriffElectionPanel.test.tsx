import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GameRound } from "../types";
import { SheriffElectionPanel } from "./SheriffElectionPanel";

const baseRound: GameRound = {
  number: 1,
  players: ["Alice", "Bob", "Cora", "Dan"],
  attacked: null,
  eliminated: null,
  protected: null,
  investigated: null,
  exiled: null,
  saved_by_witch: null,
  poisoned: null,
  hunter_shot: null,
  idiot_revealed: null,
  night_deaths: [],
  day_deaths: [],
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

describe("SheriffElectionPanel", () => {
  it("returns null when the round has no sheriff election, badge, or speech direction data", () => {
    const { container } = render(<SheriffElectionPanel round={baseRound} />);

    expect(container.firstChild).toBeNull();
  });

  it("shows the full sheriff election timeline and speech direction", () => {
    render(
      <SheriffElectionPanel
        round={{
          ...baseRound,
          sheriff: "Alice",
          sheriff_candidates: ["Alice", "Bob"],
          sheriff_speeches: [
            { speaker: "Alice", message: "我上警争警徽。" },
            { speaker: "Bob", message: "我也上警。" },
          ],
          sheriff_withdrawn: ["Bob"],
          sheriff_final_candidates: ["Alice"],
          sheriff_voters: ["Cora", "Dan"],
          sheriff_votes: { Cora: "Alice", Dan: "Alice" },
          sheriff_pk_candidates: ["Alice", "Bob"],
          sheriff_pk_speeches: [
            { speaker: "Alice", message: "PK 我继续站边自己。" },
          ],
          sheriff_runoff_votes: { Cora: "Alice" },
          sheriff_elected: "Alice",
          speech_order: ["Cora", "Dan", "Bob", "Alice"],
          speech_order_choice: "警左发言",
          sheriff_badge_target: "Cora",
        }}
      />,
    );

    expect(screen.getByText("警长竞选")).toBeInTheDocument();
    expect(screen.getByText("上警：Alice、Bob")).toBeInTheDocument();
    expect(screen.getByText("警下：Cora、Dan")).toBeInTheDocument();
    expect(screen.getByText("警上发言")).toBeInTheDocument();
    expect(screen.getByText("Alice：我上警争警徽。")).toBeInTheDocument();
    expect(screen.getByText("退水：Bob")).toBeInTheDocument();
    expect(screen.getByText("最终候选：Alice")).toBeInTheDocument();
    expect(screen.getByText("PK 候选：Alice、Bob")).toBeInTheDocument();
    expect(screen.getByText("PK 发言")).toBeInTheDocument();
    expect(screen.getByText("Alice：PK 我继续站边自己。")).toBeInTheDocument();
    expect(screen.getByText("二轮投票")).toBeInTheDocument();
    expect(screen.getAllByText("Cora -> Alice")).toHaveLength(2);
    expect(screen.getByText("Alice 当选警长")).toBeInTheDocument();
    expect(screen.getByText("当前警长：Alice")).toBeInTheDocument();
    expect(screen.getByText("警徽移交：Cora")).toBeInTheDocument();
    expect(screen.getByText("发言方向：警左发言")).toBeInTheDocument();
    expect(screen.getByText("发言顺序：Cora -> Dan -> Bob -> Alice")).toBeInTheDocument();
  });

  it("shows lost badge and no-sheriff speech direction states", () => {
    render(
      <SheriffElectionPanel
        round={{
          ...baseRound,
          sheriff_badge_lost: true,
          speech_order: ["Alice", "Bob"],
        }}
      />,
    );

    expect(screen.getByText("警徽流失")).toBeInTheDocument();
    expect(screen.getByText("无警长，按座次顺序发言")).toBeInTheDocument();
    expect(screen.getByText("发言顺序：Alice -> Bob")).toBeInTheDocument();
  });
});
