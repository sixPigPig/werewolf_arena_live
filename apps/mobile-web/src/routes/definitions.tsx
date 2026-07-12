import { Navigate, type RouteObject } from "react-router-dom";

import { MobileAppShell } from "../layout/MobileAppShell";

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
      {
        path: "games",
        lazy: async () => {
          const { GamesPage } = await import("../pages/GamesPage");
          return { Component: GamesPage };
        },
      },
      {
        path: "games/:gameId",
        lazy: async () => {
          const { GameDetailPage } = await import("../pages/GameDetailPage");
          return { Component: GameDetailPage };
        },
      },
      {
        path: "games/:gameId/live",
        lazy: async () => {
          const { LivePage } = await import("../pages/LivePage");
          return { Component: LivePage };
        },
      },
      {
        path: "games/:gameId/live-replay",
        lazy: async () => {
          const { LiveReplayPage } = await import("../pages/LiveReplayPage");
          return { Component: LiveReplayPage };
        },
      },
      {
        path: "games/:gameId/replay",
        lazy: async () => {
          const { PlaybackPage } = await import("../pages/PlaybackPage");
          return { Component: PlaybackPage };
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
      {
        path: "history",
        lazy: async () => {
          const { HistoryPage } = await import("../pages/HistoryPage");
          return { Component: HistoryPage };
        },
      },
    ],
  },
];
