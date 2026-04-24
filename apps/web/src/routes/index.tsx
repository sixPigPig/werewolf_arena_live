import {
  Navigate,
  createBrowserRouter,
  type RouteObject,
} from "react-router-dom";

import { GameDetailPage } from "../pages/GameDetailPage";
import { GamesPage } from "../pages/GamesPage";

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
    path: "/games/:sessionId",
    element: <GameDetailPage />,
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}

export const router = createAppRouter();
