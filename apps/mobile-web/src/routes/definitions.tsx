import { Navigate, type RouteObject } from "react-router-dom";

import { MobileAppShell } from "../layout/MobileAppShell";
import { GameDetailPage } from "../pages/GameDetailPage";
import { GamesPage } from "../pages/GamesPage";
import { HistoryPage } from "../pages/HistoryPage";
import { LivePage } from "../pages/LivePage";
import { PlaybackPage } from "../pages/PlaybackPage";
import { PlayerDetailPage } from "../pages/PlayerDetailPage";
import { PlayersPage } from "../pages/PlayersPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <MobileAppShell />,
    children: [
      { index: true, element: <Navigate to="/games" replace /> },
      { path: "games", element: <GamesPage /> },
      { path: "games/:gameId", element: <GameDetailPage /> },
      { path: "games/:gameId/live", element: <LivePage /> },
      { path: "games/:gameId/replay", element: <PlaybackPage /> },
      { path: "players", element: <PlayersPage /> },
      { path: "players/:playerId", element: <PlayerDetailPage /> },
      { path: "history", element: <HistoryPage /> },
    ],
  },
];
