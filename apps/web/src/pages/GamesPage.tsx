import { Button } from "../components/ui";
import { useRef } from "react";

import { AppTopNav } from "../app/AppTopNav";
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
    <>
      <AppTopNav
        actions={
          <Button highContrast onClick={focusCreateForm} size="1" type="button">
            新建对局
          </Button>
        }
        showHistoryLink
      />
      <GamesWorkspace createFormRef={createFormRef} />
    </>
  );
}
