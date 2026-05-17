import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RefObject } from "react";

import { createPlayerProfile } from "../../features/games/api/createPlayerProfile";
import { deletePlayerProfile } from "../../features/games/api/deletePlayerProfile";
import { listModelOptions } from "../../features/games/api/listModelOptions";
import { listPlayerProfiles } from "../../features/games/api/listPlayerProfiles";
import { updatePlayerProfile } from "../../features/games/api/updatePlayerProfile";
import { uploadPlayerAvatar } from "../../features/games/api/uploadPlayerAvatar";
import { VirtualPlayerLibrary } from "../../features/games/components/VirtualPlayerLibrary";
import type { PlayerProfileRequest } from "../../features/games/types";

type PlayersWorkspaceProps = {
  onCreateActionReady?: (openCreate: () => void) => void;
  workspaceRef?: RefObject<HTMLDivElement | null>;
};

export function PlayersWorkspace({
  onCreateActionReady,
  workspaceRef,
}: PlayersWorkspaceProps) {
  const queryClient = useQueryClient();
  const playerProfilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  });
  const modelOptionsQuery = useQuery({
    queryKey: ["model-options"],
    queryFn: listModelOptions,
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
  const uploadAvatarMutation = useMutation({
    mutationFn: uploadPlayerAvatar,
  });
  const profiles = playerProfilesQuery.data?.profiles ?? [];
  const modelOptions = modelOptionsQuery.data?.models ?? [];
  const isSaving =
    createProfileMutation.isPending ||
    updateProfileMutation.isPending ||
    deleteProfileMutation.isPending;

  return (
    <main
      className="players-workspace-module lobby-page-shell mx-auto w-full max-w-none px-4 py-5 sm:px-6 lg:px-8"
      data-testid="players-workspace-module"
      ref={workspaceRef}
    >
      <header className="virtual-player-library-header mb-4">
        <h1 className="virtual-player-library-title">虚拟玩家工作台</h1>
      </header>
      <VirtualPlayerLibrary
        profiles={profiles}
        isError={playerProfilesQuery.isError}
        isLoading={playerProfilesQuery.isPending}
        isModelOptionsError={modelOptionsQuery.isError}
        isSaving={isSaving}
        modelOptions={modelOptions}
        onCreateActionReady={onCreateActionReady}
        onCreateProfile={(request) => createProfileMutation.mutateAsync(request)}
        onUploadAvatar={(file) => uploadAvatarMutation.mutateAsync(file)}
        onUpdateProfile={(profileId, request) =>
          updateProfileMutation.mutateAsync({ profileId, request })
        }
        onDeleteProfile={(profileId) =>
          deleteProfileMutation.mutateAsync(profileId)
        }
      />
    </main>
  );
}
