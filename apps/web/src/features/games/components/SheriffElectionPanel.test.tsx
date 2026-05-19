import { render, screen, within } from "@testing-library/react";
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
  werewolf_discussion: [],
  werewolf_vote_rounds: [],
  debate: [],
  bids: [],
  bidGroups: [],
  votes: [],
  voteTally: [],
  voteCount: 0,
  voteMajorityThreshold: null,
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
          sheriff: "Cora",
          sheriff_candidates: ["Alice", "Bob"],
          sheriff_speech_order: ["Bob", "Alice"],
          sheriff_speech_direction: "逆时针",
          sheriff_speeches: [
            { speaker: "Bob", message: "我也上警。" },
            { speaker: "Alice", message: "我上警争警徽。" },
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
          day_deaths: [
            { player: "Alice", cause: "vote_exile", source: "投票" },
          ],
          speech_order: ["Cora", "Dan", "Bob", "Alice"],
          speech_order_choice: "警左发言",
          sheriff_badge_target: "Cora",
        }}
      />,
    );

    expect(screen.getByText("警长竞选")).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "上警名单" })).getByText("Alice"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "警下名单" })).getByText("Cora"),
    ).toBeInTheDocument();
    expect(screen.getByText("警上发言方向：逆时针")).toBeInTheDocument();
    expect(screen.getByText("警上发言顺序：Bob -> Alice")).toBeInTheDocument();
    expect(screen.getByText("警上发言")).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "警上发言" })).getByText("Alice"),
    ).toBeInTheDocument();
    expect(screen.getByText("我上警争警徽。")).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "退水名单" })).getByText("Bob"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "最终候选名单" })).getByText(
        "Alice",
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "PK 候选名单" })).getByText(
        "Alice",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("PK 发言")).toBeInTheDocument();
    expect(screen.getByText("PK 我继续站边自己。")).toBeInTheDocument();
    expect(screen.getByText("二轮投票")).toBeInTheDocument();
    expect(screen.getAllByText("Cora -> Alice")).toHaveLength(2);
    expect(screen.getByText("Alice 当选警长")).toBeInTheDocument();
    expect(screen.queryByText("当前警长：Cora")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Alice 被放逐后警徽处理：移交给 Cora"),
    ).not.toBeInTheDocument();
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

    expect(screen.getByText("警徽状态：警徽流失")).toBeInTheDocument();
    expect(screen.getByText("无警长，按座次顺序发言")).toBeInTheDocument();
    expect(screen.getByText("发言顺序：Alice -> Bob")).toBeInTheDocument();
  });

  it("shows double explosion badge loss reason", () => {
    render(
      <SheriffElectionPanel
        round={{
          ...baseRound,
          werewolf_self_exploded: "Bob",
          day_ended_by_self_explosion: true,
          sheriff_pre_election_bomb_count: 2,
          sheriff_badge_lost: true,
          sheriff_badge_lost_reason: "双爆吞警徽",
        }}
      />,
    );

    expect(screen.getByText("警徽状态：双爆吞警徽，警徽流失")).toBeInTheDocument();
  });

  it("explains when police-down voting is skipped because one final candidate remains", () => {
    render(
      <SheriffElectionPanel
        round={{
          ...baseRound,
          sheriff_candidates: ["Alice", "Bob"],
          sheriff_withdrawn: ["Bob"],
          sheriff_final_candidates: ["Alice"],
          sheriff_voters: ["Cora", "Dan"],
          sheriff_elected: "Alice",
        }}
      />,
    );

    expect(
      screen.getByText("警下投票：无需投票，最终候选仅 Alice，自动当选"),
    ).toBeInTheDocument();
    expect(screen.getByText("Alice 当选警长")).toBeInTheDocument();
  });

  it("hides badge handling in the election panel when the elected sheriff dies later in the day", () => {
    render(
      <SheriffElectionPanel
        round={{
          ...baseRound,
          sheriff_candidates: ["Alice", "Bob"],
          sheriff_withdrawn: ["Bob"],
          sheriff_final_candidates: ["Alice"],
          sheriff_elected: "Alice",
          day_deaths: [
            { player: "Alice", cause: "vote_exile", source: "投票" },
          ],
          sheriff_badge_lost: true,
        }}
      />,
    );

    expect(screen.getByText("Alice 当选警长")).toBeInTheDocument();
    expect(
      screen.queryByText("Alice 被放逐后警徽处理：撕毁警徽"),
    ).not.toBeInTheDocument();
  });

  it("shows badge handling when the elected sheriff death is announced right after election", () => {
    render(
      <SheriffElectionPanel
        round={{
          ...baseRound,
          sheriff_candidates: ["Alice", "Bob"],
          sheriff_withdrawn: ["Bob"],
          sheriff_final_candidates: ["Alice"],
          sheriff_elected: "Alice",
          night_deaths: [
            { player: "Alice", cause: "werewolf_attack", source: "狼人" },
          ],
          sheriff_badge_lost: true,
        }}
      />,
    );

    expect(screen.getByText("Alice 当选警长")).toBeInTheDocument();
    expect(
      screen.getByText("Alice 夜晚出局后警徽处理：撕毁警徽"),
    ).toBeInTheDocument();
  });
});
