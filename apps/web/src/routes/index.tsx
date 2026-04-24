import { Navigate, createBrowserRouter } from "react-router-dom";

import { GameDetailPage } from "../pages/GameDetailPage";
import { GamesPage } from "../pages/GamesPage";

export const router = createBrowserRouter([
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
]);
