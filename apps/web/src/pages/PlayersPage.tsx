import { useRef } from "react";

import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
import { PlayersWorkspace } from "./components/PlayersWorkspace";

export function PlayersPage() {
  const workspaceRef = useRef<HTMLDivElement>(null);
  const startCreatePlayer = () => {
    const createButton = workspaceRef.current?.querySelector<HTMLButtonElement>(
      ".virtual-player-library-action",
    );

    createButton?.scrollIntoView?.({
      behavior: "smooth",
      block: "center",
    });
    createButton?.focus();
    createButton?.click();
  };

  return (
    <>
      <ArenaGlobalNav
        primaryAction={
          <ArenaNavButton intent="primary" onClick={startCreatePlayer}>
            新建虚拟玩家
          </ArenaNavButton>
        }
        secondaryAction={<ArenaNavButton to="/games">返回大厅</ArenaNavButton>}
      />
      <PlayersWorkspace workspaceRef={workspaceRef} />
    </>
  );
}
