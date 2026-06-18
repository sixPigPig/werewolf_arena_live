import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the mobile scaffold copy", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "狼人杀竞技场" }),
    ).toBeInTheDocument();
    expect(screen.getByText("手机版 Web 正在搭建中")).toBeInTheDocument();
  });
});
