import { render, screen } from "@testing-library/react";

import { App } from "../app/App";

describe("App", () => {
  it("renders the project shell heading", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: /python \+ react monorepo is ready/i }),
    ).toBeInTheDocument();
  });
});
