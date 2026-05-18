import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LiveDirectorControls } from "./LiveDirectorControls";

describe("LiveDirectorControls", () => {
  it("offers only 1x and 2x speed choices", () => {
    render(
      <LiveDirectorControls
        backlogCount={0}
        isPaused={false}
        onCatchUpToLatest={() => {}}
        onSpeedChange={() => {}}
        onTogglePaused={() => {}}
        speed={1}
      />,
    );

    const speedSelect = screen.getByLabelText("播放速度");
    const options = within(speedSelect).getAllByRole("option");

    expect(options).toHaveLength(2);
    expect(options.map((option) => option.textContent)).toEqual(["1x", "2x"]);
  });

  it("reports 2x speed changes", async () => {
    const user = userEvent.setup();
    const handleSpeedChange = vi.fn();

    render(
      <LiveDirectorControls
        backlogCount={0}
        isPaused={false}
        onCatchUpToLatest={() => {}}
        onSpeedChange={handleSpeedChange}
        onTogglePaused={() => {}}
        speed={1}
      />,
    );

    await user.selectOptions(screen.getByLabelText("播放速度"), "2");

    expect(handleSpeedChange).toHaveBeenCalledWith(2);
  });
});
