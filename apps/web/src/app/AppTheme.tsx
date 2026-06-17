import type { ReactNode } from "react";

import siteBackground from "../assets/werewolf-castle-background.png";

type AppThemeProps = {
  children: ReactNode;
};

export function AppTheme({ children }: AppThemeProps) {
  return (
    <div className="app-theme relative isolate min-h-screen overflow-x-hidden text-slate-50">
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 z-0 bg-cover bg-center bg-no-repeat"
        data-testid="site-background"
        style={{
          backgroundImage: `url(${siteBackground})`,
          backgroundPosition: "center top",
          backgroundSize: "cover",
        }}
      />
      <div className="site-content-layer relative z-10 min-h-screen pt-[var(--arena-nav-height,var(--app-top-nav-height,56px))]">
        {children}
      </div>
    </div>
  );
}
