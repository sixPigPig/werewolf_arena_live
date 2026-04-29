import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DebugItem, GameRound } from "../types";
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
  summaries: {},
  success: true,
};

const sheriffBadgeItem: DebugItem = {
  id: "round-1-day-sheriff-badge",
  roundNumber: 1,
  phase: "day",
  title: "警徽处理",
  actor: "Jacob",
  action: "sheriff_badge",
  choice: "撕毁警徽",
  prompt: "请选择警徽处理方式。",
  rawResponse: '{"badge":"撕毁警徽"}',
  parsed: { badge: "撕毁警徽" },
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
    expect(
      within(screen.getByRole("list", { name: "上警名单" })).getByText("Alice"),
    ).toBeInTheDocument();
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

  it("shows sheriff badge handling with the day exile result", () => {
    render(
      <DayPhase
        round={{
          ...baseRound,
          hunter_shot: null,
          idiot_revealed: null,
          exiled: "Jacob",
          day_deaths: [{ player: "Jacob", cause: "vote_exile", source: "投票" }],
          sheriff_elected: "Jacob",
          sheriff_badge_lost: true,
          votes: [
            { voter: "David", target: "Jacob", weight: 1 },
            { voter: "Tyler", target: "Jacob", weight: 1 },
          ],
          voteTally: [{ target: "Jacob", count: 2 }],
          voteCount: 2,
          voteMajorityThreshold: 2,
        }}
        items={[sheriffBadgeItem]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Jacob 被放逐")).toBeInTheDocument();
    expect(screen.getByText("白天死亡：Jacob")).toBeInTheDocument();
    expect(
      screen.getByText("警徽处理：Jacob 选择 撕毁警徽"),
    ).toBeInTheDocument();
  });

  it("hides sheriff badge handling when the day badge owner does not change", () => {
    render(
      <DayPhase
        round={{
          ...baseRound,
          hunter_shot: null,
          idiot_revealed: null,
          exiled: "Bert",
          day_deaths: [{ player: "Bert", cause: "vote_exile", source: "投票" }],
          sheriff: "Mason",
          sheriff_badge_target: "Mason",
          votes: [
            { voter: "Will", target: "Bert", weight: 1 },
            { voter: "Mason", target: "Bert", weight: 1.5 },
          ],
          voteTally: [{ target: "Bert", count: 2.5 }],
          voteCount: 2.5,
          voteMajorityThreshold: 2,
        }}
        items={[
          {
            ...sheriffBadgeItem,
            actor: "Mason",
            choice: "Mason",
          },
        ]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Bert 被放逐")).toBeInTheDocument();
    expect(screen.getByText("白天死亡：Bert")).toBeInTheDocument();
    expect(screen.queryByText(/警徽处理/)).not.toBeInTheDocument();
  });

  it("shows changed sheriff badge handling when the new sheriff is the target", () => {
    render(
      <DayPhase
        round={{
          ...baseRound,
          hunter_shot: null,
          idiot_revealed: null,
          exiled: "Alice",
          day_deaths: [{ player: "Alice", cause: "vote_exile", source: "投票" }],
          sheriff: "Cora",
          sheriff_badge_target: "Cora",
          votes: [
            { voter: "Bob", target: "Alice", weight: 1 },
            { voter: "Dan", target: "Alice", weight: 1 },
          ],
          voteTally: [{ target: "Alice", count: 2 }],
          voteCount: 2,
          voteMajorityThreshold: 2,
        }}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Alice 被放逐")).toBeInTheDocument();
    expect(screen.getByText("白天死亡：Alice")).toBeInTheDocument();
    expect(screen.getAllByText("警徽处理：移交给 Cora").length).toBeGreaterThan(0);
  });

  it("does not treat a failed sheriff election as an exiled player destroying the badge", () => {
    render(
      <DayPhase
        round={{
          ...baseRound,
          hunter_shot: null,
          idiot_revealed: null,
          exiled: "Tyler",
          day_deaths: [{ player: "Tyler", cause: "vote_exile", source: "投票" }],
          sheriff: null,
          sheriff_elected: null,
          sheriff_badge_lost: true,
          votes: [
            { voter: "Scott", target: "Tyler", weight: 1 },
            { voter: "Will", target: "Tyler", weight: 1 },
          ],
          voteTally: [{ target: "Tyler", count: 2 }],
          voteCount: 2,
          voteMajorityThreshold: 2,
        }}
        items={[]}
        selectedItem={null}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Tyler 被放逐")).toBeInTheDocument();
    expect(screen.getByText("白天死亡：Tyler")).toBeInTheDocument();
    expect(screen.queryByText("警徽处理：Tyler 选择 撕毁警徽")).not.toBeInTheDocument();
  });
});
