export type AvatarImageValue = {
  avatar_asset_id?: string | null;
  avatar_image_url?: string | null;
};

export type AvatarImageUrlOptions = {
  baseUrl?: string;
};

const API_AVATAR_ASSET_PREFIX = "/api/v1/player-profiles/avatar-assets/";

export const SYSTEM_AVATAR_ASSET_IDS = {
  "gothic-male-1": "system-gothic-male-1",
  "gothic-male-2": "system-gothic-male-2",
  "gothic-female-1": "system-gothic-female-1",
  "gothic-female-2": "system-gothic-female-2",
} as const;

const LEGACY_SYSTEM_AVATAR_URLS: Record<string, string> = Object.fromEntries(
  Object.entries(SYSTEM_AVATAR_ASSET_IDS).map(([appearanceId, assetId]) => [
    `/player-avatars/${appearanceId}.png`,
    assetId,
  ]),
);

export function systemAvatarAssetIdForAppearance(appearanceId: string) {
  return SYSTEM_AVATAR_ASSET_IDS[
    appearanceId as keyof typeof SYSTEM_AVATAR_ASSET_IDS
  ] ?? null;
}

export function avatarAssetImageUrl(
  assetId: string,
  options: AvatarImageUrlOptions = {},
) {
  return withApiBaseUrl(`${API_AVATAR_ASSET_PREFIX}${assetId}`, options.baseUrl);
}

export function resolveAvatarImageUrl(
  value: AvatarImageValue,
  options: AvatarImageUrlOptions = {},
) {
  const assetId = value.avatar_asset_id?.trim();
  if (assetId) {
    return avatarAssetImageUrl(assetId, options);
  }

  const imageUrl = value.avatar_image_url?.trim();
  if (!imageUrl) {
    return "";
  }

  const legacyAssetId = LEGACY_SYSTEM_AVATAR_URLS[imageUrl];
  if (legacyAssetId) {
    return avatarAssetImageUrl(legacyAssetId, options);
  }

  if (imageUrl.startsWith("/api/")) {
    return withApiBaseUrl(imageUrl, options.baseUrl);
  }

  return imageUrl;
}

function withApiBaseUrl(path: string, explicitBaseUrl?: string) {
  const baseUrl = explicitBaseUrl ?? defaultApiBaseUrl();
  if (!baseUrl) {
    return path;
  }
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function defaultApiBaseUrl() {
  const meta = import.meta as ImportMeta & {
    env?: { VITE_API_BASE_URL?: string };
  };

  return meta.env?.VITE_API_BASE_URL ?? "";
}
