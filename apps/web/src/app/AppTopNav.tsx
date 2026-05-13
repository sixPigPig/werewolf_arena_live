import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import brandLogoSrc from "../assets/langrensha-arena-nav-logo.png";
import logoSrc from "../assets/langrensha-c-logo@1x.png";

type AppTopNavProps = {
  actions?: ReactNode;
  brand?: "full" | "compact";
  className?: string;
  context?: ReactNode;
  density?: "regular" | "compact";
  projectName?: string;
  tone?: "default" | "nocturne";
  utilityActions?: ReactNode;
  variant?: "global" | "command";
};

export function AppTopNav({
  actions,
  brand = "full",
  className,
  context,
  density = "regular",
  projectName = "狼人杀竞技场",
  tone = "default",
  utilityActions,
  variant = "global",
}: AppTopNavProps) {
  const isCommand = variant === "command";
  const isCompactBrand = brand === "compact";
  const toneClass =
    tone === "nocturne"
      ? "border-white/10 text-amber-50 shadow-[0_12px_40px_rgba(0,0,0,0.10)]"
      : "border-white/10 text-slate-50 shadow-[0_12px_40px_rgba(15,23,42,0.10)]";
  const fixedTopClass = "fixed inset-x-0 top-0 z-50";
  const frostedClass = "bg-slate-950/[0.08] backdrop-blur-xl";
  const headerClass = isCommand
    ? `app-top-nav live-command-nav ${fixedTopClass} ${frostedClass} h-[var(--app-top-nav-height)] min-h-[var(--app-top-nav-height)] w-full border-b ${toneClass}`
    : `app-top-nav ${fixedTopClass} ${frostedClass} h-[var(--app-top-nav-height)] min-h-[var(--app-top-nav-height)] w-full border-b ${toneClass}`;
  const innerClass = isCommand
    ? "app-top-nav-inner live-command-nav-inner mx-auto flex h-full w-full max-w-none flex-row items-center justify-between gap-3 overflow-x-auto rounded-none px-3 shadow-[0_18px_55px_rgba(0,0,0,0.42),inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-xl"
    : "app-top-nav-inner mx-auto flex h-full w-full max-w-none flex-row items-center justify-between gap-3 px-3";
  const primaryClass = isCommand
    ? "app-top-nav-primary flex min-w-0 flex-1 flex-row items-center gap-3"
    : context
      ? "app-top-nav-primary flex min-w-0 flex-1 flex-row items-center gap-3"
      : "app-top-nav-primary flex min-w-0 flex-row items-center";
  const linkClass = isCommand
    ? "group flex min-w-0 shrink-0 items-center rounded-md text-left transition focus:outline-none"
    : "group flex min-w-0 shrink-0 items-center rounded-md text-left focus:outline-none";
  const actionsClass = isCommand
    ? "app-top-nav-actions live-command-actions flex w-auto shrink-0 flex-nowrap items-center gap-2"
    : "app-top-nav-actions flex w-auto shrink-0 flex-nowrap items-center justify-end gap-1.5";
  const brandClass = isCompactBrand
    ? "app-brand-logo h-12 w-12 shrink-0 rounded-md object-cover"
    : "app-brand-logo h-16 w-auto max-w-[13rem] shrink-0 object-contain";

  return (
    <header
      className={[headerClass, className].filter(Boolean).join(" ")}
      data-density={density}
      data-testid="app-top-nav"
      data-tone={tone}
      data-variant={variant}
    >
      <div className={innerClass}>
        <div className={primaryClass}>
          <Link className={linkClass} data-testid="app-brand-link" to="/games">
            <img
              alt={projectName}
              className={brandClass}
              data-testid="app-brand-logo"
              src={isCompactBrand ? logoSrc : brandLogoSrc}
            />
          </Link>
          {context ? (
            <div
              className="app-top-nav-context min-w-0 flex-1"
              data-testid="app-top-nav-context"
            >
              {context}
            </div>
          ) : null}
        </div>
        <nav
          aria-label="页面功能"
          className={actionsClass}
          data-testid="app-top-nav-actions"
        >
          <div className="contents" data-testid="app-top-nav-primary-actions">
            {actions}
          </div>
          <div className="contents" data-testid="app-top-nav-utility-actions">
            {utilityActions}
          </div>
        </nav>
      </div>
    </header>
  );
}
