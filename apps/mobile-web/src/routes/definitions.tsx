import { Navigate, type RouteObject } from "react-router-dom";

import { GameDetailPage } from "../pages/GameDetailPage";
import { GamesPage } from "../pages/GamesPage";
import { HistoryPage } from "../pages/HistoryPage";
import { LivePage } from "../pages/LivePage";
import { PlaybackPage } from "../pages/PlaybackPage";
import { PlayersPage } from "../pages/PlayersPage";

export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/games" replace /> },
  { path: "/games", element: <GamesPage /> },
  { path: "/players", element: <PlayersPage /> },
  { path: "/games/history", element: <HistoryPage /> },
  { path: "/games/live/:runId", element: <LivePage /> },
  { path: "/games/playback/:sessionId", element: <PlaybackPage /> },
  { path: "/games/:sessionId", element: <GameDetailPage /> },
];
