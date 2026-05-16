import { CreateGameRunForm } from "../../features/games/components/CreateGameRunForm";
import { VirtualPlayerLibrary } from "../../features/games/components/VirtualPlayerLibrary";
import { createPlayerProfile } from "../../features/games/api/createPlayerProfile";
import { deletePlayerProfile } from "../../features/games/api/deletePlayerProfile";
import { listPlayerProfiles } from "../../features/games/api/listPlayerProfiles";
import { updatePlayerProfile } from "../../features/games/api/updatePlayerProfile";
import type { PlayerProfileRequest } from "../../features/games/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RefObject } from "react";

type GamesWorkspaceProps = {
  createFormRef: RefObject<HTMLDivElement | null>;
};

export function GamesWorkspace({ createFormRef }: GamesWorkspaceProps) {
  const queryClient = useQueryClient();
  const playerProfilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  });
  const invalidatePlayerProfiles = () =>
    queryClient.invalidateQueries({ queryKey: ["player-profiles"] });
  const createProfileMutation = useMutation({
    mutationFn: createPlayerProfile,
    onSuccess: invalidatePlayerProfiles,
  });
  const updateProfileMutation = useMutation({
    mutationFn: ({
      profileId,
      request,
    }: {
      profileId: string;
      request: PlayerProfileRequest;
    }) => updatePlayerProfile(profileId, request),
    onSuccess: invalidatePlayerProfiles,
  });
  const deleteProfileMutation = useMutation({
    mutationFn: deletePlayerProfile,
    onSuccess: invalidatePlayerProfiles,
  });
  const profiles = playerProfilesQuery.data?.profiles ?? [];
  const isSaving =
    createProfileMutation.isPending ||
    updateProfileMutation.isPending ||
    deleteProfileMutation.isPending;

  return (
    <main
      className="games-workspace-module lobby-page-shell mx-auto w-full max-w-none px-4 py-5 sm:px-6 lg:px-8"
      data-testid="games-workspace-module"
    >
      <VirtualPlayerLibrary
        profiles={profiles}
        isError={playerProfilesQuery.isError}
        isLoading={playerProfilesQuery.isPending}
        isSaving={isSaving}
        onCreateProfile={(request) => createProfileMutation.mutate(request)}
        onUpdateProfile={(profileId, request) =>
          updateProfileMutation.mutate({ profileId, request })
        }
        onDeleteProfile={(profileId) => deleteProfileMutation.mutate(profileId)}
      />
      <div ref={createFormRef}>
        <CreateGameRunForm profiles={profiles} />
      </div>
    </main>
  );
}
