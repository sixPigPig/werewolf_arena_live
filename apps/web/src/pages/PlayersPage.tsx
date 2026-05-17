import { useCallback, useRef } from "react";

import { ArenaGlobalNav, ArenaNavButton } from "../app/navigation";
import { PlayersWorkspace } from "./components/PlayersWorkspace";

export function PlayersPage() {
  const openCreateRef = useRef<(() => void) | null>(null);
  const handleCreateActionReady = useCallback((openCreate: () => void) => {
    openCreateRef.current = openCreate;
  }, []);
  const startCreatePlayer = () => {
    openCreateRef.current?.();
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
      <PlayersWorkspace onCreateActionReady={handleCreateActionReady} />
    </>
  );
}
