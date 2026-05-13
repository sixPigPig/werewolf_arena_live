import type { ReactNode } from "react";

import siteBackground from "../assets/werewolf-site-background.png";

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
          backgroundImage: `linear-gradient(180deg, rgba(2, 6, 13, 0.26) 0%, rgba(2, 6, 13, 0.58) 48%, rgba(2, 6, 13, 0.82) 100%), url(${siteBackground})`,
          backgroundPosition: "center top",
        }}
      />
      <div className="site-content-layer relative z-10 min-h-screen pt-[var(--app-top-nav-height)]">
        {children}
      </div>
    </div>
  );
}
