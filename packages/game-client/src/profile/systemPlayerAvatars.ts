import { avatarAssetImageUrl, SYSTEM_AVATAR_ASSET_IDS } from "./avatarImageUrl";

export type SystemPlayerAvatar = {
  id: string;
  assetId: string;
  label: string;
  gender: "male" | "female";
  mime: "image/png";
};

export const SYSTEM_PLAYER_AVATARS: SystemPlayerAvatar[] = [
  {
    id: "gothic-male-1",
    assetId: SYSTEM_AVATAR_ASSET_IDS["gothic-male-1"],
    label: "夜甲行者",
    gender: "male",
    mime: "image/png",
  },
  {
    id: "gothic-male-2",
    assetId: SYSTEM_AVATAR_ASSET_IDS["gothic-male-2"],
    label: "银发贵族",
    gender: "male",
    mime: "image/png",
  },
  {
    id: "gothic-female-1",
    assetId: SYSTEM_AVATAR_ASSET_IDS["gothic-female-1"],
    label: "霜银骑士",
    gender: "female",
    mime: "image/png",
  },
  {
    id: "gothic-female-2",
    assetId: SYSTEM_AVATAR_ASSET_IDS["gothic-female-2"],
    label: "黑纱预言者",
    gender: "female",
    mime: "image/png",
  },
];

export function systemPlayerAvatarImageUrl(avatar: SystemPlayerAvatar) {
  return avatarAssetImageUrl(avatar.assetId);
}

export function randomSystemPlayerAvatar(rng = Math.random) {
  const index = Math.floor(rng() * SYSTEM_PLAYER_AVATARS.length);
  return SYSTEM_PLAYER_AVATARS[index] ?? SYSTEM_PLAYER_AVATARS[0];
}
