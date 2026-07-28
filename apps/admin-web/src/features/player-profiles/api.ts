import { adminApiFetch } from "@/api/client";
import {
  parseAdminPlayerProfile,
  parseAdminPlayerProfileAiDraft,
  parseAdminPlayerProfileList,
  parseAdminPlayerVoicePreview,
  parsePlayerProfileOptions,
  parsePlayerTtsSpeakerOptions,
} from "@/features/player-profiles/parsers";
import type {
  AdminPlayerProfile,
  AdminPlayerProfileList,
  CreatePlayerProfileRequest,
  PlayerProfileListParams,
  PlayerProfileMoveRequest,
  PlayerProfileOptions,
  PlayerTtsSpeakerOptions,
  PlayerProfileTransitionRequest,
  PlayerVoicePreviewRequest,
  UpdatePlayerProfileRequest,
} from "@/features/player-profiles/types";

const PLAYER_PROFILES_PATH = "/api/v1/admin/player-profiles";
const PLAYER_PROFILE_OPTIONS_PATH = "/api/v1/admin/player-profile-options";
const PLAYER_PROFILE_TTS_SPEAKERS_PATH =
  "/api/v1/admin/player-profile-tts-speakers";
const PLAYER_PROFILE_AI_DRAFT_PATH =
  "/api/v1/admin/player-profile-ai-drafts";
const PLAYER_PROFILE_VOICE_PREVIEW_PATH =
  "/api/v1/admin/player-profile-voice-previews";

export async function generateAdminPlayerProfileAiDraft(
  mode: "name" | "template",
  csrfToken: string,
) {
  const value = await adminApiFetch<unknown>(PLAYER_PROFILE_AI_DRAFT_PATH, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({ mode }),
  });
  return parseAdminPlayerProfileAiDraft(value);
}

export async function previewAdminPlayerProfileVoice(
  request: PlayerVoicePreviewRequest,
  csrfToken: string,
) {
  const value = await adminApiFetch<unknown>(PLAYER_PROFILE_VOICE_PREVIEW_PATH, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify(request),
  });
  return parseAdminPlayerVoicePreview(value);
}

export async function listAdminPlayerProfiles(
  params: PlayerProfileListParams,
  signal?: AbortSignal,
): Promise<AdminPlayerProfileList> {
  const searchParams = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.page_size),
    sort: `${params.direction === "desc" ? "-" : ""}${params.sort}`,
  });
  appendOptional(searchParams, "q", params.q);
  appendOptional(searchParams, "status", params.status);
  appendOptional(searchParams, "model", params.model);
  appendOptional(searchParams, "personality_id", params.personality_id);
  const value = await adminApiFetch<unknown>(
    `${PLAYER_PROFILES_PATH}?${searchParams.toString()}`,
    { signal },
  );
  return parseAdminPlayerProfileList(value);
}

export async function getAdminPlayerProfile(
  profileId: string,
  signal?: AbortSignal,
): Promise<AdminPlayerProfile> {
  const value = await adminApiFetch<unknown>(
    `${PLAYER_PROFILES_PATH}/${encodeURIComponent(profileId)}`,
    { signal },
  );
  return parseAdminPlayerProfile(value);
}

export async function getPlayerProfileOptions(
  signal?: AbortSignal,
): Promise<PlayerProfileOptions> {
  const value = await adminApiFetch<unknown>(PLAYER_PROFILE_OPTIONS_PATH, {
    signal,
  });
  return parsePlayerProfileOptions(value);
}

export async function getPlayerTtsSpeakerOptions(
  signal?: AbortSignal,
): Promise<PlayerTtsSpeakerOptions> {
  const value = await adminApiFetch<unknown>(PLAYER_PROFILE_TTS_SPEAKERS_PATH, {
    signal,
  });
  return parsePlayerTtsSpeakerOptions(value);
}

export async function createAdminPlayerProfile(
  request: CreatePlayerProfileRequest,
  csrfToken: string,
) {
  return writePlayerProfile(PLAYER_PROFILES_PATH, "POST", request, csrfToken);
}

export async function updateAdminPlayerProfile(
  profileId: string,
  request: UpdatePlayerProfileRequest,
  csrfToken: string,
) {
  return writePlayerProfile(
    `${PLAYER_PROFILES_PATH}/${encodeURIComponent(profileId)}`,
    "PATCH",
    request,
    csrfToken,
  );
}

export async function transitionAdminPlayerProfile(
  profileId: string,
  action: "archive" | "publish" | "restore",
  request: PlayerProfileTransitionRequest,
  csrfToken: string,
) {
  return writePlayerProfile(
    `${PLAYER_PROFILES_PATH}/${encodeURIComponent(profileId)}/${action}`,
    "POST",
    request,
    csrfToken,
  );
}

export async function moveAdminPlayerProfile(
  profileId: string,
  request: PlayerProfileMoveRequest,
  csrfToken: string,
) {
  return writePlayerProfile(
    `${PLAYER_PROFILES_PATH}/${encodeURIComponent(profileId)}/move`,
    "POST",
    request,
    csrfToken,
  );
}

async function writePlayerProfile(
  path: string,
  method: "PATCH" | "POST",
  body:
    | CreatePlayerProfileRequest
    | PlayerProfileMoveRequest
    | PlayerProfileTransitionRequest
    | UpdatePlayerProfileRequest,
  csrfToken: string,
) {
  const value = await adminApiFetch<unknown>(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify(body),
  });
  return parseAdminPlayerProfile(value);
}

function appendOptional(
  params: URLSearchParams,
  key: string,
  value: string | undefined,
) {
  const normalized = value?.trim();
  if (normalized) {
    params.set(key, normalized);
  }
}
