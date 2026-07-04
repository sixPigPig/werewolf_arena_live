import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LivePhaseBar } from "./LivePhaseBar";
import type { LivePhaseSegment } from "../livePhaseBar";

const segments: LivePhaseSegment[] = [
  {
    id: "round-1-night",
    round: 1,
    phase: "night",
    label: "夜一",
    startEventId: 3,
    isCurrent: false,
    isVisited: true,
  },
  {
    id: "round-1-day",
    round: 1,
    phase: "day",
    label: "昼一",
    startEventId: 8,
    isCurrent: true,
    isVisited: true,
  },
  {
    id: "round-2-night",
    round: 2,
    phase: "night",
    label: "夜二",
    startEventId: 13,
    isCurrent: false,
    isVisited: false,
  },
];

describe("LivePhaseBar", () => {
  it("renders phase buttons and marks the current step", () => {
    render(<LivePhaseBar onSelectPhase={() => {}} segments={segments} />);

    expect(screen.getByTestId("live-phase-bar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "从夜一开始播放" })).toHaveTextContent(
      "夜一",
    );
    expect(screen.getByRole("button", { name: "从昼一开始播放" })).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.getByRole("button", { name: "从夜二开始播放" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("selects the clicked phase segment", async () => {
    const user = userEvent.setup();
    const handleSelectPhase = vi.fn();
    render(
      <LivePhaseBar onSelectPhase={handleSelectPhase} segments={segments} />,
    );

    await user.click(screen.getByRole("button", { name: "从夜二开始播放" }));

    expect(handleSelectPhase).toHaveBeenCalledWith(segments[2]);
  });

  it("renders nothing when no phase segments exist", () => {
    const { container } = render(
      <LivePhaseBar onSelectPhase={() => {}} segments={[]} />,
    );

    expect(screen.queryByTestId("live-phase-bar")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});
