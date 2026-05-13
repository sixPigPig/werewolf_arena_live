import { useEffect, useState } from "react";

import type { ArenaNavSurface } from "./arenaNav.types";

function getCurrentSurface(): ArenaNavSurface {
  if (typeof window === "undefined") {
    return "transparent";
  }

  return window.scrollY > 0 ? "frosted" : "transparent";
}

export function useArenaNavSurface() {
  const [surface, setSurface] = useState<ArenaNavSurface>(getCurrentSurface);

  useEffect(() => {
    const updateSurface = () => {
      setSurface(getCurrentSurface());
    };

    updateSurface();
    window.addEventListener("scroll", updateSurface, { passive: true });

    return () => {
      window.removeEventListener("scroll", updateSurface);
    };
  }, []);

  return surface;
}
