import { Button } from "../components/ui";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import logoSrc from "../assets/langrensha-c-logo@1x.png";

type AppTopNavProps = {
  actions?: ReactNode;
  className?: string;
  context?: ReactNode;
  layout?: "default" | "command";
  projectName?: string;
  showHistoryLink?: boolean;
  showLobbyBack?: boolean;
  tone?: "default" | "nocturne";
};

export function AppTopNav({
  actions,
  className,
  context,
  layout = "default",
  projectName = "狼人杀竞技场",
  showHistoryLink = false,
  showLobbyBack = false,
  tone = "default",
}: AppTopNavProps) {
  const isCommand = layout === "command";
  const toneClass =
    tone === "nocturne"
      ? "border-amber-500/20 text-amber-50 shadow-[0_18px_55px_rgba(0,0,0,0.36)]"
      : "border-slate-800 text-slate-50 shadow-[0_12px_40px_rgba(15,23,42,0.18)]";
  const headerClass = isCommand
    ? "app-top-nav live-command-nav h-[56px] min-h-[56px] w-full border-b border-amber-500/20 text-amber-50"
    : `app-top-nav h-[56px] min-h-[56px] w-full border-b backdrop-blur-xl ${toneClass}`;
  const innerClass = isCommand
    ? "app-top-nav-inner live-command-nav-inner mx-auto flex h-full w-full max-w-none flex-row items-center justify-between gap-3 overflow-x-auto rounded-none px-3 shadow-[0_18px_55px_rgba(0,0,0,0.42),inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-xl"
    : "app-top-nav-inner mx-auto flex h-full w-full max-w-none flex-row items-center justify-between gap-3 px-3";
  const primaryClass = isCommand
    ? "app-top-nav-primary flex min-w-0 flex-1 flex-row items-center gap-3"
    : context
      ? "app-top-nav-primary flex min-w-0 flex-1 flex-row items-center gap-3"
      : "app-top-nav-primary flex min-w-0 flex-row items-center";
  const linkClass = isCommand
    ? "group flex h-12 w-12 shrink-0 items-center justify-center rounded-md text-left transition focus:outline-none focus:ring-2 focus:ring-amber-300/70"
    : "group flex min-w-0 shrink-0 items-center gap-2 rounded-md text-left focus:outline-none focus:ring-2 focus:ring-amber-300/70";
  const logoClass = isCommand
    ? "app-logo-placeholder flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-md"
    : "app-logo-placeholder h-12 w-12 shrink-0 overflow-hidden rounded-md";
  const actionsClass = isCommand
    ? "app-top-nav-actions live-command-actions flex w-auto shrink-0 flex-nowrap items-center gap-2"
    : "app-top-nav-actions flex w-auto shrink-0 flex-nowrap items-center justify-end gap-1.5";

  return (
    <header
      className={[headerClass, className].filter(Boolean).join(" ")}
      data-testid="app-top-nav"
    >
      <div className={innerClass}>
        <div className={primaryClass}>
          <Link
            className={linkClass}
            to="/games"
          >
            <span
              aria-hidden="true"
              className={logoClass}
              data-testid="app-logo-placeholder"
            >
              <img
                alt=""
                className="h-full w-full rounded-[inherit] object-cover"
                data-testid="app-logo-image"
                src={logoSrc}
              />
            </span>
            <span
              className={
                isCommand
                  ? "app-project-name sr-only"
                  : "app-project-name truncate text-sm font-semibold tracking-wide"
              }
            >
              {projectName}
            </span>
          </Link>
          {context ? (
            <div className="app-top-nav-context min-w-0 flex-1">
              {context}
            </div>
          ) : null}
        </div>
        <nav
          aria-label="页面功能"
          className={actionsClass}
          data-testid="app-top-nav-actions"
        >
          {showHistoryLink ? (
            <Button asChild color="gray" highContrast size="1" variant="surface">
              <Link to="/games/history">对局历史</Link>
            </Button>
          ) : null}
          {showLobbyBack ? (
            <Button asChild color="gray" highContrast size="1" variant="surface">
              <Link to="/games">返回大厅</Link>
            </Button>
          ) : null}
          {actions}
        </nav>
      </div>
    </header>
  );
}
