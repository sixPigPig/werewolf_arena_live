import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import brandLogoSrc from "../../assets/langrensha-arena-nav-logo.png";
import type { ArenaNavDensity, ArenaNavTone } from "./arenaNav.types";
import { useArenaNavSurface } from "./useArenaNavSurface";

type ArenaCommandNavProps = {
  actions?: ReactNode;
  brandLabel?: string;
  className?: string;
  commands?: ReactNode;
  context?: ReactNode;
  density?: ArenaNavDensity;
  tone?: ArenaNavTone;
};

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function surfaceClass(surface: ReturnType<typeof useArenaNavSurface>) {
  return surface === "frosted"
    ? "border-white/10 bg-slate-950/[0.08] shadow-[0_12px_40px_rgba(0,0,0,0.10)] backdrop-blur-xl"
    : "border-transparent bg-transparent shadow-none";
}

function toneClass(tone: ArenaNavTone) {
  if (tone === "ornate" || tone === "nocturne") {
    return "text-amber-50";
  }

  return "text-slate-50";
}

export function ArenaCommandNav({
  actions,
  brandLabel = "狼人杀竞技场",
  className,
  commands,
  context,
  density = "compact",
  tone = "nocturne",
}: ArenaCommandNavProps) {
  const surface = useArenaNavSurface();

  return (
    <header
      className={cx(
        "arena-command-nav fixed inset-x-0 top-0 z-50 h-[var(--arena-nav-height,var(--app-top-nav-height,56px))] min-h-[var(--arena-nav-height,var(--app-top-nav-height,56px))] w-full border-b transition-[background-color,border-color,box-shadow,backdrop-filter] duration-200",
        surfaceClass(surface),
        toneClass(tone),
        className,
      )}
      data-density={density}
      data-surface={surface}
      data-testid="arena-command-nav"
      data-tone={tone}
      data-variant="command"
    >
      <div className="arena-command-inner mx-auto flex h-full w-full max-w-none items-center justify-between gap-3 overflow-x-auto px-3">
        <div className="arena-command-primary flex min-w-0 flex-1 items-center gap-3">
          <Link
            className="arena-command-brand-link flex h-full min-w-0 flex-1 items-center rounded-md text-left focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
            data-testid="arena-command-brand-link"
            to="/games"
          >
            <img
              alt={brandLabel}
              className="arena-command-brand-logo h-[var(--arena-nav-height,var(--app-top-nav-height,56px))] w-auto max-w-full shrink object-contain"
              data-testid="arena-command-brand-logo"
              src={brandLogoSrc}
            />
          </Link>
          <div
            className="arena-command-context min-w-0 shrink overflow-hidden whitespace-nowrap text-sm"
            data-testid="arena-command-context"
          >
            {context}
          </div>
        </div>
        <section
          aria-label="实时控制"
          className="arena-command-controls flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap"
          data-testid="arena-command-controls"
        >
          {commands}
        </section>
        <nav
          aria-label="实时对局操作"
          className="arena-command-action-region flex w-auto shrink-0 flex-nowrap items-center justify-end gap-1.5"
          data-testid="arena-command-action-region"
        >
          <div className="contents" data-testid="arena-command-actions">
            {actions}
          </div>
        </nav>
      </div>
    </header>
  );
}
