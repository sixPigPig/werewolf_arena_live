import { useRef } from "react";

import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
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
      <ArenaGlobalNav
        primaryAction={
          <ArenaNavButton intent="primary" onClick={focusCreateForm}>
            新建对局
          </ArenaNavButton>
        }
        secondaryAction={
          <>
            <ArenaNavButton to="/players">玩家库</ArenaNavButton>
            <ArenaNavButton to="/games/history">对局历史</ArenaNavButton>
          </>
        }
      />
      <GamesWorkspace createFormRef={createFormRef} />
    </>
  );
}
