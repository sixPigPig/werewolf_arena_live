import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MobileLivePhaseBar } from "./MobileLivePhaseBar";
import type { LivePhaseSegment } from "@werewolf-arena/game-client";

const segments: LivePhaseSegment[] = [
  {
    id: "round-1-night",
    round: 1,
    phase: "night",
    label: "夜一",
    startEventId: 2,
    isCurrent: false,
    isVisited: true,
  },
  {
    id: "round-1-day",
    round: 1,
    phase: "day",
    label: "昼一",
    startEventId: 5,
    isCurrent: true,
    isVisited: true,
  },
  {
    id: "round-2-night",
    round: 2,
    phase: "night",
    label: "夜二",
    startEventId: 8,
    isCurrent: false,
    isVisited: false,
  },
];

describe("MobileLivePhaseBar", () => {
  it("collapses night and day phases behind a current-day trigger", () => {
    render(<MobileLivePhaseBar onSelectPhase={() => {}} segments={segments} />);

    expect(screen.getByTestId("mobile-live-phase-bar")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "选择阶段，当前第1天" }),
    ).toHaveTextContent("第1天");
    expect(
      screen.queryByRole("button", { name: "跳转到夜一" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "跳转到昼一" }),
    ).not.toBeInTheDocument();
  });

  it("opens a translucent day list and marks the current day", async () => {
    const user = userEvent.setup();
    render(<MobileLivePhaseBar onSelectPhase={() => {}} segments={segments} />);

    await user.click(screen.getByRole("button", { name: "选择阶段，当前第1天" }));

    expect(screen.getByTestId("mobile-live-phase-popover")).toBeVisible();
    expect(screen.getByRole("button", { name: "跳转到第1天" })).toHaveTextContent(
      "第1天",
    );
    expect(screen.getByRole("button", { name: "跳转到第1天" })).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.getByRole("button", { name: "跳转到第2天" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.queryByText("夜一")).not.toBeInTheDocument();
    expect(screen.queryByText("昼一")).not.toBeInTheDocument();
  });

  it("selects the clicked day from its first phase and closes the list", async () => {
    const user = userEvent.setup();
    const handleSelectPhase = vi.fn();
    render(
      <MobileLivePhaseBar
        onSelectPhase={handleSelectPhase}
        segments={segments}
      />,
    );

    await user.click(screen.getByRole("button", { name: "选择阶段，当前第1天" }));
    await user.click(screen.getByRole("button", { name: "跳转到第2天" }));

    expect(handleSelectPhase).toHaveBeenCalledWith(segments[2]);
    expect(
      screen.queryByRole("button", { name: "跳转到第2天" }),
    ).not.toBeInTheDocument();
  });

  it("renders nothing without phase segments", () => {
    const { container } = render(
      <MobileLivePhaseBar onSelectPhase={() => {}} segments={[]} />,
    );

    expect(screen.queryByTestId("mobile-live-phase-bar")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});
