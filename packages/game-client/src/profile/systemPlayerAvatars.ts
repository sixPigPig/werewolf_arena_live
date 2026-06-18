export type SystemPlayerAvatar = {
  id: string;
  label: string;
  gender: "male" | "female";
  imageUrl: string;
  mime: "image/png";
};

export const SYSTEM_PLAYER_AVATARS: SystemPlayerAvatar[] = [
  {
    id: "gothic-male-1",
    label: "夜甲行者",
    gender: "male",
    imageUrl: "/player-avatars/gothic-male-1.png",
    mime: "image/png",
  },
  {
    id: "gothic-male-2",
    label: "银发贵族",
    gender: "male",
    imageUrl: "/player-avatars/gothic-male-2.png",
    mime: "image/png",
  },
  {
    id: "gothic-female-1",
    label: "霜银骑士",
    gender: "female",
    imageUrl: "/player-avatars/gothic-female-1.png",
    mime: "image/png",
  },
  {
    id: "gothic-female-2",
    label: "黑纱预言者",
    gender: "female",
    imageUrl: "/player-avatars/gothic-female-2.png",
    mime: "image/png",
  },
];

export function randomSystemPlayerAvatar(rng = Math.random) {
  const index = Math.floor(rng() * SYSTEM_PLAYER_AVATARS.length);
  return SYSTEM_PLAYER_AVATARS[index] ?? SYSTEM_PLAYER_AVATARS[0];
}
