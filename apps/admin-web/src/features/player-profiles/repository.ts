import { useMemo } from "react";

import {
  createAdminPlayerProfile,
  generateAdminPlayerProfileAiDraft,
  getAdminPlayerProfile,
  getPlayerProfileOptions,
  getPlayerTtsSpeakerOptions,
  listAdminPlayerProfiles,
  moveAdminPlayerProfile,
  previewAdminPlayerProfileVoice,
  transitionAdminPlayerProfile,
  updateAdminPlayerProfile,
} from "@/features/player-profiles/api";
import {
  createPreviewPlayerProfile,
  generatePreviewPlayerProfileAiDraft,
  getPreviewPlayerProfile,
  getPreviewPlayerProfileOptions,
  getPreviewPlayerTtsSpeakerOptions,
  listPreviewPlayerProfiles,
  movePreviewPlayerProfile,
  previewPlayerProfileVoice,
  transitionPreviewPlayerProfile,
  updatePreviewPlayerProfile,
} from "@/features/player-profiles/preview-repository";
import { useAdminSession } from "@/features/auth/session-context";
import type {
  CreatePlayerProfileRequest,
  PlayerProfileListParams,
  PlayerProfileMoveRequest,
  PlayerProfileTransitionRequest,
  PlayerVoicePreviewRequest,
  UpdatePlayerProfileRequest,
} from "@/features/player-profiles/types";

export function usePlayerProfileRepository() {
  const { runtimeMode, session } = useAdminSession();
  const csrfToken = session?.csrf_token ?? "";

  return useMemo(
    () => ({
      isPreview: runtimeMode === "preview",
      list: (params: PlayerProfileListParams, signal?: AbortSignal) =>
        runtimeMode === "preview"
          ? listPreviewPlayerProfiles(params)
          : listAdminPlayerProfiles(params, signal),
      get: (profileId: string, signal?: AbortSignal) =>
        runtimeMode === "preview"
          ? getPreviewPlayerProfile(profileId)
          : getAdminPlayerProfile(profileId, signal),
      getOptions: (signal?: AbortSignal) =>
        runtimeMode === "preview"
          ? getPreviewPlayerProfileOptions()
          : getPlayerProfileOptions(signal),
      getTtsSpeakers: (signal?: AbortSignal) =>
        runtimeMode === "preview"
          ? getPreviewPlayerTtsSpeakerOptions()
          : getPlayerTtsSpeakerOptions(signal),
      generateAiDraft: () =>
        runtimeMode === "preview"
          ? generatePreviewPlayerProfileAiDraft()
          : generateAdminPlayerProfileAiDraft("template", csrfToken),
      previewVoice: (request: PlayerVoicePreviewRequest) =>
        runtimeMode === "preview"
          ? previewPlayerProfileVoice(request)
          : previewAdminPlayerProfileVoice(request, csrfToken),
      create: (request: CreatePlayerProfileRequest) =>
        runtimeMode === "preview"
          ? createPreviewPlayerProfile(request)
          : createAdminPlayerProfile(request, csrfToken),
      update: (profileId: string, request: UpdatePlayerProfileRequest) =>
        runtimeMode === "preview"
          ? updatePreviewPlayerProfile(profileId, request)
          : updateAdminPlayerProfile(profileId, request, csrfToken),
      move: (profileId: string, request: PlayerProfileMoveRequest) =>
        runtimeMode === "preview"
          ? movePreviewPlayerProfile(profileId, request)
          : moveAdminPlayerProfile(profileId, request, csrfToken),
      transition: (
        profileId: string,
        action: "archive" | "publish" | "restore",
        request: PlayerProfileTransitionRequest,
      ) =>
        runtimeMode === "preview"
          ? transitionPreviewPlayerProfile(profileId, action, request)
          : transitionAdminPlayerProfile(
              profileId,
              action,
              request,
              csrfToken,
            ),
    }),
    [csrfToken, runtimeMode],
  );
}
