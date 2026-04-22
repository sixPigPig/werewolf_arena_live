import { render, screen } from "@testing-library/react";

import { HomePage } from "../pages/HomePage";

describe("HomePage", () => {
  it("renders the project shell heading", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", { name: /python \+ react monorepo is ready/i }),
    ).toBeInTheDocument();
  });
});
