import { QueryClientProvider } from "@tanstack/react-query";
import type { RouteObject } from "react-router-dom";

import { queryClient } from "../lib/query-client";
import { MobileAppShell } from "../layout/MobileAppShell";
import { GameHomePage } from "../pages/GameHomePage";

function starterPage(title: string) {
  return (
    <section className="mobile-page-section">
      <h2>{title}</h2>
      <p>手机版 Web 正在搭建中</p>
      <p>路由已就绪，当前页面用于验证移动端导航和页面壳。</p>
    </section>
  );
}

function gameHomePage() {
  return (
    <QueryClientProvider client={queryClient}>
      <GameHomePage />
    </QueryClientProvider>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <MobileAppShell />,
    children: [
      { index: true, element: gameHomePage() },
      { path: "players", element: starterPage("玩家") },
      { path: "history", element: starterPage("历史") },
      { path: "settings", element: starterPage("设置") },
      { path: "custom-game", element: starterPage("自定义开局") },
      { path: "live/:runId", element: starterPage("实时直播") },
      { path: "playback/:sessionId", element: starterPage("手机复盘") },
    ],
  },
];
