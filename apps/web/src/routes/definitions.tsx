import { Navigate, type RouteObject } from "react-router-dom";

import { GameDetailPage } from "../pages/GameDetailPage";
import { GamesPage } from "../pages/GamesPage";
import { LiveGamePage } from "../pages/LiveGamePage";

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
    path: "/games/live/:runId",
    element: <LiveGamePage />,
  },
  {
    path: "/games/:sessionId",
    element: <GameDetailPage />,
  },
];
