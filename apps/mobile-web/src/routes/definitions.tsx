import type { RouteObject } from "react-router-dom";

import { MobileAppShell } from "../layout/MobileAppShell";
import { CustomGamePage } from "../pages/CustomGamePage";
import { GameHomePage } from "../pages/GameHomePage";
import { LivePage } from "../pages/LivePage";

function starterPage(title: string) {
  return (
    <section className="mobile-page-section">
      <h2>{title}</h2>
      <p>手机版 Web 正在搭建中</p>
      <p>路由已就绪，当前页面用于验证移动端导航和页面壳。</p>
    </section>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <MobileAppShell />,
    children: [
      { index: true, element: <GameHomePage /> },
      { path: "players", element: starterPage("玩家") },
      { path: "history", element: starterPage("历史") },
      { path: "settings", element: starterPage("设置") },
      { path: "custom-game", element: <CustomGamePage /> },
      { path: "live/:runId", element: <LivePage /> },
      { path: "playback/:sessionId", element: starterPage("手机复盘") },
    ],
  },
];
