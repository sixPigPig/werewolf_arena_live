import type { RouteObject } from "react-router-dom";

import { MobileAppShell } from "../layout/MobileAppShell";
import { CustomGamePage } from "../pages/CustomGamePage";
import { GameHomePage } from "../pages/GameHomePage";
import { HistoryPage } from "../pages/HistoryPage";
import { LivePage } from "../pages/LivePage";
import { PlaybackPage } from "../pages/PlaybackPage";
import { PlayersPage } from "../pages/PlayersPage";
import { SettingsPage } from "../pages/SettingsPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <MobileAppShell />,
    children: [
      { index: true, element: <GameHomePage /> },
      { path: "players", element: <PlayersPage /> },
      { path: "history", element: <HistoryPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "custom-game", element: <CustomGamePage /> },
      { path: "live/:runId", element: <LivePage /> },
      { path: "playback/:sessionId", element: <PlaybackPage /> },
    ],
  },
];
