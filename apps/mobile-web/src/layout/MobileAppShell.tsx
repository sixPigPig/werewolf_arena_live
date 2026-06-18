import { Outlet } from "react-router-dom";

import { MobileTabBar } from "./MobileTabBar";

export function MobileAppShell() {
  return (
    <div className="mobile-app-frame">
      <div className="mobile-app-shell" data-testid="mobile-app-shell">
        <header className="mobile-top-bar">
          <p className="mobile-kicker">Werewolf Arena</p>
          <h1>狼人杀竞技场</h1>
        </header>
        <main className="mobile-content-region">
          <Outlet />
        </main>
        <MobileTabBar />
      </div>
    </div>
  );
}
