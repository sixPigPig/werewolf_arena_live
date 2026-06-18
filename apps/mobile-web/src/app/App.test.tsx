/// <reference types="node" />

import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { RouterProvider, createMemoryRouter, type RouteObject } from "react-router-dom";

import { routes } from "../routes/definitions";
import { updateRootFontSize } from "../styles/rem";

const requiredRoutes = [
  "/",
  "/games",
  "/games/:gameId",
  "/games/:gameId/live",
  "/games/:gameId/replay",
  "/players",
  "/players/:playerId",
  "/history",
];

const routeSmokeCases = [
  { path: "/", heading: "移动大厅" },
  { path: "/games", heading: "移动大厅" },
  { path: "/games/wolf-1", heading: "对局详情" },
  { path: "/games/wolf-1/live", heading: "实时观战" },
  { path: "/games/wolf-1/replay", heading: "移动复盘" },
  { path: "/players", heading: "玩家图鉴" },
  { path: "/players/seer-1", heading: "玩家详情" },
  { path: "/history", heading: "对局历史" },
];

function joinRoutePath(parentPath: string, childPath?: string) {
  if (!childPath) {
    return parentPath || "/";
  }

  if (childPath.startsWith("/")) {
    return childPath;
  }

  const basePath = parentPath === "/" ? "" : parentPath;

  return `${basePath}/${childPath}`;
}

function collectPublicRoutePaths(routeObjects: RouteObject[], parentPath = ""): string[] {
  return routeObjects.flatMap((route) => {
    const routePath = route.index ? parentPath || "/" : joinRoutePath(parentPath, route.path);

    if (route.children?.length) {
      return collectPublicRoutePaths(route.children, routePath);
    }

    return [routePath];
  });
}

describe("mobile app scaffold", () => {
  it("redirects the mobile root route to games", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "移动大厅" })).toBeInTheDocument();
  });

  it("declares the required mobile routes without extras", () => {
    expect(collectPublicRoutePaths(routes)).toEqual(requiredRoutes);
  });

  it("renders every required mobile route", async () => {
    for (const routeCase of routeSmokeCases) {
      const router = createMemoryRouter(routes, { initialEntries: [routeCase.path] });
      const { unmount } = render(<RouterProvider router={router} />);

      expect(await screen.findByRole("heading", { name: routeCase.heading })).toBeInTheDocument();

      unmount();
    }
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
