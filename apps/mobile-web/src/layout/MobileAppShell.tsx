import { Outlet } from "react-router-dom";

import { MobileTabBar } from "./MobileTabBar";

export function MobileAppShell() {
  return (
    <div className="mobile-app-frame">
      <div className="mobile-app-shell">
        <div className="mobile-content-region">
          <Outlet />
        </div>
        <MobileTabBar />
      </div>
    </div>
  );
}
