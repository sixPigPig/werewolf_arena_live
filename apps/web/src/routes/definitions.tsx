import { Navigate, type RouteObject } from "react-router-dom";

import { ComponentButtonShowcasePage } from "../pages/ComponentButtonShowcasePage";
import { GameDetailPage } from "../pages/GameDetailPage";
import { GameHistoryPage } from "../pages/GameHistoryPage";
import { GamePlaybackPage } from "../pages/GamePlaybackPage";
import { GamesPage } from "../pages/GamesPage";
import { LiveGamePage } from "../pages/LiveGamePage";
import { PlayersPage } from "../pages/PlayersPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Navigate to="/games" replace />,
  },
  {
    path: "/games",
    element: <GamesPage />,
  },
  {
    path: "/players",
    element: <PlayersPage />,
  },
  {
    path: "/games/history",
    element: <GameHistoryPage />,
  },
  {
    path: "/games/live/:runId",
    element: <LiveGamePage />,
  },
  {
    path: "/components/buttons",
    element: <ComponentButtonShowcasePage />,
  },
  {
    path: "/games/playback/:sessionId",
    element: <GamePlaybackPage />,
  },
  {
    path: "/games/:sessionId",
    element: <GameDetailPage />,
  },
];
