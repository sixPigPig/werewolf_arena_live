import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveNavSessionBadge } from "./LiveNavSessionBadge";

describe("LiveNavSessionBadge", () => {
  it("renders the game session id as the first-class nav context", () => {
    render(<LiveNavSessionBadge sessionId="game_1200abcd" />);

    const badge = screen.getByTestId("live-nav-session");

    expect(badge).toHaveTextContent("对局");
    expect(badge).toHaveTextContent("game_1200abcd");
    expect(screen.getByText("game_1200abcd")).toHaveClass(
      "font-mono",
      "truncate",
    );
    expect(screen.getByText("game_1200abcd")).toHaveAttribute(
      "title",
      "game_1200abcd",
    );
  });
});
