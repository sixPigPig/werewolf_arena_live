import { Navigate, type RouteObject } from "react-router-dom";

import { MobileAppShell } from "../layout/MobileAppShell";
import { godViewRoute, liveRoute } from "../match/routes";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <MobileAppShell />,
    hydrateFallbackElement: (
      <main className="mobile-route-loading" role="status">
        正在进入竞技场…
      </main>
    ),
    children: [
      { index: true, element: <Navigate to="/games" replace /> },
      liveRoute,
      godViewRoute,
      {
        path: "games",
        lazy: async () => {
          const { GamesPage } = await import("../pages/GamesPage");
          return { Component: GamesPage };
        },
      },
      {
        path: "players",
        lazy: async () => {
          const { PlayersPage } = await import("../pages/PlayersPage");
          return { Component: PlayersPage };
        },
      },
      {
        path: "players/:playerId",
        lazy: async () => {
          const { PlayerDetailPage } = await import("../pages/PlayerDetailPage");
          return { Component: PlayerDetailPage };
        },
      },
    ],
  },
];
