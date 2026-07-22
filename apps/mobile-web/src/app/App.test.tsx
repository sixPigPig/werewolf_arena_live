/// <reference types="node" />

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import {
  Navigate,
  RouterProvider,
  createMemoryRouter,
  type RouteObject,
} from "react-router-dom";

import { MobileAppShell } from "../layout/MobileAppShell";
import { GameDetailPage } from "../pages/GameDetailPage";
import { GamesPage } from "../pages/GamesPage";
import { HistoryPage } from "../pages/HistoryPage";
import { LivePage } from "../pages/LivePage";
import { LiveReplayPage } from "../pages/LiveReplayPage";
import { PlaybackPage } from "../pages/PlaybackPage";
import { PlayerDetailPage } from "../pages/PlayerDetailPage";
import { PlayersPage } from "../pages/PlayersPage";
import { routes } from "../routes/definitions";
import { updateRootFontSize } from "../styles/rem";
import { LiveV2Page } from "../v2/live/LiveV2Page";
import { GodViewPage } from "../v2/god-view/GodViewPage";

const requiredRoutes = [
  "/",
  "/v2/games/:gameId/live",
  "/v2/games/:gameId/live/god",
  "/games",
  "/games/:gameId",
  "/games/:gameId/live",
  "/games/:gameId/live-replay",
  "/games/:gameId/replay",
  "/players",
  "/players/:playerId",
  "/history",
];

const routeSmokeCases = [
  { path: "/", heading: "狼人杀对局大厅" },
  { path: "/v2/games/wolf-1/live", heading: "Live V2" },
  { path: "/v2/games/wolf-1/live/god", heading: "上帝视角" },
  { path: "/games", heading: "狼人杀对局大厅" },
  { path: "/games/wolf-1", heading: "移动复盘" },
  { path: "/games/wolf-1/live", heading: "实时观战" },
  { path: "/games/wolf-1/live-replay", heading: "历史直播回放" },
  { path: "/games/wolf-1/replay", heading: "移动复盘" },
  { path: "/players", heading: "玩家图鉴" },
  { path: "/players/seer-1", heading: "玩家详情" },
  { path: "/history", heading: "对局历史" },
];

const eagerTestRoutes: RouteObject[] = [
  {
    path: "/",
    element: <MobileAppShell />,
    children: [
      { index: true, element: <Navigate to="/games" replace /> },
      { path: "v2/games/:gameId/live", element: <LiveV2Page /> },
      { path: "v2/games/:gameId/live/god", element: <GodViewPage /> },
      { path: "games", element: <GamesPage /> },
      { path: "games/:gameId", element: <GameDetailPage /> },
      { path: "games/:gameId/live", element: <LivePage /> },
      { path: "games/:gameId/live-replay", element: <LiveReplayPage /> },
      { path: "games/:gameId/replay", element: <PlaybackPage /> },
      { path: "players", element: <PlayersPage /> },
      { path: "players/:playerId", element: <PlayerDetailPage /> },
      { path: "history", element: <HistoryPage /> },
    ],
  },
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

function renderWithQueryClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("mobile app scaffold", () => {
  it("redirects the mobile root route to games", async () => {
    const router = createMemoryRouter(eagerTestRoutes, { initialEntries: ["/"] });

    renderWithQueryClient(<RouterProvider router={router} />);

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/games");
    });
    expect(
      await screen.findByRole("heading", { name: "狼人杀对局大厅" }),
    ).toBeInTheDocument();
  });

  it("declares the required mobile routes without extras", () => {
    expect(collectPublicRoutePaths(routes)).toEqual(requiredRoutes);
  });

  it("renders every required mobile route", async () => {
    for (const routeCase of routeSmokeCases) {
      const router = createMemoryRouter(eagerTestRoutes, {
        initialEntries: [routeCase.path],
      });
      const { unmount } = renderWithQueryClient(
        <RouterProvider router={router} />,
      );

      expect(await screen.findByRole("heading", { name: routeCase.heading })).toBeInTheDocument();

      unmount();
    }
  });

  it("uses px2rem with the approved 375px baseline", () => {
    const config = readFileSync("postcss.config.cjs", "utf8");

    expect(config).toContain("postcss-pxtorem");
    expect(config).toContain("rootValue: 37.5");
  });

  it("locks the mobile viewport scale", () => {
    const html = readFileSync("index.html", "utf8");
    const viewportContent =
      html.match(/<meta\s+[^>]*name="viewport"[^>]*content="([^"]+)"/)?.[1] ?? "";
    const viewportOptions = viewportContent
      .split(",")
      .map((option) => option.trim());

    expect(viewportOptions).toEqual(
      expect.arrayContaining([
        "width=device-width",
        "initial-scale=1.0",
        "minimum-scale=1.0",
        "maximum-scale=1.0",
        "user-scalable=no",
        "viewport-fit=cover",
      ]),
    );
  });

  it("sets 37.5px root font size at a 375px viewport", () => {
    const html = document.documentElement;

    updateRootFontSize(375);

    expect(html.style.fontSize).toBe("37.5px");
  });

  it("keeps mobile typography compact for phone reading", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const bodyRule = styles.match(/(?:^|\n)body\s*{[^}]+}/)?.[0] ?? "";
    const pageTitleRule =
      styles.match(/(?:^|\n)\.mobile-page h1\s*{[^}]+}/)?.[0] ?? "";
    const buttonRule =
      styles.match(/(?:^|\n)\.mobile-button\s*{[^}]+}/)?.[0] ?? "";
    const liveStageTitleRule =
      styles.match(/(?:^|\n)\.mobile-live-center-stage strong\s*{[^}]+}/)?.[0] ?? "";
    const modalTitleRule =
      styles.match(/(?:^|\n)\.mobile-lobby-modal-header h2\s*{[^}]+}/)?.[0] ??
      "";
    const modalSubtitleRule =
      [...styles.matchAll(/(?:^|\n)\.mobile-lobby-modal-header p\s*{[^}]+}/g)]
        .map((match) => match[0])
        .find((rule) => rule.includes("font-size")) ?? "";

    expect(bodyRule).toContain("font-size: 14px");
    expect(pageTitleRule).toContain("font-size: 20px");
    expect(buttonRule).toContain("font-size: 13px");
    expect(liveStageTitleRule).toContain("font-size: 18px");
    expect(modalTitleRule).toContain("font-size: 16px");
    expect(modalSubtitleRule).toContain("font-size: 12px");
  });

  it("uses the shared 16px mobile page inline padding standard", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const rootRule = styles.match(/(?:^|\n):root\s*{[^}]+}/)?.[0] ?? "";
    const pageRule =
      styles.match(/(?:^|\n)\.mobile-page\s*{[^}]+}/)?.[0] ?? "";

    expect(rootRule).toContain("--mobile-page-padding-inline: 16px");
    expect(pageRule).toContain(
      "padding: 24px var(--mobile-page-padding-inline) 160px",
    );
  });

  it("keeps mobile form controls at the compact lobby size", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const baseFormControlRule =
      styles.match(/(?:^|\n)input,\nselect,\ntextarea\s*{[^}]+}/)?.[0] ?? "";
    const lobbyFieldRule =
      styles.match(
        /(?:^|\n)\.mobile-lobby-field input,\n\.mobile-profile-search input,\n\.mobile-profile-select select\s*{[^}]+}/,
      )?.[0] ?? "";
    const formLabelRule =
      styles.match(
        /(?:^|\n)\.mobile-lobby-field span,\n\.mobile-profile-search span,\n\.mobile-profile-select span\s*{[^}]+}/,
      )?.[0] ?? "";
    const selectTriggerRule =
      styles.match(/(?:^|\n)\.mobile-profile-select-trigger\s*{[^}]+}/)?.[0] ??
      "";
    const selectTriggerTextRule =
      styles.match(/(?:^|\n)\.mobile-profile-select-trigger span\s*{[^}]+}/)
        ?.[0] ?? "";
    const pickerRule =
      styles.match(
        /(?:^|\n)\.mobile-bottom-select-picker-popup \.adm-picker\s*{[^}]+}/,
      )?.[0] ?? "";

    expect(baseFormControlRule).toContain("font-size: 12px");
    expect(lobbyFieldRule).toContain("font-size: 12px");
    expect(formLabelRule).toContain("font-size: 12px");
    expect(selectTriggerRule).toContain("font-size: 12px");
    expect(selectTriggerTextRule).toContain("font-size: 12px");
    expect(pickerRule).toContain("--header-button-font-size: 16px");
    expect(pickerRule).toContain("--title-font-size: 16px");
    expect(pickerRule).toContain("--item-font-size: 16px");
  });
});
