import type { ReactNode } from "react";

import { ArenaBrand } from "./ArenaBrand";
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
    ? "border-white/10 bg-slate-950/[0.08] shadow-[0_12px_40px_rgba(0,0,0,0.10)] backdrop-blur-sm"
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
        "arena-global-nav fixed inset-x-0 top-0 z-50 h-[var(--arena-nav-height,var(--app-top-nav-height,56px))] min-h-[var(--arena-nav-height,var(--app-top-nav-height,56px))] w-full border-b transition-[background-color,border-color,box-shadow,backdrop-filter] duration-200",
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
        <ArenaBrand
          brandLabel={brandLabel}
          linkClassName="arena-brand-link flex h-full min-w-0 flex-1 items-center rounded-md text-left focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
          linkTestId="arena-brand-link"
          logoClassName="max-w-full"
          logoTestId="arena-brand-logo"
          wordmarkTestId="arena-brand-wordmark"
        />
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
