import { Link } from "react-router-dom";

import logoSrc from "../../assets/langrensha-c-logo.png";
import wordmarkSrc from "../../assets/langrensha-title-wordmark.png";
import type { ArenaNavBrandMode } from "./arenaNav.types";

type ArenaBrandProps = {
  brandLabel?: string;
  linkClassName: string;
  linkTestId: string;
  logoClassName?: string;
  logoTestId: string;
  mode?: ArenaNavBrandMode;
  wordmarkTestId?: string;
};

const DEFAULT_LABEL = "狼人杀竞技场";
const logoBaseClass =
  "h-[var(--arena-nav-height,var(--app-top-nav-height,56px))] w-[var(--arena-nav-height,var(--app-top-nav-height,56px))] shrink-0 rounded-md object-cover";
const wordmarkBaseClass =
  "hidden h-12 w-auto min-w-0 max-w-[13rem] shrink object-contain sm:block";

export function ArenaBrand({
  brandLabel = DEFAULT_LABEL,
  linkClassName,
  linkTestId,
  logoClassName,
  logoTestId,
  mode = "full",
  wordmarkTestId,
}: ArenaBrandProps) {
  return (
    <Link
      aria-label={brandLabel}
      className={linkClassName}
      data-testid={linkTestId}
      to="/games"
    >
      <img
        alt=""
        aria-hidden="true"
        className={[logoBaseClass, logoClassName].filter(Boolean).join(" ")}
        data-testid={logoTestId}
        src={logoSrc}
      />
      {mode === "full" ? (
        <img
          alt=""
          aria-hidden="true"
          className={wordmarkBaseClass}
          data-testid={wordmarkTestId}
          src={wordmarkSrc}
        />
      ) : null}
    </Link>
  );
}
