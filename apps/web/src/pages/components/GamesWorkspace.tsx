import { CreateGameRunForm } from "../../features/games/components/CreateGameRunForm";
import { listPlayerProfiles } from "../../features/games/api/listPlayerProfiles";
import { useQuery } from "@tanstack/react-query";
import type { RefObject } from "react";

type GamesWorkspaceProps = {
  createFormRef: RefObject<HTMLDivElement | null>;
};

export function GamesWorkspace({ createFormRef }: GamesWorkspaceProps) {
  const playerProfilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  });
  const profiles = playerProfilesQuery.data?.profiles ?? [];

  return (
    <main
      className="games-workspace-module lobby-page-shell mx-auto w-full max-w-none px-4 py-5 sm:px-6 lg:px-8"
      data-testid="games-workspace-module"
    >
      <div ref={createFormRef}>
        <CreateGameRunForm profiles={profiles} />
      </div>
    </main>
  );
}
