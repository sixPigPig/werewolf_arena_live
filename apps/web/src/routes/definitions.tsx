import { Navigate, type RouteObject } from "react-router-dom";

import { ComponentButtonShowcasePage } from "../pages/ComponentButtonShowcasePage";
import { GameDetailPage } from "../pages/GameDetailPage";
import { GameHistoryPage } from "../pages/GameHistoryPage";
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
    path: "/games/:sessionId",
    element: <GameDetailPage />,
  },
];
