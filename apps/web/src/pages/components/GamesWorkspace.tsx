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
  const profileLoadError = "无法读取虚拟玩家资料，暂时不能发起对局。";

  return (
    <main
      className="games-workspace-module lobby-page-shell mx-auto w-full max-w-none px-4 py-5 sm:px-6 lg:px-8"
      data-testid="games-workspace-module"
    >
      {playerProfilesQuery.isPending ? (
        <p
          className="mb-3 rounded-md border border-amber-300/25 bg-slate-950/35 px-3 py-2 text-sm text-amber-100"
          role="status"
        >
          正在读取虚拟玩家资料，席位选择加载完成后可用。
        </p>
      ) : null}
      {playerProfilesQuery.isError ? (
        <p
          aria-label={profileLoadError}
          className="mb-3 rounded-md border border-red-300/30 bg-red-950/35 px-3 py-2 text-sm text-red-100"
          role="alert"
        >
          {profileLoadError}
        </p>
      ) : null}
      <div ref={createFormRef}>
        <CreateGameRunForm
          isProfileListLoaded={playerProfilesQuery.isSuccess}
          profiles={profiles}
        />
      </div>
    </main>
  );
}
