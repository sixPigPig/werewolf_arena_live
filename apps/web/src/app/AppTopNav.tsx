import { Button } from "@radix-ui/themes";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type AppTopNavProps = {
  actions?: ReactNode;
  projectName?: string;
  showLobbyBack?: boolean;
  tone?: "default" | "nocturne";
};

export function AppTopNav({
  actions,
  projectName = "狼人杀竞技场",
  showLobbyBack = false,
  tone = "default",
}: AppTopNavProps) {
  const toneClass =
    tone === "nocturne"
      ? "border-amber-500/20 bg-[#071015]/95 text-amber-50 shadow-[0_18px_55px_rgba(0,0,0,0.36)]"
      : "border-slate-800 bg-slate-950 text-slate-50 shadow-[0_12px_40px_rgba(15,23,42,0.18)]";

  return (
    <header
      className={`app-top-nav w-full border-b backdrop-blur-xl ${toneClass}`}
      data-testid="app-top-nav"
    >
      <div className="app-top-nav-inner mx-auto flex w-full max-w-none flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <Link
          className="group flex min-w-0 items-center gap-3 rounded-md text-left focus:outline-none focus:ring-2 focus:ring-amber-300/70"
          to="/games"
        >
          <span
            aria-hidden="true"
            className="app-logo-placeholder h-10 w-10 shrink-0 rounded-md border border-amber-300/40 bg-slate-900/80 shadow-[inset_0_0_18px_rgba(251,191,36,0.1)] transition group-hover:border-amber-200/70"
            data-testid="app-logo-placeholder"
          />
          <span className="app-project-name truncate text-base font-semibold tracking-wide">
            {projectName}
          </span>
        </Link>
        <nav
          aria-label="页面功能"
          className="app-top-nav-actions flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end"
          data-testid="app-top-nav-actions"
        >
          {showLobbyBack ? (
            <Button asChild color="gray" highContrast variant="surface">
              <Link to="/games">返回大厅</Link>
            </Button>
          ) : null}
          {actions}
        </nav>
      </div>
    </header>
  );
}
