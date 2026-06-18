import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import { routes } from "../routes/definitions";
import { updateRootFontSize } from "../styles/rem";

describe("mobile app scaffold", () => {
  it("redirects the mobile root route to games", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "移动大厅" })).toBeInTheDocument();
  });

  it("uses px2rem with the approved 375px baseline", () => {
    const config = readFileSync("postcss.config.cjs", "utf8");

    expect(config).toContain("postcss-pxtorem");
    expect(config).toContain("rootValue: 37.5");
  });

  it("sets 37.5px root font size at a 375px viewport", () => {
    const html = document.documentElement;

    updateRootFontSize(375);

    expect(html.style.fontSize).toBe("37.5px");
  });
});
