import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import brandLogoSrc from "../../assets/langrensha-arena-nav-logo.png";
import type { ArenaNavDensity, ArenaNavTone } from "./arenaNav.types";
import { useArenaNavSurface } from "./useArenaNavSurface";

type ArenaGlobalNavProps = {
  brandLabel?: string;
  className?: string;
  density?: ArenaNavDensity;
  primaryAction?: ReactNode;
  secondaryAction?: ReactNode;
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

export function ArenaGlobalNav({
  brandLabel = "狼人杀竞技场",
  className,
  density = "regular",
  primaryAction,
  secondaryAction,
  tone = "default",
}: ArenaGlobalNavProps) {
  const surface = useArenaNavSurface();

  return (
    <header
      className={cx(
        "arena-global-nav fixed inset-x-0 top-0 z-50 h-[var(--arena-nav-height)] min-h-[var(--arena-nav-height)] w-full border-b transition-[background-color,border-color,box-shadow,backdrop-filter] duration-200",
        surfaceClass(surface),
        toneClass(tone),
        className,
      )}
      data-density={density}
      data-surface={surface}
      data-testid="arena-global-nav"
      data-tone={tone}
      data-variant="global"
    >
      <div className="arena-nav-inner mx-auto flex h-full w-full max-w-none items-center justify-between gap-3 px-3">
        <Link
          className="arena-brand-link flex h-full min-w-0 shrink-0 items-center rounded-md text-left focus:outline-none"
          data-testid="arena-brand-link"
          to="/games"
        >
          <img
            alt={brandLabel}
            className="arena-brand-logo h-[var(--arena-nav-height)] w-auto max-w-[16rem] shrink-0 object-contain"
            data-testid="arena-brand-logo"
            src={brandLogoSrc}
          />
        </Link>
        <nav
          aria-label="页面功能"
          className="arena-nav-actions flex w-auto shrink-0 flex-nowrap items-center justify-end gap-1.5"
          data-testid="arena-nav-actions"
        >
          <div className="contents" data-testid="arena-nav-primary-action">
            {primaryAction}
          </div>
          <div className="contents" data-testid="arena-nav-secondary-action">
            {secondaryAction}
          </div>
        </nav>
      </div>
    </header>
  );
}
