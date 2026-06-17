import { useRef } from "react";

import { GamesWorkspace } from "./components/GamesWorkspace";

export function GamesPage() {
  const createFormRef = useRef<HTMLDivElement>(null);
  const focusCreateForm = () => {
    createFormRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    createFormRef.current
      ?.querySelector<HTMLElement>(
        "button, input, [tabindex]:not([tabindex='-1'])",
      )
      ?.focus();
  };

  return (
    <GamesWorkspace
      createFormRef={createFormRef}
      onCreateGameClick={focusCreateForm}
    />
  );
}
